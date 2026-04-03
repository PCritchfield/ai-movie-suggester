"""HKDF key derivation and Fernet encrypt/decrypt helpers.

Derives two separate Fernet keys from SESSION_SECRET via HKDF-SHA256:
  - cookie-signing key: signs session ID cookies
  - column-encryption key: encrypts Jellyfin tokens at rest
"""

from __future__ import annotations

import base64

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

# Fixed application salt — not secret; domain separation comes from the
# HKDF info parameter.  Generated once via os.urandom(16).
_APP_SALT = bytes.fromhex("a3f1b2c4d5e6f708091a2b3c4d5e6f70")

_INFO_COOKIE_SIGNING = b"cookie-signing"
_INFO_COLUMN_ENCRYPTION = b"column-encryption"


def _derive_fernet_key(secret: str, info: bytes) -> bytes:
    """Derive a single 32-byte Fernet key from *secret* using HKDF-SHA256."""
    hkdf = HKDF(
        algorithm=SHA256(),
        length=32,
        salt=_APP_SALT,
        info=info,
    )
    raw = hkdf.derive(secret.encode("utf-8"))
    return base64.urlsafe_b64encode(raw)


def derive_keys(secret: str) -> tuple[bytes, bytes]:
    """Derive cookie-signing and column-encryption Fernet keys from *secret*.

    Returns:
        (cookie_signing_key, column_encryption_key) — each 44-byte
        base64url-encoded keys suitable for ``cryptography.fernet.Fernet``.
    """
    cookie_key = _derive_fernet_key(secret, _INFO_COOKIE_SIGNING)
    column_key = _derive_fernet_key(secret, _INFO_COLUMN_ENCRYPTION)
    return cookie_key, column_key


def fernet_encrypt(key: bytes, plaintext: str) -> bytes:
    """Encrypt *plaintext* with the given Fernet *key*."""
    return Fernet(key).encrypt(plaintext.encode("utf-8"))


def fernet_decrypt(key: bytes, ciphertext: bytes) -> str:
    """Decrypt *ciphertext* with the given Fernet *key*."""
    return Fernet(key).decrypt(ciphertext).decode("utf-8")


def decrypt_cookie(key: bytes, cookie_value: str | None) -> str | None:
    """Decrypt a session cookie value. Returns None if absent or invalid."""
    if not cookie_value:
        return None
    try:
        return fernet_decrypt(key, cookie_value.encode("utf-8"))
    except (InvalidToken, ValueError):
        # InvalidToken: tampered/corrupt cookie; ValueError: bad base64 encoding
        return None
