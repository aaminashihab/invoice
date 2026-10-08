"""Review REST API endpoints for human reviewer sign-off and finding dispositions."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.documents import get_actor_id
from app.core.dev_identity import SIMULATED_USER_HEADER
from app.core.safety import BANNER_TEXT
from app.core.security import get_current_user, require_project_access_for_case
from app.persistence.database import get_db
from app.persistence.models import FindingDispositionOrm, ReviewOrm, UserOrm
from app.persistence.repositories import (
    AuditRepository,
    CaseRepository,
    ReviewRepository,
    RunRepository,
)

router = APIRouter(prefix="/api/v1", tags=["Reviews"])


class ReviewCreateRequest(BaseModel):
    """Payload for submitting a formal human verification review."""

    outcome: str = Field(
        ...,
        description="Review outcome (VERIFIED_NO_EXCEPTIONS, VERIFIED_WITH_EXCEPTIONS, ON_HOLD_QUERIED, REJECTED)",
    )
    comment: str = Field(..., description="Reviewer notes or exception justification")
    declaration_accepted: bool = Field(..., description="Mandatory audit sign-off confirmation")
    manual_vat_checked: bool = Field(default=False, description="Whether manual VAT check was documented")
    disposition_comment: str | None = Field(default=None, description="Optional specific finding disposition text")


@router.post("/cases/{case_id}/reviews", status_code=status.HTTP_201_CREATED)
async def submit_case_review(
    case_id: str,
    payload: ReviewCreateRequest,
    current_user: Annotated[UserOrm, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)] = None,  # type: ignore[assignment]
):
    """Record an immutable human review decision for a verification case.

    * Enforces reviewer role permission (Decision D6: user.can_review must be True).
    * Enforces project-level authorization (M4A).
    * Binds to the latest verification run for the case.
    * Enforces that a verification run can only be reviewed once (uq_review_run_id).
    * Enforces zero-tolerance quantity rules (D1) and missing evidence rules (F8).
    * Automatically attaches finding dispositions (e.g. C1 justified DN reuse).
    * Logs an immutable REVIEW_RECORDED audit event and updates case status.
    """
    # 0. Enforce project-level authorization (M4A)
    require_project_access_for_case(case_id, current_user, db)

    # 1. Enforce D6 can_review permission
    if not current_user.can_review:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "REVIEW_PERMISSION_DENIED",
                "message": f"User '{current_user.name}' ({current_user.role}) does not have review permission (D6: can_review=False).",
            },
        )

    # 2. Verify case exists
    case_repo = CaseRepository(db)
    case = case_repo.get_by_id(case_id)
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "CASE_NOT_FOUND", "message": f"Verification case '{case_id}' not found."},
        )

    # 2b. Enforce Segregation of Duties (SoD)
    if case.created_by and case.created_by == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "REVIEW_SOD_VIOLATION",
                "message": f"Segregation of Duties: Reviewer '{current_user.name}' created case '{case.case_ref}' and cannot review it.",
            },
        )

    invoice_doc = next((d for d in case.documents if d.doc_type == "INVOICE" and not d.is_deleted), None)
    if invoice_doc and invoice_doc.uploaded_by and invoice_doc.uploaded_by == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "REVIEW_SOD_VIOLATION",
                "message": f"Segregation of Duties: Reviewer '{current_user.name}' uploaded the invoice for case '{case.case_ref}' and cannot review it.",
            },
        )

    # 3. Fetch latest verification run
    run_repo = RunRepository(db)
    latest_run = run_repo.get_latest_for_case(case_id)
    if not latest_run:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "NO_VERIFICATION_RUN",
                "message": f"Case '{case_id}' has no verification runs to review.",
            },
        )

    # 4. Check if run has already been reviewed (unique constraint uq_review_run_id)
    review_repo = ReviewRepository(db)
    existing_review = review_repo.get_by_run_id(latest_run.id)
    if existing_review:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "RUN_ALREADY_REVIEWED",
                "message": f"Verification run '{latest_run.id}' for case '{case_id}' has already been reviewed.",
            },
        )

    # 5. Enforce declaration acceptance
    if not payload.declaration_accepted:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "DECLARATION_REQUIRED",
                "message": "Reviewer must accept the safety declaration confirming this is an audit sign-off, not a payment approval.",
            },
        )

    # 6. Evaluate findings against permitted review outcomes (reviewValidation rules)
    findings = latest_run.findings
    has_quantity_mismatch = any(
        f.outcome == "MISMATCH" and (f.category in ("QTY_LINE", "QTY_TOTAL") or "QTY" in f.rule_code)
        for f in findings
    )
    has_missing_evidence = any(
        f.outcome == "MISSING_EVIDENCE" or f.category == "COMPLETENESS"
        for f in findings
        if f.outcome == "MISSING_EVIDENCE"
    )
    has_uncertain_evidence = any(
        f.outcome == "UNCERTAIN"
        for f in findings
    )
    has_unit_incompatible = any(
        f.outcome == "UNIT_INCOMPATIBLE" or (f.category == "UNIT" and f.outcome == "MISMATCH")
        for f in findings
    )
    has_dn_reuse = any(
        f.category == "DN_REUSE" or f.rule_code.startswith("DN_REUSE") or (f.rule_code == "DN_001" and f.outcome == "MISMATCH")
        for f in findings
    )

    outcome = payload.outcome.strip()
    trimmed_comment = payload.comment.strip()

    if outcome == "VERIFIED_NO_EXCEPTIONS":
        if has_quantity_mismatch:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "DISALLOWED_OUTCOME", "message": "Blocked: Quantity mismatch detected (D1 exact tolerance policy)."},
            )
        if has_missing_evidence:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "DISALLOWED_OUTCOME", "message": "Blocked: Missing required document or evidence (F8 evidence rule)."},
            )
        if has_uncertain_evidence:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "DISALLOWED_OUTCOME", "message": "Blocked: Uncertain or unconfirmed extracted values present."},
            )
        if has_unit_incompatible:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "DISALLOWED_OUTCOME", "message": "Blocked: Incompatible units without confirmed conversion rule."},
            )
        if has_dn_reuse:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "DISALLOWED_OUTCOME", "message": "Blocked: Delivery note reuse flagged (C1 requires noted exception)."},
            )
        if not payload.manual_vat_checked:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "VAT_CHECK_REQUIRED", "message": "Blocked: Automated VAT is NOT_CHECKED; requires documented manual VAT check (P9)."},
            )
        if len(trimmed_comment) < 3:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "COMMENT_TOO_SHORT", "message": "Reviewer note must be at least 3 characters."},
            )

    elif outcome == "VERIFIED_WITH_EXCEPTIONS":
        if has_quantity_mismatch:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "DISALLOWED_OUTCOME",
                    "message": "Prevented: Quantity mismatch cannot be verified with exceptions (D1 zero-tolerance rule requires supplier query or rejection).",
                },
            )
        if has_missing_evidence:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "DISALLOWED_OUTCOME",
                    "message": "Prevented: Missing required evidence cannot be verified with exceptions (F8 requires supplier query or rejection).",
                },
            )
        if not has_dn_reuse:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "DISALLOWED_OUTCOME",
                    "message": "Prevented: No permitted exception applicable. Clean cases must use 'VERIFIED_NO_EXCEPTIONS'.",
                },
            )
        if len(trimmed_comment) < 10:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "JUSTIFICATION_REQUIRED",
                    "message": "Reviewer justification is required for permitted exceptions (minimum 10 characters).",
                },
            )

    elif outcome == "ON_HOLD_QUERIED":
        if len(trimmed_comment) < 5:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "JUSTIFICATION_REQUIRED",
                    "message": "Supplier query rationale is required (minimum 5 characters).",
                },
            )

    elif outcome == "REJECTED":
        if len(trimmed_comment) < 5:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "JUSTIFICATION_REQUIRED",
                    "message": "Rejection rationale is required (minimum 5 characters).",
                },
            )

    else:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "INVALID_OUTCOME", "message": f"Unrecognized review outcome '{outcome}'."},
        )

    # 7. Construct Qualifiers and Dispositions
    qualifiers: list[str] = ["Automated VAT: NOT_CHECKED"]
    if payload.manual_vat_checked:
        qualifiers.append("Manual VAT check documented by reviewer")

    dispositions: list[FindingDispositionOrm] = []
    if outcome == "VERIFIED_WITH_EXCEPTIONS" and has_dn_reuse:
        dn_findings = [f for f in findings if f.category == "DN_REUSE" or f.rule_code.startswith("DN_REUSE")]
        for dnf in dn_findings:
            dispositions.append(
                FindingDispositionOrm(
                    finding_id=dnf.id,
                    disposition="REUSE_JUSTIFIED",
                    comment=payload.disposition_comment or trimmed_comment,
                    manual_check_items={"vat_manual": payload.manual_vat_checked},
                )
            )

    # 8. Atomic database transaction
    try:
        review = ReviewOrm(
            case_id=case_id,
            run_id=latest_run.id,
            reviewer_id=current_user.id,
            outcome=outcome,
            comment=trimmed_comment,
            declaration_accepted=True,
            sod_warning=False,
            qualifiers=qualifiers,
        )
        review_repo.record_review(review, dispositions)

        # Update case status
        case.status = outcome

        audit_repo = AuditRepository(db)
        audit_repo.append_event(
            action="REVIEW_RECORDED",
            entity_type="VERIFICATION_CASE",
            entity_id=case_id,
            case_id=case_id,
            actor_id=current_user.id,
            after_state={
                "outcome": outcome,
                "review_id": review.id,
                "run_id": latest_run.id,
                "reviewer": current_user.name,
                "qualifiers": qualifiers,
                "has_dispositions": len(dispositions) > 0,
            },
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "DATABASE_ERROR", "message": f"Failed to record review: {exc}"},
        ) from exc

    return {
        "banner": BANNER_TEXT,
        "synthetic_data_only": True,
        "review": {
            "id": review.id,
            "case_id": case_id,
            "run_id": latest_run.id,
            "reviewer_id": current_user.id,
            "reviewer_name": current_user.name,
            "outcome": review.outcome,
            "comment": review.comment,
            "declaration_accepted": review.declaration_accepted,
            "qualifiers": review.qualifiers,
            "created_at": review.created_at.isoformat(),
            "dispositions": [
                {
                    "id": d.id,
                    "finding_id": d.finding_id,
                    "disposition": d.disposition,
                    "comment": d.comment,
                }
                for d in dispositions
            ],
        },
        "case_status": case.status,
    }
