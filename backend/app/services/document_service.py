"""Document management service coordinating validation, storage, deduplication, and audit logging."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.persistence.models import AuditEventOrm, DocumentOrm, UserOrm, VerificationCaseOrm
from app.persistence.repositories import AuditRepository, DocumentRepository
from app.storage.interface import DocumentStorage, get_document_storage
from app.storage.validator import (
    ValidatedDocument,
    validate_uploaded_document,
)


from app.storage.scanner import MalwareDetectedError, ScannerUnavailableError, scan_content


class CaseNotFoundError(KeyError):
    """Case does not exist (HTTP 404)."""


class DocumentNotFoundError(KeyError):
    """Document does not exist (HTTP 404)."""


class DuplicateDocumentError(ValueError):
    """File with identical content is already attached to this case (HTTP 409)."""


@dataclass(frozen=True)
class DocumentUploadResult:
    """Result of uploading a document to a case."""

    document: DocumentOrm
    reuse_warning: bool
    conflict_case_id: str | None = None
    conflict_case_ref: str | None = None


MIME_TO_EXTENSION: dict[str, str] = {
    "application/pdf": "pdf",
    "image/jpeg": "jpg",
    "image/png": "png",
}


class DocumentService:
    """Service handling document lifecycle operations."""

    def __init__(
        self,
        session: Session,
        storage: DocumentStorage | None = None,
    ) -> None:
        self.session = session
        self.storage = storage or get_document_storage()
        self.doc_repo = DocumentRepository(session)
        self.audit_repo = AuditRepository(session)

    def _resolve_actor_id(self, actor_id: str | None) -> str | None:
        """Resolve simulated actor to a valid database UserOrm record to avoid FK violations."""
        if not actor_id:
            return None
        if self.session.get(UserOrm, actor_id):
            return actor_id
        alias = {
            "sim-engineer": "usr-sim-eng",
            "sim-qs": "usr-sim-qs",
            "sim-reviewer": "usr-sim-rev",
            "sim-accounts": "usr-sim-acc",
        }.get(actor_id)
        if alias and self.session.get(UserOrm, alias):
            return alias
        return None

    def upload_document(
        self,
        case_id: str,
        filename: str,
        content: bytes,
        doc_type: str,
        uploaded_by: str | None = None,
        _commit: bool = True,
    ) -> DocumentUploadResult:
        """Validate, store, and register a new document for a verification case.

        * Staged in quarantine tier first
        * Scanned for malware with fail-closed semantics
        * Inspected for active content (JS/Launch)
        * Stored in AES-256 encrypted clean storage
        * If identical file exists in the SAME case -> HTTP 409
        * If identical file exists in ANOTHER case -> HTTP 201 with reuse_warning
        """
        uploaded_by = self._resolve_actor_id(uploaded_by)
        # 1. Verify case exists
        case = self.session.get(VerificationCaseOrm, case_id)
        if not case:
            raise CaseNotFoundError(f"Verification case '{case_id}' does not exist.")

        # 2. Stage to quarantine tier
        doc_id = str(uuid.uuid4())
        ext = "pdf" if filename.lower().endswith(".pdf") else ("jpg" if filename.lower().endswith((".jpg", ".jpeg")) else "png")
        storage_key = f"{doc_id}.{ext}"

        if hasattr(self.storage, "save_quarantine"):
            self.storage.save_quarantine(storage_key, content)

        # 3. Anti-malware inspection (Fail-Closed)
        scan_res = scan_content(content)
        if not scan_res.is_clean:
            self.audit_repo.append_event(
                action="MALWARE_DETECTED",
                entity_type="DOCUMENT",
                entity_id=doc_id,
                case_id=case_id,
                actor_id=uploaded_by,
                after_state={
                    "filename": filename,
                    "signature": scan_res.signature_found,
                    "scanner": scan_res.scanner_name,
                },
            )
            if hasattr(self.storage, "quarantine"):
                self.storage.quarantine.delete(storage_key)
            raise MalwareDetectedError(
                f"Malware or viral signature detected in '{filename}': {scan_res.signature_found or scan_res.details}"
            )

        # 4. Content Validation (Magic bytes and PDF active content check)
        try:
            validated = validate_uploaded_document(filename, content)
        except Exception:
            if hasattr(self.storage, "quarantine"):
                self.storage.quarantine.delete(storage_key)
            raise

        # 5. Check for duplicates in the SAME case
        existing_in_same_case = self.session.scalars(
            select(DocumentOrm).where(
                DocumentOrm.case_id == case_id,
                DocumentOrm.sha256 == validated.sha256,
                DocumentOrm.is_deleted.is_(False),
            )
        ).first()

        if existing_in_same_case:
            if hasattr(self.storage, "quarantine"):
                self.storage.quarantine.delete(storage_key)
            raise DuplicateDocumentError(
                f"File '{filename}' with identical hash is already attached to this case "
                f"(Document ID: {existing_in_same_case.id})."
            )

        # 6. Check for duplicates in ANOTHER case (DN reuse detection)
        existing_in_other_case = self.session.scalars(
            select(DocumentOrm).where(
                DocumentOrm.case_id != case_id,
                DocumentOrm.sha256 == validated.sha256,
                DocumentOrm.is_deleted.is_(False),
            )
        ).first()

        reuse_warning = False
        conflict_case_id = None
        conflict_case_ref = None

        if existing_in_other_case:
            reuse_warning = True
            conflict_case_id = existing_in_other_case.case_id
            other_case = self.session.get(VerificationCaseOrm, conflict_case_id)
            conflict_case_ref = other_case.case_ref if other_case else conflict_case_id

        # 7. Promote payload to encrypted clean storage and remove from quarantine
        self.storage.save(storage_key, content)
        if hasattr(self.storage, "quarantine"):
            self.storage.quarantine.delete(storage_key)

        # 8. Save Document ORM & Audit within protected try block
        try:
            doc = DocumentOrm(
                id=doc_id,
                case_id=case_id,
                doc_type=doc_type.upper(),
                original_filename=filename,
                storage_key=storage_key,
                mime_type=validated.mime_type,
                size_bytes=validated.size_bytes,
                sha256=validated.sha256,
                page_count=validated.page_count,
                quarantine_status="CLEAN",
                security_scan_result=scan_res.details,
                is_quarantined=False,
                uploaded_by=uploaded_by,
                extraction_status="PENDING",
                data_review_status="UNREVIEWED",
                is_deleted=False,
            )
            self.session.add(doc)
            self.session.flush()

            # 9. Audit logging
            self.audit_repo.append_event(
                action="DOCUMENT_UPLOADED",
                entity_type="DOCUMENT",
                entity_id=doc.id,
                case_id=case_id,
                actor_id=uploaded_by,
                after_state={
                    "filename": filename,
                    "doc_type": doc.doc_type,
                    "sha256": doc.sha256,
                    "size_bytes": doc.size_bytes,
                    "quarantine_status": "CLEAN",
                    "reuse_warning": reuse_warning,
                    "conflict_case_ref": conflict_case_ref,
                },
            )

            if reuse_warning:
                self.audit_repo.append_event(
                    action="DN_REUSE_FLAGGED",
                    entity_type="DOCUMENT",
                    entity_id=doc.id,
                    case_id=case_id,
                    actor_id=uploaded_by,
                    after_state={
                        "rule": "C1_PERMANENT",
                        "conflict_case_id": conflict_case_id,
                        "conflict_case_ref": conflict_case_ref,
                        "sha256": doc.sha256,
                    },
                )

            if _commit:
                self.session.commit()

        except Exception:
            self.session.rollback()
            try:
                # Ambiguous commit defense: only delete file if document was not committed
                if not self.session.get(DocumentOrm, doc_id):
                    self.storage.delete(storage_key)
            except Exception:
                pass  # Preserve original DB exception
            raise

        return DocumentUploadResult(
            document=doc,
            reuse_warning=reuse_warning,
            conflict_case_id=conflict_case_id,
            conflict_case_ref=conflict_case_ref,
        )

    def get_document(self, document_id: str) -> DocumentOrm:
        """Fetch document metadata by ID."""
        doc = self.session.get(DocumentOrm, document_id)
        if not doc or doc.is_deleted:
            raise DocumentNotFoundError(f"Document '{document_id}' not found.")
        return doc

    def get_document_content(self, document_id: str) -> tuple[bytes, str, str]:
        """Fetch document binary content, MIME type, and filename."""
        doc = self.get_document(document_id)
        data = self.storage.read(doc.storage_key)
        return data, doc.mime_type, doc.original_filename

    def soft_delete_document(self, document_id: str, actor_id: str | None = None) -> DocumentOrm:
        """Soft-delete a document (never hard delete, preserving audit trail)."""
        actor_id = self._resolve_actor_id(actor_id)
        doc = self.session.get(DocumentOrm, document_id)
        if not doc or doc.is_deleted:
            raise DocumentNotFoundError(f"Document '{document_id}' not found.")

        doc.is_deleted = True
        self.audit_repo.append_event(
            action="DOCUMENT_DELETED",
            entity_type="DOCUMENT",
            entity_id=doc.id,
            case_id=doc.case_id,
            actor_id=actor_id,
            before_state={"is_deleted": False},
            after_state={"is_deleted": True},
        )
        self.session.commit()
        return doc

    def replace_document(
        self,
        document_id: str,
        new_filename: str,
        new_content: bytes,
        new_doc_type: str,
        actor_id: str | None = None,
    ) -> DocumentUploadResult:
        """Replace a document: creates a new document record and marks existing as superseded.

        All database modifications (new document insertion, marking old document superseded,
        and associated audit events) occur within a single database transaction.
        If any database failure occurs, changes are rolled back and the newly stored file
        is safely deleted from storage while keeping the original document and file intact.
        """
        actor_id = self._resolve_actor_id(actor_id)
        old_doc = self.get_document(document_id)
        case_id = old_doc.case_id

        # 1. Upload new document without committing immediately
        result = self.upload_document(
            case_id=case_id,
            filename=new_filename,
            content=new_content,
            doc_type=new_doc_type,
            uploaded_by=actor_id,
            _commit=False,
        )

        try:
            # 2. Mark old document as superseded and soft-deleted in the SAME transaction
            old_doc.superseded_by_id = result.document.id
            old_doc.is_deleted = True

            self.audit_repo.append_event(
                action="DOCUMENT_SUPERSEDED",
                entity_type="DOCUMENT",
                entity_id=old_doc.id,
                case_id=case_id,
                actor_id=actor_id,
                before_state={"superseded_by_id": None},
                after_state={"superseded_by_id": result.document.id},
            )

            # 3. Commit everything atomically in one transaction
            self.session.commit()
        except Exception:
            self.session.rollback()
            try:
                if 'result' in locals() and result and result.document:
                    new_doc_id = result.document.id
                    # Ambiguous commit defense: only delete if new document was not committed
                    if not self.session.get(DocumentOrm, new_doc_id):
                        self.storage.delete(result.document.storage_key)
            except Exception:
                pass
            raise

        return result
