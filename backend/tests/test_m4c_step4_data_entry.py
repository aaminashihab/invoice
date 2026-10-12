"""Automated test suite for M4C Step 4: Minimal UI Data Entry & Reconciliation.

Verifies:
1. Authorized case creation by QS and Admin.
2. Denial of unauthorized roles (Engineer, Accounts) and unassigned project scoping.
3. Duplicate case reference collision prevention (HTTP 409).
4. Manual invoice line entry with exact Decimal validation.
5. Delivery note line entry with site ticket metadata and documented rejection quantities.
6. Rejection quantity boundary validation (cannot exceed delivered quantity).
7. Invoice-to-DN line linking and Provisional Rule P2 single-link enforcement (HTTP 409).
8. On-demand automated verification engine execution via API.
9. Segregation of Duties (SoD) enforcement (case creator cannot sign off review).
10. Project-scoped projects and active suppliers catalog queries.
"""

from __future__ import annotations

from decimal import Decimal
import pytest
from starlette.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.main import create_app
from app.persistence.database import Base, get_db
from app.persistence.models import (
    AuditEventOrm,
    FindingOrm,
    LineItemOrm,
    LineLinkOrm,
    LpoOrm,
    LpoLineOrm,
    ReviewOrm,
    UserOrm,
    ProjectUserOrm,
    VerificationCaseOrm,
    VerificationRunOrm,
)
from app.persistence.seed import seed_database
from app.storage.interface import LocalStorage, get_document_storage


@pytest.fixture
def step4_test_client(tmp_path):
    """Provide a TestClient with a freshly seeded isolated SQLite database."""
    test_db_path = tmp_path / "test_step4.db"
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


def test_case_creation_by_authorized_qs(step4_test_client):
    """QS user creates a case shell on an assigned project."""
    client, SessionFactory = step4_test_client

    payload = {
        "case_ref": "CASE-SYNTH-QS-001",
        "project_id": "prj-01",
        "supplier_id": "sup-01",
        "invoice_number_hint": "INV-SYNTH-9001",
        "currency": "AED",
        "lpo_required": True,
    }

    resp = client.post(
        "/api/v1/cases",
        json=payload,
        headers={"X-Simulated-User": "sim-qs"},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    case_data = data["case"]
    assert case_data["case_ref"] == "CASE-SYNTH-QS-001"
    assert case_data["created_by"] == "usr-sim-qs"
    assert case_data["status"] == "DRAFT"
    assert data["synthetic_data_only"] is True

    case_id = case_data["id"]
    with SessionFactory() as session:
        case = session.get(VerificationCaseOrm, case_id)
        assert case is not None
        assert case.created_by == "usr-sim-qs"

        events = list(session.scalars(select(AuditEventOrm).where(AuditEventOrm.case_id == case_id)).all())
        created_event = next((e for e in events if e.action == "CASE_CREATED"), None)
        assert created_event is not None
        assert created_event.actor_id == "usr-sim-qs"


def test_case_creation_unauthorized_role(step4_test_client):
    """Site engineer and accounts lead cannot create cases."""
    client, _ = step4_test_client

    payload = {
        "case_ref": "CASE-SYNTH-FORBIDDEN-01",
        "project_id": "prj-01",
        "supplier_id": "sup-01",
    }

    # Site Engineer (role="ENGINEER")
    resp_eng = client.post(
        "/api/v1/cases",
        json=payload,
        headers={"X-Simulated-User": "sim-engineer"},
    )
    assert resp_eng.status_code == 403
    assert resp_eng.json()["detail"]["code"] == "CASE_CREATION_DENIED"

    # Accounts Lead (role="ACCOUNTS")
    resp_acc = client.post(
        "/api/v1/cases",
        json=payload,
        headers={"X-Simulated-User": "sim-accounts"},
    )
    assert resp_acc.status_code == 403
    assert resp_acc.json()["detail"]["code"] == "CASE_CREATION_DENIED"


def test_case_creation_unassigned_project(step4_test_client):
    """User without assignment to target project is rejected."""
    client, SessionFactory = step4_test_client

    # Create an unassigned QS user in DB
    with SessionFactory() as session:
        unassigned_qs = UserOrm(
            id="usr-unassigned-qs",
            name="Unassigned QS",
            email="unassigned@test.local",
            role="QS",
            can_review=False,
            active=True,
        )
        session.add(unassigned_qs)
        session.commit()

    payload = {
        "case_ref": "CASE-SYNTH-UNASSIGNED-01",
        "project_id": "prj-01",
        "supplier_id": "sup-01",
    }

    resp = client.post(
        "/api/v1/cases",
        json=payload,
        headers={"X-Simulated-User": "usr-unassigned-qs"},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "PROJECT_ACCESS_DENIED"


def test_case_creation_duplicate_case_ref(step4_test_client):
    """Attempting to create duplicate case ref returns HTTP 409."""
    client, _ = step4_test_client

    payload = {
        "case_ref": "CASE-SYNTH-DUP-01",
        "project_id": "prj-01",
        "supplier_id": "sup-01",
    }

    resp1 = client.post("/api/v1/cases", json=payload, headers={"X-Simulated-User": "sim-qs"})
    assert resp1.status_code == 201

    resp2 = client.post("/api/v1/cases", json=payload, headers={"X-Simulated-User": "sim-qs"})
    assert resp2.status_code == 409
    assert resp2.json()["detail"]["code"] == "CASE_REF_EXISTS"


def test_invoice_line_manual_entry_and_validation(step4_test_client):
    """QS creates an invoice line with confirmed Decimal quantities."""
    client, SessionFactory = step4_test_client

    # 1. Create case
    case_resp = client.post(
        "/api/v1/cases",
        json={"case_ref": "CASE-SYNTH-INV-01", "project_id": "prj-01", "supplier_id": "sup-01"},
        headers={"X-Simulated-User": "sim-qs"},
    )
    case_id = case_resp.json()["case"]["id"]

    # 2. Add valid invoice line
    line_payload = {
        "line_no": 1,
        "description": "ReadyMix Concrete C30/20",
        "invoiced_qty": "100.000",
        "unit": "m3",
        "unit_price": "250.00",
        "line_amount": "25000.00",
    }
    resp = client.post(
        f"/api/v1/cases/{case_id}/invoice-lines",
        json=line_payload,
        headers={"X-Simulated-User": "sim-qs"},
    )
    assert resp.status_code == 201, resp.text
    line_data = resp.json()["line_item"]
    assert line_data["line_no"] == 1
    assert line_data["invoiced_qty"] == "100.000"
    assert line_data["unit_price"] == "250.00"

    # 3. Add invalid negative quantity
    invalid_qty_payload = {
        "line_no": 2,
        "description": "Negative quantity line",
        "invoiced_qty": "-5.00",
        "unit": "m3",
        "unit_price": "250.00",
        "line_amount": "-1250.00",
    }
    resp_neg = client.post(
        f"/api/v1/cases/{case_id}/invoice-lines",
        json=invalid_qty_payload,
        headers={"X-Simulated-User": "sim-qs"},
    )
    assert resp_neg.status_code == 422
    assert resp_neg.json()["detail"]["code"] == "INVALID_DECIMAL_VALUE"

    # 4. Add malformed non-decimal quantity
    malformed_payload = {
        "line_no": 3,
        "description": "Malformed decimal line",
        "invoiced_qty": "abc_not_a_number",
        "unit": "m3",
        "unit_price": "250.00",
        "line_amount": "250.00",
    }
    resp_mal = client.post(
        f"/api/v1/cases/{case_id}/invoice-lines",
        json=malformed_payload,
        headers={"X-Simulated-User": "sim-qs"},
    )
    assert resp_mal.status_code == 422
    assert resp_mal.json()["detail"]["code"] == "INVALID_DECIMAL_VALUE"


def test_delivery_note_line_entry_and_rejection(step4_test_client):
    """QS creates delivery note line with site receipt and documented rejection quantities."""
    client, SessionFactory = step4_test_client

    case_resp = client.post(
        "/api/v1/cases",
        json={"case_ref": "CASE-SYNTH-DN-01", "project_id": "prj-01", "supplier_id": "sup-01"},
        headers={"X-Simulated-User": "sim-qs"},
    )
    case_id = case_resp.json()["case"]["id"]

    # 1. Valid delivery note line with rejection
    dn_payload = {
        "dn_number": "DN-SYNTH-7701",
        "line_no": 1,
        "description": "ReadyMix Concrete C30/20 Delivery 1",
        "delivered_qty": "50.000",
        "unit": "m3",
        "storekeeper_ticket_no": "SK-TKT-1001",
        "storekeeper_confirmed": True,
        "rejected_qty": "5.000",
        "rejection_reason_code": "SLUMP_FAIL",
        "has_rejection_evidence": True,
    }
    resp = client.post(
        f"/api/v1/cases/{case_id}/delivery-note-lines",
        json=dn_payload,
        headers={"X-Simulated-User": "sim-qs"},
    )
    assert resp.status_code == 201, resp.text
    dn_data = resp.json()["line_item"]
    assert dn_data["dn_number"] == "DN-SYNTH-7701"
    assert dn_data["delivered_qty"] == "50.000"
    assert dn_data["rejected_qty"] == "5.000"

    # 2. Invalid: rejected quantity exceeds delivered quantity
    excess_rejection_payload = {
        "dn_number": "DN-SYNTH-7702",
        "line_no": 1,
        "description": "ReadyMix Delivery 2",
        "delivered_qty": "40.000",
        "unit": "m3",
        "rejected_qty": "45.000",
        "rejection_reason_code": "EXCESS",
        "has_rejection_evidence": True,
    }
    resp_excess = client.post(
        f"/api/v1/cases/{case_id}/delivery-note-lines",
        json=excess_rejection_payload,
        headers={"X-Simulated-User": "sim-qs"},
    )
    assert resp_excess.status_code == 422
    assert resp_excess.json()["detail"]["code"] == "INVALID_REJECTION_QTY"


def test_line_linking_and_rule_p2_dn_reuse_prevention(step4_test_client):
    """Enforces Provisional Rule P2: a delivery note line can only be linked once."""
    client, _ = step4_test_client

    # 1. Create case
    case_resp = client.post(
        "/api/v1/cases",
        json={"case_ref": "CASE-SYNTH-LINK-01", "project_id": "prj-01", "supplier_id": "sup-01"},
        headers={"X-Simulated-User": "sim-qs"},
    )
    case_id = case_resp.json()["case"]["id"]

    # 2. Add two invoice lines
    inv1_resp = client.post(
        f"/api/v1/cases/{case_id}/invoice-lines",
        json={"line_no": 1, "description": "Concrete 1", "invoiced_qty": "50.00", "unit": "m3", "unit_price": "250.00", "line_amount": "12500.00"},
        headers={"X-Simulated-User": "sim-qs"},
    )
    inv1_id = inv1_resp.json()["line_item"]["id"]

    inv2_resp = client.post(
        f"/api/v1/cases/{case_id}/invoice-lines",
        json={"line_no": 2, "description": "Concrete 2", "invoiced_qty": "50.00", "unit": "m3", "unit_price": "250.00", "line_amount": "12500.00"},
        headers={"X-Simulated-User": "sim-qs"},
    )
    inv2_id = inv2_resp.json()["line_item"]["id"]

    # 3. Add one DN line
    dn_resp = client.post(
        f"/api/v1/cases/{case_id}/delivery-note-lines",
        json={"dn_number": "DN-LINK-01", "line_no": 1, "description": "Delivery 1", "delivered_qty": "50.00", "unit": "m3"},
        headers={"X-Simulated-User": "sim-qs"},
    )
    dn_id = dn_resp.json()["line_item"]["id"]

    # 4. Link inv1 to dn1 -> Success
    link1_resp = client.post(
        f"/api/v1/cases/{case_id}/links",
        json={"invoice_line_id": inv1_id, "dn_line_id": dn_id, "link_method": "MANUAL"},
        headers={"X-Simulated-User": "sim-qs"},
    )
    assert link1_resp.status_code == 201, link1_resp.text
    assert link1_resp.json()["link"]["invoice_line_id"] == inv1_id
    assert link1_resp.json()["link"]["dn_line_id"] == dn_id

    # 5. Attempt linking inv2 to dn1 -> Blocked under Rule P2 with HTTP 409
    link2_resp = client.post(
        f"/api/v1/cases/{case_id}/links",
        json={"invoice_line_id": inv2_id, "dn_line_id": dn_id, "link_method": "MANUAL"},
        headers={"X-Simulated-User": "sim-qs"},
    )
    assert link2_resp.status_code == 409
    assert link2_resp.json()["detail"]["code"] == "DN_LINE_ALREADY_LINKED"


def test_verification_run_via_api(step4_test_client):
    """Executes verification engine via POST /cases/{case_id}/verify and stores findings."""
    client, SessionFactory = step4_test_client

    # 1. Create case attached to seeded LPO lpo-synth-01 (prj-01, sup-02)
    case_resp = client.post(
        "/api/v1/cases",
        json={"case_ref": "CASE-SYNTH-VERIFY-01", "project_id": "prj-01", "supplier_id": "sup-02", "lpo_id": "lpo-synth-01"},
        headers={"X-Simulated-User": "sim-qs"},
    )
    assert case_resp.status_code == 201, case_resp.text
    case_id = case_resp.json()["case"]["id"]

    # 2. Add invoice line matching LPO line
    inv_resp = client.post(
        f"/api/v1/cases/{case_id}/invoice-lines",
        json={"line_no": 1, "description": "Ordinary Portland Cement (Bulk)", "invoiced_qty": "100.000", "unit": "t", "unit_price": "280.00", "line_amount": "28000.00"},
        headers={"X-Simulated-User": "sim-qs"},
    )
    inv_id = inv_resp.json()["line_item"]["id"]

    # 3. Add delivery note line matching quantity
    dn_resp = client.post(
        f"/api/v1/cases/{case_id}/delivery-note-lines",
        json={"dn_number": "DN-VERIFY-01", "line_no": 1, "description": "Ordinary Portland Cement Delivery", "delivered_qty": "100.000", "unit": "t", "storekeeper_ticket_no": "TKT-101", "storekeeper_confirmed": True},
        headers={"X-Simulated-User": "sim-qs"},
    )
    dn_id = dn_resp.json()["line_item"]["id"]

    # 4. Link invoice line to DN line and LPO line
    with SessionFactory() as session:
        lpo_line = session.scalars(select(LpoLineOrm).where(LpoLineOrm.lpo_id == "lpo-synth-01")).first()
        lpo_line_id = lpo_line.id if lpo_line else None

    link_resp = client.post(
        f"/api/v1/cases/{case_id}/links",
        json={"invoice_line_id": inv_id, "dn_line_id": dn_id, "lpo_line_id": lpo_line_id, "link_method": "MANUAL"},
        headers={"X-Simulated-User": "sim-qs"},
    )
    assert link_resp.status_code == 201

    # 5. Execute automated verification
    verify_resp = client.post(
        f"/api/v1/cases/{case_id}/verify",
        headers={"X-Simulated-User": "sim-qs"},
    )
    assert verify_resp.status_code in (200, 201), verify_resp.text
    verify_data = verify_resp.json()
    assert verify_data["run"]["id"] is not None
    assert "findings" in verify_data["run"]
    assert len(verify_data["run"]["findings"]) > 0

    # 6. Verify database records
    with SessionFactory() as session:
        case = session.get(VerificationCaseOrm, case_id)
        assert case.status in ("VERIFIED_NO_EXCEPTIONS", "VERIFIED_WITH_EXCEPTIONS", "FLAGGED_FOR_HUMAN_REVIEW", "READY_FOR_REVIEW")

        runs = list(session.scalars(select(VerificationRunOrm).where(VerificationRunOrm.case_id == case_id)).all())
        assert len(runs) == 1
        assert runs[0].ruleset_version == "1.0.0-draft"


def test_segregation_of_duties_enforcement(step4_test_client):
    """Case creator cannot submit a review for the case they created."""
    client, SessionFactory = step4_test_client

    # 1. Create a user who has can_review=True
    with SessionFactory() as session:
        dual_user = UserOrm(
            id="usr-dual-role",
            name="Dual Role Reviewer",
            email="dual@prototype.local",
            role="ADMIN",
            can_review=True,
            active=True,
        )
        session.add(dual_user)
        session.flush()
        session.add(ProjectUserOrm(project_id="prj-01", user_id="usr-dual-role"))
        session.commit()

    # 2. Case created by usr-dual-role
    case_resp = client.post(
        "/api/v1/cases",
        json={"case_ref": "CASE-SYNTH-SOD-01", "project_id": "prj-01", "supplier_id": "sup-01"},
        headers={"X-Simulated-User": "usr-dual-role"},
    )
    case_id = case_resp.json()["case"]["id"]

    # 3. Add line and run verification to produce a run to review
    inv_resp = client.post(
        f"/api/v1/cases/{case_id}/invoice-lines",
        json={"line_no": 1, "description": "Concrete", "invoiced_qty": "10.00", "unit": "m3", "unit_price": "250.00", "line_amount": "2500.00"},
        headers={"X-Simulated-User": "usr-dual-role"},
    )
    verify_resp = client.post(
        f"/api/v1/cases/{case_id}/verify",
        headers={"X-Simulated-User": "usr-dual-role"},
    )
    assert verify_resp.status_code in (200, 201)

    # 4. Attempt review submission by the creator (usr-dual-role) -> HTTP 403 REVIEW_SOD_VIOLATION
    review_payload = {
        "outcome": "REJECTED",
        "comment": "Rejection rationale documented due to missing delivery notes.",
        "declaration_accepted": True,
        "manual_vat_checked": True,
    }
    sod_resp = client.post(
        f"/api/v1/cases/{case_id}/reviews",
        json=review_payload,
        headers={"X-Simulated-User": "usr-dual-role"},
    )
    assert sod_resp.status_code == 403
    assert sod_resp.json()["detail"]["code"] == "REVIEW_SOD_VIOLATION"

    # 5. Independent reviewer (usr-sim-rev) reviews the case -> Success
    valid_review_resp = client.post(
        f"/api/v1/cases/{case_id}/reviews",
        json=review_payload,
        headers={"X-Simulated-User": "sim-reviewer"},
    )
    assert valid_review_resp.status_code == 201


def test_catalogs_endpoints(step4_test_client):
    """Verifies project catalog scoped to user and supplier catalog."""
    client, _ = step4_test_client

    # Projects catalog for QS
    p_resp = client.get("/api/v1/projects", headers={"X-Simulated-User": "sim-qs"})
    assert p_resp.status_code == 200
    projects = p_resp.json()["projects"]
    assert len(projects) >= 4
    assert any(p["code"] == "PRJ-CT4" for p in projects)

    # Suppliers catalog
    s_resp = client.get("/api/v1/suppliers", headers={"X-Simulated-User": "sim-qs"})
    assert s_resp.status_code == 200
    suppliers = s_resp.json()["suppliers"]
    assert len(suppliers) >= 5
    assert any(s["trn"] == "100234567800003" for s in suppliers)
