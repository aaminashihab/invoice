"""PDF active content and executable payload detection engine."""

from __future__ import annotations

import io
from pypdf import PdfReader


class ActiveContentProhibitedError(ValueError):
    """Raised when PDF contains forbidden active content such as scripts or launch actions."""


DISALLOWED_PDF_KEYWORDS: tuple[str, ...] = (
    "/JavaScript",
    "/JS",
    "/Launch",
    "/EmbeddedFiles",
    "/RichMedia",
    "/OpenAction",
    "/AA",  # Additional Actions
)

EXECUTABLE_EXTENSIONS: tuple[bytes, ...] = (
    b".exe",
    b".bat",
    b".cmd",
    b".vbs",
    b".ps1",
    b".scr",
    b".dll",
    b".pif",
    b".com",
)


def inspect_pdf_security(content: bytes) -> list[str]:
    """Inspect PDF bytes for malicious active content, scripts, and embedded executables.

    Returns a list of identified security violations (empty if safe).
    """
    violations: list[str] = []

    # 1. Low-level binary pattern check for dangerous operators
    for kw in DISALLOWED_PDF_KEYWORDS:
        kw_bytes = kw.encode("ascii")
        if kw_bytes in content:
            violations.append(f"Forbidden active PDF element detected: '{kw}'")

    for ext in EXECUTABLE_EXTENSIONS:
        if ext in content.lower():
            violations.append(f"Suspicious embedded executable reference detected: '{ext.decode('ascii')}'")

    # 2. Structural parsing check using pypdf
    try:
        reader = PdfReader(io.BytesIO(content))
        # Check root catalog for OpenAction or Names/JavaScript
        catalog = reader.trailer.get("/Root", {})
        if isinstance(catalog, dict):
            if "/OpenAction" in catalog:
                violations.append("Disallowed document-level /OpenAction trigger found.")
            if "/Names" in catalog:
                names = catalog.get("/Names", {})
                if isinstance(names, dict) and "/JavaScript" in names:
                    violations.append("Disallowed document-level /JavaScript dictionary found.")
    except Exception:
        # If structural parse fails on suspicious content, let CorruptDocumentError catch it elsewhere
        pass

    return list(dict.fromkeys(violations))  # Deduplicate while preserving order


def assert_safe_pdf_content(content: bytes) -> None:
    """Validate that PDF has no active executable, script, or launch content.

    Raises ActiveContentProhibitedError if violations are found.
    """
    violations = inspect_pdf_security(content)
    if violations:
        raise ActiveContentProhibitedError(
            f"Active or executable PDF content is strictly prohibited: {'; '.join(violations)}"
        )
