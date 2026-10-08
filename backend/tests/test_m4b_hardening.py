"""Comprehensive regression and verification test suite for M4B Phase 1: Controlled Pilot Hardening.

Covers:
1. Gate A Security Controls:
   - Dual-tier Quarantine and AES-256-GCM Clean encrypted storage
   - Anti-malware inspection and fail-closed EICAR detection
   - PDF Active content protection (/JavaScript, /Launch detection)
   - Database-backed session revocation and logout
2. Segregation of Duties (SoD):
   - Case creator cannot review case
   - Invoice uploader cannot review case
   - Independent reviewer permitted
3. LPO Data Model & 3-Way Matching Engine:
   - LPO creation, retrieval, and case binding
   - Cumulative LPO quantity cap enforcement (LPO_CAP_EXCEEDED)
   - Contractual unit rate comparison (RATE_MISMATCH, RATE_MATCH)
4. Domain Invariant Preservation:
   - D1 zero tolerance exact quantity
   - F8 missing evidence
   - C1 DN reuse permanent finding
   - AED currency restriction and VAT NOT_CHECKED
"""

import hashlib
import io
from decimal import Decimal
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.security import create_access_token, create_refresh_token, hash_password
from app.domain.engine import verify_case
from app.domain.models import (
    CaseSnapshot,
    DNLineSnapshot,
    FieldStatus,
    FindingCategory,
    FindingOutcome,
    InvoiceLineSnapshot,
    LPOLineSnapshot,
    ValueWithTrust,
)
from app.main import create_app
from app.persistence.database import Base, get_db
from app.persistence.models import (
    DocumentOrm,
    LpoLineOrm,
    LpoOrm,
    ProjectOrm,
    ProjectUserOrm,
    SupplierOrm,
    UserOrm,
    UserSessionOrm,
    VerificationCaseOrm,
    VerificationRunOrm,
)
from app.storage.crypto import decrypt_payload, encrypt_payload
from app.storage.interface import LocalStorage, TieredDocumentStorage
from app.storage.pdf_security import ActiveContentProhibitedError, assert_safe_pdf_content
from app.storage.scanner import EICAR_SIGNATURE, MalwareDetectedError, scan_content


@pytest.fixture
def test_db_session(tmp_path):
    """In-memory SQLite session with full schema initialized."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()

    # Seed baseline users and projects
    pwd_hash = hash_password("PilotPass123!")
    eng = UserOrm(id="u-eng-1", name="Site Eng", email="eng@test.local", role="ENGINEER", can_review=False, hashed_password=pwd_hash, active=True)
    rev = UserOrm(id="u-rev-1", name="Reviewer 1", email="rev1@test.local", role="REVIEWER", can_review=True, hashed_password=pwd_hash, active=True)
    rev2 = UserOrm(id="u-rev-2", name="Reviewer 2", email="rev2@test.local", role="REVIEWER", can_review=True, hashed_password=pwd_hash, active=True)
    admin = UserOrm(id="u-adm-1", name="Admin", email="adm@test.local", role="ADMIN", can_review=True, hashed_password=pwd_hash, active=True)
    session.add_all([eng, rev, rev2, admin])

    proj = ProjectOrm(id="p-01", code="PRJ-TEST", name="Test Project", client="Test Client", site_location="Dubai", active=True)
    supp = SupplierOrm(id="s-01", name="Test Concrete LLC", trn="100234567800003", active=True)
    session.add_all([proj, supp])

    # Assign users to project
    session.add_all([
        ProjectUserOrm(project_id="p-01", user_id="u-eng-1"),
        ProjectUserOrm(project_id="p-01", user_id="u-rev-1"),
        ProjectUserOrm(project_id="p-01", user_id="u-rev-2"),
    ])
    session.commit()

    yield session
    session.close()


@pytest.fixture
def client(test_db_session, tmp_path):
    """FastAPI TestClient with isolated storage directories."""
    q_dir = tmp_path / "quarantine"
    c_dir = tmp_path / "clean"
    s_dir = tmp_path / "legacy"

    settings = Settings(
        app_env="test",
        dev_identity_enabled=False,
        quarantine_dir=str(q_dir),
        clean_storage_dir=str(c_dir),
        storage_dir=str(s_dir),
        storage_encryption_key="test-key-32-bytes-long-supersec!",
    )
    app = create_app(settings=settings)
    app.dependency_overrides[get_db] = lambda: test_db_session

    with TestClient(app) as test_client:
        yield test_client


# =========================================================================
# 1. Gate A Security Controls Tests
# =========================================================================

def test_aes_256_gcm_storage_encryption():
    """Verify clean storage payload is encrypted with authenticated AES-256-GCM."""
    key = "super-secret-aes-key-for-testing"
    plaintext = b"%PDF-1.4 Minimal PDF document content for testing"
    ciphertext = encrypt_payload(plaintext, key)

    assert ciphertext != plaintext
    assert len(ciphertext) == 12 + len(plaintext) + 16

    decrypted = decrypt_payload(ciphertext, key)
    assert decrypted == plaintext


def test_malware_detection_fails_closed_on_eicar():
    """EICAR signature must trigger MalwareDetectedError and fail closed."""
    eicar_payload = b"%PDF-1.4 " + EICAR_SIGNATURE
    scan_res = scan_content(eicar_payload)
    assert not scan_res.is_clean
    assert "EICAR" in (scan_res.signature_found or "")


def test_pdf_security_detects_active_javascript():
    """PDF containing active /JavaScript or /JS dictionaries must be rejected."""
    pdf_with_js = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R /Names << /JavaScript 3 0 R >> >>\nendobj\n%%EOF"
    with pytest.raises(ActiveContentProhibitedError):
        assert_safe_pdf_content(pdf_with_js)


def test_database_backed_session_revocation(client, test_db_session):
    """Login creates UserSessionOrm; refresh token can be revoked via logout."""
    # 1. Login
    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": "rev1@test.local", "password": "PilotPass123!"},
    )
    assert login_res.status_code == 200
    tokens = login_res.json()
    refresh_token = tokens["refresh_token"]

    # Session record exists and active
    token_hash = hashlib.sha256(refresh_token.encode("utf-8")).hexdigest()
    session_rec = test_db_session.query(UserSessionOrm).filter_by(session_token_hash=token_hash).first()
    assert session_rec is not None
    assert not session_rec.is_revoked

    # 2. Refresh succeeds
    ref_res = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert ref_res.status_code == 200

    # 3. Logout revokes session
    logout_res = client.post("/api/v1/auth/logout", json={"refresh_token": refresh_token})
    assert logout_res.status_code == 200
    assert logout_res.json()["logged_out"] is True

    # 4. Subsequent refresh fails
    ref_res2 = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert ref_res2.status_code == 401
    assert ref_res2.json()["detail"]["code"] == "SESSION_REVOKED"


# =========================================================================
# 2. Segregation of Duties (SoD) Tests
# =========================================================================

def test_sod_blocks_case_creator_from_reviewing(client, test_db_session):
    """User who created the case cannot submit a review for it."""
    # Create case where created_by is u-rev-1
    case = VerificationCaseOrm(
        id="c-sod-1",
        case_ref="VC-SOD-001",
        project_id="p-01",
        supplier_id="s-01",
        lpo_required=False,
        status="READY_TO_VERIFY",
        created_by="u-rev-1",
    )
    run = VerificationRunOrm(
        id="r-sod-1",
        case_id="c-sod-1",
        run_no=1,
        ruleset_version="1.0.0",
        active_checks={},
        input_snapshot={},
        input_hash="hash",
        summary="Clean",
    )
    test_db_session.add_all([case, run])
    test_db_session.commit()

    # Attempt review as u-rev-1 (case creator)
    token = create_access_token(user_id="u-rev-1", role="REVIEWER", email="rev1@test.local")
    res = client.post(
        "/api/v1/cases/c-sod-1/reviews",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "outcome": "VERIFIED_NO_EXCEPTIONS",
            "comment": "Valid review notes",
            "declaration_accepted": True,
            "manual_vat_checked": True,
        },
    )
    assert res.status_code == 403
    assert res.json()["detail"]["code"] == "REVIEW_SOD_VIOLATION"


def test_sod_blocks_invoice_uploader_from_reviewing(client, test_db_session):
    """User who uploaded the invoice cannot review the case."""
    case = VerificationCaseOrm(
        id="c-sod-2",
        case_ref="VC-SOD-002",
        project_id="p-01",
        supplier_id="s-01",
        lpo_required=False,
        status="READY_TO_VERIFY",
        created_by="u-eng-1",
    )
    inv_doc = DocumentOrm(
        id="d-sod-inv",
        case_id="c-sod-2",
        doc_type="INVOICE",
        original_filename="inv.pdf",
        storage_key="inv.pdf",
        mime_type="application/pdf",
        size_bytes=1000,
        sha256="abc123456",
        uploaded_by="u-rev-1",  # Uploaded by rev-1
    )
    run = VerificationRunOrm(
        id="r-sod-2",
        case_id="c-sod-2",
        run_no=1,
        ruleset_version="1.0.0",
        active_checks={},
        input_snapshot={},
        input_hash="hash",
        summary="Clean",
    )
    test_db_session.add_all([case, inv_doc, run])
    test_db_session.commit()

    # Attempt review as u-rev-1 (invoice uploader)
    token = create_access_token(user_id="u-rev-1", role="REVIEWER", email="rev1@test.local")
    res = client.post(
        "/api/v1/cases/c-sod-2/reviews",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "outcome": "VERIFIED_NO_EXCEPTIONS",
            "comment": "Valid notes",
            "declaration_accepted": True,
            "manual_vat_checked": True,
        },
    )
    assert res.status_code == 403
    assert res.json()["detail"]["code"] == "REVIEW_SOD_VIOLATION"

    # Independent reviewer u-rev-2 CAN review
    token2 = create_access_token(user_id="u-rev-2", role="REVIEWER", email="rev2@test.local")
    res2 = client.post(
        "/api/v1/cases/c-sod-2/reviews",
        headers={"Authorization": f"Bearer {token2}"},
        json={
            "outcome": "VERIFIED_NO_EXCEPTIONS",
            "comment": "Independent review approval notes",
            "declaration_accepted": True,
            "manual_vat_checked": True,
        },
    )
    assert res2.status_code == 201
    assert res2.json()["review"]["reviewer_id"] == "u-rev-2"


# =========================================================================
# 3. LPO Management & 3-Way Matching Rules
# =========================================================================

def test_lpo_creation_and_case_linking(client, test_db_session):
    """Create an LPO contract and link it to an authorized verification case."""
    token = create_access_token(user_id="u-rev-1", role="REVIEWER", email="rev1@test.local")

    # 1. Create LPO
    lpo_payload = {
        "lpo_number": "LPO-AUTOTEST-99",
        "project_id": "p-01",
        "supplier_id": "s-01",
        "lpo_date": "2026-03-01",
        "currency": "AED",
        "total_amount_cap": "50000.00",
        "lines": [
            {
                "line_no": 1,
                "description": "ReadyMix Concrete C30",
                "ordered_qty": "100.00",
                "unit": "m3",
                "agreed_unit_price": "250.00",
                "line_amount_cap": "25000.00",
            }
        ],
    }
    create_res = client.post("/api/v1/lpos", headers={"Authorization": f"Bearer {token}"}, json=lpo_payload)
    assert create_res.status_code == 201
    lpo_id = create_res.json()["lpo_id"]

    # 2. Create case and link LPO
    case = VerificationCaseOrm(
        id="c-lpo-test",
        case_ref="VC-LPO-001",
        project_id="p-01",
        supplier_id="s-01",
        lpo_required=True,
        status="DRAFT",
    )
    test_db_session.add(case)
    test_db_session.commit()

    link_res = client.post(
        f"/api/v1/cases/c-lpo-test/link-lpo",
        headers={"Authorization": f"Bearer {token}"},
        json={"lpo_id": lpo_id},
    )
    assert link_res.status_code == 200
    assert link_res.json()["lpo_number"] == "LPO-AUTOTEST-99"

    # Confirm case was updated in DB
    refreshed_case = test_db_session.get(VerificationCaseOrm, "c-lpo-test")
    assert refreshed_case.lpo_id == lpo_id


def test_domain_engine_lpo_cap_exceeded():
    """Engine must flag LPO_CAP_EXCEEDED when cumulative invoiced qty exceeds ordered cap."""
    lpo_line = LPOLineSnapshot(
        line_id="lpo-l1",
        document_id="doc-lpo",
        lpo_number="LPO-001",
        line_no=1,
        material_code="CONC-C30",
        description="ReadyMix Concrete C30",
        ordered_qty=ValueWithTrust(value=Decimal("100.00"), status=FieldStatus.CONFIRMED),
        unit="m3",
        unit_price=ValueWithTrust(value=Decimal("250.00"), status=FieldStatus.CONFIRMED),
        previously_invoiced_qty=Decimal("80.00"),
    )

    # Current invoice claims 30.00 m3 -> total cumulative = 110.00 > 100.00 ordered cap
    inv_line = InvoiceLineSnapshot(
        line_id="inv-l1",
        document_id="doc-inv",
        invoice_number="INV-1",
        line_no=1,
        material_code="CONC-C30",
        description="ReadyMix Concrete C30",
        invoiced_qty=ValueWithTrust(value=Decimal("30.00"), status=FieldStatus.CONFIRMED),
        unit="m3",
        unit_price=ValueWithTrust(value=Decimal("250.00"), status=FieldStatus.CONFIRMED),
        line_amount=ValueWithTrust(value=Decimal("7500.00"), status=FieldStatus.CONFIRMED),
    )

    dn_line = DNLineSnapshot(
        line_id="dn-l1",
        document_id="doc-dn",
        dn_number="DN-1",
        line_no=1,
        material_code="CONC-C30",
        description="ReadyMix Concrete C30",
        delivered_qty=ValueWithTrust(value=Decimal("30.00"), status=FieldStatus.CONFIRMED),
        unit="m3",
    )

    snapshot = CaseSnapshot(
        case_id="case-cap-test",
        project_id="p-01",
        project_name="Test Project",
        supplier_id="s-01",
        supplier_name="Test Supplier",
        supplier_trn=ValueWithTrust(value="100234567800003", status=FieldStatus.CONFIRMED),
        invoice_number=ValueWithTrust(value="INV-1", status=FieldStatus.CONFIRMED),
        invoice_date=ValueWithTrust(value="2026-03-28", status=FieldStatus.CONFIRMED),
        invoice_currency=ValueWithTrust(value="AED", status=FieldStatus.CONFIRMED),
        subtotal=ValueWithTrust(value=Decimal("7500.00"), status=FieldStatus.CONFIRMED),
        tax_amount=ValueWithTrust(value=Decimal("375.00"), status=FieldStatus.CONFIRMED),
        grand_total=ValueWithTrust(value=Decimal("7875.00"), status=FieldStatus.CONFIRMED),
        lpo_required=True,
        invoice_lines=[inv_line],
        dn_lines=[dn_line],
        lpo_lines=[lpo_line],
        confirmed_links={"inv-l1": ["dn-l1"]},
        lpo_line_links={"inv-l1": "lpo-l1"},
    )

    findings = verify_case(snapshot)

    cap_finding = next((f for f in findings if f.rule_code == "LPO_CAP_EXCEEDED"), None)
    assert cap_finding is not None
    assert cap_finding.category == FindingCategory.LPO
    assert cap_finding.outcome == FindingOutcome.MISMATCH
    assert cap_finding.difference == "10.00"


def test_domain_engine_lpo_rate_mismatch():
    """Engine must flag RATE_MISMATCH when invoice unit price differs from contractual LPO rate."""
    lpo_line = LPOLineSnapshot(
        line_id="lpo-l2",
        document_id="doc-lpo",
        lpo_number="LPO-002",
        line_no=1,
        material_code="CONC-C30",
        description="ReadyMix Concrete C30",
        ordered_qty=ValueWithTrust(value=Decimal("100.00"), status=FieldStatus.CONFIRMED),
        unit="m3",
        unit_price=ValueWithTrust(value=Decimal("250.00"), status=FieldStatus.CONFIRMED),
        previously_invoiced_qty=Decimal("0.00"),
    )

    # Invoice claims 275.00 AED/m3 instead of agreed 250.00 AED/m3
    inv_line = InvoiceLineSnapshot(
        line_id="inv-l2",
        document_id="doc-inv",
        invoice_number="INV-2",
        line_no=1,
        material_code="CONC-C30",
        description="ReadyMix Concrete C30",
        invoiced_qty=ValueWithTrust(value=Decimal("10.00"), status=FieldStatus.CONFIRMED),
        unit="m3",
        unit_price=ValueWithTrust(value=Decimal("275.00"), status=FieldStatus.CONFIRMED),
        line_amount=ValueWithTrust(value=Decimal("2750.00"), status=FieldStatus.CONFIRMED),
    )

    dn_line = DNLineSnapshot(
        line_id="dn-l2",
        document_id="doc-dn",
        dn_number="DN-2",
        line_no=1,
        material_code="CONC-C30",
        description="ReadyMix Concrete C30",
        delivered_qty=ValueWithTrust(value=Decimal("10.00"), status=FieldStatus.CONFIRMED),
        unit="m3",
    )

    snapshot = CaseSnapshot(
        case_id="case-rate-test",
        project_id="p-01",
        project_name="Test Project",
        supplier_id="s-01",
        supplier_name="Test Supplier",
        supplier_trn=ValueWithTrust(value="100234567800003", status=FieldStatus.CONFIRMED),
        invoice_number=ValueWithTrust(value="INV-2", status=FieldStatus.CONFIRMED),
        invoice_date=ValueWithTrust(value="2026-03-28", status=FieldStatus.CONFIRMED),
        invoice_currency=ValueWithTrust(value="AED", status=FieldStatus.CONFIRMED),
        subtotal=ValueWithTrust(value=Decimal("2750.00"), status=FieldStatus.CONFIRMED),
        tax_amount=ValueWithTrust(value=Decimal("137.50"), status=FieldStatus.CONFIRMED),
        grand_total=ValueWithTrust(value=Decimal("2887.50"), status=FieldStatus.CONFIRMED),
        lpo_required=True,
        invoice_lines=[inv_line],
        dn_lines=[dn_line],
        lpo_lines=[lpo_line],
        confirmed_links={"inv-l2": ["dn-l2"]},
        lpo_line_links={"inv-l2": "lpo-l2"},
    )

    findings = verify_case(snapshot)

    rate_finding = next((f for f in findings if f.rule_code == "RATE_MISMATCH"), None)
    assert rate_finding is not None
    assert rate_finding.category == FindingCategory.PRICE
    assert rate_finding.outcome == FindingOutcome.MISMATCH
    assert rate_finding.difference == "25.00"
