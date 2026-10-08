"""Automated test suite for Review Submission REST API endpoint."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.main import create_app
from app.persistence.database import Base, get_db
from app.persistence.models import (
    AuditEventOrm,
    FindingDispositionOrm,
    FindingOrm,
    ReviewOrm,
    VerificationCaseOrm,
)
from app.persistence.seed import seed_database
from app.storage.interface import LocalStorage, get_document_storage


@pytest.fixture
def review_test_client(tmp_path):
    """Provide a TestClient with a freshly seeded isolated SQLite database."""
    test_db_path = tmp_path / "test_reviews.db"
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


def test_submit_review_success_clean_match(review_test_client):
    client, SessionFactory = review_test_client

    payload = {
        "outcome": "VERIFIED_NO_EXCEPTIONS",
        "comment": "All delivery notes verified; manual VAT check confirmed against tax invoice.",
        "declaration_accepted": True,
        "manual_vat_checked": True,
    }

    resp = client.post(
        "/api/v1/cases/case-synth-01/reviews",
        json=payload,
        headers={"X-Simulated-User": "sim-reviewer"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["synthetic_data_only"] is True
    assert data["case_status"] == "VERIFIED_NO_EXCEPTIONS"
    assert data["review"]["outcome"] == "VERIFIED_NO_EXCEPTIONS"
    assert data["review"]["reviewer_name"] == "Simulated Reviewer"
    assert "Automated VAT: NOT_CHECKED" in data["review"]["qualifiers"]
    assert "Manual VAT check documented by reviewer" in data["review"]["qualifiers"]

    # Verify persistence in isolated DB
    with SessionFactory() as session:
        case = session.get(VerificationCaseOrm, "case-synth-01")
        assert case.status == "VERIFIED_NO_EXCEPTIONS"

        reviews = list(session.scalars(select(ReviewOrm).where(ReviewOrm.case_id == "case-synth-01")).all())
        assert len(reviews) == 1
        assert reviews[0].outcome == "VERIFIED_NO_EXCEPTIONS"

        events = list(session.scalars(select(AuditEventOrm).where(AuditEventOrm.case_id == "case-synth-01")).all())
        rev_event = next((e for e in events if e.action == "REVIEW_RECORDED"), None)
        assert rev_event is not None
        assert rev_event.after_state["outcome"] == "VERIFIED_NO_EXCEPTIONS"


def test_submit_review_rejects_non_reviewer_role(review_test_client):
    client, _ = review_test_client

    payload = {
        "outcome": "VERIFIED_NO_EXCEPTIONS",
        "comment": "Attempted sign-off without reviewer role",
        "declaration_accepted": True,
        "manual_vat_checked": True,
    }

    # sim-engineer does NOT have can_review permission (D6)
    resp = client.post(
        "/api/v1/cases/case-synth-01/reviews",
        json=payload,
        headers={"X-Simulated-User": "sim-engineer"},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "REVIEW_PERMISSION_DENIED"


def test_submit_review_rejects_unaccepted_declaration(review_test_client):
    client, _ = review_test_client

    payload = {
        "outcome": "VERIFIED_NO_EXCEPTIONS",
        "comment": "Valid review comment text",
        "declaration_accepted": False,
        "manual_vat_checked": True,
    }

    resp = client.post(
        "/api/v1/cases/case-synth-01/reviews",
        json=payload,
        headers={"X-Simulated-User": "sim-reviewer"},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "DECLARATION_REQUIRED"


def test_submit_review_rejects_unverified_vat_without_manual_check(review_test_client):
    client, _ = review_test_client

    payload = {
        "outcome": "VERIFIED_NO_EXCEPTIONS",
        "comment": "Missing manual VAT check confirmation",
        "declaration_accepted": True,
        "manual_vat_checked": False,
    }

    resp = client.post(
        "/api/v1/cases/case-synth-01/reviews",
        json=payload,
        headers={"X-Simulated-User": "sim-reviewer"},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "VAT_CHECK_REQUIRED"


def test_submit_review_enforces_d1_quantity_mismatch_rules(review_test_client):
    client, _ = review_test_client

    # Case 2 has an overbilling quantity mismatch
    # 1. Cannot be marked VERIFIED_NO_EXCEPTIONS
    r1 = client.post(
        "/api/v1/cases/case-synth-02/reviews",
        json={
            "outcome": "VERIFIED_NO_EXCEPTIONS",
            "comment": "Attempting clean approval on mismatch",
            "declaration_accepted": True,
            "manual_vat_checked": True,
        },
        headers={"X-Simulated-User": "sim-reviewer"},
    )
    assert r1.status_code == 422
    assert r1.json()["detail"]["code"] == "DISALLOWED_OUTCOME"

    # 2. Cannot be marked VERIFIED_WITH_EXCEPTIONS (D1 exact match policy)
    r2 = client.post(
        "/api/v1/cases/case-synth-02/reviews",
        json={
            "outcome": "VERIFIED_WITH_EXCEPTIONS",
            "comment": "Attempting to accept quantity mismatch as exception",
            "declaration_accepted": True,
            "manual_vat_checked": True,
        },
        headers={"X-Simulated-User": "sim-reviewer"},
    )
    assert r2.status_code == 422
    assert r2.json()["detail"]["code"] == "DISALLOWED_OUTCOME"

    # 3. Can be marked ON_HOLD_QUERIED
    r3 = client.post(
        "/api/v1/cases/case-synth-02/reviews",
        json={
            "outcome": "ON_HOLD_QUERIED",
            "comment": "Querying supplier on 3.000 m3 overbilling discrepancy on Line 2.",
            "declaration_accepted": True,
            "manual_vat_checked": False,
        },
        headers={"X-Simulated-User": "sim-reviewer"},
    )
    assert r3.status_code == 201
    assert r3.json()["case_status"] == "ON_HOLD_QUERIED"


def test_submit_review_enforces_f8_missing_evidence_rules(review_test_client):
    client, _ = review_test_client

    # Case 3 has missing required delivery note ticket & missing LPO
    r1 = client.post(
        "/api/v1/cases/case-synth-03/reviews",
        json={
            "outcome": "VERIFIED_WITH_EXCEPTIONS",
            "comment": "Cannot accept missing delivery note as an exception",
            "declaration_accepted": True,
            "manual_vat_checked": True,
        },
        headers={"X-Simulated-User": "sim-reviewer"},
    )
    assert r1.status_code == 422
    assert r1.json()["detail"]["code"] == "DISALLOWED_OUTCOME"

    # Can be REJECTED
    r2 = client.post(
        "/api/v1/cases/case-synth-03/reviews",
        json={
            "outcome": "REJECTED",
            "comment": "Rejected and returned to supplier: Missing delivery ticket DN-6200.",
            "declaration_accepted": True,
            "manual_vat_checked": False,
        },
        headers={"X-Simulated-User": "sim-reviewer"},
    )
    assert r2.status_code == 201
    assert r2.json()["case_status"] == "REJECTED"


def test_submit_review_c1_reuse_finding_disposition(review_test_client):
    client, SessionFactory = review_test_client

    # Case 4 has delivery note reuse flagged
    # 1. Clean verification rejected
    r1 = client.post(
        "/api/v1/cases/case-synth-04/reviews",
        json={
            "outcome": "VERIFIED_NO_EXCEPTIONS",
            "comment": "Cannot cleanly verify case with reused DN",
            "declaration_accepted": True,
            "manual_vat_checked": True,
        },
        headers={"X-Simulated-User": "sim-reviewer"},
    )
    assert r1.status_code == 422
    assert r1.json()["detail"]["code"] == "DISALLOWED_OUTCOME"

    # 2. Verified with noted exceptions accepted under C1 with justification
    r2 = client.post(
        "/api/v1/cases/case-synth-04/reviews",
        json={
            "outcome": "VERIFIED_WITH_EXCEPTIONS",
            "comment": "Prior case VC-2026-00012 was cancelled and credit reissued on this invoice.",
            "declaration_accepted": True,
            "manual_vat_checked": True,
        },
        headers={"X-Simulated-User": "sim-reviewer"},
    )
    assert r2.status_code == 201
    payload = r2.json()
    assert payload["case_status"] == "VERIFIED_WITH_EXCEPTIONS"
    assert len(payload["review"]["dispositions"]) == 1
    disp = payload["review"]["dispositions"][0]
    assert disp["disposition"] == "REUSE_JUSTIFIED"

    # 3. Rule C1: verify finding remains permanent and is NOT deleted or modified
    with SessionFactory() as session:
        f4 = session.get(FindingOrm, "fnd-c4-01")
        assert f4 is not None
        assert f4.outcome == "MISMATCH"
        assert f4.category == "DN_REUSE"

        dispositions = list(session.scalars(select(FindingDispositionOrm).where(FindingDispositionOrm.finding_id == f4.id)).all())
        assert len(dispositions) == 1
        assert dispositions[0].disposition == "REUSE_JUSTIFIED"


def test_submit_duplicate_review_on_same_run_returns_409(review_test_client):
    client, _ = review_test_client

    payload = {
        "outcome": "VERIFIED_NO_EXCEPTIONS",
        "comment": "First authorized sign-off.",
        "declaration_accepted": True,
        "manual_vat_checked": True,
    }

    # First review succeeds
    r1 = client.post(
        "/api/v1/cases/case-synth-01/reviews",
        json=payload,
        headers={"X-Simulated-User": "sim-reviewer"},
    )
    assert r1.status_code == 201

    # Second review on same case/run is rejected with 409
    r2 = client.post(
        "/api/v1/cases/case-synth-01/reviews",
        json=payload,
        headers={"X-Simulated-User": "sim-reviewer"},
    )
    assert r2.status_code == 409
    assert r2.json()["detail"]["code"] == "RUN_ALREADY_REVIEWED"


def test_submit_review_nonexistent_case_returns_404(review_test_client):
    client, _ = review_test_client

    resp = client.post(
        "/api/v1/cases/case-nonexistent/reviews",
        json={
            "outcome": "VERIFIED_NO_EXCEPTIONS",
            "comment": "Some comment",
            "declaration_accepted": True,
            "manual_vat_checked": True,
        },
        headers={"X-Simulated-User": "sim-reviewer"},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "CASE_NOT_FOUND"


def test_submit_review_case_without_run_returns_422(review_test_client):
    client, _ = review_test_client

    # Case 5 has no verification runs seeded
    resp = client.post(
        "/api/v1/cases/case-synth-05/reviews",
        json={
            "outcome": "VERIFIED_NO_EXCEPTIONS",
            "comment": "Attempt review with no run",
            "declaration_accepted": True,
            "manual_vat_checked": True,
        },
        headers={"X-Simulated-User": "sim-reviewer"},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "NO_VERIFICATION_RUN"
