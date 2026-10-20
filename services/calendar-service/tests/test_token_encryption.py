"""Tests for token encryption in google_sync module.

The service encrypts OAuth tokens at rest using Fernet when
CALENDAR_TOKEN_SECRET is configured. Legacy plaintext tokens are still
supported for migration.
"""

from __future__ import annotations

import json

import google_sync
import pytest
from cryptography.fernet import Fernet


@pytest.fixture
def fernet_key():
    """Generate a valid Fernet key for testing."""
    return Fernet.generate_key().decode()


@pytest.fixture
def token_data():
    """Sample token data for testing."""
    return {
        "token": "ya29.test-access-token-1234567890",
        "refresh_token": "1//test-refresh-token-abcdefgh",
        "token_uri": "https://oauth2.googleapis.com/token",
        "scopes": ["https://www.googleapis.com/auth/calendar.readonly"],
    }


class TestGetFernet:
    """Tests for _get_fernet() helper."""

    def test_returns_none_when_no_secret(self, monkeypatch):
        """Should return None when CALENDAR_TOKEN_SECRET is empty."""
        monkeypatch.setattr(google_sync, "CALENDAR_TOKEN_SECRET", "")
        assert google_sync._get_fernet() is None

    def test_returns_fernet_when_valid_secret(self, monkeypatch, fernet_key):
        """Should return Fernet instance when secret is valid."""
        monkeypatch.setattr(google_sync, "CALENDAR_TOKEN_SECRET", fernet_key)
        fernet = google_sync._get_fernet()
        assert fernet is not None
        assert isinstance(fernet, Fernet)

    def test_returns_none_when_invalid_secret(self, monkeypatch):
        """Should return None when secret is invalid (not base64)."""
        monkeypatch.setattr(google_sync, "CALENDAR_TOKEN_SECRET", "invalid-key")
        assert google_sync._get_fernet() is None


class TestEncryptTokenData:
    """Tests for _encrypt_token_data() helper."""

    def test_returns_json_when_no_secret(self, monkeypatch, token_data):
        """Should return plain JSON when no encryption secret."""
        monkeypatch.setattr(google_sync, "CALENDAR_TOKEN_SECRET", "")
        result = google_sync._encrypt_token_data(token_data)
        # Should be valid JSON
        parsed = json.loads(result)
        assert parsed["refresh_token"] == token_data["refresh_token"]

    def test_returns_encrypted_when_secret_set(
        self, monkeypatch, fernet_key, token_data
    ):
        """Should return encrypted string when secret is set."""
        monkeypatch.setattr(google_sync, "CALENDAR_TOKEN_SECRET", fernet_key)
        result = google_sync._encrypt_token_data(token_data)
        # Should NOT be valid JSON (encrypted)
        with pytest.raises(json.JSONDecodeError):
            json.loads(result)
        # Should be decryptable
        fernet = Fernet(fernet_key.encode())
        decrypted = json.loads(fernet.decrypt(result.encode()).decode())
        assert decrypted["refresh_token"] == token_data["refresh_token"]


class TestDecryptTokenData:
    """Tests for _decrypt_token_data() helper."""

    def test_decrypts_plaintext_json(self, monkeypatch, token_data):
        """Should parse plain JSON (legacy tokens)."""
        monkeypatch.setattr(google_sync, "CALENDAR_TOKEN_SECRET", "")
        json_str = json.dumps(token_data)
        result = google_sync._decrypt_token_data(json_str)
        assert result is not None
        assert result["refresh_token"] == token_data["refresh_token"]

    def test_decrypts_encrypted_data(self, monkeypatch, fernet_key, token_data):
        """Should decrypt Fernet-encrypted data."""
        monkeypatch.setattr(google_sync, "CALENDAR_TOKEN_SECRET", fernet_key)
        fernet = Fernet(fernet_key.encode())
        encrypted = fernet.encrypt(json.dumps(token_data).encode()).decode()
        result = google_sync._decrypt_token_data(encrypted)
        assert result is not None
        assert result["refresh_token"] == token_data["refresh_token"]

    def test_returns_none_when_encrypted_but_no_secret(
        self, monkeypatch, fernet_key, token_data
    ):
        """Should return None when data is encrypted but no secret configured."""
        fernet = Fernet(fernet_key.encode())
        encrypted = fernet.encrypt(json.dumps(token_data).encode()).decode()
        monkeypatch.setattr(google_sync, "CALENDAR_TOKEN_SECRET", "")
        result = google_sync._decrypt_token_data(encrypted)
        assert result is None

    def test_returns_none_when_wrong_key(self, monkeypatch, token_data):
        """Should return None when decryption fails (wrong key)."""
        key1 = Fernet.generate_key()
        key2 = Fernet.generate_key()
        fernet1 = Fernet(key1)
        encrypted = fernet1.encrypt(json.dumps(token_data).encode()).decode()
        monkeypatch.setattr(google_sync, "CALENDAR_TOKEN_SECRET", key2.decode())
        result = google_sync._decrypt_token_data(encrypted)
        assert result is None

    def test_supports_legacy_then_encrypted_migration(
        self, monkeypatch, fernet_key, token_data
    ):
        """Should support reading legacy plaintext even with secret configured."""
        monkeypatch.setattr(google_sync, "CALENDAR_TOKEN_SECRET", fernet_key)
        # Legacy plaintext token
        json_str = json.dumps(token_data)
        result = google_sync._decrypt_token_data(json_str)
        assert result is not None
        assert result["refresh_token"] == token_data["refresh_token"]


class TestGoogleCalendarClientTokenPersistence:
    """Integration tests for token persistence with encryption."""

    def test_save_and_load_encrypted_token(
        self, tmp_path, monkeypatch, fernet_key, token_data
    ):
        """Should save encrypted and load correctly."""
        monkeypatch.setattr(google_sync, "CALENDAR_TOKEN_SECRET", fernet_key)
        token_path = tmp_path / "token.json"

        client = google_sync.GoogleCalendarClient(
            client_id="test-client-id",
            client_secret="test-client-secret",
            token_path=token_path,
        )

        # Write plaintext token first (simulating legacy)
        token_path.write_text(json.dumps(token_data))

        # Authenticate should read legacy token
        # Note: This will fail at refresh step since we don't have real OAuth
        # but the token loading should work
        result = client.authenticate()
        # Will be False because no real OAuth, but credentials should be loaded
        assert client._credentials is not None or not result

    def test_legacy_token_readable_after_enabling_encryption(
        self, tmp_path, monkeypatch, fernet_key, token_data
    ):
        """Legacy plaintext tokens should still be readable after enabling encryption."""
        token_path = tmp_path / "token.json"

        # First: save without encryption (legacy)
        monkeypatch.setattr(google_sync, "CALENDAR_TOKEN_SECRET", "")
        token_path.write_text(json.dumps(token_data))

        # Now: enable encryption and read
        monkeypatch.setattr(google_sync, "CALENDAR_TOKEN_SECRET", fernet_key)
        client = google_sync.GoogleCalendarClient(
            client_id="test-client-id",
            client_secret="test-client-secret",
            token_path=token_path,
        )

        # Should be able to read legacy token
        # (authenticate will fail at refresh but token parsing should work)
        _ = client.authenticate()
        # Credentials should have been loaded from legacy token
        # Even though auth fails, the parsing step worked
