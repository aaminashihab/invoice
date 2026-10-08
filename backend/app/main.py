"""FastAPI application factory and middleware setup for the local prototype."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session, sessionmaker

from app.api.auth import router as auth_router
from app.api.documents import router as documents_router
from app.api.lpos import router as lpos_router
from app.api.reviews import router as reviews_router
from app.core.config import Settings, get_settings
from app.core.dev_identity import (
    DEFAULT_SIMULATED_USER_ID,
    SIMULATED_USER_HEADER,
    SIMULATED_USERS,
    get_simulated_user,
)
from app.core.safety import (
    BANNER_TEXT,
    DEVELOPMENT_ENV,
    LoopbackOnlyMiddleware,
    assert_safe_configuration,
    normalized_env,
)
from app.core.security import get_current_user, require_project_access_for_case
from app.persistence.database import SessionLocal, get_db, get_engine, init_db
from app.persistence.models import UserOrm, VerificationCaseOrm
from app.persistence.repositories import AuditRepository, CaseRepository, ProjectRepository
from app.persistence.seed import ensure_synthetic_storage_files, seed_database


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Validate safety boundaries and initialize database schema on startup."""
    settings = getattr(app.state, "settings", None) or get_settings()
    assert_safe_configuration(settings)

    # Initialize database tables and seed synthetic demo data in development mode
    target_engine = get_engine(settings.database_url)
    init_db(target_engine=target_engine)
    if normalized_env(settings) == DEVELOPMENT_ENV:
        session_factory = sessionmaker(autocommit=False, autoflush=False, bind=target_engine)
        with session_factory() as session:
            seed_database(session)
        ensure_synthetic_storage_files(settings.storage_dir)

    yield


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    if settings is None:
        settings = get_settings()

    assert_safe_configuration(settings)

    app = FastAPI(
        title="Construction Invoice Verification API",
        version="0.1.0",
        description="Local prototype backend for construction invoice verification against delivery notes.",
        lifespan=lifespan,
    )
    app.state.settings = settings

    # Safety: loopback-only check
    app.add_middleware(LoopbackOnlyMiddleware)

    # CORS configuration for frontend
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list({settings.frontend_origin, "http://localhost:5173", "http://127.0.0.1:5173"}),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Attach auth, document, lpo, and review endpoints
    app.include_router(auth_router)
    app.include_router(documents_router)
    app.include_router(lpos_router)
    app.include_router(reviews_router)

    @app.get("/healthz", tags=["System"])
    async def health_check():
        """Health check endpoint confirming prototype mode and synthetic data boundary."""
        current_settings = getattr(app.state, "settings", None) or get_settings()
        return {
            "status": "healthy",
            "app_env": current_settings.app_env,
            "dev_identity_enabled": current_settings.dev_identity_enabled,
            "banner": BANNER_TEXT,
            "synthetic_data_only": True,
            "automated_vat_status": "NOT_CHECKED",
        }

    @app.get("/api/v1/auth/dev-users", tags=["Dev Identity"])
    async def list_simulated_users(request: Request):
        """List available simulated user identities (development mode only)."""
        current_settings = getattr(app.state, "settings", None) or get_settings()
        if (
            not current_settings.dev_identity_enabled
            or normalized_env(current_settings) != DEVELOPMENT_ENV
        ):
            return JSONResponse(
                status_code=403,
                content={
                    "error": {
                        "code": "DEV_IDENTITY_DISABLED",
                        "message": "Simulated identities are disabled outside local development.",
                        "details": {},
                        "field": None,
                    }
                },
            )

        active_user_id = request.headers.get(
            SIMULATED_USER_HEADER, DEFAULT_SIMULATED_USER_ID
        )
        active_user = get_simulated_user(active_user_id) or get_simulated_user(
            DEFAULT_SIMULATED_USER_ID
        )

        return {
            "banner": BANNER_TEXT,
            "active_user": active_user,
            "available_users": list(SIMULATED_USERS),
            "synthetic_data_only": True,
            "warning": (
                "Simulated users are for local functional testing only. "
                "Never upload real documents."
            ),
        }

    @app.get("/api/v1/ruleset", tags=["Ruleset"])
    async def get_active_ruleset():
        """Read-only view of active rules and gated checks (Revision 3)."""
        return {
            "version": "1.0.0-draft",
            "quantity_policy": {
                "status": "CONFIRMED",
                "rule": "Exact match (Decimal). No tolerance. Never rounded.",
            },
            "financial_rounding_policy": {
                "status": "PROVISIONAL",
                "rule": "Computed values rounded to 2 decimal places (fils, ROUND_HALF_UP) before exact comparison.",
            },
            "vat_policy": {
                "status": "NOT_CHECKED",
                "reason": "Automated VAT validation pending verified UAE VAT rule pack (Milestone M14).",
                "manual_check_allowed": True,
            },
            "payment_approval_policy": {
                "status": "CONFIRMED",
                "rule": "Never automatically approve invoices or initiate payments. Mandatory human review.",
            },
        }

    @app.get("/api/v1/cases", tags=["Cases"])
    async def list_cases(
        current_user: Annotated[UserOrm, Depends(get_current_user)],
        db: Session = Depends(get_db),
    ):
        """List persisted verification cases scoped to projects assigned to the authenticated user."""
        repo = CaseRepository(db)
        project_repo = ProjectRepository(db)
        if current_user.role == "ADMIN":
            cases = repo.list_cases()
        else:
            allowed_project_ids = project_repo.get_assigned_project_ids(current_user.id)
            cases = repo.list_cases(project_ids=allowed_project_ids)
        return {
            "banner": BANNER_TEXT,
            "synthetic_data_only": True,
            "cases": [
                {
                    "id": c.id,
                    "case_ref": c.case_ref,
                    "project": {
                        "id": c.project.id,
                        "code": c.project.code,
                        "name": c.project.name,
                        "site_location": c.project.site_location,
                    },
                    "supplier": {
                        "name": c.supplier.name,
                        "trn": c.supplier.trn,
                    },
                    "invoice_number_hint": c.invoice_number_hint,
                    "currency": c.currency,
                    "lpo_id": c.lpo_id,
                    "lpo_required": c.lpo_required,
                    "lpo_reason_code": c.lpo_reason_code,
                    "lpo_reason_text": c.lpo_reason_text,
                    "status": c.status,
                    "created_at": c.created_at.isoformat(),
                }
                for c in cases
            ],
        }

    @app.get("/api/v1/cases/{case_id}", tags=["Cases"])
    async def get_case_detail(
        case_id: str,
        current_user: Annotated[UserOrm, Depends(get_current_user)],
        db: Session = Depends(get_db),
    ):
        """Get detail of a persisted verification case including findings and audit history."""
        case_repo = CaseRepository(db)
        audit_repo = AuditRepository(db)
        c = case_repo.get_by_id(case_id)
        if not c:
            return JSONResponse(
                status_code=404,
                content={
                    "error": {
                        "code": "CASE_NOT_FOUND",
                        "message": f"Verification case {case_id} not found.",
                        "details": {},
                        "field": "case_id",
                    }
                },
            )

        # Enforce project-level authorization (M4A)
        require_project_access_for_case(case_id, current_user, db)

        audit_events = audit_repo.list_for_case(case_id)

        return {
            "banner": BANNER_TEXT,
            "synthetic_data_only": True,
            "case": {
                    "id": c.id,
                    "case_ref": c.case_ref,
                    "project": {
                        "id": c.project.id,
                        "code": c.project.code,
                        "name": c.project.name,
                    },
                    "supplier": {
                        "id": c.supplier.id,
                        "name": c.supplier.name,
                        "trn": c.supplier.trn,
                    },
                    "lpo_id": c.lpo_id,
                    "lpo": {
                        "id": c.lpo.id,
                        "lpo_number": c.lpo.lpo_number,
                        "total_amount_cap": c.lpo.total_amount_cap,
                    } if c.lpo else None,
                    "invoice_number_hint": c.invoice_number_hint,
                    "currency": c.currency,
                    "lpo_required": c.lpo_required,
                    "lpo_reason_code": c.lpo_reason_code,
                    "lpo_reason_text": c.lpo_reason_text,
                    "status": c.status,
                    "documents": [
                        {
                            "id": d.id,
                            "doc_type": d.doc_type,
                            "original_filename": d.original_filename,
                            "sha256": d.sha256,
                            "quarantine_status": d.quarantine_status,
                            "reference_no_normalized": d.reference_no_normalized,
                        }
                        for d in c.documents
                    ],
                    "runs": [
                        {
                            "id": r.id,
                            "run_no": r.run_no,
                            "summary": r.summary,
                            "summary_labels": r.summary_labels,
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
                                    "difference_pct": f.difference_pct,
                                    "unit": f.unit,
                                    "subject_type": f.subject_type,
                                    "subject_id": f.subject_id,
                                    "rule_status": f.rule_status,
                                    "numeric_policy": f.numeric_policy,
                                }
                                for f in r.findings
                            ],
                        }
                        for r in c.runs
                    ],
                    "audit_events": [
                        {
                            "id": a.id,
                            "action": a.action,
                            "actor_id": a.actor_id,
                            "at": a.at.isoformat(),
                            "entity_type": a.entity_type,
                            "after_state": a.after_state,
                        }
                        for a in audit_events
                    ],
                    "reviews": [
                        {
                            "id": rev.id,
                            "run_id": rev.run_id,
                            "reviewer_id": rev.reviewer_id,
                            "reviewer_name": rev.reviewer.name if rev.reviewer else None,
                            "outcome": rev.outcome,
                            "comment": rev.comment,
                            "declaration_accepted": rev.declaration_accepted,
                            "qualifiers": rev.qualifiers,
                            "created_at": rev.created_at.isoformat(),
                            "dispositions": [
                                {
                                    "id": disp.id,
                                    "finding_id": disp.finding_id,
                                    "disposition": disp.disposition,
                                    "comment": disp.comment,
                                }
                                for disp in rev.dispositions
                            ],
                        }
                        for rev in c.reviews
                    ],
                },
            }

    return app
