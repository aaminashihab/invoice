"""Application settings loaded from environment variables (and an optional ``.env`` file).

Safety validation of these settings lives in :mod:`app.core.safety` so that unsafe
combinations produce clear, human-readable startup errors.
"""

from __future__ import annotations

from functools import lru_cache

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB_FILE = (BACKEND_DIR / "civ_prototype.db").resolve()
DEFAULT_DB_URL = f"sqlite:///{DEFAULT_DB_FILE.as_posix()}"
DEFAULT_STORAGE_DIR = (BACKEND_DIR / "storage" / "documents").resolve()
DEFAULT_QUARANTINE_DIR = (BACKEND_DIR / "storage" / "quarantine").resolve()
DEFAULT_CLEAN_DIR = (BACKEND_DIR / "storage" / "clean").resolve()


from typing import Any

INSECURE_SECRETS_BLACKLIST: frozenset[str] = frozenset({
    "civ-pilot-secret-key-32-chars-long-minimum-jwt",
    "civ-pilot-aes256-encryption-key-for-clean-storage-32b",
    "secret",
    "changeme",
    "password",
    "12345678",
    "admin",
})

DEV_TEST_JWT_SECRET = "civ-dev-test-jwt-secret-key-32-chars-minimum-local-only"
DEV_TEST_STORAGE_KEY = "civ-dev-test-clean-storage-aes256-encryption-key-32b"


class Settings(BaseSettings):
    """Runtime settings for the local prototype."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    #: Only ``development`` (local use), ``test`` (automated tests), and ``pilot`` are supported.
    app_env: str = "development"
    #: Simulated (unauthenticated) users. Allowed only when ``app_env == "development"``.
    dev_identity_enabled: bool = True
    #: Bind address. Must be a loopback address — this prototype is never exposed on a network.
    host: str = "127.0.0.1"
    port: int = 8000
    #: Origin of the local Vite dev server (for CORS).
    frontend_origin: str = "http://127.0.0.1:5173"
    #: Predictable absolute SQLite database URL, independent of working directory.
    database_url: str = DEFAULT_DB_URL
    #: Local storage directory for document files (legacy/fallback).
    storage_dir: str = str(DEFAULT_STORAGE_DIR)
    #: Isolated quarantine directory for uninspected uploads.
    quarantine_dir: str = str(DEFAULT_QUARANTINE_DIR)
    #: AES-256 encrypted clean storage directory.
    clean_storage_dir: str = str(DEFAULT_CLEAN_DIR)
    #: Encryption key for clean storage (AES-256-GCM 32-byte key derived from this secret).
    #: In pilot mode, this must be explicitly injected via environment variables.
    storage_encryption_key: str | None = None
    #: Malware scanner configuration
    clamav_host: str = "127.0.0.1"
    clamav_port: int = 3310
    clamav_enabled: bool = False
    require_malware_scan: bool = True
    #: Reverse-proxy TLS termination trust configuration
    forwarded_allow_ips: str = "127.0.0.1"
    #: JWT authentication settings for M4A/M4B pilot.
    #: In pilot mode, this must be explicitly injected via environment variables.
    jwt_secret_key: str | None = None
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_hours: int = 8

    def model_post_init(self, __context: Any) -> None:
        super().model_post_init(__context)
        # Supply local development and test fallbacks ONLY in development/test modes.
        # In pilot mode, secrets MUST be supplied explicitly via environment.
        if self.app_env in ("development", "test"):
            if not self.jwt_secret_key:
                self.jwt_secret_key = DEV_TEST_JWT_SECRET
            if not self.storage_encryption_key:
                self.storage_encryption_key = DEV_TEST_STORAGE_KEY


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return process-wide settings (cached)."""
    return Settings()
