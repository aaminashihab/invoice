"""Development-mode safety guards (Revision 3, clarification C3).

The prototype simulates identities without authentication. It is therefore restricted to
local testing with synthetic data:

* only ``APP_ENV=development`` or ``APP_ENV=test`` are accepted — any other value
  (e.g. ``production``) refuses to start, because this prototype must not be deployed;
* simulated identities are allowed **only** when ``APP_ENV=development``;
* the server must bind to a loopback address;
* every HTTP request must originate from a loopback client (defence in depth, in case the
  server is started with a non-loopback bind address by some other means).

These safeguards cannot detect a real supplier document. Not uploading real documents is a
usage rule stated in the README and in the UI banner.
"""

from __future__ import annotations

import ipaddress

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import INSECURE_SECRETS_BLACKLIST, Settings

SUPPORTED_APP_ENVS: frozenset[str] = frozenset({"development", "test", "pilot"})
DEVELOPMENT_ENV = "development"
PILOT_ENV = "pilot"

BANNER_TEXT = "Development mode – simulated users – synthetic data only"
PILOT_BANNER_TEXT = "Pilot mode – authenticated users – controlled synthetic verification only"


class UnsafeConfigurationError(RuntimeError):
    """Raised when settings would run the prototype outside its permitted envelope."""


def is_loopback_host(host: str | None) -> bool:
    """Return True if ``host`` is ``localhost`` or a loopback IP address."""
    if not host:
        return False
    candidate = host.strip().strip("[]").lower()
    if candidate in ("localhost", "testclient"):
        return True
    try:
        return ipaddress.ip_address(candidate).is_loopback
    except ValueError:
        return False


def normalized_env(settings: Settings) -> str:
    return settings.app_env.strip().lower()


def assert_safe_configuration(settings: Settings) -> None:
    """Refuse to run with settings that break the permitted pilot/development envelope."""
    env = normalized_env(settings)
    if env not in SUPPORTED_APP_ENVS:
        raise UnsafeConfigurationError(
            f"APP_ENV={settings.app_env!r} is not supported. Supported environments: "
            "development, test, pilot."
        )
    if env == PILOT_ENV:
        if settings.dev_identity_enabled:
            raise UnsafeConfigurationError(
                "Simulated identities (DEV_IDENTITY_ENABLED=true) are prohibited in pilot mode (APP_ENV=pilot). "
                "Real named-user authentication is mandatory."
            )

        # Database guardrail: Pilot mode requires an actual production database (PostgreSQL)
        db_url = (settings.database_url or "").strip().lower()
        if db_url.startswith("sqlite"):
            raise UnsafeConfigurationError(
                "APP_ENV=pilot requires a production database (PostgreSQL). "
                "SQLite is strictly prohibited in pilot mode. Please configure DATABASE_URL (e.g. postgresql://...)."
            )

        # JWT Secret guardrail
        if not settings.jwt_secret_key or not settings.jwt_secret_key.strip():
            raise UnsafeConfigurationError(
                "JWT_SECRET_KEY is missing in pilot mode. A cryptographically secure secret "
                "(at least 32 characters) must be explicitly configured via environment variables."
            )
        if settings.jwt_secret_key.strip() in INSECURE_SECRETS_BLACKLIST:
            raise UnsafeConfigurationError(
                "JWT_SECRET_KEY uses an insecure or blacklisted fallback secret. "
                "An explicit, unique production secret must be configured."
            )
        if len(settings.jwt_secret_key.strip()) < 32:
            raise UnsafeConfigurationError(
                "JWT_SECRET_KEY is too short. Pilot mode requires at least 32 characters."
            )

        # Storage Encryption Key guardrail
        if not settings.storage_encryption_key or not settings.storage_encryption_key.strip():
            raise UnsafeConfigurationError(
                "STORAGE_ENCRYPTION_KEY is missing in pilot mode. A cryptographically secure key "
                "(at least 32 characters) must be explicitly configured via environment variables."
            )
        if settings.storage_encryption_key.strip() in INSECURE_SECRETS_BLACKLIST:
            raise UnsafeConfigurationError(
                "STORAGE_ENCRYPTION_KEY uses an insecure or blacklisted fallback secret. "
                "An explicit, unique production key must be configured."
            )
        if len(settings.storage_encryption_key.strip()) < 32:
            raise UnsafeConfigurationError(
                "STORAGE_ENCRYPTION_KEY is too short. Pilot mode requires at least 32 characters."
            )

        # Key separation guardrail
        if settings.jwt_secret_key.strip() == settings.storage_encryption_key.strip():
            raise UnsafeConfigurationError(
                "JWT_SECRET_KEY and STORAGE_ENCRYPTION_KEY must not be identical. "
                "Separate cryptographic keys must be used for authentication tokens and document encryption."
            )
    else:
        if settings.dev_identity_enabled and env != DEVELOPMENT_ENV:
            raise UnsafeConfigurationError(
                "Simulated identities (DEV_IDENTITY_ENABLED=true) are only allowed when "
                f"APP_ENV=development, but APP_ENV={settings.app_env!r}."
            )
        if not is_loopback_host(settings.host):
            raise UnsafeConfigurationError(
                f"HOST={settings.host!r} is not a loopback address. In development/test, the prototype may only bind to "
                "127.0.0.1, ::1 or localhost."
            )


class LoopbackOnlyMiddleware:
    """Pure ASGI middleware that rejects any request not coming from a loopback client."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            from app.core.config import get_settings

            settings = get_settings()
            if settings.app_env != PILOT_ENV:
                client = scope.get("client")
                host = client[0] if client else None
                if not is_loopback_host(host):
                    if scope["type"] == "websocket":
                        await send({"type": "websocket.close", "code": 1008})
                        return
                    response = JSONResponse(
                        {
                            "error": {
                                "code": "LOCAL_ACCESS_ONLY",
                                "message": (
                                    "This development prototype only accepts requests from this "
                                    "computer (loopback)."
                                ),
                                "details": {},
                                "field": None,
                            }
                        },
                        status_code=403,
                    )
                    await response(scope, receive, send)
                    return
        await self.app(scope, receive, send)
