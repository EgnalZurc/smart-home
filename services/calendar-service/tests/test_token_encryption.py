"""Tests for OAuth token encryption in google_sync module.

Validates that tokens are properly encrypted/decrypted using Fernet,
and that the migration path from plaintext to encrypted tokens works.
"""

from __future__ import annotations

import json

import pytest
from google_sync import (
    _decrypt_token_data,
    _derive_fernet_key,
    _encrypt_token_data,
    _is_encrypted_token,
)


class TestTokenEncryption:
    """Unit tests for token encryption/decryption functions."""

    def test_derive_fernet_key_is_deterministic(self):
        """Same secret produces same key."""
        secret = "my-test-secret-key"
        key1 = _derive_fernet_key(secret)
        key2 = _derive_fernet_key(secret)
        assert key1 == key2

    def test_derive_fernet_key_different_secrets(self):
        """Different secrets produce different keys."""
        key1 = _derive_fernet_key("secret-one")
        key2 = _derive_fernet_key("secret-two")
        assert key1 != key2

    def test_encrypt_decrypt_roundtrip(self):
        """Token data survives encryption/decryption roundtrip."""
        secret = "encryption-secret"
        token_data = {
            "token": "access-token-here",
            "refresh_token": "refresh-token-here",
            "token_uri": "https://oauth2.googleapis.com/token",
            "scopes": ["https://www.googleapis.com/auth/calendar.readonly"],
        }

        encrypted = _encrypt_token_data(token_data, secret)
        decrypted = _decrypt_token_data(encrypted, secret)

        assert decrypted == token_data

    def test_encrypted_token_has_marker(self):
        """Encrypted content is prefixed with the marker."""
        secret = "test-secret"
        encrypted = _encrypt_token_data({"refresh_token": "abc"}, secret)
        assert encrypted.startswith("encrypted:v1:")

    def test_is_encrypted_token_true_for_encrypted(self):
        """_is_encrypted_token returns True for encrypted content."""
        secret = "test-secret"
        encrypted = _encrypt_token_data({"refresh_token": "abc"}, secret)
        assert _is_encrypted_token(encrypted) is True

    def test_is_encrypted_token_false_for_plaintext(self):
        """_is_encrypted_token returns False for plaintext JSON."""
        plaintext = json.dumps({"refresh_token": "abc"})
        assert _is_encrypted_token(plaintext) is False

    def test_decrypt_with_wrong_key_returns_none(self):
        """Decryption with wrong key returns None."""
        encrypted = _encrypt_token_data({"refresh_token": "abc"}, "correct-secret")
        result = _decrypt_token_data(encrypted, "wrong-secret")
        assert result is None

    def test_decrypt_corrupted_data_returns_none(self):
        """Decryption of corrupted data returns None."""
        corrupted = "encrypted:v1:corrupted-garbage-data"
        result = _decrypt_token_data(corrupted, "any-secret")
        assert result is None

    def test_decrypt_non_encrypted_returns_none(self):
        """Decryption of plaintext returns None (no marker)."""
        plaintext = json.dumps({"refresh_token": "abc"})
        result = _decrypt_token_data(plaintext, "any-secret")
        assert result is None


class TestTokenEncryptionEdgeCases:
    """Edge cases for token encryption."""

    def test_empty_token_data(self):
        """Empty dict can be encrypted/decrypted."""
        secret = "test"
        encrypted = _encrypt_token_data({}, secret)
        decrypted = _decrypt_token_data(encrypted, secret)
        assert decrypted == {}

    def test_unicode_in_token(self):
        """Unicode characters survive encryption roundtrip."""
        secret = "test"
        token_data = {"refresh_token": "token-with-émojis-🔐"}
        encrypted = _encrypt_token_data(token_data, secret)
        decrypted = _decrypt_token_data(encrypted, secret)
        assert decrypted == token_data

    def test_long_secret(self):
        """Long secrets work (SHA-256 handles any length)."""
        secret = "a" * 1000
        token_data = {"refresh_token": "abc"}
        encrypted = _encrypt_token_data(token_data, secret)
        decrypted = _decrypt_token_data(encrypted, secret)
        assert decrypted == token_data

    def test_short_secret(self):
        """Short secrets work (SHA-256 pads to 32 bytes)."""
        secret = "x"
        token_data = {"refresh_token": "abc"}
        encrypted = _encrypt_token_data(token_data, secret)
        decrypted = _decrypt_token_data(encrypted, secret)
        assert decrypted == token_data
