"""AES-256-GCM authenticated encryption for clean document storage at rest."""

from __future__ import annotations

import hashlib
import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class CryptoError(ValueError):
    """Raised when encryption or decryption fails."""


def derive_key(key_material: str | bytes) -> bytes:
    """Derive a deterministic 32-byte (256-bit) key for AES-256-GCM."""
    if isinstance(key_material, str):
        key_material = key_material.encode("utf-8")
    return hashlib.sha256(key_material).digest()


def encrypt_payload(data: bytes, key_material: str | bytes) -> bytes:
    """Encrypt payload using AES-256-GCM.

    Format: [12-byte random nonce] + [ciphertext + 16-byte authentication tag]
    """
    key = derive_key(key_material)
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, data, None)
    return nonce + ciphertext


def decrypt_payload(encrypted_data: bytes, key_material: str | bytes) -> bytes:
    """Decrypt payload using AES-256-GCM and verify authentication tag.

    Expects: [12-byte nonce] + [ciphertext + tag]
    """
    if len(encrypted_data) < 28:  # 12-byte nonce + 16-byte tag minimum
        raise CryptoError("Encrypted payload too short or malformed.")

    key = derive_key(key_material)
    aesgcm = AESGCM(key)
    nonce = encrypted_data[:12]
    ciphertext = encrypted_data[12:]
    try:
        return aesgcm.decrypt(nonce, ciphertext, None)
    except Exception as exc:
        raise CryptoError(f"Decryption failed or payload was tampered with: {exc}") from exc
