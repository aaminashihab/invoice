"""Security, password hashing, JWT token handling, and project-scoped authorization."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated, Any

import bcrypt
import jwt
from fastapi import Depends, Header, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.dev_identity import DEFAULT_SIMULATED_USER_ID, SIMULATED_USER_HEADER
from app.persistence.database import get_db
from app.persistence.models import UserOrm
from app.persistence.repositories import CaseRepository, ProjectRepository, UserRepository


security_bearer = HTTPBearer(auto_error=False)


def hash_password(plain_password: str) -> str:
    """Hash a plaintext password using bcrypt."""
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(plain_password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str | None) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    if not hashed_password:
        return False
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False


def create_access_token(
    user_id: str,
    role: str,
    email: str,
    expires_delta: timedelta | None = None,
) -> str:
    """Generate a signed JWT access token (30-minute default TTL)."""
    settings = get_settings()
    if expires_delta is None:
        expires_delta = timedelta(minutes=settings.access_token_expire_minutes)

    now = datetime.utcnow()
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "type": "access",
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token(
    user_id: str,
    expires_delta: timedelta | None = None,
) -> str:
    """Generate a signed JWT refresh token (8-hour default TTL)."""
    settings = get_settings()
    if expires_delta is None:
        expires_delta = timedelta(hours=settings.refresh_token_expire_hours)

    now = datetime.utcnow()
    payload = {
        "sub": user_id,
        "type": "refresh",
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_jwt_token(token: str) -> dict[str, Any]:
    """Decode and validate a signed JWT token."""
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        return payload
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "TOKEN_EXPIRED", "message": "Authentication token has expired."},
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_TOKEN", "message": "Authentication token is invalid."},
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def get_current_user(
    auth_header: Annotated[HTTPAuthorizationCredentials | None, Depends(security_bearer)],
    simulated_user_header: Annotated[str | None, Header(alias=SIMULATED_USER_HEADER)] = None,
    token_query: Annotated[str | None, Query(alias="token")] = None,
    db: Session = Depends(get_db),
) -> UserOrm:
    """FastAPI dependency resolving the authenticated UserOrm.

    * In Pilot/Production mode, a valid Bearer JWT is mandatory (header or query param).
    * In Development mode (APP_ENV=development), falls back to simulated identity if no Bearer token.
    """
    settings = get_settings()
    user_repo = UserRepository(db)

    # 1. Bearer Token path (Primary for M4A Pilot and authenticated clients)
    raw_token = auth_header.credentials if (auth_header and auth_header.credentials) else token_query
    if raw_token:
        payload = decode_jwt_token(raw_token)
        if payload.get("type") != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "INVALID_TOKEN_TYPE", "message": "Expected access token."},
                headers={"WWW-Authenticate": "Bearer"},
            )

        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "INVALID_TOKEN", "message": "Token missing subject claim."},
                headers={"WWW-Authenticate": "Bearer"},
            )

        user = user_repo.get_by_id(user_id)
        if not user or not user.active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "USER_INACTIVE", "message": "User account is disabled or does not exist."},
                headers={"WWW-Authenticate": "Bearer"},
            )
        return user

    # 2. Simulated Identity fallback (Allowed ONLY in development/test mode with dev_identity_enabled=True)
    if settings.app_env in ("development", "test") and settings.dev_identity_enabled:
        raw_user = simulated_user_header or DEFAULT_SIMULATED_USER_ID
        aliases = {
            "sim-engineer": "usr-sim-eng",
            "sim-qs": "usr-sim-qs",
            "sim-reviewer": "usr-sim-rev",
            "sim-accounts": "usr-sim-acc",
            "sim-admin": "usr-sim-admin",
        }
        user_id = aliases.get(raw_user, raw_user)
        user = user_repo.get_by_id(user_id)
        if user:
            return user

    # 3. If in pilot or no valid token provided
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "NOT_AUTHENTICATED", "message": "Authentication credentials required."},
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_project_access_for_case(
    case_id: str,
    current_user: UserOrm,
    db: Session,
) -> None:
    """Enforce project-scoped access control.

    Raises HTTP 403 PROJECT_ACCESS_DENIED if current_user is not assigned to the case's project.
    """
    if current_user.role == "ADMIN":
        return

    case = CaseRepository(db).get_by_id(case_id)
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "CASE_NOT_FOUND", "message": f"Verification case '{case_id}' not found."},
        )

    project_repo = ProjectRepository(db)
    if not project_repo.is_user_assigned(current_user.id, case.project_id):
        project_name = case.project.name if case.project else case.project_id
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "PROJECT_ACCESS_DENIED",
                "message": f"User '{current_user.name}' is not authorized to access project '{project_name}' ({case.project_id}).",
            },
        )
