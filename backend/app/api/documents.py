"""Document REST API endpoints for upload, inspection, download, replacement, and soft-deletion."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Response, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.dev_identity import DEFAULT_SIMULATED_USER_ID, SIMULATED_USER_HEADER
from app.core.safety import BANNER_TEXT
from app.core.security import get_current_user, require_project_access_for_case
from app.persistence.database import get_db
from app.persistence.models import UserOrm
from app.services.document_service import (
    CaseNotFoundError,
    DocumentNotFoundError,
    DocumentService,
    DuplicateDocumentError,
)
from app.storage.interface import DocumentStorage, get_document_storage
from app.storage.pdf_security import ActiveContentProhibitedError
from app.storage.scanner import MalwareDetectedError, ScannerUnavailableError
from app.storage.validator import (
    CorruptDocumentError,
    EncryptedDocumentError,
    FileTooLargeError,
    PageLimitExceededError,
    UnsupportedMediaTypeError,
)

router = APIRouter(prefix="/api/v1", tags=["Documents"])


def get_actor_id(user_header: str | None) -> str:
    raw = user_header or DEFAULT_SIMULATED_USER_ID
    aliases = {
        "sim-engineer": "usr-sim-eng",
        "sim-qs": "usr-sim-qs",
        "sim-reviewer": "usr-sim-rev",
        "sim-accounts": "usr-sim-acc",
    }
    return aliases.get(raw, raw)


@router.post("/cases/{case_id}/documents", status_code=201)
async def upload_document_to_case(
    case_id: str,
    file: Annotated[UploadFile, File(...)],
    doc_type: Annotated[str, Form(...)],
    current_user: Annotated[UserOrm, Depends(get_current_user)],
    db: Session = Depends(get_db),
    storage: DocumentStorage = Depends(get_document_storage),
):
    """Upload and attach a document to a verification case.

    * Enforces project-level authorization (M4A)
    * Enforces max 20 MB size (413)
    * Enforces allowed file types: PDF, JPEG, PNG (415)
    * Rejects encrypted or corrupt documents (422)
    * Rejects duplicates in the SAME case (409)
    * Allows duplicates across cases with a `reuse_warning` (201)
    """
    require_project_access_for_case(case_id, current_user, db)

    content = await file.read()
    filename = file.filename or "uploaded_document"
    actor_id = current_user.id

    service = DocumentService(db, storage=storage)

    try:
        result = service.upload_document(
            case_id=case_id,
            filename=filename,
            content=content,
            doc_type=doc_type,
            uploaded_by=actor_id,
        )
    except MalwareDetectedError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "MALWARE_DETECTED", "message": str(exc)},
        ) from exc
    except ActiveContentProhibitedError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "ACTIVE_CONTENT_PROHIBITED", "message": str(exc)},
        ) from exc
    except ScannerUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "SCANNER_UNAVAILABLE", "message": str(exc)},
        ) from exc
    except CaseNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "CASE_NOT_FOUND", "message": str(exc)},
        ) from exc
    except FileTooLargeError as exc:
        raise HTTPException(
            status_code=413,
            detail={"code": "FILE_TOO_LARGE", "message": str(exc)},
        ) from exc
    except UnsupportedMediaTypeError as exc:
        raise HTTPException(
            status_code=415,
            detail={"code": "UNSUPPORTED_MEDIA_TYPE", "message": str(exc)},
        ) from exc
    except (EncryptedDocumentError, PageLimitExceededError, CorruptDocumentError) as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": exc.__class__.__name__, "message": str(exc)},
        ) from exc
    except DuplicateDocumentError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "DUPLICATE_DOCUMENT_IN_CASE", "message": str(exc)},
        ) from exc

    doc = result.document

    return {
        "banner": BANNER_TEXT,
        "synthetic_data_only": True,
        "document": {
            "id": doc.id,
            "case_id": doc.case_id,
            "doc_type": doc.doc_type,
            "original_filename": doc.original_filename,
            "mime_type": doc.mime_type,
            "size_bytes": doc.size_bytes,
            "sha256": doc.sha256,
            "page_count": doc.page_count,
            "extraction_status": doc.extraction_status,
            "data_review_status": doc.data_review_status,
            "uploaded_at": doc.uploaded_at.isoformat(),
        },
        "reuse_warning": result.reuse_warning,
        "conflict_case_id": result.conflict_case_id,
        "conflict_case_ref": result.conflict_case_ref,
    }


@router.get("/documents/{document_id}")
async def get_document_metadata(
    document_id: str,
    current_user: Annotated[UserOrm, Depends(get_current_user)],
    db: Session = Depends(get_db),
    storage: DocumentStorage = Depends(get_document_storage),
):
    """Retrieve metadata of a stored document."""
    service = DocumentService(db, storage=storage)
    try:
        doc = service.get_document(document_id)
    except DocumentNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "DOCUMENT_NOT_FOUND", "message": str(exc)},
        ) from exc

    if doc.case_id:
        require_project_access_for_case(doc.case_id, current_user, db)

    return {
        "banner": BANNER_TEXT,
        "synthetic_data_only": True,
        "document": {
            "id": doc.id,
            "case_id": doc.case_id,
            "doc_type": doc.doc_type,
            "original_filename": doc.original_filename,
            "mime_type": doc.mime_type,
            "size_bytes": doc.size_bytes,
            "sha256": doc.sha256,
            "page_count": doc.page_count,
            "extraction_status": doc.extraction_status,
            "data_review_status": doc.data_review_status,
            "uploaded_at": doc.uploaded_at.isoformat(),
            "superseded_by_id": doc.superseded_by_id,
        },
    }


@router.get("/documents/{document_id}/content")
async def get_document_content(
    document_id: str,
    current_user: Annotated[UserOrm, Depends(get_current_user)],
    db: Session = Depends(get_db),
    storage: DocumentStorage = Depends(get_document_storage),
):
    """Stream raw document binary content with project-scoped access control."""
    service = DocumentService(db, storage=storage)
    try:
        doc = service.get_document(document_id)
    except DocumentNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "DOCUMENT_NOT_FOUND", "message": str(exc)},
        ) from exc

    if doc.case_id:
        require_project_access_for_case(doc.case_id, current_user, db)

    try:
        data, mime_type, filename = service.get_document_content(document_id)
    except DocumentNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "DOCUMENT_NOT_FOUND", "message": str(exc)},
        ) from exc
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "STORAGE_FILE_MISSING", "message": str(exc)},
        ) from exc

    return Response(
        content=data,
        media_type=mime_type,
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.get("/documents/{document_id}/pages/{page_num}")
async def get_document_page_info(
    document_id: str,
    page_num: int,
    current_user: Annotated[UserOrm, Depends(get_current_user)],
    db: Session = Depends(get_db),
    storage: DocumentStorage = Depends(get_document_storage),
):
    """Retrieve metadata/page details for a specific document page."""
    service = DocumentService(db, storage=storage)
    try:
        doc = service.get_document(document_id)
    except DocumentNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "DOCUMENT_NOT_FOUND", "message": str(exc)},
        ) from exc

    if doc.case_id:
        require_project_access_for_case(doc.case_id, current_user, db)

    if page_num < 1 or page_num > doc.page_count:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "PAGE_OUT_OF_RANGE",
                "message": f"Requested page {page_num} is out of bounds for document with {doc.page_count} pages.",
            },
        )

    return {
        "document_id": doc.id,
        "page_number": page_num,
        "total_pages": doc.page_count,
        "mime_type": doc.mime_type,
    }


@router.delete("/documents/{document_id}")
async def soft_delete_document(
    document_id: str,
    current_user: Annotated[UserOrm, Depends(get_current_user)],
    db: Session = Depends(get_db),
    storage: DocumentStorage = Depends(get_document_storage),
):
    """Soft-delete a document (never permanently purge from storage, preserving auditability)."""
    service = DocumentService(db, storage=storage)
    doc_meta = service.get_document(document_id)
    if doc_meta and doc_meta.case_id:
        require_project_access_for_case(doc_meta.case_id, current_user, db)

    actor_id = current_user.id
    try:
        doc = service.soft_delete_document(document_id, actor_id=actor_id)
    except DocumentNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "DOCUMENT_NOT_FOUND", "message": str(exc)},
        ) from exc

    return {
        "deleted": True,
        "document_id": doc.id,
        "case_id": doc.case_id,
        "is_deleted": True,
    }


@router.post("/documents/{document_id}/replace", status_code=201)
async def replace_document(
    document_id: str,
    file: Annotated[UploadFile, File(...)],
    doc_type: Annotated[str, Form(...)],
    current_user: Annotated[UserOrm, Depends(get_current_user)],
    db: Session = Depends(get_db),
    storage: DocumentStorage = Depends(get_document_storage),
):
    """Replace a document: creates new document and marks existing as superseded."""
    service = DocumentService(db, storage=storage)
    doc_meta = service.get_document(document_id)
    if doc_meta and doc_meta.case_id:
        require_project_access_for_case(doc_meta.case_id, current_user, db)

    content = await file.read()
    filename = file.filename or "replaced_document"
    actor_id = current_user.id

    try:
        result = service.replace_document(
            document_id=document_id,
            new_filename=filename,
            new_content=content,
            new_doc_type=doc_type,
            actor_id=actor_id,
        )
    except MalwareDetectedError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "MALWARE_DETECTED", "message": str(exc)},
        ) from exc
    except ActiveContentProhibitedError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "ACTIVE_CONTENT_PROHIBITED", "message": str(exc)},
        ) from exc
    except ScannerUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "SCANNER_UNAVAILABLE", "message": str(exc)},
        ) from exc
    except DocumentNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "DOCUMENT_NOT_FOUND", "message": str(exc)},
        ) from exc
    except FileTooLargeError as exc:
        raise HTTPException(
            status_code=413,
            detail={"code": "FILE_TOO_LARGE", "message": str(exc)},
        ) from exc
    except UnsupportedMediaTypeError as exc:
        raise HTTPException(
            status_code=415,
            detail={"code": "UNSUPPORTED_MEDIA_TYPE", "message": str(exc)},
        ) from exc
    except (EncryptedDocumentError, PageLimitExceededError, CorruptDocumentError) as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": exc.__class__.__name__, "message": str(exc)},
        ) from exc
    except DuplicateDocumentError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "DUPLICATE_DOCUMENT_IN_CASE", "message": str(exc)},
        ) from exc

    new_doc = result.document

    return {
        "banner": BANNER_TEXT,
        "synthetic_data_only": True,
        "superseded_document_id": document_id,
        "new_document": {
            "id": new_doc.id,
            "case_id": new_doc.case_id,
            "doc_type": new_doc.doc_type,
            "original_filename": new_doc.original_filename,
            "size_bytes": new_doc.size_bytes,
            "sha256": new_doc.sha256,
            "page_count": new_doc.page_count,
        },
        "reuse_warning": result.reuse_warning,
    }
