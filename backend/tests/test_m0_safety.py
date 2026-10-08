"""Tests for M0 safety guards, environment configuration, loopback restrictions, and simulated identity."""

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.dev_identity import SIMULATED_USERS
from app.core.safety import UnsafeConfigurationError, assert_safe_configuration
from app.main import create_app


def test_safety_guard_rejects_production():
    """APP_ENV=production must be rejected on startup."""
    unsafe = Settings(app_env="production", dev_identity_enabled=False, host="127.0.0.1")
    with pytest.raises(UnsafeConfigurationError) as exc_info:
        assert_safe_configuration(unsafe)
    assert "APP_ENV='production' is not supported" in str(exc_info.value)


def test_safety_guard_rejects_non_loopback_host():
    """HOST=0.0.0.0 or external IP must be rejected."""
    unsafe = Settings(app_env="development", dev_identity_enabled=True, host="0.0.0.0")
    with pytest.raises(UnsafeConfigurationError) as exc_info:
        assert_safe_configuration(unsafe)
    assert "not a loopback address" in str(exc_info.value)


def test_safety_guard_rejects_dev_identity_in_test_without_development():
    """Simulated identities cannot be enabled in test environment unless development."""
    unsafe = Settings(app_env="test", dev_identity_enabled=True, host="127.0.0.1")
    with pytest.raises(UnsafeConfigurationError) as exc_info:
        assert_safe_configuration(unsafe)
    assert "DEV_IDENTITY_ENABLED=true" in str(exc_info.value)


def test_healthz_endpoint(tmp_path):
    """Health endpoint must confirm local prototype boundary, banner, and NOT_CHECKED VAT."""
    test_db = tmp_path / "safety_test.db"
    settings = Settings(
        app_env="development",
        dev_identity_enabled=True,
        host="127.0.0.1",
        database_url=f"sqlite:///{test_db}",
    )
    app = create_app(settings)
    client = TestClient(app)

    response = client.get("/healthz")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["app_env"] == "development"
    assert data["synthetic_data_only"] is True
    assert data["automated_vat_status"] == "NOT_CHECKED"
    assert "Development mode" in data["banner"]


def test_dev_users_endpoint(tmp_path):
    """Dev users endpoint lists simulated identities with simulated=True."""
    test_db = tmp_path / "safety_test.db"
    settings = Settings(
        app_env="development",
        dev_identity_enabled=True,
        host="127.0.0.1",
        database_url=f"sqlite:///{test_db}",
    )
    app = create_app(settings)
    client = TestClient(app)

    response = client.get("/api/v1/auth/dev-users")
    assert response.status_code == 200
    data = response.json()
    assert len(data["available_users"]) == len(SIMULATED_USERS)
    assert any(u["role"] == "REVIEWER" and u["can_review"] for u in data["available_users"])


def test_ruleset_endpoint(tmp_path):
    """Ruleset endpoint shows exact quantity match and provisional 2-dp financial rounding."""
    test_db = tmp_path / "safety_test.db"
    settings = Settings(
        app_env="development",
        dev_identity_enabled=True,
        host="127.0.0.1",
        database_url=f"sqlite:///{test_db}",
    )
    app = create_app(settings)
    client = TestClient(app)

    response = client.get("/api/v1/ruleset")
    assert response.status_code == 200
    data = response.json()
    assert data["quantity_policy"]["status"] == "CONFIRMED"
    assert data["financial_rounding_policy"]["status"] == "PROVISIONAL"
    assert data["vat_policy"]["status"] == "NOT_CHECKED"
