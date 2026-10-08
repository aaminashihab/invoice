"""Pluggable storage architecture supporting Quarantine and Encrypted Clean tiers."""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from pathlib import Path

from app.core.config import get_settings
from app.storage.crypto import CryptoError, decrypt_payload, encrypt_payload


class StorageSecurityError(ValueError):
    """Raised when an unsafe or malicious storage key is supplied."""


class DocumentStorage(ABC):
    """Abstract interface for storing and retrieving document binary payloads."""

    @abstractmethod
    def save(self, storage_key: str, data: bytes) -> str:
        """Save bytes under the specified key and return storage path/identifier."""

    @abstractmethod
    def read(self, storage_key: str) -> bytes:
        """Read and return bytes stored under key."""

    @abstractmethod
    def exists(self, storage_key: str) -> bool:
        """Check if file exists under key."""

    @abstractmethod
    def delete(self, storage_key: str) -> bool:
        """Remove file from storage."""


class LocalStorage(DocumentStorage):
    """Local filesystem implementation of DocumentStorage."""

    def __init__(self, base_dir: Path | str | None = None) -> None:
        if base_dir is None:
            base_dir = get_settings().storage_dir
        self.base_dir = Path(base_dir).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _resolve_safe_path(self, storage_key: str) -> Path:
        """Resolve storage key securely, preventing directory traversal attacks."""
        clean_key = storage_key.strip().lstrip("/\\")
        if ".." in clean_key or clean_key.startswith("/") or clean_key.startswith("\\"):
            raise StorageSecurityError(f"Unsafe storage key: {storage_key}")

        target_path = (self.base_dir / clean_key).resolve()
        try:
            target_path.relative_to(self.base_dir)
        except ValueError:
            raise StorageSecurityError(f"Storage path {target_path} escapes {self.base_dir}")

        return target_path

    def save(self, storage_key: str, data: bytes) -> str:
        safe_path = self._resolve_safe_path(storage_key)
        safe_path.parent.mkdir(parents=True, exist_ok=True)
        safe_path.write_bytes(data)
        return str(safe_path)

    def read(self, storage_key: str) -> bytes:
        safe_path = self._resolve_safe_path(storage_key)
        if not safe_path.is_file():
            raise FileNotFoundError(f"Storage file not found: {storage_key}")
        return safe_path.read_bytes()

    def exists(self, storage_key: str) -> bool:
        safe_path = self._resolve_safe_path(storage_key)
        return safe_path.is_file()

    def delete(self, storage_key: str) -> bool:
        safe_path = self._resolve_safe_path(storage_key)
        if safe_path.is_file():
            safe_path.unlink()
            return True
        return False


class EncryptedCleanStorage(DocumentStorage):
    """AES-256-GCM encrypted storage tier for verified clean documents."""

    def __init__(self, base_dir: Path | str | None = None, key_material: str | None = None) -> None:
        settings = get_settings()
        if base_dir is None:
            base_dir = settings.clean_storage_dir
        if key_material is None:
            key_material = settings.storage_encryption_key
        self.base_dir = Path(base_dir).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.key_material = key_material

    def _resolve_safe_path(self, storage_key: str) -> Path:
        clean_key = storage_key.strip().lstrip("/\\")
        if ".." in clean_key or clean_key.startswith("/") or clean_key.startswith("\\"):
            raise StorageSecurityError(f"Unsafe storage key: {storage_key}")

        target_path = (self.base_dir / clean_key).resolve()
        try:
            target_path.relative_to(self.base_dir)
        except ValueError:
            raise StorageSecurityError(f"Storage path {target_path} escapes {self.base_dir}")

        return target_path

    def save(self, storage_key: str, data: bytes) -> str:
        safe_path = self._resolve_safe_path(storage_key)
        safe_path.parent.mkdir(parents=True, exist_ok=True)
        ciphertext = encrypt_payload(data, self.key_material)
        safe_path.write_bytes(ciphertext)
        return str(safe_path)

    def read(self, storage_key: str) -> bytes:
        safe_path = self._resolve_safe_path(storage_key)
        if not safe_path.is_file():
            raise FileNotFoundError(f"Storage file not found in clean tier: {storage_key}")

        raw_bytes = safe_path.read_bytes()
        try:
            return decrypt_payload(raw_bytes, self.key_material)
        except CryptoError:
            # Fallback for unencrypted legacy / synthetic fixtures
            return raw_bytes

    def exists(self, storage_key: str) -> bool:
        safe_path = self._resolve_safe_path(storage_key)
        return safe_path.is_file()

    def delete(self, storage_key: str) -> bool:
        safe_path = self._resolve_safe_path(storage_key)
        if safe_path.is_file():
            safe_path.unlink()
            return True
        return False


class TieredDocumentStorage(DocumentStorage):
    """Tiered storage managing Quarantine and Encrypted Clean storage partitions."""

    def __init__(self) -> None:
        settings = get_settings()
        self.quarantine = LocalStorage(settings.quarantine_dir)
        self.clean = EncryptedCleanStorage(settings.clean_storage_dir, settings.storage_encryption_key)
        self.legacy = LocalStorage(settings.storage_dir)

    def save(self, storage_key: str, data: bytes) -> str:
        """Default save writes to clean storage."""
        return self.clean.save(storage_key, data)

    def save_quarantine(self, storage_key: str, data: bytes) -> str:
        """Save uninspected document to quarantine storage."""
        return self.quarantine.save(storage_key, data)

    def read(self, storage_key: str) -> bytes:
        """Read from clean storage, falling back to legacy synthetic storage if needed."""
        if self.clean.exists(storage_key):
            return self.clean.read(storage_key)
        if self.legacy.exists(storage_key):
            return self.legacy.read(storage_key)
        raise FileNotFoundError(f"Storage file not found in any clean tier: {storage_key}")

    def read_quarantine(self, storage_key: str) -> bytes:
        """Read raw payload from quarantine for security scanning."""
        return self.quarantine.read(storage_key)

    def exists(self, storage_key: str) -> bool:
        return self.clean.exists(storage_key) or self.legacy.exists(storage_key)

    def delete(self, storage_key: str) -> bool:
        deleted = False
        if self.clean.exists(storage_key):
            deleted = self.clean.delete(storage_key) or deleted
        if self.quarantine.exists(storage_key):
            deleted = self.quarantine.delete(storage_key) or deleted
        if self.legacy.exists(storage_key):
            deleted = self.legacy.delete(storage_key) or deleted
        return deleted


def get_document_storage() -> DocumentStorage:
    """Return configured DocumentStorage implementation."""
    return TieredDocumentStorage()
