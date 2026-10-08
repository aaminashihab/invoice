"""Synthetic-data End-to-End Workflow Integration Tests.

Validates the full prototype workflow from case listing, document attachment,
and binary retrieval, to business-rule enforcement, audit logging, and
human review persistence using purely synthetic data.
"""

from __future__ import annotations

import io
import pytest
from starlette.testclient import TestClient
from pypdf import PdfWriter
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.main import create_app
from app.persistence.database import Base, get_db
from app.persistence.seed import seed_database
from app.storage.interface import LocalStorage, get_document_storage


def generate_synthetic_pdf(text_label: str = "Synthetic Test Document") -> bytes:
    """Generate in-memory synthetic PDF bytes for testing."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=72, height=72)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


@pytest.fixture
def e2e_test_env(tmp_path):
    """Provide a TestClient and isolated DB/storage environment."""
    test_db_path = tmp_path / "e2e_workflow.db"
    test_storage_path = tmp_path / "storage"
    test_storage_path.mkdir()

    engine = create_engine(
        f"sqlite:///{test_db_path}",
        connect_args={"check_same_thread": False},
    )
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys = ON;")

    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    with TestingSession() as session:
        seed_database(session)

    settings = Settings(
        app_env="development",
        dev_identity_enabled=True,
        database_url=f"sqlite:///{test_db_path}",
        storage_dir=str(test_storage_path),
    )
    app = create_app(settings)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_document_storage] = lambda: LocalStorage(base_dir=test_storage_path)

    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        yield client, TestingSession


def test_e2e_clean_workflow_listing_upload_and_review(e2e_test_env):
    """Scenario 1: Full successful workflow on a clean verification case."""
    client, _ = e2e_test_env

    # 1. List cases from API
    resp = client.get("/api/v1/cases")
    assert resp.status_code == 200
    cases_payload = resp.json()
    assert cases_payload["synthetic_data_only"] is True
    assert len(cases_payload["cases"]) >= 5
    case_ids = [c["id"] for c in cases_payload["cases"]]
    assert "case-synth-01" in case_ids

    # 2. Get Case Detail
    detail_resp = client.get("/api/v1/cases/case-synth-01")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()["case"]
    assert detail["case_ref"] == "VC-2026-00001"
    assert detail["supplier"]["name"] == "Emirates Cement Factory LLC (Synthetic)"
    assert len(detail["documents"]) >= 3
    assert len(detail["runs"]) >= 1

    # 3. Attach an additional synthetic delivery note document
    pdf_bytes = generate_synthetic_pdf("Synthetic Addendum DN")
    upload_resp = client.post(
        "/api/v1/cases/case-synth-01/documents",
        files={"file": ("synthetic_dn_ticket_extra.pdf", pdf_bytes, "application/pdf")},
        data={"doc_type": "DELIVERY_NOTE"},
        headers={"X-Simulated-User": "sim-reviewer"},
    )
    assert upload_resp.status_code == 201
    upload_payload = upload_resp.json()
    assert upload_payload["synthetic_data_only"] is True
    assert upload_payload["reuse_warning"] is False
    new_doc_id = upload_payload["document"]["id"]

    # 4. Verify binary document content endpoint
    content_resp = client.get(f"/api/v1/documents/{new_doc_id}/content")
    assert content_resp.status_code == 200
    assert content_resp.content == pdf_bytes

    # 5. Reviewer records formal sign-off
    review_resp = client.post(
        "/api/v1/cases/case-synth-01/reviews",
        json={
            "outcome": "VERIFIED_NO_EXCEPTIONS",
            "comment": "All delivery notes checked and matched. VAT stated rate confirmed manually.",
            "declaration_accepted": True,
            "manual_vat_checked": True,
        },
        headers={"X-Simulated-User": "sim-reviewer"},
    )
    assert review_resp.status_code == 201
    review_payload = review_resp.json()
    assert review_payload["case_status"] == "VERIFIED_NO_EXCEPTIONS"
    assert review_payload["review"]["outcome"] == "VERIFIED_NO_EXCEPTIONS"
    assert "Automated VAT: NOT_CHECKED" in review_payload["review"]["qualifiers"]
    assert "Manual VAT check documented by reviewer" in review_payload["review"]["qualifiers"]

    # 6. Re-fetch case detail to verify persisted state and audit trail
    refetched = client.get("/api/v1/cases/case-synth-01").json()["case"]
    assert refetched["status"] == "VERIFIED_NO_EXCEPTIONS"
    assert len(refetched["reviews"]) == 1
    assert refetched["reviews"][0]["outcome"] == "VERIFIED_NO_EXCEPTIONS"

    # Audit events must include REVIEW_RECORDED and serialize actor_id
    actions = [a["action"] for a in refetched["audit_events"]]
    assert "REVIEW_RECORDED" in actions
    review_ev = next(a for a in refetched["audit_events"] if a["action"] == "REVIEW_RECORDED")
    assert review_ev["actor_id"] == "usr-sim-rev"
    upload_ev = next(a for a in refetched["audit_events"] if a["action"] == "DOCUMENT_UPLOADED")
    assert upload_ev["actor_id"] == "usr-sim-rev"


def test_e2e_cross_case_duplicate_triggers_reuse_warning(e2e_test_env):
    """Scenario 2: Uploading duplicate content across cases raises reuse_warning."""
    client, _ = e2e_test_env

    pdf_bytes = generate_synthetic_pdf("Shared Synthetic Delivery Ticket")

    # Upload to Case 1
    r1 = client.post(
        "/api/v1/cases/case-synth-01/documents",
        files={"file": ("shared_dn.pdf", pdf_bytes, "application/pdf")},
        data={"doc_type": "DELIVERY_NOTE"},
        headers={"X-Simulated-User": "sim-reviewer"},
    )
    assert r1.status_code == 201
    assert r1.json()["reuse_warning"] is False

    # Upload identical bytes to Case 5 (cross-case)
    r2 = client.post(
        "/api/v1/cases/case-synth-05/documents",
        files={"file": ("shared_dn_copy.pdf", pdf_bytes, "application/pdf")},
        data={"doc_type": "DELIVERY_NOTE"},
        headers={"X-Simulated-User": "sim-reviewer"},
    )
    assert r2.status_code == 201
    assert r2.json()["reuse_warning"] is True
    assert r2.json()["conflict_case_id"] == "case-synth-01"


def test_e2e_disallowed_review_outcomes_and_role_protection(e2e_test_env):
    """Scenario 3: Non-reviewer rejection and business-rule enforcement."""
    client, _ = e2e_test_env

    # 1. Non-reviewer user cannot submit review
    r_unauth = client.post(
        "/api/v1/cases/case-synth-02/reviews",
        json={
            "outcome": "ON_HOLD_QUERIED",
            "comment": "Querying supplier on variance",
            "declaration_accepted": True,
            "manual_vat_checked": False,
        },
        headers={"X-Simulated-User": "sim-accounts"},  # sim-accounts has can_review=False
    )
    assert r_unauth.status_code == 403
    assert r_unauth.json()["detail"]["code"] == "REVIEW_PERMISSION_DENIED"

    # 2. Case 2 (quantity mismatch) cannot be approved with exceptions (D1 zero-tolerance)
    r_d1 = client.post(
        "/api/v1/cases/case-synth-02/reviews",
        json={
            "outcome": "VERIFIED_WITH_EXCEPTIONS",
            "comment": "Attempting to accept quantity discrepancy",
            "declaration_accepted": True,
            "manual_vat_checked": True,
        },
        headers={"X-Simulated-User": "sim-reviewer"},
    )
    assert r_d1.status_code == 422
    assert r_d1.json()["detail"]["code"] == "DISALLOWED_OUTCOME"

    # 3. Case 2 correctly transitioned to ON_HOLD_QUERIED
    r_hold = client.post(
        "/api/v1/cases/case-synth-02/reviews",
        json={
            "outcome": "ON_HOLD_QUERIED",
            "comment": "Held pending supplier investigation into +3.000 m3 overbilling.",
            "declaration_accepted": True,
            "manual_vat_checked": False,
        },
        headers={"X-Simulated-User": "sim-reviewer"},
    )
    assert r_hold.status_code == 201
    assert r_hold.json()["case_status"] == "ON_HOLD_QUERIED"


def test_case_detail_lpo_serialization_and_findings_preserved(e2e_test_env):
    """Verify that case detail endpoints correctly serialize LPO reason fields and preserve existing LPO findings."""
    client, _ = e2e_test_env

    # 1. Case 3 (Apex Steel): lpo_required is True, reason is recorded, but no LPO document attached
    r_c3 = client.get("/api/v1/cases/case-synth-03")
    assert r_c3.status_code == 200
    c3 = r_c3.json()["case"]
    assert c3["lpo_required"] is True
    assert c3["lpo_reason_code"] == "MISSING_NOT_PROVIDED_BY_SITE"
    assert c3["lpo_reason_text"] == "Site team has not uploaded signed LPO copy."
    # Documents include invoice and DN, but no LPO
    doc_types = [d["doc_type"] for d in c3["documents"]]
    assert "LPO" not in doc_types

    # Verify LPO finding fnd-c3-02 is preserved
    findings = c3["runs"][0]["findings"]
    lpo_findings = [f for f in findings if f["category"] == "LPO"]
    assert len(lpo_findings) == 1
    f_lpo = lpo_findings[0]
    assert f_lpo["rule_code"] == "LPO_001"
    assert f_lpo["outcome"] == "MISSING_EVIDENCE"
    assert "LPO required for this invoice but missing document" in f_lpo["message"]

    # 2. Case 4 (Apex Blocks): lpo_required is False with non-required reason
    r_c4 = client.get("/api/v1/cases/case-synth-04")
    assert r_c4.status_code == 200
    c4 = r_c4.json()["case"]
    assert c4["lpo_required"] is False
    assert c4["lpo_reason_code"] == "NOT_REQUIRED_LOW_VALUE"
    assert "Low-value" in c4["lpo_reason_text"]

