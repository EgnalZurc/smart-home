"""Unit tests for auth_devices.py - Jaspan pattern device tokens."""

import sqlite3
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock

import auth_devices
import pytest


@pytest.fixture
def temp_db():
    """Create a fresh temp database for each test."""
    temp_dir = tempfile.mkdtemp()
    db_path = str(Path(temp_dir) / "test_auth.db")

    # Store original value
    orig_db = auth_devices.AUTH_DB_PATH

    # Set test value
    auth_devices.AUTH_DB_PATH = db_path

    yield {"db_path": db_path, "temp_dir": temp_dir}

    # Restore original value
    auth_devices.AUTH_DB_PATH = orig_db

    # Cleanup
    import shutil

    shutil.rmtree(temp_dir, ignore_errors=True)


class TestHelpers:
    def test_hash_produces_hex_digest(self):
        result = auth_devices._hash("test-token")
        assert len(result) == 64  # SHA-256 hex
        assert all(c in "0123456789abcdef" for c in result)

    def test_hash_is_deterministic(self):
        h1 = auth_devices._hash("same-token")
        h2 = auth_devices._hash("same-token")
        assert h1 == h2

    def test_hash_differs_for_different_input(self):
        h1 = auth_devices._hash("token1")
        h2 = auth_devices._hash("token2")
        assert h1 != h2

    def test_generate_produces_url_safe_token(self):
        token = auth_devices._generate()
        assert len(token) == 43  # 32 bytes base64
        assert all(c.isalnum() or c in "-_" for c in token)

    def test_encode_cookie(self):
        result = auth_devices._encode_cookie("series123", "token456")
        assert result == "series123:token456"

    def test_decode_cookie_valid(self):
        result = auth_devices._decode_cookie("series123:token456")
        assert result == ("series123", "token456")

    def test_decode_cookie_empty(self):
        assert auth_devices._decode_cookie("") is None

    def test_decode_cookie_no_separator(self):
        assert auth_devices._decode_cookie("noseparator") is None

    def test_decode_cookie_empty_parts(self):
        assert auth_devices._decode_cookie(":token") is None
        assert auth_devices._decode_cookie("series:") is None


class TestDeviceTokenOperations:
    def test_create_returns_cookie(self, temp_db):
        cookie = auth_devices.create_device_token(
            "testuser", "Mozilla/5.0", "192.168.1.1"
        )
        assert ":" in cookie
        series, token = cookie.split(":", 1)
        assert len(series) > 20
        assert len(token) > 20

    def test_create_stores_in_db(self, temp_db):
        auth_devices.create_device_token("testuser", "UA", "IP")

        conn = sqlite3.connect(temp_db["db_path"])
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM device_tokens").fetchone()
        conn.close()

        assert row is not None
        assert row["username"] == "testuser"
        assert row["user_agent"] == "UA"
        assert row["ip_address"] == "IP"

    def test_list_devices_returns_user_tokens(self, temp_db):
        auth_devices.create_device_token("user1", "UA1", "IP1")
        auth_devices.create_device_token("user1", "UA2", "IP2")
        auth_devices.create_device_token("user2", "UA3", "IP3")

        devices = auth_devices.list_devices("user1")
        assert len(devices) == 2
        user_agents = [d["user_agent"] for d in devices]
        assert "UA1" in user_agents
        assert "UA2" in user_agents

    def test_list_devices_empty_for_unknown_user(self, temp_db):
        devices = auth_devices.list_devices("nonexistent")
        assert devices == []

    def test_revoke_all_devices(self, temp_db):
        auth_devices.create_device_token("user1", "UA1", "IP1")
        auth_devices.create_device_token("user1", "UA2", "IP2")

        count = auth_devices.revoke_all_devices("user1")

        assert count == 2
        assert auth_devices.list_devices("user1") == []

    def test_revoke_device_by_series(self, temp_db):
        cookie = auth_devices.create_device_token("user1", "UA", "IP")
        series = cookie.split(":")[0]

        result = auth_devices.revoke_device(series)

        assert result is True
        assert auth_devices.list_devices("user1") == []

    def test_revoke_device_unknown_series(self, temp_db):
        result = auth_devices.revoke_device("nonexistent-series")
        assert result is False


class TestVerifyAndRotate:
    def test_invalid_cookie_format(self, temp_db):
        result = auth_devices.verify_and_rotate("invalid")
        assert result.ok is False
        assert result.theft_detected is False

    def test_unknown_series(self, temp_db):
        result = auth_devices.verify_and_rotate("unknown:token")
        assert result.ok is False

    def test_valid_token_rotates(self, temp_db):
        original_cookie = auth_devices.create_device_token("user1", "UA", "IP")

        result = auth_devices.verify_and_rotate(original_cookie)

        assert result.ok is True
        assert result.username == "user1"
        assert result.new_cookie_value != original_cookie
        assert result.new_cookie_value != ""

    def test_rotated_token_works(self, temp_db):
        original_cookie = auth_devices.create_device_token("user1", "UA", "IP")
        result1 = auth_devices.verify_and_rotate(original_cookie)

        result2 = auth_devices.verify_and_rotate(result1.new_cookie_value)

        assert result2.ok is True
        assert result2.username == "user1"

    def test_old_token_in_grace_window(self, temp_db):
        original_cookie = auth_devices.create_device_token("user1", "UA", "IP")

        # First verification rotates the token
        auth_devices.verify_and_rotate(original_cookie)

        # Using original (now prev) token within grace window should work
        result = auth_devices.verify_and_rotate(original_cookie)

        assert result.ok is True
        # new_cookie_value is empty to signal "use existing JWT"
        assert result.new_cookie_value == ""

    def test_expired_token(self, temp_db):
        cookie = auth_devices.create_device_token("user1", "UA", "IP")
        series = cookie.split(":")[0]

        # Manually expire the token
        conn = sqlite3.connect(temp_db["db_path"])
        conn.execute(
            "UPDATE device_tokens SET expires_at = ? WHERE series = ?",
            (time.time() - 100, series),
        )
        conn.commit()
        conn.close()

        result = auth_devices.verify_and_rotate(cookie)

        assert result.ok is False
        assert auth_devices.list_devices("user1") == []


class TestVerifyResult:
    def test_default_values(self):
        result = auth_devices.VerifyResult(ok=False)
        assert result.ok is False
        assert result.username == ""
        assert result.new_cookie_value == ""
        assert result.theft_detected is False

    def test_with_all_values(self):
        result = auth_devices.VerifyResult(
            ok=True,
            username="testuser",
            new_cookie_value="series:token",
            theft_detected=False,
        )
        assert result.ok is True
        assert result.username == "testuser"
        assert result.new_cookie_value == "series:token"


class TestGetDeviceCookieFromRequest:
    def test_returns_cookie_value(self, temp_db):
        request = MagicMock()
        request.cookies = {"smh_device": "series:token"}

        result = auth_devices.get_device_cookie_from_request(request)
        assert result == "series:token"

    def test_returns_none_when_missing(self, temp_db):
        request = MagicMock()
        request.cookies = {}

        result = auth_devices.get_device_cookie_from_request(request)
        assert result is None


class TestConstants:
    def test_cookie_name(self):
        assert auth_devices.DEVICE_COOKIE_NAME == "smh_device"

    def test_ttl_is_one_year(self):
        assert auth_devices.DEVICE_TOKEN_TTL == 365 * 24 * 3600

    def test_grace_window(self):
        assert auth_devices.GRACE_WINDOW_SECONDS == 30
