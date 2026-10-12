"""Unit and Integration Tests for Milestone M4C Phase 2 Synthetic Ingestion Path.

Tests:
1. Successful ingestion across all 5 synthetic calibration cases.
2. Invariant preservation (LPO cap, exact decimal matching, DN reuse detection, site rejection).
3. Duplicate execution prevention (aborts safely without creating duplicate records).
4. Missing prerequisite handling (invalid project, supplier, or user references).
5. Engine verification behavior over all 5 ingested cases.
"""

from __future__ import annotations

from decimal import Decimal
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

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
from app.persistence.database import Base
from app.persistence.models import (
    AuditEventOrm,
    DocumentOrm,
    LineItemOrm,
    LineLinkOrm,
    LpoOrm,
    ProjectOrm,
    ProjectUserOrm,
    SupplierOrm,
    UserOrm,
    VerificationCaseOrm,
)
from scripts.ingest_synthetic_pilot_cases import (
    PILOT_PROJECT_ID,
    SUPPLIER_RMC_ID,
    SUPPLIER_STEEL_ID,
    USER_ENG_ID,
    USER_PM_ID,
    USER_QS_ID,
    USER_STORE_ID,
    SyntheticIngestionError,
    ingest_synthetic_pilot_cases,
)


@pytest.fixture
def isolated_pilot_db():
    """Create an isolated in-memory SQLite database pre-populated with Phase 1 groundwork."""
    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys = ON;")

    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    # Seed Phase 1 Groundwork Entities
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
        UserOrm(id=USER_QS_ID, name="Ramesh (Project QS)", email="ramesh.qs@pilot.civ.local", role="QS", can_review=False, active=True),
        UserOrm(id=USER_STORE_ID, name="Tariq Mansoor", email="tariq.store@pilot.civ.local", role="ENGINEER", can_review=False, active=True),
        UserOrm(id=USER_ENG_ID, name="Ahmed Al-Hashimi", email="ahmed.eng@pilot.civ.local", role="ENGINEER", can_review=False, active=True),
        UserOrm(id=USER_PM_ID, name="David Sterling", email="david.pm@pilot.civ.local", role="REVIEWER", can_review=True, active=True),
    ]

    session.add_all([project, sup_rmc, sup_stl, *users])
    session.flush()

    for u in users:
        session.add(ProjectUserOrm(project_id=project.id, user_id=u.id, assigned_by=USER_PM_ID))

    session.commit()
    yield session
    session.close()


def test_successful_synthetic_ingestion(isolated_pilot_db):
    """Verify clean ingestion of all 5 synthetic cases and associated LPOs/links."""
    res = ingest_synthetic_pilot_cases(isolated_pilot_db, stop_on_duplicates=True)
    assert res["cases"] == 5
    assert res["lpos"] == 2
    assert res["documents"] == 9
    assert res["line_items"] == 9
    assert res["line_links"] == 4

    # Verify cases in DB
    cases = isolated_pilot_db.scalars(select(VerificationCaseOrm)).all()
    assert len(cases) == 5
    case_refs = {c.case_ref for c in cases}
    assert case_refs == {
        "VC-PILOT-2026-001",
        "VC-PILOT-2026-002",
        "VC-PILOT-2026-003",
        "VC-PILOT-2026-004",
        "VC-PILOT-2026-005",
    }

    # Verify LPOs exist
    lpos = isolated_pilot_db.scalars(select(LpoOrm)).all()
    assert len(lpos) == 2


def test_duplicate_ingestion_aborts_safely(isolated_pilot_db):
    """Running ingestion a second time must detect existing cases and abort safely."""
    ingest_synthetic_pilot_cases(isolated_pilot_db, stop_on_duplicates=True)

    with pytest.raises(SyntheticIngestionError) as exc_info:
        ingest_synthetic_pilot_cases(isolated_pilot_db, stop_on_duplicates=True)

    assert "Duplicate ingestion prevented" in str(exc_info.value)

    # When stop_on_duplicates=False, returns ALREADY_PROVISIONED summary
    res = ingest_synthetic_pilot_cases(isolated_pilot_db, stop_on_duplicates=False)
    assert res["status"] == "ALREADY_PROVISIONED"
    assert res["cases_count"] == 5


def test_missing_prerequisites_raises_error():
    """Ingestion fails immediately if groundwork project or users are missing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    empty_db = Session()

    with pytest.raises(SyntheticIngestionError) as exc:
        ingest_synthetic_pilot_cases(empty_db, stop_on_duplicates=True)

    assert "Precondition failed: Pilot project" in str(exc.value)
    empty_db.close()


def test_case_1_clean_exact_4way_match_behavior(isolated_pilot_db):
    """Case 1 must result in clean EXACT MATCH across LPO, DN, site receipt, and invoice."""
    ingest_synthetic_pilot_cases(isolated_pilot_db)

    c1 = isolated_pilot_db.get(VerificationCaseOrm, "case-pilot-syn-01")
    assert c1 is not None

    inv_line = isolated_pilot_db.get(LineItemOrm, "li-p1-inv-1")
    dn_line = isolated_pilot_db.get(LineItemOrm, "li-p1-dn-1")
    lpo = isolated_pilot_db.get(LpoOrm, "lpo-pilot-rmc-01")
    lpo_line = lpo.lines[0]

    # Verify Site Acceptance Metadata is fully recorded
    assert dn_line.storekeeper_confirmed is True
    assert dn_line.engineer_verified is True
    assert dn_line.storekeeper_ticket_no == "GATE-2026-0881"

    # Build snapshot and verify via domain engine
    snapshot = CaseSnapshot(
        case_id=c1.id,
        project_id=c1.project_id,
        project_name=c1.project.name,
        supplier_id=c1.supplier_id,
        supplier_name=c1.supplier.name,
        supplier_trn=ValueWithTrust(value=c1.supplier.trn, status=FieldStatus.CONFIRMED),
        invoice_number=ValueWithTrust(value=c1.invoice_number_hint, status=FieldStatus.CONFIRMED),
        invoice_date=ValueWithTrust(value="2026-04-01", status=FieldStatus.CONFIRMED),
        invoice_currency=ValueWithTrust(value="AED", status=FieldStatus.CONFIRMED),
        subtotal=ValueWithTrust(value=Decimal("8640.00"), status=FieldStatus.CONFIRMED),
        tax_amount=ValueWithTrust(value=Decimal("432.00"), status=FieldStatus.CONFIRMED),
        grand_total=ValueWithTrust(value=Decimal("9072.00"), status=FieldStatus.CONFIRMED),
        lpo_required=True,
        invoice_lines=[
            InvoiceLineSnapshot(
                line_id=inv_line.id,
                document_id="doc-p1-inv-101",
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
                line_id=dn_line.id,
                document_id="doc-p1-dn-201",
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
                line_id=lpo_line.id,
                document_id="doc-lpo-rmc",
                lpo_number=lpo.lpo_number,
                line_no=1,
                material_code="CONC-C40",
                description=lpo_line.description,
                ordered_qty=ValueWithTrust(value=Decimal(lpo_line.ordered_qty), status=FieldStatus.CONFIRMED),
                unit="m3",
                unit_price=ValueWithTrust(value=Decimal(lpo_line.agreed_unit_price), status=FieldStatus.CONFIRMED),
            )
        ],
        confirmed_links={inv_line.id: [dn_line.id]},
        lpo_line_links={inv_line.id: lpo_line.id},
    )

    findings = verify_case(snapshot)

    qty_finding = next((f for f in findings if f.rule_code == "QTY_003"), None)
    assert qty_finding is not None
    assert qty_finding.outcome == FindingOutcome.MATCH

    rate_finding = next((f for f in findings if f.rule_code == "RATE_MATCH"), None)
    assert rate_finding is not None
    assert rate_finding.outcome == FindingOutcome.MATCH

    cap_finding = next((f for f in findings if f.rule_code == "LPO_CAP_OK"), None)
    assert cap_finding is not None
    assert cap_finding.outcome == FindingOutcome.MATCH


def test_case_2_overbilling_mismatch_detected(isolated_pilot_db):
    """Case 2 must flag QTY_004 MISMATCH for 5.00 t overbilling."""
    ingest_synthetic_pilot_cases(isolated_pilot_db)

    c2 = isolated_pilot_db.get(VerificationCaseOrm, "case-pilot-syn-02")
    inv_line = isolated_pilot_db.get(LineItemOrm, "li-p2-inv-1")
    dn_line = isolated_pilot_db.get(LineItemOrm, "li-p2-dn-1")

    # Invoiced 20.00 t vs Delivered 15.00 t
    snapshot = CaseSnapshot(
        case_id=c2.id,
        project_id=c2.project_id,
        project_name=c2.project.name,
        supplier_id=c2.supplier_id,
        supplier_name=c2.supplier.name,
        supplier_trn=ValueWithTrust(value=c2.supplier.trn, status=FieldStatus.CONFIRMED),
        invoice_number=ValueWithTrust(value=c2.invoice_number_hint, status=FieldStatus.CONFIRMED),
        invoice_date=ValueWithTrust(value="2026-04-02", status=FieldStatus.CONFIRMED),
        invoice_currency=ValueWithTrust(value="AED", status=FieldStatus.CONFIRMED),
        subtotal=ValueWithTrust(value=Decimal("57000.00"), status=FieldStatus.CONFIRMED),
        tax_amount=ValueWithTrust(value=Decimal("2850.00"), status=FieldStatus.CONFIRMED),
        grand_total=ValueWithTrust(value=Decimal("59850.00"), status=FieldStatus.CONFIRMED),
        lpo_required=False,
        invoice_lines=[
            InvoiceLineSnapshot(
                line_id=inv_line.id,
                document_id="doc-p2-inv-102",
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
                line_id=dn_line.id,
                document_id="doc-p2-dn-202",
                dn_number="DN-PILOT-202",
                line_no=1,
                material_code="REBAR-16",
                description="High Tensile Rebar 16mm",
                delivered_qty=ValueWithTrust(value=Decimal("15.00"), status=FieldStatus.CONFIRMED),
                unit="t",
            )
        ],
        confirmed_links={inv_line.id: [dn_line.id]},
    )

    findings = verify_case(snapshot)
    mismatch = next((f for f in findings if f.rule_code == "QTY_004"), None)
    assert mismatch is not None
    assert mismatch.outcome == FindingOutcome.MISMATCH
    assert mismatch.difference == "5.00"


def test_case_3_missing_delivery_note_evidence(isolated_pilot_db):
    """Case 3 must flag COMP_002 MISSING_EVIDENCE when no delivery notes are present."""
    ingest_synthetic_pilot_cases(isolated_pilot_db)

    c3 = isolated_pilot_db.get(VerificationCaseOrm, "case-pilot-syn-03")
    inv_line = isolated_pilot_db.get(LineItemOrm, "li-p3-inv-1")

    snapshot = CaseSnapshot(
        case_id=c3.id,
        project_id=c3.project_id,
        project_name=c3.project.name,
        supplier_id=c3.supplier_id,
        supplier_name=c3.supplier.name,
        supplier_trn=ValueWithTrust(value=c3.supplier.trn, status=FieldStatus.CONFIRMED),
        invoice_number=ValueWithTrust(value=c3.invoice_number_hint, status=FieldStatus.CONFIRMED),
        invoice_date=ValueWithTrust(value="2026-04-03", status=FieldStatus.CONFIRMED),
        invoice_currency=ValueWithTrust(value="AED", status=FieldStatus.CONFIRMED),
        subtotal=ValueWithTrust(value=Decimal("9600.00"), status=FieldStatus.CONFIRMED),
        tax_amount=ValueWithTrust(value=Decimal("480.00"), status=FieldStatus.CONFIRMED),
        grand_total=ValueWithTrust(value=Decimal("10080.00"), status=FieldStatus.CONFIRMED),
        lpo_required=False,
        invoice_lines=[
            InvoiceLineSnapshot(
                line_id=inv_line.id,
                document_id="doc-p3-inv-103",
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
        dn_lines=[],  # No delivery notes
    )

    findings = verify_case(snapshot)
    missing = next((f for f in findings if f.rule_code == "COMP_002"), None)
    assert missing is not None
    assert missing.outcome == FindingOutcome.MISSING_EVIDENCE
    assert missing.category == FindingCategory.COMPLETENESS


def test_case_4_cross_case_dn_reuse_detected(isolated_pilot_db):
    """Case 4 must flag DN_REUSE_001 when DN-PILOT-202 was already linked in Case 2."""
    ingest_synthetic_pilot_cases(isolated_pilot_db)

    c4 = isolated_pilot_db.get(VerificationCaseOrm, "case-pilot-syn-04")
    inv_line = isolated_pilot_db.get(LineItemOrm, "li-p4-inv-1")
    dn_line = isolated_pilot_db.get(LineItemOrm, "li-p4-dn-1")

    # Cross-case reuse index: engine uses normalize_dn_number("DN-PILOT-202") -> "DNPILOT202"
    from app.domain.engine import normalize_dn_number
    supplier_key = f"{c4.supplier_id}:{normalize_dn_number('DN-PILOT-202')}"
    snapshot = CaseSnapshot(
        case_id=c4.id,
        project_id=c4.project_id,
        project_name=c4.project.name,
        supplier_id=c4.supplier_id,
        supplier_name=c4.supplier.name,
        supplier_trn=ValueWithTrust(value=c4.supplier.trn, status=FieldStatus.CONFIRMED),
        invoice_number=ValueWithTrust(value=c4.invoice_number_hint, status=FieldStatus.CONFIRMED),
        invoice_date=ValueWithTrust(value="2026-04-04", status=FieldStatus.CONFIRMED),
        invoice_currency=ValueWithTrust(value="AED", status=FieldStatus.CONFIRMED),
        subtotal=ValueWithTrust(value=Decimal("42750.00"), status=FieldStatus.CONFIRMED),
        tax_amount=ValueWithTrust(value=Decimal("2137.50"), status=FieldStatus.CONFIRMED),
        grand_total=ValueWithTrust(value=Decimal("44887.50"), status=FieldStatus.CONFIRMED),
        lpo_required=False,
        invoice_lines=[
            InvoiceLineSnapshot(
                line_id=inv_line.id,
                document_id="doc-p4-inv-104",
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
                line_id=dn_line.id,
                document_id="doc-p4-dn-202-reused",
                dn_number="DN-PILOT-202",
                line_no=1,
                material_code="REBAR-16",
                description="High Tensile Rebar 16mm",
                delivered_qty=ValueWithTrust(value=Decimal("15.00"), status=FieldStatus.CONFIRMED),
                unit="t",
            )
        ],
        confirmed_links={inv_line.id: [dn_line.id]},
        cross_case_dn_index={supplier_key: ["VC-PILOT-2026-002"]},
    )

    findings = verify_case(snapshot)
    reuse = next((f for f in findings if f.rule_code == "DN_REUSE_001"), None)
    assert reuse is not None
    assert reuse.category == FindingCategory.DN_REUSE
    assert reuse.outcome == FindingOutcome.MISMATCH
    assert "VC-PILOT-2026-002" in reuse.message


def test_case_5_site_rejection_with_documented_evidence(isolated_pilot_db):
    """Case 5: Delivered 36.00 m3 - Rejected 6.00 m3 = 30.00 m3 net accepted. Matches 30.00 m3 invoice."""
    ingest_synthetic_pilot_cases(isolated_pilot_db)

    c5 = isolated_pilot_db.get(VerificationCaseOrm, "case-pilot-syn-05")
    inv_line = isolated_pilot_db.get(LineItemOrm, "li-p5-inv-1")
    dn_line = isolated_pilot_db.get(LineItemOrm, "li-p5-dn-1")

    assert dn_line.has_rejection_evidence is True
    assert dn_line.rejection_reason_code == "SLUMP_FAILURE"
    assert dn_line.rejected_qty == "6.00"

    snapshot = CaseSnapshot(
        case_id=c5.id,
        project_id=c5.project_id,
        project_name=c5.project.name,
        supplier_id=c5.supplier_id,
        supplier_name=c5.supplier.name,
        supplier_trn=ValueWithTrust(value=c5.supplier.trn, status=FieldStatus.CONFIRMED),
        invoice_number=ValueWithTrust(value=c5.invoice_number_hint, status=FieldStatus.CONFIRMED),
        invoice_date=ValueWithTrust(value="2026-04-05", status=FieldStatus.CONFIRMED),
        invoice_currency=ValueWithTrust(value="AED", status=FieldStatus.CONFIRMED),
        subtotal=ValueWithTrust(value=Decimal("7200.00"), status=FieldStatus.CONFIRMED),
        tax_amount=ValueWithTrust(value=Decimal("360.00"), status=FieldStatus.CONFIRMED),
        grand_total=ValueWithTrust(value=Decimal("7560.00"), status=FieldStatus.CONFIRMED),
        lpo_required=False,
        invoice_lines=[
            InvoiceLineSnapshot(
                line_id=inv_line.id,
                document_id="doc-p5-inv-105",
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
                line_id=dn_line.id,
                document_id="doc-p5-dn-205",
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
        confirmed_links={inv_line.id: [dn_line.id]},
    )

    findings = verify_case(snapshot)

    qty_match = next((f for f in findings if f.rule_code == "QTY_003"), None)
    assert qty_match is not None
    assert qty_match.outcome == FindingOutcome.MATCH
    assert qty_match.actual_value == "30.00"  # Net accepted (36 - 6)
