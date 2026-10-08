"""Authentication REST API endpoints for user login, token refresh, logout, and profile inspection."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_jwt_token,
    get_current_user,
    verify_password,
)
from app.persistence.database import get_db
from app.persistence.models import UserOrm, UserSessionOrm
from app.persistence.repositories import AuditRepository, ProjectRepository, UserRepository

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


class LoginRequest(BaseModel):
    """Payload for user credentials authentication."""

    email: str = Field(..., description="Corporate user email address")
    password: str = Field(..., min_length=1, description="Account password")


class RefreshRequest(BaseModel):
    """Payload for renewing an expired access token."""

    refresh_token: str = Field(..., description="Valid refresh token")


class LogoutRequest(BaseModel):
    """Payload for logging out and revoking session."""

    refresh_token: str = Field(..., description="Refresh token associated with session")


class UserProjectSummary(BaseModel):
    id: str
    code: str
    name: str


class UserProfileResponse(BaseModel):
    id: str
    name: str
    email: str
    role: str
    can_review: bool
    active: bool
    assigned_projects: list[UserProjectSummary]


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in_seconds: int
    user: UserProfileResponse


def hash_token(token: str) -> str:
    """Compute deterministic SHA-256 hash for database session lookup."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Authenticate a named user, register an active database session, and issue access + refresh JWT tokens."""
    user_repo = UserRepository(db)
    user = user_repo.get_by_email(payload.email)

    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_CREDENTIALS", "message": "Invalid email address or password."},
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "ACCOUNT_DISABLED", "message": "User account has been deactivated."},
            headers={"WWW-Authenticate": "Bearer"},
        )

    settings = get_settings()
    access_token = create_access_token(user_id=user.id, role=user.role, email=user.email)
    refresh_token = create_refresh_token(user_id=user.id)

    # Register active database session for revocation enforcement
    token_hash = hash_token(refresh_token)
    session_record = UserSessionOrm(
        user_id=user.id,
        session_token_hash=token_hash,
        expires_at=datetime.utcnow() + timedelta(hours=settings.refresh_token_expire_hours),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        is_revoked=False,
    )
    db.add(session_record)

    # Fetch assigned projects
    project_repo = ProjectRepository(db)
    assigned_projects = [
        UserProjectSummary(id=p.id, code=p.code, name=p.name)
        for p in project_repo.get_assigned_projects(user.id)
    ]

    # Audit login
    audit_repo = AuditRepository(db)
    audit_repo.append_event(
        action="USER_AUTHENTICATED",
        entity_type="USER",
        entity_id=user.id,
        actor_id=user.id,
        after_state={
            "role": user.role,
            "email": user.email,
            "session_id": session_record.id,
            "ip_address": session_record.ip_address,
        },
    )

    db.commit()

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in_seconds=settings.access_token_expire_minutes * 60,
        user=UserProfileResponse(
            id=user.id,
            name=user.name,
            email=user.email,
            role=user.role,
            can_review=user.can_review,
            active=user.active,
            assigned_projects=assigned_projects,
        ),
    )


@router.post("/refresh")
async def refresh_token(
    payload: RefreshRequest,
    db: Session = Depends(get_db),
):
    """Renew an expired access token using a valid, non-revoked refresh token."""
    decoded = decode_jwt_token(payload.refresh_token)
    if decoded.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_TOKEN_TYPE", "message": "Expected refresh token."},
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = decoded.get("sub")
    user = UserRepository(db).get_by_id(user_id)
    if not user or not user.active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "USER_INACTIVE", "message": "User account no longer active."},
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Validate against database session revocation
    token_hash = hash_token(payload.refresh_token)
    session_record = db.scalars(
        select(UserSessionOrm).where(
            UserSessionOrm.session_token_hash == token_hash,
        )
    ).first()

    if not session_record or session_record.is_revoked or session_record.expires_at < datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "SESSION_REVOKED", "message": "Refresh session has been revoked or expired."},
            headers={"WWW-Authenticate": "Bearer"},
        )

    settings = get_settings()
    new_access_token = create_access_token(user_id=user.id, role=user.role, email=user.email)
    return {
        "access_token": new_access_token,
        "token_type": "bearer",
        "expires_in_seconds": settings.access_token_expire_minutes * 60,
    }


@router.post("/logout")
async def logout(
    payload: LogoutRequest,
    db: Session = Depends(get_db),
):
    """Revoke an active refresh session in the database."""
    token_hash = hash_token(payload.refresh_token)
    session_record = db.scalars(
        select(UserSessionOrm).where(
            UserSessionOrm.session_token_hash == token_hash,
        )
    ).first()

    if session_record and not session_record.is_revoked:
        session_record.is_revoked = True
        session_record.revoked_at = datetime.utcnow()

        audit_repo = AuditRepository(db)
        audit_repo.append_event(
            action="USER_LOGGED_OUT",
            entity_type="USER_SESSION",
            entity_id=session_record.id,
            actor_id=session_record.user_id,
            after_state={"revoked_at": session_record.revoked_at.isoformat()},
        )
        db.commit()

    return {"logged_out": True, "revoked": bool(session_record)}


@router.post("/revoke-all")
async def revoke_all_sessions(
    current_user: Annotated[UserOrm, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Revoke all active sessions for the current authenticated user."""
    sessions = db.scalars(
        select(UserSessionOrm).where(
            UserSessionOrm.user_id == current_user.id,
            UserSessionOrm.is_revoked.is_(False),
        )
    ).all()

    now = datetime.utcnow()
    for s in sessions:
        s.is_revoked = True
        s.revoked_at = now

    audit_repo = AuditRepository(db)
    audit_repo.append_event(
        action="ALL_SESSIONS_REVOKED",
        entity_type="USER",
        entity_id=current_user.id,
        actor_id=current_user.id,
        after_state={"revoked_sessions_count": len(sessions)},
    )
    db.commit()

    return {"revoked_count": len(sessions)}


@router.get("/me", response_model=UserProfileResponse)
async def get_my_profile(
    current_user: Annotated[UserOrm, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Return the profile and assigned construction projects for the authenticated user."""
    project_repo = ProjectRepository(db)
    assigned_projects = [
        UserProjectSummary(id=p.id, code=p.code, name=p.name)
        for p in project_repo.get_assigned_projects(current_user.id)
    ]

    return UserProfileResponse(
        id=current_user.id,
        name=current_user.name,
        email=current_user.email,
        role=current_user.role,
        can_review=current_user.can_review,
        active=current_user.active,
        assigned_projects=assigned_projects,
    )
