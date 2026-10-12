"""Milestone M4C Phase 2 Preparation: Deterministic Synthetic Ingestion Script.

Provisions a controlled set of 5 synthetic pilot verification cases for PRJ-DXB-01
representing the key calibration scenarios:
  Case 1: Clean Exact 4-Way Match (Ready-mix concrete)
  Case 2: Quantity Overbilling Mismatch (Reinforcement steel)
  Case 3: Missing Delivery Note Evidence (Ready-mix concrete)
  Case 4: Delivery Note Reuse Attempt (Steel rebar cross-case reuse)
  Case 5: Site Rejection with Documented Evidence (Ready-mix slump failure)

Invariants Enforced:
- 100% Synthetic data. Zero real commercial documents.
- Idempotent and safe to rerun (fails/stops if duplicate cases detected unless explicit override).
- Enforces exact Decimal quantities, LPO caps and rates, SoD, and full audit provenance.
- Directly persists structured line items, extracted fields, and line links into PostgreSQL.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.engine import verify_case
from app.domain.models import (
    CaseSnapshot,
    DNLineSnapshot,
    FieldStatus,
    InvoiceLineSnapshot,
    LPOLineSnapshot,
    ValueWithTrust,
)
from app.persistence.database import SessionLocal
from app.persistence.models import (
    AuditEventOrm,
    DocumentOrm,
    ExtractedFieldOrm,
    FindingOrm,
    LineItemOrm,
    LineLinkOrm,
    LpoLineOrm,
    LpoOrm,
    ProjectOrm,
    ProjectUserOrm,
    SupplierOrm,
    UserOrm,
    VerificationCaseOrm,
    VerificationRunOrm,
)
from app.persistence.repositories import AuditRepository, CaseRepository, RunRepository
from app.persistence.seed import generate_synthetic_pdf_bytes


class SyntheticIngestionError(Exception):
    """Raised when synthetic ingestion invariants are breached."""


# Calibration Configuration for Phase 2 Dual-Run Testing
PILOT_PROJECT_ID = "prj-pilot-dxb-01"
SUPPLIER_RMC_ID = "sup-pilot-rmc-01"
SUPPLIER_STEEL_ID = "sup-pilot-steel-02"

USER_QS_ID = "usr-pilot-project-qs"
USER_STORE_ID = "usr-pilot-storekeeper"
USER_ENG_ID = "usr-pilot-site-eng"
USER_PM_ID = "usr-pilot-pm-reviewer"


SYNTHETIC_LPO_DATA = [
    {
        "id": "lpo-pilot-rmc-01",
        "lpo_number": "LPO-DXB-2026-RMC-01",
        "project_id": PILOT_PROJECT_ID,
        "supplier_id": SUPPLIER_RMC_ID,
        "lpo_date": "2026-03-01",
        "currency": "AED",
        "total_amount_cap": "250000.00",
        "created_by": USER_QS_ID,
        "lines": [
            {
                "id": "lpo-line-pilot-rmc-01",
                "line_no": 1,
                "description": "ReadyMix Concrete C40/20 OPC (Pump Mix)",
                "ordered_qty": "1000.00",
                "unit": "m3",
                "agreed_unit_price": "240.00",
                "line_amount_cap": "240000.00",
            }
        ],
    },
    {
        "id": "lpo-pilot-steel-01",
        "lpo_number": "LPO-DXB-2026-STL-01",
        "project_id": PILOT_PROJECT_ID,
        "supplier_id": SUPPLIER_STEEL_ID,
        "lpo_date": "2026-03-05",
        "currency": "AED",
        "total_amount_cap": "180000.00",
        "created_by": USER_QS_ID,
        "lines": [
            {
                "id": "lpo-line-pilot-stl-01",
                "line_no": 1,
                "description": "High Tensile Deformed Steel Rebar 16mm (Grade 500B)",
                "ordered_qty": "60.00",
                "unit": "t",
                "agreed_unit_price": "2850.00",
                "line_amount_cap": "171000.00",
            }
        ],
    },
]


def ingest_synthetic_pilot_cases(
    db: Session,
    stop_on_duplicates: bool = True,
) -> dict[str, Any]:
    """Deterministically ingest 5 synthetic pilot cases into the database.

    Enforces:
    - Precondition: Pilot project, suppliers, and users must exist.
    - Idempotency / Duplicate detection: Aborts if cases already exist.
    - Full 4-way line linkages and audit trail events.
    """
    audit_repo = AuditRepository(db)

    # 1. Verify Prerequisites
    project = db.get(ProjectOrm, PILOT_PROJECT_ID)
    if not project:
        raise SyntheticIngestionError(
            f"Precondition failed: Pilot project '{PILOT_PROJECT_ID}' does not exist in database."
        )

    for sup_id in (SUPPLIER_RMC_ID, SUPPLIER_STEEL_ID):
        if not db.get(SupplierOrm, sup_id):
            raise SyntheticIngestionError(
                f"Precondition failed: Participating supplier '{sup_id}' does not exist."
            )

    for usr_id in (USER_QS_ID, USER_STORE_ID, USER_ENG_ID, USER_PM_ID):
        if not db.get(UserOrm, usr_id):
            raise SyntheticIngestionError(
                f"Precondition failed: Named pilot user '{usr_id}' does not exist."
            )

    # 2. Check for Duplicate Cases
    case_ids = [f"case-pilot-syn-{i:02d}" for i in range(1, 6)]
    existing_cases = db.scalars(
        select(VerificationCaseOrm).where(VerificationCaseOrm.id.in_(case_ids))
    ).all()
    if existing_cases:
        existing_refs = [c.case_ref for c in existing_cases]
        if stop_on_duplicates:
            raise SyntheticIngestionError(
                f"Duplicate ingestion prevented: Pilot cases already exist: {existing_refs}."
            )
        return {
            "status": "ALREADY_PROVISIONED",
            "cases_count": len(existing_cases),
            "case_refs": existing_refs,
        }

    counts = {
        "lpos": 0,
        "cases": 0,
        "documents": 0,
        "line_items": 0,
        "line_links": 0,
        "audit_events": 0,
    }

    # 3. Provision LPO Master Contracts
    for lpo_data in SYNTHETIC_LPO_DATA:
        existing_lpo = db.get(LpoOrm, lpo_data["id"])
        if not existing_lpo:
            lpo = LpoOrm(
                id=lpo_data["id"],
                lpo_number=lpo_data["lpo_number"],
                project_id=lpo_data["project_id"],
                supplier_id=lpo_data["supplier_id"],
                lpo_date=lpo_data["lpo_date"],
                currency=lpo_data["currency"],
                total_amount_cap=lpo_data["total_amount_cap"],
                is_active=True,
                created_by=lpo_data["created_by"],
            )
            db.add(lpo)
            db.flush()

            for line_data in lpo_data["lines"]:
                line = LpoLineOrm(
                    id=line_data["id"],
                    lpo_id=lpo.id,
                    line_no=line_data["line_no"],
                    description=line_data["description"],
                    ordered_qty=line_data["ordered_qty"],
                    unit=line_data["unit"],
                    agreed_unit_price=line_data["agreed_unit_price"],
                    line_amount_cap=line_data["line_amount_cap"],
                )
                db.add(line)

            audit_repo.append_event(
                action="LPO_CREATED",
                entity_type="LPO",
                entity_id=lpo.id,
                actor_id=lpo.created_by,
                after_state={
                    "lpo_number": lpo.lpo_number,
                    "total_amount_cap": lpo.total_amount_cap,
                    "lines_count": len(lpo_data["lines"]),
                },
            )
            counts["lpos"] += 1

    # 4. Provision Five Controlled Synthetic Cases

    # -------------------------------------------------------------------------
    # CASE 1: Clean Exact 4-Way Match (Ready-mix concrete)
    # -------------------------------------------------------------------------
    c1 = VerificationCaseOrm(
        id="case-pilot-syn-01",
        case_ref="VC-PILOT-2026-001",
        project_id=PILOT_PROJECT_ID,
        supplier_id=SUPPLIER_RMC_ID,
        lpo_id="lpo-pilot-rmc-01",
        invoice_number_hint="INV-PILOT-101",
        currency="AED",
        lpo_required=True,
        status="READY_TO_VERIFY",
        created_by=USER_QS_ID,
        created_at=datetime(2026, 4, 1, 9, 0, 0),
    )
    db.add(c1)
    db.flush()

    inv1_doc = DocumentOrm(
        id="doc-p1-inv-101",
        case_id=c1.id,
        doc_type="INVOICE",
        original_filename="INV-PILOT-101.pdf",
        storage_key="synthetic_pilot_inv_101.pdf",
        mime_type="application/pdf",
        size_bytes=150000,
        sha256="1010101010101010101010101010101010101010101010101010101010101010",
        page_count=1,
        quarantine_status="CLEAN",
        uploaded_by=USER_QS_ID,
        extraction_status="EXTRACTED",
        data_review_status="CONFIRMED",
        reference_no_normalized="101",
    )
    dn1_doc = DocumentOrm(
        id="doc-p1-dn-201",
        case_id=c1.id,
        doc_type="DELIVERY_NOTE",
        original_filename="DN-PILOT-201.pdf",
        storage_key="synthetic_pilot_dn_201.pdf",
        mime_type="application/pdf",
        size_bytes=110000,
        sha256="2010201020102010201020102010201020102010201020102010201020102010",
        page_count=1,
        quarantine_status="CLEAN",
        uploaded_by=USER_STORE_ID,
        extraction_status="EXTRACTED",
        data_review_status="CONFIRMED",
        reference_no_normalized="201",
    )
    db.add_all([inv1_doc, dn1_doc])
    db.flush()

    # Invoice line: 36.00 m3 @ 240.00 AED = 8640.00 AED
    inv1_line = LineItemOrm(
        id="li-p1-inv-1",
        document_id=inv1_doc.id,
        line_no=1,
        kind="MATERIAL",
    )
    # DN line: 36.00 m3 accepted by storekeeper and engineer
    dn1_line = LineItemOrm(
        id="li-p1-dn-1",
        document_id=dn1_doc.id,
        line_no=1,
        kind="MATERIAL",
        storekeeper_ticket_no="GATE-2026-0881",
        gate_entry_at=datetime(2026, 4, 1, 8, 30, 0),
        storekeeper_confirmed=True,
        storekeeper_user_id=USER_STORE_ID,
        engineer_verified=True,
        engineer_user_id=USER_ENG_ID,
    )
    db.add_all([inv1_line, dn1_line])
    db.flush()

    # Link inv line -> dn line & lpo line
    link1 = LineLinkOrm(
        id="link-p1-01",
        case_id=c1.id,
        invoice_line_id=inv1_line.id,
        dn_line_id=dn1_line.id,
        lpo_line_id="lpo-line-pilot-rmc-01",
        link_method="EXACT_REF",
        status="CONFIRMED",
        confirmed_by=USER_QS_ID,
    )
    db.add(link1)

    # -------------------------------------------------------------------------
    # CASE 2: Quantity Overbilling Mismatch (Reinforcement steel)
    # Billed: 20.00 t, Delivered: 15.00 t (Difference: +5.00 t overbill)
    # -------------------------------------------------------------------------
    c2 = VerificationCaseOrm(
        id="case-pilot-syn-02",
        case_ref="VC-PILOT-2026-002",
        project_id=PILOT_PROJECT_ID,
        supplier_id=SUPPLIER_STEEL_ID,
        lpo_id="lpo-pilot-steel-01",
        invoice_number_hint="INV-PILOT-102",
        currency="AED",
        lpo_required=True,
        status="READY_TO_VERIFY",
        created_by=USER_QS_ID,
        created_at=datetime(2026, 4, 2, 9, 0, 0),
    )
    db.add(c2)
    db.flush()

    inv2_doc = DocumentOrm(
        id="doc-p2-inv-102",
        case_id=c2.id,
        doc_type="INVOICE",
        original_filename="INV-PILOT-102.pdf",
        storage_key="synthetic_pilot_inv_102.pdf",
        mime_type="application/pdf",
        size_bytes=152000,
        sha256="1020102010201020102010201020102010201020102010201020102010201020",
        page_count=1,
        quarantine_status="CLEAN",
        uploaded_by=USER_QS_ID,
        extraction_status="EXTRACTED",
        data_review_status="CONFIRMED",
        reference_no_normalized="102",
    )
    dn2_doc = DocumentOrm(
        id="doc-p2-dn-202",
        case_id=c2.id,
        doc_type="DELIVERY_NOTE",
        original_filename="DN-PILOT-202.pdf",
        storage_key="synthetic_pilot_dn_202.pdf",
        mime_type="application/pdf",
        size_bytes=115000,
        sha256="2020202020202020202020202020202020202020202020202020202020202020",
        page_count=1,
        quarantine_status="CLEAN",
        uploaded_by=USER_STORE_ID,
        extraction_status="EXTRACTED",
        data_review_status="CONFIRMED",
        reference_no_normalized="202",
    )
    db.add_all([inv2_doc, dn2_doc])
    db.flush()

    inv2_line = LineItemOrm(
        id="li-p2-inv-1",
        document_id=inv2_doc.id,
        line_no=1,
        kind="MATERIAL",
    )
    dn2_line = LineItemOrm(
        id="li-p2-dn-1",
        document_id=dn2_doc.id,
        line_no=1,
        kind="MATERIAL",
        storekeeper_ticket_no="GATE-2026-0895",
        gate_entry_at=datetime(2026, 4, 2, 8, 45, 0),
        storekeeper_confirmed=True,
        storekeeper_user_id=USER_STORE_ID,
        engineer_verified=True,
        engineer_user_id=USER_ENG_ID,
    )
    db.add_all([inv2_line, dn2_line])
    db.flush()

    link2 = LineLinkOrm(
        id="link-p2-01",
        case_id=c2.id,
        invoice_line_id=inv2_line.id,
        dn_line_id=dn2_line.id,
        lpo_line_id="lpo-line-pilot-stl-01",
        link_method="EXACT_REF",
        status="CONFIRMED",
        confirmed_by=USER_QS_ID,
    )
    db.add(link2)

    # -------------------------------------------------------------------------
    # CASE 3: Missing Delivery Note Evidence (Ready-mix concrete)
    # Invoice uploaded, but NO Delivery Notes uploaded. Must flag MISSING_EVIDENCE.
    # -------------------------------------------------------------------------
    c3 = VerificationCaseOrm(
        id="case-pilot-syn-03",
        case_ref="VC-PILOT-2026-003",
        project_id=PILOT_PROJECT_ID,
        supplier_id=SUPPLIER_RMC_ID,
        lpo_id="lpo-pilot-rmc-01",
        invoice_number_hint="INV-PILOT-103",
        currency="AED",
        lpo_required=True,
        status="AWAITING_DOCUMENTS",
        created_by=USER_QS_ID,
        created_at=datetime(2026, 4, 3, 10, 0, 0),
    )
    db.add(c3)
    db.flush()

    inv3_doc = DocumentOrm(
        id="doc-p3-inv-103",
        case_id=c3.id,
        doc_type="INVOICE",
        original_filename="INV-PILOT-103.pdf",
        storage_key="synthetic_pilot_inv_103.pdf",
        mime_type="application/pdf",
        size_bytes=148000,
        sha256="1030103010301030103010301030103010301030103010301030103010301030",
        page_count=1,
        quarantine_status="CLEAN",
        uploaded_by=USER_QS_ID,
        extraction_status="EXTRACTED",
        data_review_status="CONFIRMED",
        reference_no_normalized="103",
    )
    db.add(inv3_doc)
    db.flush()

    inv3_line = LineItemOrm(
        id="li-p3-inv-1",
        document_id=inv3_doc.id,
        line_no=1,
        kind="MATERIAL",
    )
    db.add(inv3_line)
    db.flush()

    # -------------------------------------------------------------------------
    # CASE 4: Delivery Note Reuse Attempt (Steel rebar)
    # Attempts to attach DN-PILOT-202 (already used in Case 2) to Case 4.
    # -------------------------------------------------------------------------
    c4 = VerificationCaseOrm(
        id="case-pilot-syn-04",
        case_ref="VC-PILOT-2026-004",
        project_id=PILOT_PROJECT_ID,
        supplier_id=SUPPLIER_STEEL_ID,
        lpo_id="lpo-pilot-steel-01",
        invoice_number_hint="INV-PILOT-104",
        currency="AED",
        lpo_required=True,
        status="READY_TO_VERIFY",
        created_by=USER_QS_ID,
        created_at=datetime(2026, 4, 4, 11, 0, 0),
    )
    db.add(c4)
    db.flush()

    inv4_doc = DocumentOrm(
        id="doc-p4-inv-104",
        case_id=c4.id,
        doc_type="INVOICE",
        original_filename="INV-PILOT-104.pdf",
        storage_key="synthetic_pilot_inv_104.pdf",
        mime_type="application/pdf",
        size_bytes=155000,
        sha256="1040104010401040104010401040104010401040104010401040104010401040",
        page_count=1,
        quarantine_status="CLEAN",
        uploaded_by=USER_QS_ID,
        extraction_status="EXTRACTED",
        data_review_status="CONFIRMED",
        reference_no_normalized="104",
    )
    # Reused DN: Identical normalized reference "202" and SHA as in Case 2
    dn4_reused_doc = DocumentOrm(
        id="doc-p4-dn-202-reused",
        case_id=c4.id,
        doc_type="DELIVERY_NOTE",
        original_filename="DN-PILOT-202-reused.pdf",
        storage_key="synthetic_pilot_dn_202.pdf",
        mime_type="application/pdf",
        size_bytes=115000,
        sha256="2020202020202020202020202020202020202020202020202020202020202020",
        page_count=1,
        quarantine_status="CLEAN",
        uploaded_by=USER_STORE_ID,
        extraction_status="EXTRACTED",
        data_review_status="CONFIRMED",
        reference_no_normalized="202",
    )
    db.add_all([inv4_doc, dn4_reused_doc])
    db.flush()

    inv4_line = LineItemOrm(
        id="li-p4-inv-1",
        document_id=inv4_doc.id,
        line_no=1,
        kind="MATERIAL",
    )
    dn4_line = LineItemOrm(
        id="li-p4-dn-1",
        document_id=dn4_reused_doc.id,
        line_no=1,
        kind="MATERIAL",
        storekeeper_ticket_no="GATE-2026-0910",
        gate_entry_at=datetime(2026, 4, 4, 10, 15, 0),
        storekeeper_confirmed=True,
        storekeeper_user_id=USER_STORE_ID,
        engineer_verified=True,
        engineer_user_id=USER_ENG_ID,
    )
    db.add_all([inv4_line, dn4_line])
    db.flush()

    link4 = LineLinkOrm(
        id="link-p4-01",
        case_id=c4.id,
        invoice_line_id=inv4_line.id,
        dn_line_id=dn4_line.id,
        lpo_line_id="lpo-line-pilot-stl-01",
        link_method="EXACT_REF",
        status="CONFIRMED",
        confirmed_by=USER_QS_ID,
    )
    db.add(link4)

    # -------------------------------------------------------------------------
    # CASE 5: Site Rejection with Documented Evidence (Ready-mix concrete)
    # Delivered: 36.00 m3, Rejected (slump failure): 6.00 m3 -> Net Accepted: 30.00 m3
    # Billed: 30.00 m3 -> Clean MATCH after documented deduction.
    # -------------------------------------------------------------------------
    c5 = VerificationCaseOrm(
        id="case-pilot-syn-05",
        case_ref="VC-PILOT-2026-005",
        project_id=PILOT_PROJECT_ID,
        supplier_id=SUPPLIER_RMC_ID,
        lpo_id="lpo-pilot-rmc-01",
        invoice_number_hint="INV-PILOT-105",
        currency="AED",
        lpo_required=True,
        status="READY_TO_VERIFY",
        created_by=USER_QS_ID,
        created_at=datetime(2026, 4, 5, 9, 30, 0),
    )
    db.add(c5)
    db.flush()

    inv5_doc = DocumentOrm(
        id="doc-p5-inv-105",
        case_id=c5.id,
        doc_type="INVOICE",
        original_filename="INV-PILOT-105.pdf",
        storage_key="synthetic_pilot_inv_105.pdf",
        mime_type="application/pdf",
        size_bytes=151000,
        sha256="1050105010501050105010501050105010501050105010501050105010501050",
        page_count=1,
        quarantine_status="CLEAN",
        uploaded_by=USER_QS_ID,
        extraction_status="EXTRACTED",
        data_review_status="CONFIRMED",
        reference_no_normalized="105",
    )
    dn5_doc = DocumentOrm(
        id="doc-p5-dn-205",
        case_id=c5.id,
        doc_type="DELIVERY_NOTE",
        original_filename="DN-PILOT-205.pdf",
        storage_key="synthetic_pilot_dn_205.pdf",
        mime_type="application/pdf",
        size_bytes=114000,
        sha256="2050205020502050205020502050205020502050205020502050205020502050",
        page_count=1,
        quarantine_status="CLEAN",
        uploaded_by=USER_STORE_ID,
        extraction_status="EXTRACTED",
        data_review_status="CONFIRMED",
        reference_no_normalized="205",
    )
    db.add_all([inv5_doc, dn5_doc])
    db.flush()

    inv5_line = LineItemOrm(
        id="li-p5-inv-1",
        document_id=inv5_doc.id,
        line_no=1,
        kind="MATERIAL",
    )
    # Delivered 36.00 m3, Rejected 6.00 m3 with documented slump failure
    dn5_line = LineItemOrm(
        id="li-p5-dn-1",
        document_id=dn5_doc.id,
        line_no=1,
        kind="MATERIAL",
        storekeeper_ticket_no="GATE-2026-0940",
        gate_entry_at=datetime(2026, 4, 5, 8, 15, 0),
        storekeeper_confirmed=True,
        storekeeper_user_id=USER_STORE_ID,
        engineer_verified=True,
        engineer_user_id=USER_ENG_ID,
        rejected_qty="6.00",
        rejection_reason_code="SLUMP_FAILURE",
        has_rejection_evidence=True,
    )
    db.add_all([inv5_line, dn5_line])
    db.flush()

    link5 = LineLinkOrm(
        id="link-p5-01",
        case_id=c5.id,
        invoice_line_id=inv5_line.id,
        dn_line_id=dn5_line.id,
        lpo_line_id="lpo-line-pilot-rmc-01",
        link_method="EXACT_REF",
        status="CONFIRMED",
        confirmed_by=USER_QS_ID,
    )
    db.add(link5)

    # 5. Populate Extracted Field Data for Complete Snapshot Fidelity
    fields_data = [
        # Case 1
        (inv1_doc.id, inv1_line.id, "invoiced_qty", "36.00", "DECIMAL", "CONFIRMED"),
        (inv1_doc.id, inv1_line.id, "unit", "m3", "STRING", "CONFIRMED"),
        (inv1_doc.id, inv1_line.id, "unit_price", "240.00", "DECIMAL", "CONFIRMED"),
        (inv1_doc.id, inv1_line.id, "line_amount", "8640.00", "DECIMAL", "CONFIRMED"),
        (dn1_doc.id, dn1_line.id, "delivered_qty", "36.00", "DECIMAL", "CONFIRMED"),
        (dn1_doc.id, dn1_line.id, "unit", "m3", "STRING", "CONFIRMED"),
        (inv1_doc.id, None, "subtotal", "8640.00", "DECIMAL", "CONFIRMED"),
        (inv1_doc.id, None, "tax_amount", "432.00", "DECIMAL", "CONFIRMED"),
        (inv1_doc.id, None, "grand_total", "9072.00", "DECIMAL", "CONFIRMED"),
        # Case 2
        (inv2_doc.id, inv2_line.id, "invoiced_qty", "20.00", "DECIMAL", "CONFIRMED"),
        (inv2_doc.id, inv2_line.id, "unit", "t", "STRING", "CONFIRMED"),
        (inv2_doc.id, inv2_line.id, "unit_price", "2850.00", "DECIMAL", "CONFIRMED"),
        (inv2_doc.id, inv2_line.id, "line_amount", "57000.00", "DECIMAL", "CONFIRMED"),
        (dn2_doc.id, dn2_line.id, "delivered_qty", "15.00", "DECIMAL", "CONFIRMED"),
        (dn2_doc.id, dn2_line.id, "unit", "t", "STRING", "CONFIRMED"),
        (inv2_doc.id, None, "subtotal", "57000.00", "DECIMAL", "CONFIRMED"),
        (inv2_doc.id, None, "tax_amount", "2850.00", "DECIMAL", "CONFIRMED"),
        (inv2_doc.id, None, "grand_total", "59850.00", "DECIMAL", "CONFIRMED"),
        # Case 3
        (inv3_doc.id, inv3_line.id, "invoiced_qty", "40.00", "DECIMAL", "CONFIRMED"),
        (inv3_doc.id, inv3_line.id, "unit", "m3", "STRING", "CONFIRMED"),
        (inv3_doc.id, inv3_line.id, "unit_price", "240.00", "DECIMAL", "CONFIRMED"),
        (inv3_doc.id, inv3_line.id, "line_amount", "9600.00", "DECIMAL", "CONFIRMED"),
        (inv3_doc.id, None, "subtotal", "9600.00", "DECIMAL", "CONFIRMED"),
        (inv3_doc.id, None, "tax_amount", "480.00", "DECIMAL", "CONFIRMED"),
        (inv3_doc.id, None, "grand_total", "10080.00", "DECIMAL", "CONFIRMED"),
        # Case 4
        (inv4_doc.id, inv4_line.id, "invoiced_qty", "15.00", "DECIMAL", "CONFIRMED"),
        (inv4_doc.id, inv4_line.id, "unit", "t", "STRING", "CONFIRMED"),
        (inv4_doc.id, inv4_line.id, "unit_price", "2850.00", "DECIMAL", "CONFIRMED"),
        (inv4_doc.id, inv4_line.id, "line_amount", "42750.00", "DECIMAL", "CONFIRMED"),
        (dn4_reused_doc.id, dn4_line.id, "delivered_qty", "15.00", "DECIMAL", "CONFIRMED"),
        (dn4_reused_doc.id, dn4_line.id, "unit", "t", "STRING", "CONFIRMED"),
        (inv4_doc.id, None, "subtotal", "42750.00", "DECIMAL", "CONFIRMED"),
        (inv4_doc.id, None, "tax_amount", "2137.50", "DECIMAL", "CONFIRMED"),
        (inv4_doc.id, None, "grand_total", "44887.50", "DECIMAL", "CONFIRMED"),
        # Case 5
        (inv5_doc.id, inv5_line.id, "invoiced_qty", "30.00", "DECIMAL", "CONFIRMED"),
        (inv5_doc.id, inv5_line.id, "unit", "m3", "STRING", "CONFIRMED"),
        (inv5_doc.id, inv5_line.id, "unit_price", "240.00", "DECIMAL", "CONFIRMED"),
        (inv5_doc.id, inv5_line.id, "line_amount", "7200.00", "DECIMAL", "CONFIRMED"),
        (dn5_doc.id, dn5_line.id, "delivered_qty", "36.00", "DECIMAL", "CONFIRMED"),
        (dn5_doc.id, dn5_line.id, "rejected_qty", "6.00", "DECIMAL", "CONFIRMED"),
        (dn5_doc.id, dn5_line.id, "unit", "m3", "STRING", "CONFIRMED"),
        (inv5_doc.id, None, "subtotal", "7200.00", "DECIMAL", "CONFIRMED"),
        (inv5_doc.id, None, "tax_amount", "360.00", "DECIMAL", "CONFIRMED"),
        (inv5_doc.id, None, "grand_total", "7560.00", "DECIMAL", "CONFIRMED"),
    ]

    for doc_id, line_id, key, val, val_type, status in fields_data:
        f = ExtractedFieldOrm(
            document_id=doc_id,
            line_item_id=line_id,
            field_key=key,
            raw_value=val,
            normalized_value=val,
            value_type=val_type,
            status=status,
            confidence="1.00",
            method="MANUAL_ENTRY",
            updated_by=USER_QS_ID,
        )
        db.add(f)

    # 6. Record Audit Trail for Each Provisioned Case
    for case_obj in (c1, c2, c3, c4, c5):
        audit_repo.append_event(
            action="CASE_CREATED",
            entity_type="VERIFICATION_CASE",
            entity_id=case_obj.id,
            case_id=case_obj.id,
            actor_id=USER_QS_ID,
            after_state={
                "case_ref": case_obj.case_ref,
                "project_id": case_obj.project_id,
                "supplier_id": case_obj.supplier_id,
                "currency": case_obj.currency,
                "lpo_id": case_obj.lpo_id,
            },
        )
        counts["cases"] += 1

    counts["documents"] = 9
    counts["line_items"] = 9
    counts["line_links"] = 4
    counts["audit_events"] = 5 + len(SYNTHETIC_LPO_DATA)

    db.commit()
    return counts


if __name__ == "__main__":
    db = SessionLocal()
    try:
        res = ingest_synthetic_pilot_cases(db, stop_on_duplicates=True)
        print("Synthetic pilot cases successfully ingested:")
        for k, v in res.items():
            print(f"  {k}: {v}")
    finally:
        db.close()
