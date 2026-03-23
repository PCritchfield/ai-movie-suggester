"""Unit tests for HKDF key derivation and Fernet encrypt/decrypt helpers."""

from __future__ import annotations

import base64

import pytest

from app.auth.crypto import derive_keys, fernet_decrypt, fernet_encrypt


class TestDeriveKeys:
    """Tests for HKDF key derivation from SESSION_SECRET."""

    def test_produces_two_distinct_keys(self) -> None:
        """Cookie-signing and column-encryption keys must differ."""
        cookie_key, column_key = derive_keys("test-secret-at-least-32-characters-long")
        assert cookie_key != column_key

    def test_deterministic_output(self) -> None:
        """Same secret always produces the same key pair."""
        secret = "test-secret-at-least-32-characters-long"
        first = derive_keys(secret)
        second = derive_keys(secret)
        assert first == second

    def test_different_secrets_produce_different_keys(self) -> None:
        """Different secrets must produce different key pairs."""
        keys_a = derive_keys("secret-alpha-at-least-32-characters-long")
        keys_b = derive_keys("secret-bravo-at-least-32-characters-long")
        assert keys_a[0] != keys_b[0]
        assert keys_a[1] != keys_b[1]

    def test_keys_are_valid_fernet_keys(self) -> None:
        """Each key must be a 44-character base64url-encoded Fernet key."""
        cookie_key, column_key = derive_keys("test-secret-at-least-32-characters-long")
        for key in (cookie_key, column_key):
            decoded = base64.urlsafe_b64decode(key)
            assert len(decoded) == 32
            assert len(key) == 44


class TestFernetHelpers:
    """Tests for Fernet encrypt/decrypt round-trip."""

    def test_encrypt_decrypt_round_trip(self) -> None:
        """Encrypting then decrypting returns original plaintext."""
        _, column_key = derive_keys("test-secret-at-least-32-characters-long")
        plaintext = "my-secret-jellyfin-token"
        ciphertext = fernet_encrypt(column_key, plaintext)
        assert fernet_decrypt(column_key, ciphertext) == plaintext

    def test_tampered_ciphertext_raises(self) -> None:
        """Tampered ciphertext must raise InvalidToken."""
        from cryptography.fernet import InvalidToken

        _, column_key = derive_keys("test-secret-at-least-32-characters-long")
        ciphertext = fernet_encrypt(column_key, "secret-token")
        tampered = ciphertext[:-1] + (b"X" if ciphertext[-1:] != b"X" else b"Y")
        with pytest.raises(InvalidToken):
            fernet_decrypt(column_key, tampered)

    def test_wrong_key_raises(self) -> None:
        """Decrypting with the wrong key must raise InvalidToken."""
        from cryptography.fernet import InvalidToken

        cookie_key, column_key = derive_keys("test-secret-at-least-32-characters-long")
        ciphertext = fernet_encrypt(column_key, "secret-token")
        with pytest.raises(InvalidToken):
            fernet_decrypt(cookie_key, ciphertext)
