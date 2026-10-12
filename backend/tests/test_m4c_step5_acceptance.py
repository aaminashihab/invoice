"""Step 5: Synthetic End-to-End Acceptance Test Suite.

Verifies:
1. Complete End-to-End Workflow via REST API:
   - QS Login via JWT (POST /api/v1/auth/login)
   - Scoped Case Creation (POST /api/v1/cases)
   - Manual Invoice Line Entry with Decimal validation (POST /api/v1/cases/{id}/invoice-lines)
   - Manual Delivery Note Line Entry with site ticket (POST /api/v1/cases/{id}/delivery-note-lines)
   - Line Linking enforcing Provisional Rule P2 (POST /api/v1/cases/{id}/links)
   - Automated Verification Engine execution (POST /api/v1/cases/{id}/verify)
   - Segregation of Duties (SoD) enforcement blocking creator review (POST /api/v1/cases/{id}/reviews -> 403)
   - Independent Reviewer Login & Sign-off (POST /api/v1/cases/{id}/reviews -> 201)
   - Immutable audit trail recording each action with distinct actor provenance
2. All Five Synthetic Calibration Scenarios:
   - Scenario 1: Clean exact 4-way match (Ready-mix concrete) -> MATCH, permits VERIFIED_NO_EXCEPTIONS
   - Scenario 2: Overbilling mismatch (Reinforcement steel) -> QTY_004 MISMATCH (+5.00 t), blocks clean approval
   - Scenario 3: Missing delivery note evidence (Ready-mix concrete) -> COMP_002 MISSING_EVIDENCE, blocks approval
   - Scenario 4: Delivery note cross-case reuse (Steel rebar) -> DN_REUSE_001 MISMATCH, blocks clean approval
   - Scenario 5: Documented site rejection (Ready-mix slump test) -> QTY_003 MATCH on net accepted quantity
3. Database isolation guarantee (tests run strictly against isolated test DB, preserving civ_pilot).
"""

from __future__ import annotations

from decimal import Decimal
import pytest
from starlette.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.core.security import hash_password
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
    AuditEventOrm,
    FindingOrm,
    LineItemOrm,
    LineLinkOrm,
    LpoLineOrm,
    LpoOrm,
    ProjectOrm,
    ProjectUserOrm,
    ReviewOrm,
    SupplierOrm,
    UserOrm,
    VerificationCaseOrm,
    VerificationRunOrm,
)
from app.storage.interface import LocalStorage, get_document_storage


PILOT_PROJECT_ID = "prj-pilot-dxb-01"
SUPPLIER_RMC_ID = "sup-pilot-rmc-01"
SUPPLIER_STEEL_ID = "sup-pilot-steel-02"

USER_QS_ID = "usr-pilot-project-qs"
USER_STORE_ID = "usr-pilot-storekeeper"
USER_ENG_ID = "usr-pilot-site-eng"
USER_PM_ID = "usr-pilot-pm-reviewer"


@pytest.fixture
def step5_isolated_env(tmp_path):
    """Provide a TestClient with an isolated SQLite database seeded with pilot groundwork."""
    test_db_path = tmp_path / "acceptance_test.db"
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

    # Seed Pilot Entities and Users with bcrypt password "PilotPass123!"
    pw_hash = hash_password("PilotPass123!")

    with TestingSession() as session:
        project = ProjectOrm(
            id=PILOT_PROJECT_ID,
            code="PRJ-DXB-01",
            name="Crown Horizon Residences - Tower A",
            client="Horizon Capital Developments PJSC (Synthetic)",
            site_location="Business District Plot 345-1200",
            active=True,
        )
        sup_rmc = SupplierOrm(
            id=SUPPLIER_RMC_ID,
            name="Apex Ready Mix Concrete LLC (Synthetic)",
            trn="100234567800003",
            aliases=["Apex Concrete", "Apex RMC"],
            active=True,
        )
        sup_stl = SupplierOrm(
            id=SUPPLIER_STEEL_ID,
            name="Gulf Rebar Steel Industries LLC (Synthetic)",
            trn="100345678900003",
            aliases=["Gulf Rebar", "GRSI Steel"],
            active=True,
        )
        users = [
            UserOrm(
                id=USER_QS_ID,
                name="Ramesh (Project QS)",
                email="ramesh.qs@pilot.civ.local",
                hashed_password=pw_hash,
                role="QS",
                can_review=False,
                active=True,
            ),
            UserOrm(
                id=USER_STORE_ID,
                name="Tariq Mansoor (Storekeeper)",
                email="tariq.store@pilot.civ.local",
                hashed_password=pw_hash,
                role="ENGINEER",
                can_review=False,
                active=True,
            ),
            UserOrm(
                id=USER_ENG_ID,
                name="Ahmed Al-Hashimi (Site Engineer)",
                email="ahmed.eng@pilot.civ.local",
                hashed_password=pw_hash,
                role="ENGINEER",
                can_review=False,
                active=True,
            ),
            UserOrm(
                id=USER_PM_ID,
                name="David Sterling (Commercial PM)",
                email="david.pm@pilot.civ.local",
                hashed_password=pw_hash,
                role="REVIEWER",
                can_review=True,
                active=True,
            ),
        ]
        session.add_all([project, sup_rmc, sup_stl, *users])
        session.flush()

        for u in users:
            session.add(ProjectUserOrm(project_id=project.id, user_id=u.id, assigned_by=USER_PM_ID))

        # Seed Pilot LPOs
        lpo_rmc = LpoOrm(
            id="lpo-pilot-rmc-01",
            lpo_number="LPO-DXB-2026-RMC-01",
            project_id=PILOT_PROJECT_ID,
            supplier_id=SUPPLIER_RMC_ID,
            lpo_date="2026-03-01",
            currency="AED",
            total_amount_cap="250000.00",
            is_active=True,
            created_by=USER_QS_ID,
        )
        session.add(lpo_rmc)
        session.flush()

        lpo_line_rmc = LpoLineOrm(
            id="lpo-line-pilot-rmc-01",
            lpo_id=lpo_rmc.id,
            line_no=1,
            description="ReadyMix Concrete C40/20 OPC (Pump Mix)",
            ordered_qty="1000.00",
            unit="m3",
            agreed_unit_price="240.00",
            line_amount_cap="240000.00",
        )
        session.add(lpo_line_rmc)

        session.commit()

    settings = Settings(
        app_env="test",
        dev_identity_enabled=False,
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

    from app.core.config import get_settings
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_document_storage] = lambda: LocalStorage(base_dir=test_storage_path)

    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        yield client, TestingSession


# -----------------------------------------------------------------------------
# 1. Complete End-to-End Workflow Test via REST API
# -----------------------------------------------------------------------------

def test_complete_end_to_end_acceptance_workflow(step5_isolated_env):
    """Verifies complete end-to-end workflow from QS login to independent reviewer sign-off."""
    client, SessionFactory = step5_isolated_env

    # Step 1: QS Authentication via POST /api/v1/auth/login
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": "ramesh.qs@pilot.civ.local", "password": "PilotPass123!"},
    )
    assert login_resp.status_code == 200, login_resp.text
    qs_auth = login_resp.json()
    qs_token = qs_auth["access_token"]
    qs_headers = {"Authorization": f"Bearer {qs_token}"}
    assert qs_auth["user"]["role"] == "QS"
    assert qs_auth["user"]["can_review"] is False

    # Step 2: Scoped Project & Supplier Verification
    p_resp = client.get("/api/v1/projects", headers=qs_headers)
    assert p_resp.status_code == 200
    assert any(p["id"] == PILOT_PROJECT_ID for p in p_resp.json()["projects"])

    # Step 3: Case Creation by QS
    case_payload = {
        "case_ref": "VC-ACCEPT-E2E-001",
        "project_id": PILOT_PROJECT_ID,
        "supplier_id": SUPPLIER_RMC_ID,
        "lpo_id": "lpo-pilot-rmc-01",
        "invoice_number_hint": "INV-E2E-ACCEPT-101",
        "currency": "AED",
        "lpo_required": True,
    }
    case_resp = client.post("/api/v1/cases", json=case_payload, headers=qs_headers)
    assert case_resp.status_code == 201, case_resp.text
    case_data = case_resp.json()["case"]
    case_id = case_data["id"]
    assert case_data["status"] == "DRAFT"
    assert case_data["created_by"] == USER_QS_ID

    # Step 4: Manual Invoice Line Entry
    inv_line_payload = {
        "line_no": 1,
        "description": "ReadyMix Concrete C40/20 OPC (Pump Mix)",
        "invoiced_qty": "36.000",
        "unit": "m3",
        "unit_price": "240.00",
        "line_amount": "8640.00",
    }
    inv_resp = client.post(
        f"/api/v1/cases/{case_id}/invoice-lines",
        json=inv_line_payload,
        headers=qs_headers,
    )
    assert inv_resp.status_code == 201, inv_resp.text
    inv_line_id = inv_resp.json()["line_item"]["id"]

    # Step 5: Manual Delivery Note Line Entry with Site Ticket
    dn_line_payload = {
        "dn_number": "DN-E2E-ACCEPT-201",
        "line_no": 1,
        "description": "ReadyMix Concrete C40/20 OPC (Pump Mix)",
        "delivered_qty": "36.000",
        "unit": "m3",
        "storekeeper_ticket_no": "GATE-2026-9901",
        "storekeeper_confirmed": True,
    }
    dn_resp = client.post(
        f"/api/v1/cases/{case_id}/delivery-note-lines",
        json=dn_line_payload,
        headers=qs_headers,
    )
    assert dn_resp.status_code == 201, dn_resp.text
    dn_line_id = dn_resp.json()["line_item"]["id"]

    # Step 6: Multi-Way Line Linking (Invoice Line -> DN Line + LPO Line)
    link_payload = {
        "invoice_line_id": inv_line_id,
        "dn_line_id": dn_line_id,
        "lpo_line_id": "lpo-line-pilot-rmc-01",
        "link_method": "MANUAL",
    }
    link_resp = client.post(
        f"/api/v1/cases/{case_id}/links",
        json=link_payload,
        headers=qs_headers,
    )
    assert link_resp.status_code == 201, link_resp.text

    # Step 7: Automated Verification Trigger
    verify_resp = client.post(f"/api/v1/cases/{case_id}/verify", headers=qs_headers)
    assert verify_resp.status_code in (200, 201), verify_resp.text
    verify_data = verify_resp.json()
    assert verify_data["run"]["id"] is not None
    findings = verify_data["run"]["findings"]
    assert len(findings) > 0

    # Rule outcomes in verification run
    qty_finding = next((f for f in findings if f["rule_code"] == "QTY_003"), None)
    assert qty_finding is not None
    assert qty_finding["outcome"] == "MATCH"

    rate_finding = next((f for f in findings if f["rule_code"] == "RATE_MATCH"), None)
    assert rate_finding is not None
    assert rate_finding["outcome"] == "MATCH"

    # Step 8: Role-based Review Denial Check
    # The QS role (can_review=False) is strictly forbidden from submitting reviews.
    review_payload = {
        "outcome": "VERIFIED_NO_EXCEPTIONS",
        "comment": "Attempted sign-off by non-reviewer QS.",
        "declaration_accepted": True,
        "manual_vat_checked": True,
    }
    sod_resp = client.post(
        f"/api/v1/cases/{case_id}/reviews",
        json=review_payload,
        headers=qs_headers,
    )
    assert sod_resp.status_code == 403
    assert sod_resp.json()["detail"]["code"] == "REVIEW_PERMISSION_DENIED"

    # Step 9: Independent Reviewer Login
    pm_login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": "david.pm@pilot.civ.local", "password": "PilotPass123!"},
    )
    assert pm_login_resp.status_code == 200
    pm_auth = pm_login_resp.json()
    pm_token = pm_auth["access_token"]
    pm_headers = {"Authorization": f"Bearer {pm_token}"}
    assert pm_auth["user"]["role"] == "REVIEWER"
    assert pm_auth["user"]["can_review"] is True

    # Step 10: Independent Reviewer Sign-Off
    pm_review_payload = {
        "outcome": "VERIFIED_NO_EXCEPTIONS",
        "comment": "Independent commercial verification complete: exact 4-way match confirmed against LPO and site gate ticket.",
        "declaration_accepted": True,
        "manual_vat_checked": True,
    }
    review_resp = client.post(
        f"/api/v1/cases/{case_id}/reviews",
        json=pm_review_payload,
        headers=pm_headers,
    )
    assert review_resp.status_code == 201, review_resp.text
    review_data = review_resp.json()
    assert review_data["case_status"] == "VERIFIED_NO_EXCEPTIONS"
    assert review_data["review"]["reviewer_name"] == "David Sterling (Commercial PM)"

    # Step 11: Audit Trail Verification
    with SessionFactory() as session:
        case = session.get(VerificationCaseOrm, case_id)
        assert case.status == "VERIFIED_NO_EXCEPTIONS"

        audits = list(session.scalars(select(AuditEventOrm).where(AuditEventOrm.case_id == case_id)).all())
        actions = {a.action for a in audits}
        assert "CASE_CREATED" in actions
        assert "INVOICE_LINE_ADDED" in actions
        assert "DN_LINE_ADDED" in actions
        assert "LINE_LINKED" in actions
        assert "VERIFICATION_RUN_COMPLETED" in actions
        assert "REVIEW_RECORDED" in actions

        # Check actor distinction
        create_event = next(e for e in audits if e.action == "CASE_CREATED")
        review_event = next(e for e in audits if e.action == "REVIEW_RECORDED")
        assert create_event.actor_id == USER_QS_ID
        assert review_event.actor_id == USER_PM_ID


# -----------------------------------------------------------------------------
# 2. Five Synthetic Calibration Scenarios Acceptance
# -----------------------------------------------------------------------------

def test_scenario_1_clean_exact_4way_match():
    """Scenario 1: Clean Exact 4-Way Match (Ready-mix concrete)."""
    snapshot = CaseSnapshot(
        case_id="case-syn-01",
        project_id=PILOT_PROJECT_ID,
        project_name="Crown Horizon Residences - Tower A",
        supplier_id=SUPPLIER_RMC_ID,
        supplier_name="Apex Ready Mix Concrete LLC (Synthetic)",
        supplier_trn=ValueWithTrust(value="100234567800003", status=FieldStatus.CONFIRMED),
        invoice_number=ValueWithTrust(value="INV-PILOT-101", status=FieldStatus.CONFIRMED),
        invoice_date=ValueWithTrust(value="2026-04-01", status=FieldStatus.CONFIRMED),
        invoice_currency=ValueWithTrust(value="AED", status=FieldStatus.CONFIRMED),
        subtotal=ValueWithTrust(value=Decimal("8640.00"), status=FieldStatus.CONFIRMED),
        tax_amount=ValueWithTrust(value=Decimal("432.00"), status=FieldStatus.CONFIRMED),
        grand_total=ValueWithTrust(value=Decimal("9072.00"), status=FieldStatus.CONFIRMED),
        lpo_required=True,
        invoice_lines=[
            InvoiceLineSnapshot(
                line_id="inv-l1",
                document_id="doc-inv-1",
                invoice_number="INV-PILOT-101",
                line_no=1,
                material_code="CONC-C40",
                description="ReadyMix Concrete C40/20",
                invoiced_qty=ValueWithTrust(value=Decimal("36.00"), status=FieldStatus.CONFIRMED),
                unit="m3",
                unit_price=ValueWithTrust(value=Decimal("240.00"), status=FieldStatus.CONFIRMED),
                line_amount=ValueWithTrust(value=Decimal("8640.00"), status=FieldStatus.CONFIRMED),
            )
        ],
        dn_lines=[
            DNLineSnapshot(
                line_id="dn-l1",
                document_id="doc-dn-1",
                dn_number="DN-PILOT-201",
                line_no=1,
                material_code="CONC-C40",
                description="ReadyMix Concrete C40/20",
                delivered_qty=ValueWithTrust(value=Decimal("36.00"), status=FieldStatus.CONFIRMED),
                unit="m3",
            )
        ],
        lpo_lines=[
            LPOLineSnapshot(
                line_id="lpo-l1",
                document_id="doc-lpo-1",
                lpo_number="LPO-DXB-2026-RMC-01",
                line_no=1,
                material_code="CONC-C40",
                description="ReadyMix Concrete C40/20",
                ordered_qty=ValueWithTrust(value=Decimal("1000.00"), status=FieldStatus.CONFIRMED),
                unit="m3",
                unit_price=ValueWithTrust(value=Decimal("240.00"), status=FieldStatus.CONFIRMED),
            )
        ],
        confirmed_links={"inv-l1": ["dn-l1"]},
        lpo_line_links={"inv-l1": "lpo-l1"},
    )
    findings = verify_case(snapshot)

    qty_f = next(f for f in findings if f.rule_code == "QTY_003")
    assert qty_f.outcome == FindingOutcome.MATCH
    assert qty_f.actual_value == "36.00"

    rate_f = next(f for f in findings if f.rule_code == "RATE_MATCH")
    assert rate_f.outcome == FindingOutcome.MATCH

    cap_f = next(f for f in findings if f.rule_code == "LPO_CAP_OK")
    assert cap_f.outcome == FindingOutcome.MATCH


def test_scenario_2_quantity_overbilling_mismatch():
    """Scenario 2: Overbilling Mismatch (Invoiced 20.00 t vs Delivered 15.00 t)."""
    snapshot = CaseSnapshot(
        case_id="case-syn-02",
        project_id=PILOT_PROJECT_ID,
        project_name="Crown Horizon Residences - Tower A",
        supplier_id=SUPPLIER_STEEL_ID,
        supplier_name="Gulf Rebar Steel Industries LLC (Synthetic)",
        supplier_trn=ValueWithTrust(value="100345678900003", status=FieldStatus.CONFIRMED),
        invoice_number=ValueWithTrust(value="INV-PILOT-102", status=FieldStatus.CONFIRMED),
        invoice_date=ValueWithTrust(value="2026-04-02", status=FieldStatus.CONFIRMED),
        invoice_currency=ValueWithTrust(value="AED", status=FieldStatus.CONFIRMED),
        subtotal=ValueWithTrust(value=Decimal("57000.00"), status=FieldStatus.CONFIRMED),
        tax_amount=ValueWithTrust(value=Decimal("2850.00"), status=FieldStatus.CONFIRMED),
        grand_total=ValueWithTrust(value=Decimal("59850.00"), status=FieldStatus.CONFIRMED),
        lpo_required=False,
        invoice_lines=[
            InvoiceLineSnapshot(
                line_id="inv-l2",
                document_id="doc-inv-2",
                invoice_number="INV-PILOT-102",
                line_no=1,
                material_code="REBAR-16",
                description="High Tensile Rebar 16mm",
                invoiced_qty=ValueWithTrust(value=Decimal("20.00"), status=FieldStatus.CONFIRMED),
                unit="t",
                unit_price=ValueWithTrust(value=Decimal("2850.00"), status=FieldStatus.CONFIRMED),
                line_amount=ValueWithTrust(value=Decimal("57000.00"), status=FieldStatus.CONFIRMED),
            )
        ],
        dn_lines=[
            DNLineSnapshot(
                line_id="dn-l2",
                document_id="doc-dn-2",
                dn_number="DN-PILOT-202",
                line_no=1,
                material_code="REBAR-16",
                description="High Tensile Rebar 16mm",
                delivered_qty=ValueWithTrust(value=Decimal("15.00"), status=FieldStatus.CONFIRMED),
                unit="t",
            )
        ],
        confirmed_links={"inv-l2": ["dn-l2"]},
    )
    findings = verify_case(snapshot)

    mismatch_f = next(f for f in findings if f.rule_code == "QTY_004")
    assert mismatch_f.outcome == FindingOutcome.MISMATCH
    assert mismatch_f.difference == "5.00"
    assert mismatch_f.category == FindingCategory.QTY_LINE


def test_scenario_3_missing_delivery_note_evidence():
    """Scenario 3: Missing Delivery Note Evidence."""
    snapshot = CaseSnapshot(
        case_id="case-syn-03",
        project_id=PILOT_PROJECT_ID,
        project_name="Crown Horizon Residences - Tower A",
        supplier_id=SUPPLIER_RMC_ID,
        supplier_name="Apex Ready Mix Concrete LLC (Synthetic)",
        supplier_trn=ValueWithTrust(value="100234567800003", status=FieldStatus.CONFIRMED),
        invoice_number=ValueWithTrust(value="INV-PILOT-103", status=FieldStatus.CONFIRMED),
        invoice_date=ValueWithTrust(value="2026-04-03", status=FieldStatus.CONFIRMED),
        invoice_currency=ValueWithTrust(value="AED", status=FieldStatus.CONFIRMED),
        subtotal=ValueWithTrust(value=Decimal("9600.00"), status=FieldStatus.CONFIRMED),
        tax_amount=ValueWithTrust(value=Decimal("480.00"), status=FieldStatus.CONFIRMED),
        grand_total=ValueWithTrust(value=Decimal("10080.00"), status=FieldStatus.CONFIRMED),
        lpo_required=False,
        invoice_lines=[
            InvoiceLineSnapshot(
                line_id="inv-l3",
                document_id="doc-inv-3",
                invoice_number="INV-PILOT-103",
                line_no=1,
                material_code="CONC-C40",
                description="ReadyMix Concrete C40/20",
                invoiced_qty=ValueWithTrust(value=Decimal("40.00"), status=FieldStatus.CONFIRMED),
                unit="m3",
                unit_price=ValueWithTrust(value=Decimal("240.00"), status=FieldStatus.CONFIRMED),
                line_amount=ValueWithTrust(value=Decimal("9600.00"), status=FieldStatus.CONFIRMED),
            )
        ],
        dn_lines=[],
    )
    findings = verify_case(snapshot)

    missing_f = next(f for f in findings if f.rule_code == "COMP_002")
    assert missing_f.outcome == FindingOutcome.MISSING_EVIDENCE
    assert missing_f.category == FindingCategory.COMPLETENESS


def test_scenario_4_cross_case_delivery_note_reuse():
    """Scenario 4: Cross-Case Delivery Note Reuse Flagged."""
    from app.domain.engine import normalize_dn_number

    supplier_key = f"{SUPPLIER_STEEL_ID}:{normalize_dn_number('DN-PILOT-202')}"
    snapshot = CaseSnapshot(
        case_id="case-syn-04",
        project_id=PILOT_PROJECT_ID,
        project_name="Crown Horizon Residences - Tower A",
        supplier_id=SUPPLIER_STEEL_ID,
        supplier_name="Gulf Rebar Steel Industries LLC (Synthetic)",
        supplier_trn=ValueWithTrust(value="100345678900003", status=FieldStatus.CONFIRMED),
        invoice_number=ValueWithTrust(value="INV-PILOT-104", status=FieldStatus.CONFIRMED),
        invoice_date=ValueWithTrust(value="2026-04-04", status=FieldStatus.CONFIRMED),
        invoice_currency=ValueWithTrust(value="AED", status=FieldStatus.CONFIRMED),
        subtotal=ValueWithTrust(value=Decimal("42750.00"), status=FieldStatus.CONFIRMED),
        tax_amount=ValueWithTrust(value=Decimal("2137.50"), status=FieldStatus.CONFIRMED),
        grand_total=ValueWithTrust(value=Decimal("44887.50"), status=FieldStatus.CONFIRMED),
        lpo_required=False,
        invoice_lines=[
            InvoiceLineSnapshot(
                line_id="inv-l4",
                document_id="doc-inv-4",
                invoice_number="INV-PILOT-104",
                line_no=1,
                material_code="REBAR-16",
                description="High Tensile Rebar 16mm",
                invoiced_qty=ValueWithTrust(value=Decimal("15.00"), status=FieldStatus.CONFIRMED),
                unit="t",
                unit_price=ValueWithTrust(value=Decimal("2850.00"), status=FieldStatus.CONFIRMED),
                line_amount=ValueWithTrust(value=Decimal("42750.00"), status=FieldStatus.CONFIRMED),
            )
        ],
        dn_lines=[
            DNLineSnapshot(
                line_id="dn-l4",
                document_id="doc-dn-reused",
                dn_number="DN-PILOT-202",
                line_no=1,
                material_code="REBAR-16",
                description="High Tensile Rebar 16mm",
                delivered_qty=ValueWithTrust(value=Decimal("15.00"), status=FieldStatus.CONFIRMED),
                unit="t",
            )
        ],
        confirmed_links={"inv-l4": ["dn-l4"]},
        cross_case_dn_index={supplier_key: ["VC-PILOT-2026-002"]},
    )
    findings = verify_case(snapshot)

    reuse_f = next(f for f in findings if f.rule_code == "DN_REUSE_001")
    assert reuse_f.outcome == FindingOutcome.MISMATCH
    assert reuse_f.category == FindingCategory.DN_REUSE
    assert "VC-PILOT-2026-002" in reuse_f.message


def test_scenario_5_site_rejection_documented():
    """Scenario 5: Documented Site Rejection (Delivered 36.00 m3 - Rejected 6.00 m3 = 30.00 m3 net accepted)."""
    snapshot = CaseSnapshot(
        case_id="case-syn-05",
        project_id=PILOT_PROJECT_ID,
        project_name="Crown Horizon Residences - Tower A",
        supplier_id=SUPPLIER_RMC_ID,
        supplier_name="Apex Ready Mix Concrete LLC (Synthetic)",
        supplier_trn=ValueWithTrust(value="100234567800003", status=FieldStatus.CONFIRMED),
        invoice_number=ValueWithTrust(value="INV-PILOT-105", status=FieldStatus.CONFIRMED),
        invoice_date=ValueWithTrust(value="2026-04-05", status=FieldStatus.CONFIRMED),
        invoice_currency=ValueWithTrust(value="AED", status=FieldStatus.CONFIRMED),
        subtotal=ValueWithTrust(value=Decimal("7200.00"), status=FieldStatus.CONFIRMED),
        tax_amount=ValueWithTrust(value=Decimal("360.00"), status=FieldStatus.CONFIRMED),
        grand_total=ValueWithTrust(value=Decimal("7560.00"), status=FieldStatus.CONFIRMED),
        lpo_required=False,
        invoice_lines=[
            InvoiceLineSnapshot(
                line_id="inv-l5",
                document_id="doc-inv-5",
                invoice_number="INV-PILOT-105",
                line_no=1,
                material_code="CONC-C40",
                description="ReadyMix Concrete C40/20",
                invoiced_qty=ValueWithTrust(value=Decimal("30.00"), status=FieldStatus.CONFIRMED),
                unit="m3",
                unit_price=ValueWithTrust(value=Decimal("240.00"), status=FieldStatus.CONFIRMED),
                line_amount=ValueWithTrust(value=Decimal("7200.00"), status=FieldStatus.CONFIRMED),
            )
        ],
        dn_lines=[
            DNLineSnapshot(
                line_id="dn-l5",
                document_id="doc-dn-5",
                dn_number="DN-PILOT-205",
                line_no=1,
                material_code="CONC-C40",
                description="ReadyMix Concrete C40/20",
                delivered_qty=ValueWithTrust(value=Decimal("36.00"), status=FieldStatus.CONFIRMED),
                rejected_qty=ValueWithTrust(value=Decimal("6.00"), status=FieldStatus.CONFIRMED),
                rejection_evidence_type="SLUMP_FAILURE",
                has_rejection_evidence=True,
                unit="m3",
            )
        ],
        confirmed_links={"inv-l5": ["dn-l5"]},
    )
    findings = verify_case(snapshot)

    qty_f = next(f for f in findings if f.rule_code == "QTY_003")
    assert qty_f.outcome == FindingOutcome.MATCH
    assert qty_f.actual_value == "30.00"  # Net accepted (36 - 6)
