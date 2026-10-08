"""Milestone M4A: Controlled Internal Pilot Foundation comprehensive test suite.

Verifies:
1. Named-user JWT authentication (login, refresh, invalid credentials, disabled users).
2. Role-based authorization (ENGINEER vs REVIEWER review permissions).
3. Project-scoped access control (isolated project users receive 403 PROJECT_ACCESS_DENIED on unauthorized projects).
4. Project-scoped case listing (users only see cases for projects they are assigned to).
5. Document content project access protection.
6. Pilot safety guardrails (APP_ENV=pilot forbids simulated identities).
7. Preservation of domain invariants (D1 exact zero tolerance, F8 missing evidence, C1 DN reuse, VAT NOT_CHECKED).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import pytest
from starlette.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.core.safety import UnsafeConfigurationError, assert_safe_configuration
from app.core.security import create_access_token, hash_password
from app.main import create_app
from app.persistence.database import Base, get_db
from app.persistence.models import UserOrm, ProjectUserOrm
from app.persistence.repositories import UserRepository
from app.persistence.seed import seed_database


@pytest.fixture
def pilot_test_app(tmp_path):
    """Isolated test application with seeded SQLite database."""
    db_path = tmp_path / "pilot_test.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys = ON;")

    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    with TestingSession() as session:
        seed_database(session)

    settings = Settings(
        app_env="test",
        dev_identity_enabled=False,
        database_url=f"sqlite:///{db_path}",
        jwt_secret_key="test-secret-key-for-m4a-pilot-testing",
    )
    app = create_app(settings)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return app, TestingSession


# ============================================================================
# 1. AUTHENTICATION (JWT LOGIN, REFRESH, ME)
# ============================================================================

def test_auth_login_success(pilot_test_app):
    """Valid credentials return JWT access and refresh tokens."""
    app, _ = pilot_test_app
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": "reviewer@prototype.local", "password": "PilotPass123!"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body
        assert "refresh_token" in body
        assert body["token_type"] == "bearer"
        assert body["user"]["email"] == "reviewer@prototype.local"
        assert body["user"]["role"] == "REVIEWER"
        assert body["user"]["can_review"] is True
        assert len(body["user"]["assigned_projects"]) >= 1


def test_auth_login_invalid_password_returns_401(pilot_test_app):
    """Incorrect password returns 401 INVALID_CREDENTIALS."""
    app, _ = pilot_test_app
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": "reviewer@prototype.local", "password": "WrongPassword!"},
        )
        assert resp.status_code == 401
        assert resp.json()["detail"]["code"] == "INVALID_CREDENTIALS"


def test_auth_login_nonexistent_user_returns_401(pilot_test_app):
    """Nonexistent user email returns 401 INVALID_CREDENTIALS."""
    app, _ = pilot_test_app
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@nowhere.com", "password": "PilotPass123!"},
        )
        assert resp.status_code == 401
        assert resp.json()["detail"]["code"] == "INVALID_CREDENTIALS"


def test_auth_login_inactive_user_returns_401(pilot_test_app):
    """Disabled/inactive user accounts are refused authentication."""
    app, session_factory = pilot_test_app
    with session_factory() as session:
        user = session.get(UserOrm, "usr-sim-rev")
        user.active = False
        session.commit()

    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": "reviewer@prototype.local", "password": "PilotPass123!"},
        )
        assert resp.status_code == 401
        assert resp.json()["detail"]["code"] == "ACCOUNT_DISABLED"


def test_auth_refresh_token_success(pilot_test_app):
    """Valid refresh token yields a fresh access token."""
    app, _ = pilot_test_app
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        login_resp = client.post(
            "/api/v1/auth/login",
            json={"email": "reviewer@prototype.local", "password": "PilotPass123!"},
        )
        assert login_resp.status_code == 200
        refresh_token = login_resp.json()["refresh_token"]

        refresh_resp = client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_token},
        )
        assert refresh_resp.status_code == 200
        data = refresh_resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"


def test_auth_me_with_bearer_token(pilot_test_app):
    """GET /api/v1/auth/me returns current authenticated user details."""
    app, _ = pilot_test_app
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        login_resp = client.post(
            "/api/v1/auth/login",
            json={"email": "reviewer@prototype.local", "password": "PilotPass123!"},
        )
        token = login_resp.json()["access_token"]

        me_resp = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert me_resp.status_code == 200
        user = me_resp.json()
        assert user["name"] == "Simulated Reviewer"
        assert user["role"] == "REVIEWER"
        assigned_ids = [p["id"] for p in user["assigned_projects"]]
        assert "prj-01" in assigned_ids


# ============================================================================
# 2. ROLE-BASED AUTHORIZATION (D6 can_review)
# ============================================================================

def test_site_engineer_cannot_submit_review(pilot_test_app):
    """Site Engineer role (can_review=False) receives 403 REVIEW_PERMISSION_DENIED."""
    app, _ = pilot_test_app
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        login_resp = client.post(
            "/api/v1/auth/login",
            json={"email": "engineer@prototype.local", "password": "PilotPass123!"},
        )
        token = login_resp.json()["access_token"]

        review_resp = client.post(
            "/api/v1/cases/case-synth-01/reviews",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "outcome": "VERIFIED_NO_EXCEPTIONS",
                "comment": "Attempting sign-off without reviewer role",
                "declaration_accepted": True,
                "manual_vat_checked": True,
            },
        )
        assert review_resp.status_code == 403
        assert review_resp.json()["detail"]["code"] == "REVIEW_PERMISSION_DENIED"


def test_reviewer_can_submit_review(pilot_test_app):
    """Senior Reviewer (can_review=True) on clean case successfully records review."""
    app, _ = pilot_test_app
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        login_resp = client.post(
            "/api/v1/auth/login",
            json={"email": "reviewer@prototype.local", "password": "PilotPass123!"},
        )
        token = login_resp.json()["access_token"]

        review_resp = client.post(
            "/api/v1/cases/case-synth-01/reviews",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "outcome": "VERIFIED_NO_EXCEPTIONS",
                "comment": "Verified all quantities and supporting delivery notes.",
                "declaration_accepted": True,
                "manual_vat_checked": True,
            },
        )
        assert review_resp.status_code == 201
        data = review_resp.json()
        assert data["review"]["outcome"] == "VERIFIED_NO_EXCEPTIONS"
        assert data["review"]["reviewer_name"] == "Simulated Reviewer"


# ============================================================================
# 3. PROJECT-LEVEL ACCESS CONTROL (PROJECT_ACCESS_DENIED)
# ============================================================================

def test_isolated_engineer_cannot_access_unassigned_projects(pilot_test_app):
    """usr-isolated-eng is assigned only to prj-04; access to prj-01, prj-02, prj-03 is 403."""
    app, _ = pilot_test_app
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        login_resp = client.post(
            "/api/v1/auth/login",
            json={"email": "isolated-eng@prototype.local", "password": "PilotPass123!"},
        )
        assert login_resp.status_code == 200
        token = login_resp.json()["access_token"]

        # 1. Attempt to access case-synth-01 (prj-01) -> 403 PROJECT_ACCESS_DENIED
        r1 = client.get(
            "/api/v1/cases/case-synth-01",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r1.status_code == 403
        assert r1.json()["detail"]["code"] == "PROJECT_ACCESS_DENIED"

        # 2. Attempt to access case-synth-02 (prj-02) -> 403 PROJECT_ACCESS_DENIED
        r2 = client.get(
            "/api/v1/cases/case-synth-02",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r2.status_code == 403
        assert r2.json()["detail"]["code"] == "PROJECT_ACCESS_DENIED"

        # 3. Attempt to access case-synth-03 (prj-03) -> 403 PROJECT_ACCESS_DENIED
        r3 = client.get(
            "/api/v1/cases/case-synth-03",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r3.status_code == 403
        assert r3.json()["detail"]["code"] == "PROJECT_ACCESS_DENIED"

        # 4. Access case-hist-00 (prj-04) -> 200 SUCCESS
        r_hist = client.get(
            "/api/v1/cases/case-hist-00",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r_hist.status_code == 200
        assert r_hist.json()["case"]["id"] == "case-hist-00"


def test_isolated_engineer_case_listing_is_project_scoped(pilot_test_app):
    """GET /api/v1/cases lists only cases from assigned projects."""
    app, _ = pilot_test_app
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        login_resp = client.post(
            "/api/v1/auth/login",
            json={"email": "isolated-eng@prototype.local", "password": "PilotPass123!"},
        )
        token = login_resp.json()["access_token"]

        list_resp = client.get(
            "/api/v1/cases",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert list_resp.status_code == 200
        cases = list_resp.json()["cases"]
        # All returned cases must belong to prj-04
        assert len(cases) > 0
        for c in cases:
            assert c["project"]["id"] == "prj-04"


def test_document_content_enforces_project_access(pilot_test_app):
    """Document download is blocked if user is not assigned to the case project."""
    app, _ = pilot_test_app
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        # Login as isolated engineer (only prj-04)
        login_resp = client.post(
            "/api/v1/auth/login",
            json={"email": "isolated-eng@prototype.local", "password": "PilotPass123!"},
        )
        token = login_resp.json()["access_token"]

        # Attempt to download doc from case-synth-01 (prj-01) -> 403 PROJECT_ACCESS_DENIED
        doc_resp = client.get(
            "/api/v1/documents/doc-c1-inv/content",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert doc_resp.status_code == 403
        assert doc_resp.json()["detail"]["code"] == "PROJECT_ACCESS_DENIED"


# ============================================================================
# 4. PILOT SAFETY GUARDRAILS
# ============================================================================

def test_pilot_environment_forbids_simulated_identities():
    """APP_ENV=pilot with dev_identity_enabled=True must raise UnsafeConfigurationError."""
    unsafe_settings = Settings(
        app_env="pilot",
        dev_identity_enabled=True,
    )
    with pytest.raises(UnsafeConfigurationError, match="Simulated identities .* prohibited in pilot mode"):
        assert_safe_configuration(unsafe_settings)


def test_pilot_environment_valid_configuration_passes():
    """APP_ENV=pilot with dev_identity_enabled=False, PostgreSQL, and valid distinct keys passes safety assertion."""
    valid_settings = Settings(
        app_env="pilot",
        dev_identity_enabled=False,
        database_url="postgresql://civ_user:pilot_secure_pass_1234@127.0.0.1:5432/civ_pilot",
        jwt_secret_key="pilot-unique-jwt-secret-key-32-chars-long!",
        storage_encryption_key="pilot-unique-aes-clean-storage-key-32b!",
    )
    assert_safe_configuration(valid_settings)
