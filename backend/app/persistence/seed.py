"""Deterministic synthetic seed data for local prototype testing.

All data is strictly synthetic and clearly marked with fictitious parties,
synthetic UAE TRNs, and fixed AED amounts.
"""

from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path
from typing import Any
from PIL import Image, ImageDraw
from sqlalchemy.orm import Session

from app.persistence.models import (
    AuditEventOrm,
    DocumentOrm,
    ExtractedFieldOrm,
    FindingOrm,
    LineItemOrm,
    LineLinkOrm,
    LpoLineOrm,
    LpoOrm,
    MaterialOrm,
    ProjectOrm,
    ProjectUserOrm,
    SupplierOrm,
    UnitOrm,
    UserOrm,
    VerificationCaseOrm,
    VerificationRunOrm,
)


def seed_database(session: Session) -> dict[str, int]:
    """Idempotently seed the database with deterministic synthetic data and pilot credentials."""
    from app.core.security import hash_password

    counts = {"users": 0, "projects": 0, "suppliers": 0, "materials": 0, "units": 0, "cases": 0}
    pilot_password_hash = hash_password("PilotPass123!")

    # 1. Synthetic / Pilot Users
    users_data = [
        {"id": "usr-sim-eng", "name": "Simulated Site Engineer", "email": "engineer@prototype.local", "role": "ENGINEER", "can_review": False, "hashed_password": pilot_password_hash},
        {"id": "usr-sim-qs", "name": "Simulated Quantity Surveyor", "email": "qs@prototype.local", "role": "QS", "can_review": False, "hashed_password": pilot_password_hash},
        {"id": "usr-sim-rev", "name": "Simulated Reviewer", "email": "reviewer@prototype.local", "role": "REVIEWER", "can_review": True, "hashed_password": pilot_password_hash},
        {"id": "usr-sim-acc", "name": "Simulated Accounts Lead", "email": "accounts@prototype.local", "role": "ACCOUNTS", "can_review": False, "hashed_password": pilot_password_hash},
        {"id": "usr-sim-admin", "name": "Simulated Administrator", "email": "admin@prototype.local", "role": "ADMIN", "can_review": False, "hashed_password": pilot_password_hash},
        {"id": "usr-isolated-eng", "name": "Isolated Site Engineer (Palm Crest Only)", "email": "isolated-eng@prototype.local", "role": "ENGINEER", "can_review": False, "hashed_password": pilot_password_hash},
    ]
    for u in users_data:
        existing = session.get(UserOrm, u["id"])
        if not existing:
            session.add(UserOrm(**u, active=True))
            counts["users"] += 1
        elif not existing.hashed_password:
            existing.hashed_password = pilot_password_hash

    # 2. Synthetic Units
    units_data = [
        {"code": "m3", "dimension": "VOLUME", "aliases": ["CUM", "CBM", "m³"]},
        {"code": "t", "dimension": "MASS", "aliases": ["MT", "tonne", "tonnes"]},
        {"code": "kg", "dimension": "MASS", "aliases": ["KG", "kilogram"]},
        {"code": "pcs", "dimension": "COUNT", "aliases": ["nos", "pieces", "ea"]},
        {"code": "bag", "dimension": "COUNT", "aliases": ["bags"]},
        {"code": "load", "dimension": "COUNT", "aliases": ["trip", "trips"]},
        {"code": "m", "dimension": "LENGTH", "aliases": ["LM", "metre"]},
        {"code": "m2", "dimension": "AREA", "aliases": ["SQM", "sqm"]},
        {"code": "L", "dimension": "VOLUME", "aliases": ["litre", "liters"]},
    ]
    for un in units_data:
        if not session.get(UnitOrm, un["code"]):
            session.add(UnitOrm(**un))
            counts["units"] += 1

    # 3. Synthetic Materials
    materials_data = [
        {"id": "mat-conc-30", "code": "CONC-C30", "name": "ReadyMix Concrete C30/20", "category": "CONCRETE", "default_unit": "m3", "aliases": ["C30 Concrete"], "spec_attributes": {"grade": "C30/20", "slump": "150mm"}},
        {"id": "mat-conc-40", "code": "CONC-C40", "name": "ReadyMix Concrete C40/20", "category": "CONCRETE", "default_unit": "m3", "aliases": ["C40 Concrete"], "spec_attributes": {"grade": "C40/20", "slump": "160mm"}},
        {"id": "mat-cem-opc", "code": "CEM-OPC", "name": "Ordinary Portland Cement (Bulk)", "category": "CEMENT", "default_unit": "t", "aliases": ["OPC Cement"], "spec_attributes": {"standard": "BS EN 197-1"}},
        {"id": "mat-stl-16", "code": "STL-16MM", "name": "High Tensile Rebar 16mm", "category": "STEEL", "default_unit": "t", "aliases": ["16mm Rebar"], "spec_attributes": {"diameter": 16, "grade": "B500B"}},
        {"id": "mat-blk-200", "code": "BLK-200", "name": "Solid Masonry Blocks 200mm", "category": "BLOCKS", "default_unit": "pcs", "aliases": ["200mm Solid Blocks"], "spec_attributes": {"size": "400x200x200"}},
        {"id": "mat-agg-040", "code": "AGG-040", "name": "Sub-base Crushed Aggregate 0-40mm", "category": "AGGREGATE", "default_unit": "t", "aliases": ["Road Base Aggregate"], "spec_attributes": {"grading": "0-40mm"}},
    ]
    for m in materials_data:
        if not session.get(MaterialOrm, m["id"]):
            session.add(MaterialOrm(**m))
            counts["materials"] += 1

    # 4. Synthetic Projects
    projects_data = [
        {"id": "prj-01", "code": "PRJ-CT4", "name": "Alpha Horizon Tower Phase 1", "client": "Horizon Development PJSC (Synthetic)", "site_location": "Horizon Harbour Plot 1", "active": True},
        {"id": "prj-02", "code": "PRJ-MG2", "name": "Azure Bay Tower 2", "client": "Azure Bay Development LLC (Synthetic)", "site_location": "Azure Marina Plot 2", "active": True},
        {"id": "prj-03", "code": "PRJ-DSQ", "name": "Metropolis Central Square", "client": "Metropolis Commercial Properties LLC (Synthetic)", "site_location": "Central Business District", "active": True},
        {"id": "prj-04", "code": "PRJ-JBV", "name": "Palm Crest Villa 12", "client": "Oasis Leisure Developments LLC (Synthetic)", "site_location": "Palm Crest Enclave", "active": True},
    ]
    for p in projects_data:
        if not session.get(ProjectOrm, p["id"]):
            session.add(ProjectOrm(**p))
            counts["projects"] += 1

    # 5. Synthetic Suppliers (Fictitious 15-digit UAE TRNs)
    suppliers_data = [
        {"id": "sup-01", "name": "Gulf ReadyMix Concrete LLC (Synthetic)", "trn": "100234567800003", "aliases": ["Gulf ReadyMix"], "active": True},
        {"id": "sup-02", "name": "Emirates Cement Factory LLC (Synthetic)", "trn": "100023456700003", "aliases": ["Emirates Cement"], "active": True},
        {"id": "sup-03", "name": "Apex Steel Industries LLC (Synthetic)", "trn": "100456789000003", "aliases": ["Apex Steel"], "active": True},
        {"id": "sup-04", "name": "Apex Blocks & Pavers LLC (Synthetic)", "trn": "100567890100003", "aliases": ["Apex Blocks"], "active": True},
        {"id": "sup-05", "name": "Barari Aggregates LLC (Synthetic)", "trn": "100678901200003", "aliases": ["Barari Aggregates"], "active": True},
    ]
    for s in suppliers_data:
        if not session.get(SupplierOrm, s["id"]):
            session.add(SupplierOrm(**s))
            counts["suppliers"] += 1

    session.flush()

    # 5b. Project-User Assignments (M4A Controlled Pilot)
    project_assignments = [
        {"project_id": "prj-01", "user_id": "usr-sim-eng"},
        {"project_id": "prj-02", "user_id": "usr-sim-eng"},
        {"project_id": "prj-03", "user_id": "usr-sim-eng"},
        {"project_id": "prj-04", "user_id": "usr-sim-eng"},
        {"project_id": "prj-01", "user_id": "usr-sim-qs"},
        {"project_id": "prj-02", "user_id": "usr-sim-qs"},
        {"project_id": "prj-03", "user_id": "usr-sim-qs"},
        {"project_id": "prj-04", "user_id": "usr-sim-qs"},
        {"project_id": "prj-01", "user_id": "usr-sim-rev"},
        {"project_id": "prj-02", "user_id": "usr-sim-rev"},
        {"project_id": "prj-03", "user_id": "usr-sim-rev"},
        {"project_id": "prj-04", "user_id": "usr-sim-rev"},
        {"project_id": "prj-01", "user_id": "usr-sim-acc"},
        {"project_id": "prj-02", "user_id": "usr-sim-acc"},
        {"project_id": "prj-03", "user_id": "usr-sim-acc"},
        {"project_id": "prj-04", "user_id": "usr-sim-acc"},
        {"project_id": "prj-01", "user_id": "usr-sim-admin"},
        {"project_id": "prj-02", "user_id": "usr-sim-admin"},
        {"project_id": "prj-03", "user_id": "usr-sim-admin"},
        {"project_id": "prj-04", "user_id": "usr-sim-admin"},
        {"project_id": "prj-04", "user_id": "usr-isolated-eng"},
    ]
    from sqlalchemy import select
    for pa in project_assignments:
        stmt = select(ProjectUserOrm).where(
            ProjectUserOrm.project_id == pa["project_id"],
            ProjectUserOrm.user_id == pa["user_id"],
        )
        if not session.scalars(stmt).first():
            session.add(ProjectUserOrm(
                project_id=pa["project_id"],
                user_id=pa["user_id"],
                assigned_by="usr-sim-admin",
            ))

    session.flush()

    # 6. Historical Reference Case (for DN reuse reference)
    if not session.get(VerificationCaseOrm, "case-hist-00"):
        hist_case = VerificationCaseOrm(
            id="case-hist-00",
            case_ref="VC-2026-00012",
            project_id="prj-04",
            supplier_id="sup-04",
            invoice_number_hint="INV-HIST-110",
            currency="AED",
            lpo_required=False,
            lpo_reason_code="NOT_REQUIRED_LOW_VALUE",
            lpo_reason_text="Prior call-off under framework agreement.",
            status="REVIEWED",
            created_at=datetime(2026, 3, 1, 10, 0, 0),
        )
        session.add(hist_case)
        session.flush()

        hist_dn = DocumentOrm(
            id="doc-hist-dn7019",
            case_id="case-hist-00",
            doc_type="DELIVERY_NOTE",
            original_filename="DN-7019-signed.pdf",
            storage_key="synthetic_dn_7019.pdf",
            mime_type="application/pdf",
            size_bytes=104857,
            sha256="7019e075a34e5698b671a5332f17042a1bc3ef400d78ef865239a519800dfa42",
            reference_no_normalized="7019",
            data_review_status="CONFIRMED",
            extraction_status="EXTRACTED",
        )
        session.add(hist_dn)
        session.flush()

    # 6b. Synthetic LPO Master Record (M4B Phase 1 3-way matching)
    if not session.get(LpoOrm, "lpo-synth-01"):
        lpo1 = LpoOrm(
            id="lpo-synth-01",
            lpo_number="LPO-2026-0044",
            project_id="prj-01",
            supplier_id="sup-02",
            lpo_date="2026-03-01",
            currency="AED",
            total_amount_cap="150000.00",
            is_active=True,
            created_by="usr-sim-qs",
        )
        session.add(lpo1)
        session.flush()

        lpo1_line1 = LpoLineOrm(
            id="lpo-line-synth-01",
            lpo_id="lpo-synth-01",
            line_no=1,
            material_id="mat-cem-opc",
            description="Ordinary Portland Cement (Bulk)",
            ordered_qty="500.00",
            unit="t",
            agreed_unit_price="280.00",
            line_amount_cap="140000.00",
        )
        session.add(lpo1_line1)
        session.flush()

    # 7. Five Primary Synthetic Verification Cases
    # Case 1: Clean Exact Match (Emirates Cement)
    c1_existing = session.get(VerificationCaseOrm, "case-synth-01")
    if c1_existing and not c1_existing.lpo_id:
        c1_existing.lpo_id = "lpo-synth-01"

    if not c1_existing:
        c1 = VerificationCaseOrm(
            id="case-synth-01",
            case_ref="VC-2026-00001",
            project_id="prj-01",
            supplier_id="sup-02",
            lpo_id="lpo-synth-01",
            invoice_number_hint="INV-8821",
            currency="AED",
            lpo_required=True,
            status="READY_TO_VERIFY",
            created_at=datetime(2026, 3, 28, 11, 0, 0),
        )
        session.add(c1)
        session.flush()

        inv1 = DocumentOrm(
            id="doc-c1-inv",
            case_id=c1.id,
            doc_type="INVOICE",
            original_filename="INV-8821.pdf",
            storage_key="synthetic_inv_8821.pdf",
            mime_type="application/pdf",
            size_bytes=245000,
            sha256="1a2b3c4d5e6f8821aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            data_review_status="CONFIRMED",
            extraction_status="EXTRACTED",
            reference_no_normalized="8821",
        )
        dn1_1 = DocumentOrm(
            id="doc-c1-dn4401",
            case_id=c1.id,
            doc_type="DELIVERY_NOTE",
            original_filename="DN-4401.pdf",
            storage_key="synthetic_dn_4401.pdf",
            mime_type="application/pdf",
            size_bytes=120000,
            sha256="4401bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            data_review_status="CONFIRMED",
            extraction_status="EXTRACTED",
            reference_no_normalized="4401",
        )
        dn1_2 = DocumentOrm(
            id="doc-c1-dn4402",
            case_id=c1.id,
            doc_type="DELIVERY_NOTE",
            original_filename="DN-4402.pdf",
            storage_key="synthetic_dn_4402.pdf",
            mime_type="application/pdf",
            size_bytes=119000,
            sha256="4402cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
            data_review_status="CONFIRMED",
            extraction_status="EXTRACTED",
            reference_no_normalized="4402",
        )
        session.add_all([inv1, dn1_1, dn1_2])
        session.flush()

        run1 = VerificationRunOrm(
            id="run-c1-01",
            case_id=c1.id,
            run_no=1,
            ruleset_version="1.0.0-draft",
            active_checks={"QUANTITY": True, "FINANCIAL": True, "VAT": False},
            input_snapshot={"case_ref": "VC-2026-00001", "invoice_no": "INV-8821"},
            input_hash="hash_clean_match_001",
            summary="No discrepancies found in performed checks",
            summary_labels=["No discrepancies found in performed checks", "Some checks not performed (UAE VAT)"],
            duration_ms=45,
        )
        session.add(run1)
        session.flush()

        f1 = FindingOrm(
            id="fnd-c1-01",
            run_id=run1.id,
            category="QTY_TOTAL",
            rule_code="QTY_001",
            outcome="MATCH",
            severity="INFO",
            subject_type="MATERIAL",
            subject_id="mat-cem-opc",
            message="Ordinary Portland Cement: exact match of 40.000 t across delivery notes DN-4401 and DN-4402.",
            expected="40.000",
            actual="40.000",
            difference="0.000",
            unit="t",
            rule_status="CONFIRMED",
            numeric_policy="QTY_EXACT",
        )
        session.add(f1)
        counts["cases"] += 1

    # Case 2: Quantity Overbilling Mismatch (Gulf ReadyMix)
    if not session.get(VerificationCaseOrm, "case-synth-02"):
        c2 = VerificationCaseOrm(
            id="case-synth-02",
            case_ref="VC-2026-00002",
            project_id="prj-02",
            supplier_id="sup-01",
            invoice_number_hint="INV-9042",
            currency="AED",
            lpo_required=True,
            status="VERIFIED_AWAITING_REVIEW",
            created_at=datetime(2026, 3, 29, 10, 0, 0),
        )
        session.add(c2)
        session.flush()

        inv2 = DocumentOrm(
            id="doc-c2-inv",
            case_id=c2.id,
            doc_type="INVOICE",
            original_filename="INV-9042.pdf",
            storage_key="synthetic_inv_9042.pdf",
            mime_type="application/pdf",
            size_bytes=260000,
            sha256="9042eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
            data_review_status="CONFIRMED",
            extraction_status="EXTRACTED",
            reference_no_normalized="9042",
        )
        dn2_1 = DocumentOrm(
            id="doc-c2-dn5110",
            case_id=c2.id,
            doc_type="DELIVERY_NOTE",
            original_filename="DN-5110.pdf",
            storage_key="synthetic_dn_5110.pdf",
            mime_type="application/pdf",
            size_bytes=134000,
            sha256="5110ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
            data_review_status="CONFIRMED",
            extraction_status="EXTRACTED",
            reference_no_normalized="5110",
        )
        dn2_2 = DocumentOrm(
            id="doc-c2-dn5112",
            case_id=c2.id,
            doc_type="DELIVERY_NOTE",
            original_filename="DN-5112.pdf",
            storage_key="synthetic_dn_5112.pdf",
            mime_type="application/pdf",
            size_bytes=132000,
            sha256="5112000000000000000000000000000000000000000000000000000000000000",
            data_review_status="CONFIRMED",
            extraction_status="EXTRACTED",
            reference_no_normalized="5112",
        )
        session.add_all([inv2, dn2_1, dn2_2])
        session.flush()

        run2 = VerificationRunOrm(
            id="run-c2-01",
            case_id=c2.id,
            run_no=1,
            ruleset_version="1.0.0-draft",
            active_checks={"QUANTITY": True, "FINANCIAL": True, "VAT": False},
            input_snapshot={"case_ref": "VC-2026-00002", "invoice_no": "INV-9042"},
            input_hash="hash_mismatch_002",
            summary="Discrepancies found",
            summary_labels=["Discrepancies found", "Some checks not performed (UAE VAT)"],
            duration_ms=52,
        )
        session.add(run2)
        session.flush()

        f2 = FindingOrm(
            id="fnd-c2-01",
            run_id=run2.id,
            category="QTY_LINE",
            rule_code="QTY_002",
            outcome="MISMATCH",
            severity="CRITICAL",
            subject_type="LINE_ITEM",
            subject_id="line-2-c40",
            message="Concrete C40/20: Invoiced 24.000 m³ exceeds delivered accepted quantity 21.000 m³ (+3.000 m³ discrepancy).",
            expected="21.000",
            actual="24.000",
            difference="+3.000",
            difference_pct="+14.29%",
            unit="m3",
            rule_status="CONFIRMED",
            numeric_policy="QTY_EXACT",
        )
        session.add(f2)

        aud2 = AuditEventOrm(
            action="VERIFICATION_RUN_COMPLETED",
            entity_type="VERIFICATION_RUN",
            entity_id=run2.id,
            case_id=c2.id,
            after_state={"summary": "Discrepancies found", "mismatch_line": "Concrete C40/20 (+3.000 m³)"},
        )
        session.add(aud2)
        counts["cases"] += 1

    # Case 3: Missing Required Evidence (Apex Steel)
    if not session.get(VerificationCaseOrm, "case-synth-03"):
        c3 = VerificationCaseOrm(
            id="case-synth-03",
            case_ref="VC-2026-00003",
            project_id="prj-03",
            supplier_id="sup-03",
            invoice_number_hint="INV-3104",
            currency="AED",
            lpo_required=True,
            lpo_reason_code="MISSING_NOT_PROVIDED_BY_SITE",
            lpo_reason_text="Site team has not uploaded signed LPO copy.",
            status="VERIFIED_AWAITING_REVIEW",
            created_at=datetime(2026, 3, 30, 14, 0, 0),
        )
        session.add(c3)
        session.flush()

        inv3 = DocumentOrm(
            id="doc-c3-inv",
            case_id=c3.id,
            doc_type="INVOICE",
            original_filename="INV-3104.pdf",
            storage_key="synthetic_inv_3104.pdf",
            mime_type="application/pdf",
            size_bytes=198000,
            sha256="3104111111111111111111111111111111111111111111111111111111111111",
            data_review_status="CONFIRMED",
            extraction_status="EXTRACTED",
            reference_no_normalized="3104",
        )
        session.add(inv3)
        session.flush()

        run3 = VerificationRunOrm(
            id="run-c3-01",
            case_id=c3.id,
            run_no=1,
            ruleset_version="1.0.0-draft",
            active_checks={"QUANTITY": True, "FINANCIAL": True, "VAT": False},
            input_snapshot={"case_ref": "VC-2026-00003", "invoice_no": "INV-3104"},
            input_hash="hash_missing_003",
            summary="Evidence incomplete",
            summary_labels=["Evidence incomplete", "Some checks not performed (UAE VAT)"],
            duration_ms=38,
        )
        session.add(run3)
        session.flush()

        f3_1 = FindingOrm(
            id="fnd-c3-01",
            run_id=run3.id,
            category="COMPLETENESS",
            rule_code="DOC_002",
            outcome="MISSING_EVIDENCE",
            severity="CRITICAL",
            subject_type="DELIVERY_NOTE",
            subject_id="DN-6200",
            message="Referenced delivery note DN-6200 is missing signed site storekeeper acceptance ticket.",
            rule_status="CONFIRMED",
            numeric_policy=None,
        )
        f3_2 = FindingOrm(
            id="fnd-c3-02",
            run_id=run3.id,
            category="LPO",
            rule_code="LPO_001",
            outcome="MISSING_EVIDENCE",
            severity="WARNING",
            subject_type="LPO",
            subject_id="LPO_REQUIRED",
            message="LPO required for this invoice but missing document. Reason recorded: 'Site team has not uploaded signed LPO copy.'",
            rule_status="CONFIRMED",
            numeric_policy=None,
        )
        session.add_all([f3_1, f3_2])
        counts["cases"] += 1

    # Case 4: Delivery Note Reuse Flagged (Apex Blocks, DN-7019 reuse)
    if not session.get(VerificationCaseOrm, "case-synth-04"):
        c4 = VerificationCaseOrm(
            id="case-synth-04",
            case_ref="VC-2026-00004",
            project_id="prj-04",
            supplier_id="sup-04",
            invoice_number_hint="INV-1290",
            currency="AED",
            lpo_required=False,
            lpo_reason_code="NOT_REQUIRED_LOW_VALUE",
            lpo_reason_text="Low-value site repair masonry under AED 15,000 threshold.",
            status="VERIFIED_AWAITING_REVIEW",
            created_at=datetime(2026, 3, 31, 16, 0, 0),
        )
        session.add(c4)
        session.flush()

        inv4 = DocumentOrm(
            id="doc-c4-inv",
            case_id=c4.id,
            doc_type="INVOICE",
            original_filename="INV-1290.pdf",
            storage_key="synthetic_inv_1290.pdf",
            mime_type="application/pdf",
            size_bytes=175000,
            sha256="1290222222222222222222222222222222222222222222222222222222222222",
            data_review_status="CONFIRMED",
            extraction_status="EXTRACTED",
            reference_no_normalized="1290",
        )
        # Identical hash and reference as hist_dn to trigger reuse
        dn4 = DocumentOrm(
            id="doc-c4-dn7019",
            case_id=c4.id,
            doc_type="DELIVERY_NOTE",
            original_filename="DN-7019-reused.pdf",
            storage_key="synthetic_dn_7019.pdf",
            mime_type="application/pdf",
            size_bytes=104857,
            sha256="7019e075a34e5698b671a5332f17042a1bc3ef400d78ef865239a519800dfa42",
            reference_no_normalized="7019",
            data_review_status="CONFIRMED",
            extraction_status="EXTRACTED",
        )
        session.add_all([inv4, dn4])
        session.flush()

        run4 = VerificationRunOrm(
            id="run-c4-01",
            case_id=c4.id,
            run_no=1,
            ruleset_version="1.0.0-draft",
            active_checks={"QUANTITY": True, "FINANCIAL": True, "VAT": False, "DN_REUSE": True},
            input_snapshot={"case_ref": "VC-2026-00004", "invoice_no": "INV-1290"},
            input_hash="hash_reuse_004",
            summary="Discrepancies found",
            summary_labels=["Discrepancies found", "DN reuse flagged", "Some checks not performed (UAE VAT)"],
            duration_ms=48,
        )
        session.add(run4)
        session.flush()

        f4 = FindingOrm(
            id="fnd-c4-01",
            run_id=run4.id,
            category="DN_REUSE",
            rule_code="DN_REUSE_001",
            outcome="MISMATCH",
            severity="CRITICAL",
            subject_type="DELIVERY_NOTE",
            subject_id="doc-c4-dn7019",
            message="Delivery note DN-7019 is already associated with case VC-2026-00012 (Reviewed). Prototype allows one invoice per DN. PERMANENT AUDIT FINDING (Rule C1).",
            sources=[
                {"document_id": "doc-c4-dn7019", "label": "DN-7019 (this case)", "page": 1, "value": "DN-7019"},
                {"document_id": "doc-hist-dn7019", "label": "DN-7019 (VC-2026-00012)", "page": 1, "value": "DN-7019"},
            ],
            details={"other_case_ref": "VC-2026-00012", "other_case_status": "REVIEWED", "match_basis": ["SUPPLIER_AND_DN_NUMBER", "FILE_SHA256"]},
            rule_status="CONFIRMED",
            numeric_policy=None,
        )
        session.add(f4)

        # Permanent audit event for DN reuse
        aud4 = AuditEventOrm(
            action="DN_REUSE_FLAGGED",
            entity_type="DELIVERY_NOTE",
            entity_id="doc-c4-dn7019",
            case_id=c4.id,
            after_state={"conflict_case": "VC-2026-00012", "dn_ref": "DN-7019", "rule": "C1_PERMANENT"},
        )
        session.add(aud4)
        counts["cases"] += 1

    # Case 5: Pending Initial Review (Barari Aggregates)
    if not session.get(VerificationCaseOrm, "case-synth-05"):
        c5 = VerificationCaseOrm(
            id="case-synth-05",
            case_ref="VC-2026-00005",
            project_id="prj-01",
            supplier_id="sup-05",
            invoice_number_hint="INV-7719",
            currency="AED",
            lpo_required=True,
            status="PENDING",
            created_at=datetime(2026, 4, 1, 9, 0, 0),
        )
        session.add(c5)
        counts["cases"] += 1

    session.commit()
    return counts


# ---------------------------------------------------------------------------
# Synthetic Storage Files (Preview Consistency)
# ---------------------------------------------------------------------------

SYNTHETIC_DOCUMENT_FILES: dict[str, dict[str, Any]] = {
    "synthetic_inv_8821.pdf": {
        "title": "TAX INVOICE INV-8821",
        "doc_ref": "INV-8821",
        "case_ref": "VC-2026-00001",
        "party": "Emirates Cement Factory LLC (Synthetic)",
        "details": [
            ("Project:", "Alpha Horizon Tower Phase 1 (PRJ-CT4)"),
            ("Material:", "Ordinary Portland Cement (Bulk)"),
            ("Invoiced Qty:", "40.000 t"),
            ("Total Stated:", "AED 10,800.00 (Excl. VAT)"),
        ],
    },
    "synthetic_dn_4401.pdf": {
        "title": "DELIVERY NOTE DN-4401",
        "doc_ref": "DN-4401",
        "case_ref": "VC-2026-00001",
        "party": "Emirates Cement Factory LLC (Synthetic)",
        "details": [
            ("Project:", "Alpha Horizon Tower Phase 1 (PRJ-CT4)"),
            ("Material:", "Ordinary Portland Cement (Bulk)"),
            ("Delivered Qty:", "20.000 t"),
            ("Ticket Status:", "Signed & Received on Site"),
        ],
    },
    "synthetic_dn_4402.pdf": {
        "title": "DELIVERY NOTE DN-4402",
        "doc_ref": "DN-4402",
        "case_ref": "VC-2026-00001",
        "party": "Emirates Cement Factory LLC (Synthetic)",
        "details": [
            ("Project:", "Alpha Horizon Tower Phase 1 (PRJ-CT4)"),
            ("Material:", "Ordinary Portland Cement (Bulk)"),
            ("Delivered Qty:", "20.000 t"),
            ("Ticket Status:", "Signed & Received on Site"),
        ],
    },
    "synthetic_inv_9042.pdf": {
        "title": "TAX INVOICE INV-9042",
        "doc_ref": "INV-9042",
        "case_ref": "VC-2026-00002",
        "party": "Gulf ReadyMix Concrete LLC (Synthetic)",
        "details": [
            ("Project:", "Azure Bay Tower 2 (PRJ-MG2)"),
            ("Material:", "ReadyMix Concrete C40/20"),
            ("Invoiced Qty:", "24.000 m3"),
            ("Total Stated:", "AED 45,200.00 (Excl. VAT)"),
        ],
    },
    "synthetic_dn_5110.pdf": {
        "title": "DELIVERY NOTE DN-5110",
        "doc_ref": "DN-5110",
        "case_ref": "VC-2026-00002",
        "party": "Gulf ReadyMix Concrete LLC (Synthetic)",
        "details": [
            ("Project:", "Azure Bay Tower 2 (PRJ-MG2)"),
            ("Material:", "ReadyMix Concrete C40/20"),
            ("Delivered Qty:", "21.000 m3"),
            ("Ticket Status:", "Signed & Received on Site"),
        ],
    },
    "synthetic_dn_5112.pdf": {
        "title": "DELIVERY NOTE DN-5112",
        "doc_ref": "DN-5112",
        "case_ref": "VC-2026-00002",
        "party": "Gulf ReadyMix Concrete LLC (Synthetic)",
        "details": [
            ("Project:", "Azure Bay Tower 2 (PRJ-MG2)"),
            ("Material:", "ReadyMix Concrete C40/20"),
            ("Delivered Qty:", "0.000 m3 (Cancelled)"),
            ("Ticket Status:", "Batching Plant Cancellation Note"),
        ],
    },
    "synthetic_inv_3104.pdf": {
        "title": "TAX INVOICE INV-3104",
        "doc_ref": "INV-3104",
        "case_ref": "VC-2026-00003",
        "party": "Apex Steel Industries LLC (Synthetic)",
        "details": [
            ("Project:", "Metropolis Central Square (PRJ-DSQ)"),
            ("Material:", "High Tensile Rebar 16mm"),
            ("Invoiced Qty:", "55.000 t"),
        ],
    },
    "synthetic_inv_1290.pdf": {
        "title": "TAX INVOICE INV-1290",
        "doc_ref": "INV-1290",
        "case_ref": "VC-2026-00004",
        "party": "Apex Blocks & Pavers LLC (Synthetic)",
        "details": [
            ("Project:", "Palm Crest Villa 12 (PRJ-JBV)"),
            ("Material:", "Solid Masonry Blocks 200mm"),
            ("Invoiced Qty:", "4,200 pcs"),
        ],
    },
    "synthetic_dn_7019.pdf": {
        "title": "DELIVERY NOTE DN-7019",
        "doc_ref": "DN-7019",
        "case_ref": "VC-2026-00004 / VC-2026-00012",
        "party": "Apex Blocks & Pavers LLC (Synthetic)",
        "details": [
            ("Project:", "Palm Crest Villa 12 (PRJ-JBV)"),
            ("Material:", "Solid Masonry Blocks 200mm"),
            ("Delivered Qty:", "4,200 pcs"),
            ("Ticket Status:", "Flagged for Re-use across Cases"),
        ],
    },
}


def generate_synthetic_pdf_bytes(
    title: str,
    doc_ref: str,
    case_ref: str,
    supplier: str,
    details: list[tuple[str, str]] | None = None,
) -> bytes:
    """Generate deterministically rendered synthetic PDF document bytes."""
    img = Image.new("RGB", (800, 1100), color="#FAFAFA")
    draw = ImageDraw.Draw(img)

    # Outer border
    draw.rectangle([(20, 20), (780, 1080)], outline="#CCCCCC", width=2)

    # Red prototype warning banner
    draw.rectangle([(30, 30), (770, 80)], fill="#FEE2E2", outline="#EF4444", width=1)
    draw.text((50, 48), "SYNTHETIC TEST DOCUMENT - NOT A REAL FINANCIAL RECORD", fill="#991B1B")

    # Document Title
    draw.text((50, 110), title, fill="#0F172A")
    draw.line([(50, 140), (750, 140)], fill="#CBD5E1", width=1)

    # Key metadata fields
    y = 160
    fields: list[tuple[str, str]] = [
        ("Document Reference:", doc_ref),
        ("Associated Case:", case_ref),
        ("Supplier / Entity:", supplier),
        ("Environment:", "Local Prototype (Synthetic Data Only)"),
    ]
    if details:
        fields.extend(details)

    for label, val in fields:
        draw.text((50, y), label, fill="#64748B")
        draw.text((220, y), val, fill="#0F172A")
        y += 30

    draw.line([(50, y + 10), (750, y + 10)], fill="#E2E8F0", width=1)
    y += 30
    draw.text((50, y), "Content Notice:", fill="#64748B")
    draw.text((50, y + 25), "This document was deterministically generated for prototype verification.", fill="#334155")
    draw.text((50, y + 50), "No real supplier, contractor, or commercial data is contained herein.", fill="#334155")

    buf = io.BytesIO()
    img.save(buf, format="PDF")
    return buf.getvalue()


def ensure_synthetic_storage_files(storage_dir: Path | str | None = None) -> list[str]:
    """Ensure all seeded synthetic PDF files exist in the storage directory.

    Idempotently creates synthetic PDF fixtures without altering database records.
    """
    if storage_dir is None:
        from app.core.config import get_settings

        storage_dir = get_settings().storage_dir

    target_dir = Path(storage_dir).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    created: list[str] = []
    for filename, meta in SYNTHETIC_DOCUMENT_FILES.items():
        file_path = target_dir / filename
        if not file_path.is_file():
            pdf_bytes = generate_synthetic_pdf_bytes(
                title=meta["title"],
                doc_ref=meta["doc_ref"],
                case_ref=meta["case_ref"],
                supplier=meta["party"],
                details=meta.get("details"),
            )
            file_path.write_bytes(pdf_bytes)
            created.append(filename)
    return created
