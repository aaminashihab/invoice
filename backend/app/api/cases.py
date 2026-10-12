"""Verification case management, manual line entry, line linking, and verification execution endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.safety import BANNER_TEXT
from app.core.security import get_current_user, require_project_access_for_case
from app.domain.engine import normalize_dn_number, verify_case
from app.domain.models import (
    CaseSnapshot,
    DNLineSnapshot,
    FieldStatus,
    InvoiceLineSnapshot,
    LPOLineSnapshot,
    ValueWithTrust,
)
from app.persistence.database import get_db
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
    SupplierOrm,
    UserOrm,
    VerificationCaseOrm,
    VerificationRunOrm,
)
from app.persistence.repositories import (
    AuditRepository,
    CaseRepository,
    DocumentRepository,
    ProjectRepository,
    RunRepository,
)

router = APIRouter(prefix="/api/v1", tags=["Cases"])


# ---------------------------------------------------------------------------
# Pydantic Request Models
# ---------------------------------------------------------------------------


class CaseCreateRequest(BaseModel):
    case_ref: str = Field(..., min_length=3, max_length=50)
    project_id: str = Field(..., min_length=1)
    supplier_id: str = Field(..., min_length=1)
    invoice_number_hint: str | None = Field(default=None, max_length=100)
    currency: str = Field(default="AED")
    lpo_required: bool = Field(default=True)
    lpo_reason_code: str | None = None
    lpo_reason_text: str | None = None
    lpo_id: str | None = None


class InvoiceLineCreateRequest(BaseModel):
    line_no: int = Field(..., ge=1)
    description: str = Field(..., min_length=1, max_length=255)
    invoiced_qty: str = Field(..., min_length=1)
    unit: str = Field(..., min_length=1, max_length=20)
    unit_price: str = Field(..., min_length=1)
    line_amount: str = Field(..., min_length=1)
    material_id: str | None = None
    document_id: str | None = None


class DeliveryNoteLineCreateRequest(BaseModel):
    dn_number: str = Field(..., min_length=1, max_length=100)
    line_no: int = Field(..., ge=1)
    description: str = Field(..., min_length=1, max_length=255)
    delivered_qty: str = Field(..., min_length=1)
    unit: str = Field(..., min_length=1, max_length=20)
    storekeeper_ticket_no: str | None = None
    storekeeper_confirmed: bool = Field(default=True)
    rejected_qty: str | None = None
    rejection_reason_code: str | None = None
    has_rejection_evidence: bool = Field(default=False)
    document_id: str | None = None


class LineLinkCreateRequest(BaseModel):
    invoice_line_id: str = Field(..., min_length=1)
    dn_line_id: str = Field(..., min_length=1)
    lpo_line_id: str | None = None
    link_method: str = Field(default="MANUAL")


# ---------------------------------------------------------------------------
# Reference Endpoints for Projects & Suppliers
# ---------------------------------------------------------------------------


@router.get("/projects")
async def list_projects(
    current_user: Annotated[UserOrm, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """List active construction projects scoped to the authenticated user."""
    project_repo = ProjectRepository(db)
    if current_user.role == "ADMIN":
        projects = db.scalars(select(ProjectOrm).where(ProjectOrm.active.is_(True))).all()
    else:
        assigned_ids = project_repo.get_assigned_project_ids(current_user.id)
        projects = db.scalars(
            select(ProjectOrm).where(ProjectOrm.id.in_(assigned_ids), ProjectOrm.active.is_(True))
        ).all()

    return {
        "banner": BANNER_TEXT,
        "synthetic_data_only": True,
        "projects": [
            {
                "id": p.id,
                "code": p.code,
                "name": p.name,
                "client": p.client,
                "site_location": p.site_location,
            }
            for p in projects
        ],
    }


@router.get("/suppliers")
async def list_suppliers(
    current_user: Annotated[UserOrm, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """List active supplier master catalog."""
    suppliers = db.scalars(select(SupplierOrm).where(SupplierOrm.active.is_(True))).all()
    return {
        "banner": BANNER_TEXT,
        "synthetic_data_only": True,
        "suppliers": [
            {
                "id": s.id,
                "name": s.name,
                "trn": s.trn,
                "aliases": s.aliases,
            }
            for s in suppliers
        ],
    }


# ---------------------------------------------------------------------------
# Case Creation & Retrieval
# ---------------------------------------------------------------------------


@router.post("/cases", status_code=status.HTTP_201_CREATED)
async def create_case(
    payload: CaseCreateRequest,
    current_user: Annotated[UserOrm, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Create a new verification case shell.

    - Authorized Roles: QS or ADMIN (Enforcing separation of duties from reviewers)
    - Enforces project scoping
    - Fixed to UAE AED currency
    """
    if current_user.role not in ("QS", "ADMIN"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "CASE_CREATION_DENIED",
                "message": f"User role '{current_user.role}' is not authorized to create verification cases. Only QS and ADMIN roles may create cases.",
            },
        )

    project_repo = ProjectRepository(db)
    if current_user.role != "ADMIN" and not project_repo.is_user_assigned(current_user.id, payload.project_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "PROJECT_ACCESS_DENIED", "message": "User not authorized for this project."},
        )

    if payload.currency.strip().upper() != "AED":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "INVALID_CURRENCY", "message": "Currency must be AED."},
        )

    project = db.get(ProjectOrm, payload.project_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "PROJECT_NOT_FOUND", "message": f"Project '{payload.project_id}' not found."},
        )

    supplier = db.get(SupplierOrm, payload.supplier_id)
    if not supplier:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "SUPPLIER_NOT_FOUND", "message": f"Supplier '{payload.supplier_id}' not found."},
        )

    # Check case_ref uniqueness
    existing = db.scalars(select(VerificationCaseOrm).where(VerificationCaseOrm.case_ref == payload.case_ref)).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "CASE_REF_EXISTS", "message": f"Case reference '{payload.case_ref}' already exists."},
        )

    # Optional initial LPO verification
    if payload.lpo_id:
        lpo = db.get(LpoOrm, payload.lpo_id)
        if not lpo or not lpo.is_active:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "LPO_NOT_FOUND", "message": f"Active LPO '{payload.lpo_id}' not found."},
            )
        if lpo.project_id != payload.project_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "PROJECT_MISMATCH", "message": "LPO project does not match case project."},
            )
        if lpo.supplier_id != payload.supplier_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "SUPPLIER_MISMATCH", "message": "LPO supplier does not match case supplier."},
            )

    case = VerificationCaseOrm(
        case_ref=payload.case_ref,
        project_id=payload.project_id,
        supplier_id=payload.supplier_id,
        invoice_number_hint=payload.invoice_number_hint,
        currency="AED",
        lpo_id=payload.lpo_id,
        lpo_required=payload.lpo_required,
        lpo_reason_code=payload.lpo_reason_code,
        lpo_reason_text=payload.lpo_reason_text,
        status="DRAFT",
        created_by=current_user.id,
    )
    db.add(case)
    db.flush()

    audit_repo = AuditRepository(db)
    audit_repo.append_event(
        action="CASE_CREATED",
        entity_type="VERIFICATION_CASE",
        entity_id=case.id,
        case_id=case.id,
        actor_id=current_user.id,
        after_state={
            "case_ref": case.case_ref,
            "project_id": case.project_id,
            "supplier_id": case.supplier_id,
            "currency": case.currency,
            "lpo_id": case.lpo_id,
        },
    )

    db.commit()

    return {
        "banner": BANNER_TEXT,
        "synthetic_data_only": True,
        "case": {
            "id": case.id,
            "case_ref": case.case_ref,
            "project_id": case.project_id,
            "supplier_id": case.supplier_id,
            "invoice_number_hint": case.invoice_number_hint,
            "currency": case.currency,
            "status": case.status,
            "created_by": case.created_by,
            "created_at": case.created_at.isoformat(),
        },
    }


# ---------------------------------------------------------------------------
# Manual Invoice Line Entry
# ---------------------------------------------------------------------------


@router.post("/cases/{case_id}/invoice-lines", status_code=status.HTTP_201_CREATED)
async def add_invoice_line(
    case_id: str,
    payload: InvoiceLineCreateRequest,
    current_user: Annotated[UserOrm, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Add a manual invoice line item and its confirmed extracted fields.

    - Authorized Roles: QS or ADMIN
    - Validates exact positive Decimal quantities
    """
    require_project_access_for_case(case_id, current_user, db)

    if current_user.role not in ("QS", "ADMIN"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "LINE_ENTRY_DENIED",
                "message": "Only QS and ADMIN roles may add invoice line items.",
            },
        )

    case = db.get(VerificationCaseOrm, case_id)
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "CASE_NOT_FOUND", "message": f"Case '{case_id}' not found."},
        )

    # Validate Decimal inputs
    try:
        qty_dec = Decimal(payload.invoiced_qty)
        rate_dec = Decimal(payload.unit_price)
        amt_dec = Decimal(payload.line_amount)
        if qty_dec <= 0 or rate_dec < 0 or amt_dec < 0:
            raise ValueError()
    except (InvalidOperation, ValueError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "INVALID_DECIMAL_VALUE",
                "message": "Quantity, unit price, and line amount must be valid non-negative Decimals (quantity > 0).",
            },
        )

    # Locate or create the case's INVOICE document
    doc = None
    if payload.document_id:
        doc = db.get(DocumentOrm, payload.document_id)
        if not doc or doc.case_id != case_id or doc.doc_type != "INVOICE":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "DOCUMENT_NOT_FOUND", "message": "Valid INVOICE document not found for this case."},
            )
    else:
        doc = next((d for d in case.documents if d.doc_type == "INVOICE" and not d.is_deleted), None)
        if not doc:
            doc = DocumentOrm(
                case_id=case_id,
                doc_type="INVOICE",
                original_filename=f"{case.invoice_number_hint or case.case_ref}_manual.pdf",
                storage_key=f"synthetic/{case.id}/invoice_manual.pdf",
                mime_type="application/pdf",
                size_bytes=1024,
                sha256=hashlib.sha256(f"inv-manual-{case.id}".encode()).hexdigest(),
                uploaded_by=current_user.id,
            )
            db.add(doc)
            db.flush()

    line_item = LineItemOrm(
        document_id=doc.id,
        line_no=payload.line_no,
        kind="MATERIAL",
        material_id=payload.material_id,
    )
    db.add(line_item)
    db.flush()

    # Create Extracted Fields
    fields_to_add = [
        ("invoiced_qty", str(qty_dec), "DECIMAL"),
        ("unit", payload.unit.strip(), "STRING"),
        ("unit_price", str(rate_dec), "DECIMAL"),
        ("line_amount", str(amt_dec), "DECIMAL"),
    ]
    for key, val, val_type in fields_to_add:
        field_orm = ExtractedFieldOrm(
            document_id=doc.id,
            line_item_id=line_item.id,
            field_key=key,
            raw_value=val,
            normalized_value=val,
            value_type=val_type,
            status="CONFIRMED",
            confidence="1.00",
            method="MANUAL_ENTRY",
            updated_by=current_user.id,
        )
        db.add(field_orm)

    audit_repo = AuditRepository(db)
    audit_repo.append_event(
        action="INVOICE_LINE_ADDED",
        entity_type="LINE_ITEM",
        entity_id=line_item.id,
        case_id=case_id,
        actor_id=current_user.id,
        after_state={
            "line_no": line_item.line_no,
            "description": payload.description,
            "invoiced_qty": str(qty_dec),
            "unit": payload.unit,
            "unit_price": str(rate_dec),
            "line_amount": str(amt_dec),
        },
    )

    db.commit()

    return {
        "banner": BANNER_TEXT,
        "synthetic_data_only": True,
        "line_item": {
            "id": line_item.id,
            "document_id": doc.id,
            "line_no": line_item.line_no,
            "description": payload.description,
            "invoiced_qty": str(qty_dec),
            "unit": payload.unit,
            "unit_price": str(rate_dec),
            "line_amount": str(amt_dec),
        },
    }


# ---------------------------------------------------------------------------
# Manual Delivery Note Line Entry & Site Receipt
# ---------------------------------------------------------------------------


@router.post("/cases/{case_id}/delivery-note-lines", status_code=status.HTTP_201_CREATED)
async def add_delivery_note_line(
    case_id: str,
    payload: DeliveryNoteLineCreateRequest,
    current_user: Annotated[UserOrm, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Add a manual delivery note line with site ticket verification and rejection quantities.

    - Authorized Roles: QS, ENGINEER, or ADMIN
    - Validates exact positive Decimal delivered quantities
    - Detects cross-case delivery note reuse
    """
    require_project_access_for_case(case_id, current_user, db)

    if current_user.role not in ("QS", "ENGINEER", "ADMIN"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "LINE_ENTRY_DENIED",
                "message": "Only QS, ENGINEER, and ADMIN roles may log delivery note lines.",
            },
        )

    case = db.get(VerificationCaseOrm, case_id)
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "CASE_NOT_FOUND", "message": f"Case '{case_id}' not found."},
        )

    try:
        deliv_dec = Decimal(payload.delivered_qty)
        if deliv_dec <= 0:
            raise ValueError()
        rej_dec = Decimal(payload.rejected_qty) if payload.rejected_qty else None
        if rej_dec is not None and rej_dec < 0:
            raise ValueError()
    except (InvalidOperation, ValueError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "INVALID_DECIMAL_VALUE",
                "message": "Delivered quantity must be > 0 and rejected quantity >= 0.",
            },
        )

    if rej_dec is not None and rej_dec > deliv_dec:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "INVALID_REJECTION_QTY",
                "message": "Rejected quantity cannot exceed delivered quantity.",
            },
        )

    normalized_dn = normalize_dn_number(payload.dn_number)

    # Check for delivery note reuse across cases
    doc_repo = DocumentRepository(db)
    reused_docs = doc_repo.find_dn_by_supplier_and_number(case.supplier_id, normalized_dn)
    other_cases = [d.case.case_ref for d in reused_docs if d.case_id != case_id and d.case]
    reuse_detected = len(other_cases) > 0

    # Locate or create the delivery note document for this ticket
    doc = None
    if payload.document_id:
        doc = db.get(DocumentOrm, payload.document_id)
        if not doc or doc.case_id != case_id or doc.doc_type != "DELIVERY_NOTE":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "DOCUMENT_NOT_FOUND", "message": "Delivery note document not found."},
            )
    else:
        # Check if a document for this normalized DN already exists on this case
        doc = next(
            (
                d
                for d in case.documents
                if d.doc_type == "DELIVERY_NOTE"
                and d.reference_no_normalized == normalized_dn
                and not d.is_deleted
            ),
            None,
        )
        if not doc:
            doc = DocumentOrm(
                case_id=case_id,
                doc_type="DELIVERY_NOTE",
                original_filename=f"{payload.dn_number}.pdf",
                reference_no_normalized=normalized_dn,
                storage_key=f"synthetic/{case.id}/dn_{normalized_dn}.pdf",
                mime_type="application/pdf",
                size_bytes=1024,
                sha256=hashlib.sha256(f"dn-{case.supplier_id}-{normalized_dn}".encode()).hexdigest(),
                uploaded_by=current_user.id,
            )
            db.add(doc)
            db.flush()

    line_item = LineItemOrm(
        document_id=doc.id,
        line_no=payload.line_no,
        kind="MATERIAL",
        storekeeper_ticket_no=payload.storekeeper_ticket_no or f"GATE-{payload.dn_number}",
        storekeeper_confirmed=payload.storekeeper_confirmed,
        storekeeper_user_id=current_user.id if current_user.role == "ENGINEER" else None,
        engineer_verified=True,
        engineer_user_id=current_user.id,
        rejected_qty=str(rej_dec) if rej_dec is not None else None,
        rejection_reason_code=payload.rejection_reason_code,
        has_rejection_evidence=payload.has_rejection_evidence,
    )
    db.add(line_item)
    db.flush()

    fields_to_add = [
        ("delivered_qty", str(deliv_dec), "DECIMAL"),
        ("unit", payload.unit.strip(), "STRING"),
    ]
    if rej_dec is not None:
        fields_to_add.append(("rejected_qty", str(rej_dec), "DECIMAL"))

    for key, val, val_type in fields_to_add:
        field_orm = ExtractedFieldOrm(
            document_id=doc.id,
            line_item_id=line_item.id,
            field_key=key,
            raw_value=val,
            normalized_value=val,
            value_type=val_type,
            status="CONFIRMED",
            confidence="1.00",
            method="MANUAL_ENTRY",
            updated_by=current_user.id,
        )
        db.add(field_orm)

    audit_repo = AuditRepository(db)
    audit_repo.append_event(
        action="DN_LINE_ADDED",
        entity_type="LINE_ITEM",
        entity_id=line_item.id,
        case_id=case_id,
        actor_id=current_user.id,
        after_state={
            "dn_number": payload.dn_number,
            "line_no": line_item.line_no,
            "delivered_qty": str(deliv_dec),
            "rejected_qty": str(rej_dec) if rej_dec else None,
            "reuse_detected": reuse_detected,
            "reused_in_cases": other_cases,
        },
    )

    db.commit()

    return {
        "banner": BANNER_TEXT,
        "synthetic_data_only": True,
        "line_item": {
            "id": line_item.id,
            "document_id": doc.id,
            "dn_number": payload.dn_number,
            "line_no": line_item.line_no,
            "description": payload.description,
            "delivered_qty": str(deliv_dec),
            "unit": payload.unit,
            "rejected_qty": str(rej_dec) if rej_dec else None,
            "has_rejection_evidence": line_item.has_rejection_evidence,
            "reuse_detected": reuse_detected,
            "other_cases": other_cases,
        },
    }


# ---------------------------------------------------------------------------
# Invoice-to-DN Line Linking (Rule P2 Enforcement)
# ---------------------------------------------------------------------------


@router.post("/cases/{case_id}/links", status_code=status.HTTP_201_CREATED)
async def create_line_link(
    case_id: str,
    payload: LineLinkCreateRequest,
    current_user: Annotated[UserOrm, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Link an invoice line to a delivery note line and optionally an LPO line.

    - Authorized Roles: QS or ADMIN
    - Enforces Provisional Rule P2: a DN line can only be linked to at most one invoice line per case.
    """
    require_project_access_for_case(case_id, current_user, db)

    if current_user.role not in ("QS", "ADMIN"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "LINK_DENIED", "message": "Only QS and ADMIN roles may link reconciliation lines."},
        )

    case = db.get(VerificationCaseOrm, case_id)
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "CASE_NOT_FOUND", "message": f"Case '{case_id}' not found."},
        )

    inv_line = db.get(LineItemOrm, payload.invoice_line_id)
    if not inv_line or inv_line.document.case_id != case_id or inv_line.document.doc_type != "INVOICE":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "INVOICE_LINE_NOT_FOUND", "message": "Invoice line item not found for this case."},
        )

    dn_line = db.get(LineItemOrm, payload.dn_line_id)
    if not dn_line or dn_line.document.case_id != case_id or dn_line.document.doc_type != "DELIVERY_NOTE":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "DN_LINE_NOT_FOUND", "message": "Delivery note line item not found for this case."},
        )

    # Enforce Rule P2: Each DN line appears in at most one confirmed link per case
    existing_link = db.scalars(
        select(LineLinkOrm).where(
            LineLinkOrm.case_id == case_id,
            LineLinkOrm.dn_line_id == payload.dn_line_id,
        )
    ).first()

    if existing_link:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "DN_LINE_ALREADY_LINKED",
                "message": (
                    f"Provisional Rule P2: Delivery note line '{payload.dn_line_id}' is already linked to "
                    f"invoice line '{existing_link.invoice_line_id}'. A delivery note line cannot be linked multiple times."
                ),
            },
        )

    # Optional LPO line validation
    if payload.lpo_line_id:
        lpo_line = db.get(LpoLineOrm, payload.lpo_line_id)
        if not lpo_line or (case.lpo_id and lpo_line.lpo_id != case.lpo_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "LPO_LINE_NOT_FOUND", "message": "Contractual LPO line not found for this case."},
            )

    link = LineLinkOrm(
        case_id=case_id,
        invoice_line_id=payload.invoice_line_id,
        dn_line_id=payload.dn_line_id,
        lpo_line_id=payload.lpo_line_id,
        link_method=payload.link_method,
        status="CONFIRMED",
        confirmed_by=current_user.id,
    )
    db.add(link)
    db.flush()

    audit_repo = AuditRepository(db)
    audit_repo.append_event(
        action="LINE_LINKED",
        entity_type="LINE_LINK",
        entity_id=link.id,
        case_id=case_id,
        actor_id=current_user.id,
        after_state={
            "invoice_line_id": payload.invoice_line_id,
            "dn_line_id": payload.dn_line_id,
            "lpo_line_id": payload.lpo_line_id,
        },
    )

    db.commit()

    return {
        "banner": BANNER_TEXT,
        "synthetic_data_only": True,
        "link": {
            "id": link.id,
            "case_id": case_id,
            "invoice_line_id": link.invoice_line_id,
            "dn_line_id": link.dn_line_id,
            "lpo_line_id": link.lpo_line_id,
            "status": link.status,
        },
    }


# ---------------------------------------------------------------------------
# Trigger Rule Verification Engine
# ---------------------------------------------------------------------------


def build_case_snapshot(case: VerificationCaseOrm, db: Session) -> CaseSnapshot:
    """Build a domain CaseSnapshot from database ORM records."""
    inv_doc = next((d for d in case.documents if d.doc_type == "INVOICE" and not d.is_deleted), None)

    # Invoice line snapshots
    invoice_lines: list[InvoiceLineSnapshot] = []
    if inv_doc:
        for line in inv_doc.line_items:
            if line.deleted_reason:
                continue
            qty_val = next((f.normalized_value for f in line.fields if f.field_key == "invoiced_qty"), None)
            unit_val = next((f.normalized_value for f in line.fields if f.field_key == "unit"), "m3")
            rate_val = next((f.normalized_value for f in line.fields if f.field_key == "unit_price"), None)
            amt_val = next((f.normalized_value for f in line.fields if f.field_key == "line_amount"), None)
            inv_mat = db.get(MaterialOrm, line.material_id) if line.material_id else None

            invoice_lines.append(
                InvoiceLineSnapshot(
                    line_id=line.id,
                    document_id=inv_doc.id,
                    invoice_number=case.invoice_number_hint or case.case_ref,
                    line_no=line.line_no,
                    material_code=inv_mat.code if inv_mat else "MATERIAL",
                    description=inv_mat.name if inv_mat else f"Line {line.line_no}",
                    invoiced_qty=ValueWithTrust(
                        value=Decimal(str(qty_val)) if qty_val else None,
                        status=FieldStatus.CONFIRMED if qty_val else FieldStatus.MISSING,
                    ),
                    unit=unit_val or "m3",
                    unit_price=ValueWithTrust(
                        value=Decimal(str(rate_val)) if rate_val else None,
                        status=FieldStatus.CONFIRMED if rate_val else FieldStatus.MISSING,
                    ),
                    line_amount=ValueWithTrust(
                        value=Decimal(str(amt_val)) if amt_val else None,
                        status=FieldStatus.CONFIRMED if amt_val else FieldStatus.MISSING,
                    ),
                )
            )

    # DN line snapshots
    dn_lines: list[DNLineSnapshot] = []
    dn_file_hashes: dict[str, str] = {}
    for d in case.documents:
        if d.doc_type == "DELIVERY_NOTE" and not d.is_deleted:
            dn_file_hashes[d.id] = d.sha256
            for line in d.line_items:
                if line.deleted_reason:
                    continue
                qty_val = next((f.normalized_value for f in line.fields if f.field_key == "delivered_qty"), None)
                unit_val = next((f.normalized_value for f in line.fields if f.field_key == "unit"), "m3")
                rej_val = line.rejected_qty
                dn_mat = db.get(MaterialOrm, line.material_id) if line.material_id else None

                dn_lines.append(
                    DNLineSnapshot(
                        line_id=line.id,
                        document_id=d.id,
                        dn_number=d.reference_no_normalized or d.original_filename,
                        line_no=line.line_no,
                        material_code=dn_mat.code if dn_mat else "MATERIAL",
                        description=dn_mat.name if dn_mat else f"DN Line {line.line_no}",
                        delivered_qty=ValueWithTrust(
                            value=Decimal(str(qty_val)) if qty_val else None,
                            status=FieldStatus.CONFIRMED if qty_val else FieldStatus.MISSING,
                        ),
                        rejected_qty=(
                            ValueWithTrust(value=Decimal(str(rej_val)), status=FieldStatus.CONFIRMED)
                            if rej_val
                            else None
                        ),
                        has_rejection_evidence=line.has_rejection_evidence,
                        unit=unit_val or "m3",
                    )
                )

    # LPO Line snapshots
    lpo_lines: list[LPOLineSnapshot] = []
    if case.lpo:
        for l_line in case.lpo.lines:
            # Calculate previously invoiced qty across other cases
            links_stmt = select(LineLinkOrm).where(
                LineLinkOrm.lpo_line_id == l_line.id,
                LineLinkOrm.case_id != case.id,
            )
            other_links = db.scalars(links_stmt).all()
            prev_qty = Decimal("0")
            for o_link in other_links:
                inv_l = db.get(LineItemOrm, o_link.invoice_line_id)
                if inv_l:
                    q_str = next((f.normalized_value for f in inv_l.fields if f.field_key == "invoiced_qty"), None)
                    if q_str:
                        try:
                            prev_qty += Decimal(str(q_str))
                        except Exception:
                            pass

            lpo_lines.append(
                LPOLineSnapshot(
                    line_id=l_line.id,
                    document_id=case.lpo.document_id or "doc-lpo",
                    lpo_number=case.lpo.lpo_number,
                    line_no=l_line.line_no,
                    material_code=l_line.material.code if l_line.material else "MATERIAL",
                    description=l_line.description,
                    ordered_qty=ValueWithTrust(value=Decimal(str(l_line.ordered_qty)), status=FieldStatus.CONFIRMED),
                    unit=l_line.unit,
                    unit_price=ValueWithTrust(value=Decimal(str(l_line.agreed_unit_price)), status=FieldStatus.CONFIRMED),
                    previously_invoiced_qty=prev_qty,
                )
            )

    # Confirmed links mapping
    confirmed_links: dict[str, list[str]] = {}
    lpo_line_links: dict[str, str] = {}
    for link in case.line_links:
        if link.status == "CONFIRMED":
            confirmed_links.setdefault(link.invoice_line_id, []).append(link.dn_line_id)
            if link.lpo_line_id:
                lpo_line_links[link.invoice_line_id] = link.lpo_line_id

    # Cross-case DN index
    all_dn_docs = db.scalars(
        select(DocumentOrm)
        .where(
            DocumentOrm.doc_type == "DELIVERY_NOTE",
            DocumentOrm.is_deleted.is_(False),
            DocumentOrm.case_id != case.id,
        )
        .options(joinedload(DocumentOrm.case))
    ).all()

    cross_case_dn_index: dict[str, list[str]] = {}
    cross_case_sha_index: dict[str, list[str]] = {}
    for d in all_dn_docs:
        if d.case and d.reference_no_normalized:
            key = f"{d.case.supplier_id}:{d.reference_no_normalized}"
            cross_case_dn_index.setdefault(key, []).append(d.case.case_ref)
        if d.case and d.sha256:
            cross_case_sha_index.setdefault(d.sha256, []).append(d.case.case_ref)

    # Compute totals
    subtotal_dec = sum(
        (Decimal(str(f.normalized_value)) for l in (inv_doc.line_items if inv_doc else []) for f in l.fields if f.field_key == "line_amount" and f.normalized_value),
        Decimal("0"),
    )
    tax_dec = (subtotal_dec * Decimal("0.05")).quantize(Decimal("0.01"))
    grand_total_dec = subtotal_dec + tax_dec

    return CaseSnapshot(
        case_id=case.id,
        project_id=case.project_id,
        project_name=case.project.name if case.project else case.project_id,
        supplier_id=case.supplier_id,
        supplier_name=case.supplier.name if case.supplier else case.supplier_id,
        supplier_trn=ValueWithTrust(value=case.supplier.trn if case.supplier else "TRN", status=FieldStatus.CONFIRMED),
        invoice_number=ValueWithTrust(value=case.invoice_number_hint or case.case_ref, status=FieldStatus.CONFIRMED),
        invoice_date=ValueWithTrust(value=datetime.utcnow().strftime("%Y-%m-%d"), status=FieldStatus.CONFIRMED),
        invoice_currency=ValueWithTrust(value=case.currency, status=FieldStatus.CONFIRMED),
        subtotal=ValueWithTrust(value=subtotal_dec, status=FieldStatus.CONFIRMED),
        tax_amount=ValueWithTrust(value=tax_dec, status=FieldStatus.CONFIRMED),
        grand_total=ValueWithTrust(value=grand_total_dec, status=FieldStatus.CONFIRMED),
        lpo_required=case.lpo_required,
        lpo_reason_code=case.lpo_reason_code,
        lpo_reason_text=case.lpo_reason_text,
        invoice_lines=invoice_lines,
        dn_lines=dn_lines,
        lpo_lines=lpo_lines,
        confirmed_links=confirmed_links,
        lpo_line_links=lpo_line_links,
        cross_case_dn_index=cross_case_dn_index,
        cross_case_sha_index=cross_case_sha_index,
        dn_file_hashes=dn_file_hashes,
    )


@router.post("/cases/{case_id}/verify", status_code=status.HTTP_201_CREATED)
async def execute_verification(
    case_id: str,
    current_user: Annotated[UserOrm, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Execute the rule-based verification engine on the current case snapshot.

    - Authorized Roles: QS, REVIEWER, or ADMIN
    - Evaluates exact Decimal quantities, cumulative caps, DN reuse, and SoD
    - Persists an immutable VerificationRun and Findings
    """
    require_project_access_for_case(case_id, current_user, db)

    case = db.get(VerificationCaseOrm, case_id)
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "CASE_NOT_FOUND", "message": f"Case '{case_id}' not found."},
        )

    # Build pure domain snapshot
    snapshot = build_case_snapshot(case, db)

    # Run pure verification engine
    findings = verify_case(snapshot)

    # Determine next run number
    run_repo = RunRepository(db)
    latest_run = run_repo.get_latest_for_case(case_id)
    next_run_no = (latest_run.run_no + 1) if latest_run else 1

    # Summarize findings
    has_mismatch = any(f.outcome.value in ("MISMATCH", "UNIT_INCOMPATIBLE") for f in findings)
    has_missing = any(f.outcome.value == "MISSING_EVIDENCE" for f in findings)
    summary_labels: list[str] = []
    if has_mismatch:
        summary_labels.append("Discrepancies Detected")
        case_verif_status = "MISMATCH"
    elif has_missing:
        summary_labels.append("Missing Evidence")
        case_verif_status = "MISSING_EVIDENCE"
    else:
        summary_labels.append("Verified Exact Match")
        case_verif_status = "MATCH"

    run_orm = VerificationRunOrm(
        case_id=case_id,
        run_no=next_run_no,
        ruleset_version="1.0.0-draft",
        active_checks={"policy": "Exact Decimal Zero-Tolerance", "vat": "NOT_CHECKED"},
        input_snapshot={
            "case_ref": case.case_ref,
            "invoice_lines_count": len(snapshot.invoice_lines),
            "dn_lines_count": len(snapshot.dn_lines),
            "links_count": len(snapshot.confirmed_links),
        },
        input_hash=hashlib.sha256(f"{case.id}-{next_run_no}".encode()).hexdigest(),
        summary=f"Run {next_run_no}: {case_verif_status}",
        summary_labels=summary_labels,
        started_by=current_user.id,
    )
    db.add(run_orm)
    db.flush()

    for f in findings:
        f_orm = FindingOrm(
            run_id=run_orm.id,
            category=f.category.value,
            rule_code=f.rule_code,
            outcome=f.outcome.value,
            severity=f.severity.value,
            subject_type=f.subject_type or "GENERAL",
            subject_id=f.subject_id,
            message=f.message,
            expected=f.expected_value,
            actual=f.actual_value,
            difference=f.difference,
            difference_pct=f.difference_pct,
            unit=f.unit,
            rule_status=f.rule_status.value,
            numeric_policy=f.numeric_policy.value if f.numeric_policy else None,
            sources=[{"doc_id": s.document_id, "label": s.label} for s in f.sources],
            details=f.details,
        )
        db.add(f_orm)

    case.status = "READY_FOR_REVIEW"

    audit_repo = AuditRepository(db)
    audit_repo.append_event(
        action="VERIFICATION_RUN_COMPLETED",
        entity_type="VERIFICATION_RUN",
        entity_id=run_orm.id,
        case_id=case_id,
        actor_id=current_user.id,
        after_state={
            "run_no": run_orm.run_no,
            "summary": run_orm.summary,
            "findings_count": len(findings),
            "status": case_verif_status,
        },
    )

    db.commit()

    return {
        "banner": BANNER_TEXT,
        "synthetic_data_only": True,
        "run": {
            "id": run_orm.id,
            "run_no": run_orm.run_no,
            "summary": run_orm.summary,
            "summary_labels": run_orm.summary_labels,
            "findings": [
                {
                    "id": f.id,
                    "category": f.category,
                    "rule_code": f.rule_code,
                    "outcome": f.outcome,
                    "severity": f.severity,
                    "message": f.message,
                    "expected": f.expected,
                    "actual": f.actual,
                    "difference": f.difference,
                    "unit": f.unit,
                    "rule_status": f.rule_status,
                }
                for f in run_orm.findings
            ],
        },
        "case_status": case.status,
    }
