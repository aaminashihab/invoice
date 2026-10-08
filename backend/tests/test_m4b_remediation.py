"""Milestone M4B Phase 1B: Security and Pilot Environment Remediation Test Suite.

Verifies:
1. Production secrets hygiene (absence or blacklisted JWT_SECRET_KEY causes fail-fast startup).
2. Encryption key management (absence, blacklisted, short, or reused keys fail-fast; AES-256-GCM round-trip).
3. Production database enforcement (APP_ENV=pilot strictly rejects SQLite and requires PostgreSQL).
4. ClamAV fail-closed behavior (EICAR detection, scanner-unavailable raises ScannerUnavailableError).
5. Backup and restore procedure (atomic bundle creation, isolated restoration, schema and entity verification).
6. TLS reverse proxy configuration validation.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import (
    DEV_TEST_JWT_SECRET,
    DEV_TEST_STORAGE_KEY,
    INSECURE_SECRETS_BLACKLIST,
    Settings,
)
from app.core.safety import UnsafeConfigurationError, assert_safe_configuration
from app.persistence.database import Base
from app.persistence.seed import seed_database
from app.storage.crypto import CryptoError, decrypt_payload, encrypt_payload
from app.storage.scanner import (
    EICAR_SIGNATURE,
    ScannerUnavailableError,
    scan_content,
    scan_via_clamd,
)
from scripts.backup_restore import (
    backup_clean_storage,
    create_backup_bundle,
    restore_clean_storage,
    restore_database,
    verify_recovery,
)


# ============================================================================
# 1. SECRETS HYGIENE & PILOT STARTUP FAIL-FAST TESTS
# ============================================================================


def test_secrets_absence_in_pilot_mode_fails_startup():
    """APP_ENV=pilot with missing JWT_SECRET_KEY must fail startup."""
    settings = Settings(
        app_env="pilot",
        dev_identity_enabled=False,
        database_url="postgresql://user:pass@127.0.0.1:5432/civ_pilot",
        jwt_secret_key="",
        storage_encryption_key="pilot-strong-storage-encryption-key-32b!",
    )
    with pytest.raises(UnsafeConfigurationError, match="JWT_SECRET_KEY is missing"):
        assert_safe_configuration(settings)


def test_blacklisted_jwt_secret_in_pilot_mode_fails_startup():
    """APP_ENV=pilot with blacklisted fallback JWT secret must fail startup."""
    for bad_secret in INSECURE_SECRETS_BLACKLIST:
        settings = Settings(
            app_env="pilot",
            dev_identity_enabled=False,
            database_url="postgresql://user:pass@127.0.0.1:5432/civ_pilot",
            jwt_secret_key=bad_secret,
            storage_encryption_key="pilot-strong-storage-encryption-key-32b!",
        )
        with pytest.raises(UnsafeConfigurationError, match="(insecure or blacklisted|too short)"):
            assert_safe_configuration(settings)


def test_short_jwt_secret_in_pilot_mode_fails_startup():
    """APP_ENV=pilot with JWT secret < 32 chars must fail startup."""
    settings = Settings(
        app_env="pilot",
        dev_identity_enabled=False,
        database_url="postgresql://user:pass@127.0.0.1:5432/civ_pilot",
        jwt_secret_key="short-secret-under-32",
        storage_encryption_key="pilot-strong-storage-encryption-key-32b!",
    )
    with pytest.raises(UnsafeConfigurationError, match="JWT_SECRET_KEY is too short"):
        assert_safe_configuration(settings)


# ============================================================================
# 2. ENCRYPTION KEY MANAGEMENT TESTS
# ============================================================================


def test_encryption_key_absence_in_pilot_mode_fails_startup():
    """APP_ENV=pilot with missing STORAGE_ENCRYPTION_KEY must fail startup."""
    settings = Settings(
        app_env="pilot",
        dev_identity_enabled=False,
        database_url="postgresql://user:pass@127.0.0.1:5432/civ_pilot",
        jwt_secret_key="pilot-strong-jwt-secret-key-32-chars-long!",
        storage_encryption_key="",
    )
    with pytest.raises(UnsafeConfigurationError, match="STORAGE_ENCRYPTION_KEY is missing"):
        assert_safe_configuration(settings)


def test_blacklisted_encryption_key_in_pilot_mode_fails_startup():
    """APP_ENV=pilot with blacklisted storage key must fail startup."""
    settings = Settings(
        app_env="pilot",
        dev_identity_enabled=False,
        database_url="postgresql://user:pass@127.0.0.1:5432/civ_pilot",
        jwt_secret_key="pilot-strong-jwt-secret-key-32-chars-long!",
        storage_encryption_key="civ-pilot-aes256-encryption-key-for-clean-storage-32b",
    )
    with pytest.raises(UnsafeConfigurationError, match="insecure or blacklisted fallback secret"):
        assert_safe_configuration(settings)


def test_short_encryption_key_in_pilot_mode_fails_startup():
    """APP_ENV=pilot with storage key < 32 chars must fail startup."""
    settings = Settings(
        app_env="pilot",
        dev_identity_enabled=False,
        database_url="postgresql://user:pass@127.0.0.1:5432/civ_pilot",
        jwt_secret_key="pilot-strong-jwt-secret-key-32-chars-long!",
        storage_encryption_key="key-too-short",
    )
    with pytest.raises(UnsafeConfigurationError, match="STORAGE_ENCRYPTION_KEY is too short"):
        assert_safe_configuration(settings)


def test_identical_jwt_and_encryption_keys_in_pilot_mode_fails_startup():
    """Key separation: JWT_SECRET_KEY and STORAGE_ENCRYPTION_KEY must not be identical."""
    shared_key = "a-very-secure-key-that-is-over-32-chars-long-used-twice"
    settings = Settings(
        app_env="pilot",
        dev_identity_enabled=False,
        database_url="postgresql://user:pass@127.0.0.1:5432/civ_pilot",
        jwt_secret_key=shared_key,
        storage_encryption_key=shared_key,
    )
    with pytest.raises(UnsafeConfigurationError, match="must not be identical"):
        assert_safe_configuration(settings)


def test_aes256_gcm_encryption_roundtrip():
    """AES-256-GCM encryption roundtrip succeeds and fails on tampered payload or incorrect key."""
    key = "valid-pilot-secure-encryption-key-32b!!"
    wrong_key = "different-pilot-encryption-key-32b!!"
    payload = b"Sample synthetic invoice payload bytes for testing"

    ciphertext = encrypt_payload(payload, key)
    assert ciphertext != payload
    assert len(ciphertext) > len(payload) + 12

    # Decrypt with correct key
    decrypted = decrypt_payload(ciphertext, key)
    assert decrypted == payload

    # Decrypt with wrong key fails
    with pytest.raises(CryptoError):
        decrypt_payload(ciphertext, wrong_key)

    # Tampered ciphertext fails
    tampered = bytearray(ciphertext)
    tampered[-1] ^= 0xFF
    with pytest.raises(CryptoError):
        decrypt_payload(bytes(tampered), key)


# ============================================================================
# 3. PRODUCTION DATABASE ENFORCEMENT TESTS
# ============================================================================


def test_pilot_mode_rejects_sqlite_database_url():
    """APP_ENV=pilot strictly prohibits SQLite."""
    settings = Settings(
        app_env="pilot",
        dev_identity_enabled=False,
        database_url="sqlite:///D:/Invoice/backend/civ_prototype.db",
        jwt_secret_key="pilot-strong-jwt-secret-key-32-chars-long!",
        storage_encryption_key="pilot-strong-storage-encryption-key-32b!",
    )
    with pytest.raises(UnsafeConfigurationError, match="requires a production database .* SQLite is strictly prohibited"):
        assert_safe_configuration(settings)


def test_pilot_mode_with_valid_postgresql_passes():
    """APP_ENV=pilot with PostgreSQL and valid secrets passes assert_safe_configuration."""
    settings = Settings(
        app_env="pilot",
        dev_identity_enabled=False,
        database_url="postgresql://civ_user:pilot_pw123@db.internal:5432/civ_pilot",
        jwt_secret_key="pilot-strong-jwt-secret-key-32-chars-long!",
        storage_encryption_key="pilot-strong-storage-encryption-key-32b!",
    )
    assert_safe_configuration(settings)


# ============================================================================
# 4. CLAMAV ANTI-MALWARE SCANNER TESTS
# ============================================================================


def test_eicar_signature_detection():
    """EICAR test signature is detected and flagged clean=False."""
    result = scan_content(EICAR_SIGNATURE)
    assert result.is_clean is False
    assert "EICAR" in (result.signature_found or "")


def test_clamav_unreachable_fails_closed():
    """When ClamAV daemon is unreachable on configured port, ScannerUnavailableError is raised."""
    # Port 33199 is not open
    with pytest.raises(ScannerUnavailableError, match="Failed to communicate with ClamAV"):
        scan_via_clamd(b"clean test bytes", "127.0.0.1", 33199)


# ============================================================================
# 5. BACKUP AND RESTORE PROCEDURE VERIFICATION
# ============================================================================


def test_backup_restore_and_recovery_verification(tmp_path):
    """End-to-end backup creation, isolated restoration, and recovery verification."""
    # 1. Setup source test database and clean storage
    src_db_file = tmp_path / "source.db"
    src_db_url = f"sqlite:///{src_db_file}"
    engine = create_engine(src_db_url)
    Base.metadata.create_all(bind=engine)

    SessionMaker = sessionmaker(bind=engine)
    with SessionMaker() as session:
        seed_database(session)

    src_storage = tmp_path / "src_clean"
    src_storage.mkdir(parents=True)
    test_file = src_storage / "sample_doc.bin"
    test_file.write_bytes(b"Encrypted test document payload")

    # 2. Create backup bundle
    bundle_out = tmp_path / "backups"
    bundle_dir = create_backup_bundle(src_db_url, src_storage, bundle_out)

    assert bundle_dir.exists()
    assert (bundle_dir / "manifest.json").exists()
    assert (bundle_dir / "database.sqlite").exists()
    assert (bundle_dir / "clean_storage.tar.gz").exists()

    # 3. Restore to isolated target database and clean storage
    target_db_file = tmp_path / "isolated_target.db"
    target_db_url = f"sqlite:///{target_db_file}"
    target_storage = tmp_path / "target_clean"

    restore_database(target_db_url, bundle_dir / "database.sqlite")
    restore_clean_storage(bundle_dir / "clean_storage.tar.gz", target_storage)

    # 4. Verify recovery
    assert (target_storage / "sample_doc.bin").exists()
    assert (target_storage / "sample_doc.bin").read_bytes() == b"Encrypted test document payload"

    recovery_report = verify_recovery(target_db_url, target_storage)
    assert recovery_report["status"] == "VERIFIED"
    assert recovery_report["tables_present"] >= 12
    assert recovery_report["user_count"] > 0
    assert recovery_report["project_count"] > 0


# ============================================================================
# 6. TLS CADDYFILE VALIDATION
# ============================================================================


def test_caddyfile_configuration_syntax():
    """Verify Caddyfile passes formal validation if caddy executable is available."""
    caddy_path = shutil.which("caddy")
    if not caddy_path:
        # Check standard winget install path
        winget_caddy = Path(
            os.environ.get("LOCALAPPDATA", "")
        ) / "Microsoft" / "WinGet" / "Packages" / "CaddyServer.Caddy_Microsoft.Winget.Source_8wekyb3d8bbwe" / "caddy.exe"
        if winget_caddy.exists():
            caddy_path = str(winget_caddy)

    if not caddy_path:
        pytest.skip("Caddy binary not available in PATH for syntax verification")

    caddyfile = Path(__file__).resolve().parent.parent.parent / "deploy" / "Caddyfile"
    assert caddyfile.exists(), f"deploy/Caddyfile does not exist at {caddyfile}"

    proc = subprocess.run([caddy_path, "validate", "--config", str(caddyfile)], capture_output=True, text=True)
    assert proc.returncode == 0, f"Caddyfile validation failed: {proc.stderr}\n{proc.stdout}"
