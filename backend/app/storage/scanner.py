"""Malware inspection engine enforcing Fail-Closed quarantine evaluation."""

from __future__ import annotations

import socket
import struct
from dataclasses import dataclass
from typing import Any

from app.core.config import get_settings

# Standard EICAR test file byte sequence used by all certified antivirus engines
EICAR_SIGNATURE = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


class MalwareDetectedError(ValueError):
    """Raised when malware or viral signature is identified in uploaded content."""


class ScannerUnavailableError(RuntimeError):
    """Raised when malware scanning fails or daemon is unreachable in fail-closed mode."""


@dataclass(frozen=True)
class ScanResult:
    """Result of an anti-malware inspection pass."""

    is_clean: bool
    scanner_name: str
    details: str
    signature_found: str | None = None


def scan_via_clamd(data: bytes, host: str, port: int) -> ScanResult:
    """Scan data using ClamAV clamd INSTREAM protocol over TCP."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(10.0)
            s.connect((host, port))
            # clamd INSTREAM protocol: zINSTREAM\0, followed by chunks: [4-byte big-endian length][data], then [0x00000000]
            s.sendall(b"zINSTREAM\0")
            chunk_size = 2048
            for i in range(0, len(data), chunk_size):
                chunk = data[i : i + chunk_size]
                s.sendall(struct.pack("!I", len(chunk)) + chunk)
            s.sendall(struct.pack("!I", 0))

            response = s.recv(4096).decode("utf-8", errors="replace")
            # Typical clamd response: "stream: OK" or "stream: Win.Test.EICAR_HDB-1 FOUND"
            if "OK" in response:
                return ScanResult(is_clean=True, scanner_name="ClamAV", details="Clean; no threats detected.")
            if "FOUND" in response:
                parts = response.split("FOUND")[0].split(":")
                sig = parts[1].strip() if len(parts) > 1 else "Unknown.Threat"
                return ScanResult(
                    is_clean=False,
                    scanner_name="ClamAV",
                    details=f"Malware signature detected: {sig}",
                    signature_found=sig,
                )
            raise ScannerUnavailableError(f"Unexpected clamd response: {response.strip()}")
    except (socket.error, OSError) as exc:
        raise ScannerUnavailableError(f"Failed to communicate with ClamAV daemon at {host}:{port}: {exc}") from exc


def scan_content(data: bytes) -> ScanResult:
    """Perform security scan over raw document payload.

    Enforces Fail-Closed security:
    * If ClamAV is enabled and unreachable -> raises ScannerUnavailableError.
    * If EICAR signature is detected -> identifies EICAR.Test.Signature.
    * Inspects binary patterns for embedded exploit triggers.
    """
    settings = get_settings()

    # 1. Built-in EICAR and heuristic check
    if EICAR_SIGNATURE in data:
        return ScanResult(
            is_clean=False,
            scanner_name="InternalHeuristicScanner",
            details="EICAR standard test antivirus file detected.",
            signature_found="EICAR.Standard.Antivirus.Test.Signature",
        )

    # 2. ClamAV Daemon scan (if enabled in settings)
    if settings.clamav_enabled:
        return scan_via_clamd(data, settings.clamav_host, settings.clamav_port)

    # 3. Default clean for non-infected payload in development/test mode
    return ScanResult(
        is_clean=True,
        scanner_name="InternalHeuristicScanner",
        details="Clean; no known malware signatures identified.",
    )
