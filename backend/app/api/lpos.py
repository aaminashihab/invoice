"""LPO (Local Purchase Order) management and reconciliation link endpoints."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.safety import BANNER_TEXT
from app.core.security import get_current_user, require_project_access_for_case
from app.persistence.database import get_db
from app.persistence.models import (
    LineItemOrm,
    LineLinkOrm,
    LpoLineOrm,
    LpoOrm,
    ProjectOrm,
    SupplierOrm,
    UserOrm,
    VerificationCaseOrm,
)
from app.persistence.repositories import AuditRepository, ProjectRepository

router = APIRouter(prefix="/api/v1", tags=["LPOs"])


class LpoLineCreate(BaseModel):
    line_no: int = Field(..., ge=1)
    material_id: str | None = None
    description: str = Field(..., min_length=1)
    ordered_qty: str = Field(..., min_length=1)
    unit: str = Field(..., min_length=1)
    agreed_unit_price: str = Field(..., min_length=1)
    line_amount_cap: str | None = None


class LpoCreateRequest(BaseModel):
    lpo_number: str = Field(..., min_length=1)
    project_id: str = Field(..., min_length=1)
    supplier_id: str = Field(..., min_length=1)
    lpo_date: str = Field(..., min_length=1)
    currency: str = Field(default="AED")
    document_id: str | None = None
    total_amount_cap: str | None = None
    lines: list[LpoLineCreate] = Field(..., min_length=1)


class LinkLpoRequest(BaseModel):
    lpo_id: str = Field(..., min_length=1)


class LinkLpoLineRequest(BaseModel):
    lpo_line_id: str = Field(..., min_length=1)


@router.post("/lpos", status_code=status.HTTP_201_CREATED)
async def create_lpo(
    payload: LpoCreateRequest,
    current_user: Annotated[UserOrm, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Create a new Local Purchase Order (LPO) master contract."""
    # Enforce project assignment
    project_repo = ProjectRepository(db)
    if current_user.role != "ADMIN" and not project_repo.is_user_assigned(current_user.id, payload.project_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "PROJECT_ACCESS_DENIED", "message": "User not authorized for this project."},
        )

    # Check project and supplier exist
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

    # Check uniqueness of lpo_number
    existing = db.scalars(select(LpoOrm).where(LpoOrm.lpo_number == payload.lpo_number)).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "LPO_NUMBER_EXISTS", "message": f"LPO number '{payload.lpo_number}' already exists."},
        )

    lpo = LpoOrm(
        lpo_number=payload.lpo_number,
        project_id=payload.project_id,
        supplier_id=payload.supplier_id,
        lpo_date=payload.lpo_date,
        currency=payload.currency,
        document_id=payload.document_id,
        total_amount_cap=payload.total_amount_cap,
        is_active=True,
        created_by=current_user.id,
    )
    db.add(lpo)
    db.flush()

    for line_in in payload.lines:
        line = LpoLineOrm(
            lpo_id=lpo.id,
            line_no=line_in.line_no,
            material_id=line_in.material_id,
            description=line_in.description,
            ordered_qty=line_in.ordered_qty,
            unit=line_in.unit,
            agreed_unit_price=line_in.agreed_unit_price,
            line_amount_cap=line_in.line_amount_cap,
        )
        db.add(line)

    audit_repo = AuditRepository(db)
    audit_repo.append_event(
        action="LPO_CREATED",
        entity_type="LPO",
        entity_id=lpo.id,
        actor_id=current_user.id,
        after_state={
            "lpo_number": lpo.lpo_number,
            "project_id": lpo.project_id,
            "supplier_id": lpo.supplier_id,
            "lines_count": len(payload.lines),
        },
    )

    db.commit()
    return {
        "banner": BANNER_TEXT,
        "synthetic_data_only": True,
        "lpo_id": lpo.id,
        "lpo_number": lpo.lpo_number,
    }


@router.get("/lpos")
async def list_lpos(
    current_user: Annotated[UserOrm, Depends(get_current_user)],
    project_id: str | None = Query(None),
    supplier_id: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """List active LPOs filtered by project or supplier with user project scoping."""
    project_repo = ProjectRepository(db)
    allowed_project_ids = (
        None if current_user.role == "ADMIN" else project_repo.get_assigned_project_ids(current_user.id)
    )

    query = select(LpoOrm).where(LpoOrm.is_active.is_(True))
    if allowed_project_ids is not None:
        query = query.where(LpoOrm.project_id.in_(allowed_project_ids))
    if project_id:
        query = query.where(LpoOrm.project_id == project_id)
    if supplier_id:
        query = query.where(LpoOrm.supplier_id == supplier_id)

    lpos = db.scalars(query).all()
    return {
        "banner": BANNER_TEXT,
        "synthetic_data_only": True,
        "lpos": [
            {
                "id": l.id,
                "lpo_number": l.lpo_number,
                "project_id": l.project_id,
                "project_code": l.project.code if l.project else None,
                "supplier_id": l.supplier_id,
                "supplier_name": l.supplier.name if l.supplier else None,
                "lpo_date": l.lpo_date,
                "currency": l.currency,
                "total_amount_cap": l.total_amount_cap,
                "lines_count": len(l.lines),
                "created_at": l.created_at.isoformat(),
            }
            for l in lpos
        ],
    }


@router.get("/lpos/{lpo_id}")
async def get_lpo_detail(
    lpo_id: str,
    current_user: Annotated[UserOrm, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Retrieve full details of an LPO including line items and cumulative consumption."""
    lpo = db.get(LpoOrm, lpo_id)
    if not lpo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "LPO_NOT_FOUND", "message": f"LPO '{lpo_id}' not found."},
        )

    project_repo = ProjectRepository(db)
    if current_user.role != "ADMIN" and not project_repo.is_user_assigned(current_user.id, lpo.project_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "PROJECT_ACCESS_DENIED", "message": "User not authorized for this project."},
        )

    # Compute cumulative consumption per line
    lines_summary = []
    for line in lpo.lines:
        links = db.scalars(select(LineLinkOrm).where(LineLinkOrm.lpo_line_id == line.id)).all()
        cumulative_qty = Decimal("0")
        for link in links:
            inv_line = db.get(LineItemOrm, link.invoice_line_id)
            if inv_line:
                for f in inv_line.fields:
                    if f.field_key == "quantity" and f.normalized_value:
                        try:
                            cumulative_qty += Decimal(str(f.normalized_value))
                        except Exception:
                            pass
        ordered_dec = Decimal(str(line.ordered_qty))
        remaining_qty = max(Decimal("0"), ordered_dec - cumulative_qty)

        lines_summary.append({
            "id": line.id,
            "line_no": line.line_no,
            "material_id": line.material_id,
            "description": line.description,
            "ordered_qty": line.ordered_qty,
            "unit": line.unit,
            "agreed_unit_price": line.agreed_unit_price,
            "line_amount_cap": line.line_amount_cap,
            "cumulative_consumed_qty": str(cumulative_qty),
            "remaining_qty": str(remaining_qty),
        })

    return {
        "banner": BANNER_TEXT,
        "synthetic_data_only": True,
        "lpo": {
            "id": lpo.id,
            "lpo_number": lpo.lpo_number,
            "project_id": lpo.project_id,
            "project_code": lpo.project.code if lpo.project else None,
            "supplier_id": lpo.supplier_id,
            "supplier_name": lpo.supplier.name if lpo.supplier else None,
            "lpo_date": lpo.lpo_date,
            "currency": lpo.currency,
            "total_amount_cap": lpo.total_amount_cap,
            "lines": lines_summary,
            "created_at": lpo.created_at.isoformat(),
        },
    }


@router.post("/cases/{case_id}/link-lpo")
async def link_lpo_to_case(
    case_id: str,
    payload: LinkLpoRequest,
    current_user: Annotated[UserOrm, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Link an authorized LPO to a verification case for 3-way matching."""
    require_project_access_for_case(case_id, current_user, db)

    case = db.get(VerificationCaseOrm, case_id)
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "CASE_NOT_FOUND", "message": f"Case '{case_id}' not found."},
        )

    lpo = db.get(LpoOrm, payload.lpo_id)
    if not lpo or not lpo.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "LPO_NOT_FOUND", "message": f"Active LPO '{payload.lpo_id}' not found."},
        )

    if lpo.project_id != case.project_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "PROJECT_MISMATCH",
                "message": f"LPO project '{lpo.project_id}' does not match case project '{case.project_id}'.",
            },
        )

    if lpo.supplier_id != case.supplier_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "SUPPLIER_MISMATCH",
                "message": f"LPO supplier '{lpo.supplier_id}' does not match case supplier '{case.supplier_id}'.",
            },
        )

    case.lpo_id = lpo.id

    audit_repo = AuditRepository(db)
    audit_repo.append_event(
        action="LPO_LINKED_TO_CASE",
        entity_type="VERIFICATION_CASE",
        entity_id=case.id,
        case_id=case.id,
        actor_id=current_user.id,
        after_state={"lpo_id": lpo.id, "lpo_number": lpo.lpo_number},
    )

    db.commit()

    return {
        "banner": BANNER_TEXT,
        "synthetic_data_only": True,
        "case_id": case.id,
        "lpo_id": lpo.id,
        "lpo_number": lpo.lpo_number,
    }


@router.post("/cases/{case_id}/lines/{invoice_line_id}/link-lpo-line")
async def link_lpo_line_to_invoice_line(
    case_id: str,
    invoice_line_id: str,
    payload: LinkLpoLineRequest,
    current_user: Annotated[UserOrm, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Link an invoice line item to a contractual LPO line item."""
    require_project_access_for_case(case_id, current_user, db)

    lpo_line = db.get(LpoLineOrm, payload.lpo_line_id)
    if not lpo_line:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "LPO_LINE_NOT_FOUND", "message": f"LPO line '{payload.lpo_line_id}' not found."},
        )

    # Find line links for this invoice line
    links = db.scalars(
        select(LineLinkOrm).where(
            LineLinkOrm.case_id == case_id,
            LineLinkOrm.invoice_line_id == invoice_line_id,
        )
    ).all()

    if not links:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "LINE_LINK_NOT_FOUND", "message": f"No line links found for invoice line '{invoice_line_id}'."},
        )

    for link in links:
        link.lpo_line_id = lpo_line.id

    audit_repo = AuditRepository(db)
    audit_repo.append_event(
        action="LPO_LINE_LINKED",
        entity_type="LINE_LINK",
        entity_id=invoice_line_id,
        case_id=case_id,
        actor_id=current_user.id,
        after_state={"lpo_line_id": lpo_line.id, "lpo_id": lpo_line.lpo_id, "line_no": lpo_line.line_no},
    )

    db.commit()

    return {
        "banner": BANNER_TEXT,
        "synthetic_data_only": True,
        "case_id": case_id,
        "invoice_line_id": invoice_line_id,
        "lpo_line_id": lpo_line.id,
    }
