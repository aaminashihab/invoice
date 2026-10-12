"""Repositories for database querying, persistence, and audit operations."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.persistence.models import (
    AuditEventOrm,
    DocumentOrm,
    FindingDispositionOrm,
    FindingOrm,
    MaterialOrm,
    ProjectOrm,
    ReviewOrm,
    SupplierOrm,
    UserOrm,
    VerificationCaseOrm,
    VerificationRunOrm,
)


class CaseRepository:
    """Operations on verification cases."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_id(self, case_id: str) -> VerificationCaseOrm | None:
        stmt = (
            select(VerificationCaseOrm)
            .where(VerificationCaseOrm.id == case_id)
            .options(
                joinedload(VerificationCaseOrm.project),
                joinedload(VerificationCaseOrm.supplier),
                joinedload(VerificationCaseOrm.documents),
                joinedload(VerificationCaseOrm.runs),
                joinedload(VerificationCaseOrm.reviews),
                joinedload(VerificationCaseOrm.line_links),
            )
        )
        return self.session.scalars(stmt).unique().first()

    def get_by_ref(self, case_ref: str) -> VerificationCaseOrm | None:
        stmt = select(VerificationCaseOrm).where(VerificationCaseOrm.case_ref == case_ref)
        return self.session.scalars(stmt).first()

    def list_cases(
        self, limit: int = 100, offset: int = 0, project_ids: list[str] | None = None
    ) -> list[VerificationCaseOrm]:
        stmt = (
            select(VerificationCaseOrm)
            .order_by(VerificationCaseOrm.created_at.desc())
            .limit(limit)
            .offset(offset)
            .options(
                joinedload(VerificationCaseOrm.project),
                joinedload(VerificationCaseOrm.supplier),
            )
        )
        if project_ids is not None:
            stmt = stmt.where(VerificationCaseOrm.project_id.in_(project_ids))
        return list(self.session.scalars(stmt).unique().all())

    def create(self, case: VerificationCaseOrm) -> VerificationCaseOrm:
        self.session.add(case)
        self.session.flush()
        return case


class DocumentRepository:
    """Operations on documents."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_id(self, document_id: str) -> DocumentOrm | None:
        return self.session.get(DocumentOrm, document_id)

    def find_by_sha256(self, sha256_hash: str) -> list[DocumentOrm]:
        stmt = (
            select(DocumentOrm)
            .where(DocumentOrm.sha256 == sha256_hash, DocumentOrm.is_deleted.is_(False))
            .options(joinedload(DocumentOrm.case))
        )
        return list(self.session.scalars(stmt).all())

    def find_dn_by_supplier_and_number(
        self, supplier_id: str, normalized_ref: str
    ) -> list[DocumentOrm]:
        stmt = (
            select(DocumentOrm)
            .join(VerificationCaseOrm)
            .where(
                VerificationCaseOrm.supplier_id == supplier_id,
                DocumentOrm.reference_no_normalized == normalized_ref,
                DocumentOrm.doc_type == "DELIVERY_NOTE",
                DocumentOrm.is_deleted.is_(False),
            )
            .options(joinedload(DocumentOrm.case))
        )
        return list(self.session.scalars(stmt).all())


class RunRepository:
    """Operations on verification runs and findings."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_id(self, run_id: str) -> VerificationRunOrm | None:
        stmt = (
            select(VerificationRunOrm)
            .where(VerificationRunOrm.id == run_id)
            .options(
                joinedload(VerificationRunOrm.findings),
                joinedload(VerificationRunOrm.review),
            )
        )
        return self.session.scalars(stmt).unique().first()

    def get_latest_for_case(self, case_id: str) -> VerificationRunOrm | None:
        stmt = (
            select(VerificationRunOrm)
            .where(VerificationRunOrm.case_id == case_id)
            .order_by(VerificationRunOrm.run_no.desc())
            .options(
                joinedload(VerificationRunOrm.findings),
                joinedload(VerificationRunOrm.review),
            )
        )
        return self.session.scalars(stmt).unique().first()

    def create_run(self, run: VerificationRunOrm) -> VerificationRunOrm:
        self.session.add(run)
        self.session.flush()
        return run


class ReviewRepository:
    """Operations on human reviews and finding dispositions."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_run_id(self, run_id: str) -> ReviewOrm | None:
        stmt = (
            select(ReviewOrm)
            .where(ReviewOrm.run_id == run_id)
            .options(
                joinedload(ReviewOrm.dispositions),
                joinedload(ReviewOrm.reviewer),
            )
        )
        return self.session.scalars(stmt).unique().first()

    def record_review(
        self, review: ReviewOrm, dispositions: list[FindingDispositionOrm]
    ) -> ReviewOrm:
        self.session.add(review)
        self.session.flush()
        for disp in dispositions:
            disp.review_id = review.id
            self.session.add(disp)
        self.session.flush()
        return review


class AuditRepository:
    """Append-only audit trail logging and retrieval."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def append_event(
        self,
        action: str,
        entity_type: str,
        entity_id: str,
        case_id: str | None = None,
        actor_id: str | None = None,
        before_state: dict[str, Any] | None = None,
        after_state: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> AuditEventOrm:
        event = AuditEventOrm(
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            case_id=case_id,
            actor_id=actor_id,
            before_state=before_state,
            after_state=after_state,
            request_id=request_id,
        )
        self.session.add(event)
        self.session.flush()
        return event

    def list_for_case(self, case_id: str) -> list[AuditEventOrm]:
        stmt = (
            select(AuditEventOrm)
            .where(AuditEventOrm.case_id == case_id)
            .order_by(AuditEventOrm.at.desc())
        )
        return list(self.session.scalars(stmt).all())


class ProjectRepository:
    """Operations on projects and user project assignments."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_assigned_project_ids(self, user_id: str) -> list[str]:
        from app.persistence.models import ProjectUserOrm

        stmt = select(ProjectUserOrm.project_id).where(ProjectUserOrm.user_id == user_id)
        return list(self.session.scalars(stmt).all())

    def get_assigned_projects(self, user_id: str) -> list[ProjectOrm]:
        from app.persistence.models import ProjectUserOrm

        stmt = (
            select(ProjectOrm)
            .join(ProjectUserOrm, ProjectUserOrm.project_id == ProjectOrm.id)
            .where(ProjectUserOrm.user_id == user_id)
        )
        return list(self.session.scalars(stmt).all())

    def is_user_assigned(self, user_id: str, project_id: str) -> bool:
        from app.persistence.models import ProjectUserOrm

        stmt = select(ProjectUserOrm).where(
            ProjectUserOrm.user_id == user_id,
            ProjectUserOrm.project_id == project_id,
        )
        return self.session.scalars(stmt).first() is not None

    def assign_user_to_project(
        self, user_id: str, project_id: str, assigned_by: str | None = None
    ):
        from app.persistence.models import ProjectUserOrm

        # Check existing
        if self.is_user_assigned(user_id, project_id):
            return None
        assignment = ProjectUserOrm(
            user_id=user_id,
            project_id=project_id,
            assigned_by=assigned_by,
        )
        self.session.add(assignment)
        self.session.flush()
        return assignment


class UserRepository:
    """Operations on user accounts and credentials."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_id(self, user_id: str) -> UserOrm | None:
        return self.session.get(UserOrm, user_id)

    def get_by_email(self, email: str) -> UserOrm | None:
        stmt = select(UserOrm).where(UserOrm.email == email.strip().lower())
        return self.session.scalars(stmt).first()

