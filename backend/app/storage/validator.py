"""Document validation engine enforcing type, magic-byte, size, encryption, and page limits."""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from typing import BinaryIO

from PIL import Image
from pypdf import PdfReader
from pypdf.errors import EmptyFileError, PdfReadError

from app.storage.pdf_security import ActiveContentProhibitedError, assert_safe_pdf_content

MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB limit
MAX_PAGE_COUNT = 50  # 50 pages limit


class FileTooLargeError(ValueError):
    """File size exceeds 20 MB limit (HTTP 413)."""


class UnsupportedMediaTypeError(ValueError):
    """MIME type or magic bytes not permitted (HTTP 415)."""


class CorruptDocumentError(ValueError):
    """File content is corrupt, empty, or unreadable (HTTP 422)."""


class EncryptedDocumentError(ValueError):
    """PDF is password-protected or encrypted (HTTP 422)."""


class PageLimitExceededError(ValueError):
    """Document exceeds maximum allowed page count (HTTP 422)."""


@dataclass(frozen=True)
class ValidatedDocument:
    """Metadata computed from a successfully validated document payload."""

    mime_type: str
    size_bytes: int
    sha256: str
    page_count: int


def compute_sha256(content: bytes) -> str:
    """Compute standard SHA-256 hex digest for document integrity and deduplication."""
    return hashlib.sha256(content).hexdigest()


def detect_mime_type_from_magic_bytes(content: bytes) -> str | None:
    """Inspect leading magic bytes to identify and verify real file format."""
    if not content:
        return None

    if content.startswith(b"%PDF-"):
        return "application/pdf"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"

    return None


def validate_uploaded_document(filename: str, content: bytes) -> ValidatedDocument:
    """Validate document against enterprise MVP security and compliance rules.

    Enforces:
    * Non-empty content
    * Size <= 20 MB
    * Magic byte verification (PDF, JPEG, PNG only)
    * PDF encryption check (reject password-protected PDFs)
    * Page count limit <= 50
    * SHA-256 digest computation
    """
    size_bytes = len(content)

    if size_bytes == 0:
        raise CorruptDocumentError("Uploaded file is empty (0 bytes).")

    if size_bytes > MAX_FILE_SIZE_BYTES:
        raise FileTooLargeError(
            f"File size ({size_bytes / (1024 * 1024):.2f} MB) exceeds maximum allowed limit of 20 MB."
        )

    mime_type = detect_mime_type_from_magic_bytes(content)
    if mime_type is None:
        raise UnsupportedMediaTypeError(
            f"Unsupported file format for '{filename}'. Allowed formats: PDF, JPEG, PNG."
        )

    sha256 = compute_sha256(content)
    page_count = 1

    if mime_type == "application/pdf":
        assert_safe_pdf_content(content)
        try:
            reader = PdfReader(io.BytesIO(content))
            if reader.is_encrypted:
                raise EncryptedDocumentError(
                    "Password-protected or encrypted PDFs are not accepted. "
                    "Provide an unencrypted document or enter values manually."
                )

            page_count = len(reader.pages)
            if page_count == 0:
                raise CorruptDocumentError("PDF document has 0 pages.")

            if page_count > MAX_PAGE_COUNT:
                raise PageLimitExceededError(
                    f"PDF document has {page_count} pages, which exceeds the maximum limit of {MAX_PAGE_COUNT} pages."
                )

        except (PdfReadError, EmptyFileError) as exc:
            raise CorruptDocumentError(f"Corrupt or malformed PDF file: {exc}") from exc
        except (EncryptedDocumentError, PageLimitExceededError, CorruptDocumentError):
            raise
        except Exception as exc:
            raise CorruptDocumentError(f"Failed to inspect PDF: {exc}") from exc

    elif mime_type in ("image/jpeg", "image/png"):
        try:
            with Image.open(io.BytesIO(content)) as img:
                img.verify()
            page_count = 1
        except Exception as exc:
            raise CorruptDocumentError(f"Corrupt or malformed image file: {exc}") from exc

    return ValidatedDocument(
        mime_type=mime_type,
        size_bytes=size_bytes,
        sha256=sha256,
        page_count=page_count,
    )
