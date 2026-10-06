"""Unit tests for auth_users.py - user store and trusted device management.

These tests use a fresh database per test to avoid state pollution.
The database is created in a temp directory unique to each test.
"""

import sqlite3
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def isolated_auth_users():
    """Create an isolated auth_users module with a fresh temp database.

    This fixture:
    1. Creates a temp directory
    2. Patches the module-level constants
    3. Yields the module for testing
    4. Cleans up after the test
    """
    import shutil

    import auth_users

    temp_dir = tempfile.mkdtemp()
    db_path = str(Path(temp_dir) / "test_auth.db")
    htpasswd_path = str(Path(temp_dir) / ".htpasswd")

    # Store originals
    orig_db = auth_users.AUTH_DB_PATH
    orig_htpasswd = auth_users.HTPASSWD_PATH
    orig_secret = auth_users.TRUST_SECRET

    # Set test values
    auth_users.AUTH_DB_PATH = db_path
    auth_users.HTPASSWD_PATH = htpasswd_path
    auth_users.TRUST_SECRET = "test-secret-key-for-hmac-signing"

    yield {"module": auth_users, "db_path": db_path, "temp_dir": temp_dir}

    # Restore originals
    auth_users.AUTH_DB_PATH = orig_db
    auth_users.HTPASSWD_PATH = orig_htpasswd
    auth_users.TRUST_SECRET = orig_secret

    # Cleanup
    shutil.rmtree(temp_dir, ignore_errors=True)


class TestCreateUser:
    def test_returns_uuid(self, isolated_auth_users):
        auth_users = isolated_auth_users["module"]
        user_id = auth_users.create_user("testuser", "password123", "Test User")
        assert user_id is not None
        assert len(user_id) == 36  # UUID format

    def test_hashes_password_with_apr1(self, isolated_auth_users):
        auth_users = isolated_auth_users["module"]
        db_path = isolated_auth_users["db_path"]
        auth_users.create_user("testuser", "password123")

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT password_hash FROM users WHERE username = ?", ("testuser",)
        ).fetchone()
        conn.close()

        assert row is not None
        assert row[0].startswith("$apr1$")

    def test_generates_display_name_from_username(self, isolated_auth_users):
        auth_users = isolated_auth_users["module"]
        user_id = auth_users.create_user("johndoe", "password123")
        user = auth_users.get_user_by_id(user_id)
        assert user["display_name"] == "Johndoe"

    def test_duplicate_username_raises_value_error(self, isolated_auth_users):
        auth_users = isolated_auth_users["module"]
        auth_users.create_user("testuser", "password123")
        with pytest.raises(ValueError, match="already exists"):
            auth_users.create_user("testuser", "different")


class TestGetUser:
    def test_get_by_id_returns_user(self, isolated_auth_users):
        auth_users = isolated_auth_users["module"]
        user_id = auth_users.create_user("testuser", "password123", "Test")
        user = auth_users.get_user_by_id(user_id)

        assert user is not None
        assert user["id"] == user_id
        assert user["username"] == "testuser"
        assert user["display_name"] == "Test"
        assert "password_hash" not in user

    def test_get_by_id_returns_none_for_unknown(self, isolated_auth_users):
        auth_users = isolated_auth_users["module"]
        user = auth_users.get_user_by_id("nonexistent-uuid")
        assert user is None

    def test_get_by_username_returns_user(self, isolated_auth_users):
        auth_users = isolated_auth_users["module"]
        auth_users.create_user("testuser", "password123")
        user = auth_users.get_user_by_username("testuser")

        assert user is not None
        assert user["username"] == "testuser"
        assert "password_hash" not in user

    def test_get_by_username_returns_none_for_unknown(self, isolated_auth_users):
        auth_users = isolated_auth_users["module"]
        user = auth_users.get_user_by_username("nonexistent")
        assert user is None

    def test_get_all_returns_list(self, isolated_auth_users):
        auth_users = isolated_auth_users["module"]
        auth_users.create_user("user1", "pass1")
        auth_users.create_user("user2", "pass2")

        users = auth_users.get_all_users()

        assert len(users) == 2
        usernames = [u["username"] for u in users]
        assert "user1" in usernames
        assert "user2" in usernames


class TestUpdateUser:
    def test_update_display_name(self, isolated_auth_users):
        auth_users = isolated_auth_users["module"]
        user_id = auth_users.create_user("testuser", "password123")
        auth_users.update_user(user_id, display_name="New Name")

        user = auth_users.get_user_by_id(user_id)
        assert user["display_name"] == "New Name"

    def test_update_icon(self, isolated_auth_users):
        auth_users = isolated_auth_users["module"]
        user_id = auth_users.create_user("testuser", "password123")
        auth_users.update_user(user_id, icon="🏠")

        user = auth_users.get_user_by_id(user_id)
        assert user["icon"] == "🏠"

    def test_update_password(self, isolated_auth_users):
        auth_users = isolated_auth_users["module"]
        user_id = auth_users.create_user("testuser", "oldpassword")
        auth_users.update_user(user_id, password="newpassword")

        assert auth_users.authenticate_user("testuser", "newpassword")
        assert not auth_users.authenticate_user("testuser", "oldpassword")

    def test_update_nonexistent_raises(self, isolated_auth_users):
        auth_users = isolated_auth_users["module"]
        with pytest.raises(ValueError, match="not found"):
            auth_users.update_user("nonexistent-uuid", display_name="Test")

    def test_update_with_no_changes_is_noop(self, isolated_auth_users):
        auth_users = isolated_auth_users["module"]
        user_id = auth_users.create_user("testuser", "password123")
        # Should not raise
        auth_users.update_user(user_id)


class TestDeleteUser:
    def test_deletes_user(self, isolated_auth_users):
        auth_users = isolated_auth_users["module"]
        user_id = auth_users.create_user("testuser", "password123")
        auth_users.delete_user(user_id)

        user = auth_users.get_user_by_id(user_id)
        assert user is None

    def test_delete_nonexistent_raises(self, isolated_auth_users):
        auth_users = isolated_auth_users["module"]
        with pytest.raises(ValueError, match="not found"):
            auth_users.delete_user("nonexistent-uuid")


class TestAuthenticate:
    def test_authenticate_success(self, isolated_auth_users):
        auth_users = isolated_auth_users["module"]
        auth_users.create_user("testuser", "correctpassword")
        assert auth_users.authenticate_user("testuser", "correctpassword")

    def test_authenticate_wrong_password(self, isolated_auth_users):
        auth_users = isolated_auth_users["module"]
        auth_users.create_user("testuser", "correctpassword")
        assert not auth_users.authenticate_user("testuser", "wrongpassword")

    def test_authenticate_unknown_user(self, isolated_auth_users):
        auth_users = isolated_auth_users["module"]
        # Should return False without revealing user doesn't exist
        assert not auth_users.authenticate_user("nonexistent", "anypassword")


class TestUserExists:
    def test_returns_true_for_existing(self, isolated_auth_users):
        auth_users = isolated_auth_users["module"]
        auth_users.create_user("testuser", "password123")
        assert auth_users.user_exists("testuser")

    def test_returns_false_for_nonexistent(self, isolated_auth_users):
        auth_users = isolated_auth_users["module"]
        assert not auth_users.user_exists("nonexistent")


class TestTrustRequests:
    def test_create_returns_token(self, isolated_auth_users):
        auth_users = isolated_auth_users["module"]
        token = auth_users.create_trust_request(
            "testuser", "Mozilla/5.0", "192.168.1.1"
        )
        assert token is not None
        assert len(token) > 20

    def test_get_status_pending(self, isolated_auth_users):
        auth_users = isolated_auth_users["module"]
        token = auth_users.create_trust_request("testuser", "UA", "IP")
        status = auth_users.get_trust_status(token)
        assert status == "pending"

    def test_get_status_unknown_returns_none(self, isolated_auth_users):
        auth_users = isolated_auth_users["module"]
        status = auth_users.get_trust_status("nonexistent-token")
        assert status is None

    def test_resolve_approve(self, isolated_auth_users):
        auth_users = isolated_auth_users["module"]
        token = auth_users.create_trust_request("testuser", "UA", "IP")
        row = auth_users.resolve_trust_request(token, "approved")

        assert row is not None
        assert row["username"] == "testuser"
        assert auth_users.get_trust_status(token) == "approved"

    def test_resolve_reject(self, isolated_auth_users):
        auth_users = isolated_auth_users["module"]
        token = auth_users.create_trust_request("testuser", "UA", "IP")
        row = auth_users.resolve_trust_request(token, "rejected")

        assert row is not None
        assert auth_users.get_trust_status(token) == "rejected"

    def test_resolve_invalid_action_raises(self, isolated_auth_users):
        auth_users = isolated_auth_users["module"]
        token = auth_users.create_trust_request("testuser", "UA", "IP")
        with pytest.raises(ValueError, match="Invalid action"):
            auth_users.resolve_trust_request(token, "invalid")

    def test_resolve_already_resolved_returns_none(self, isolated_auth_users):
        auth_users = isolated_auth_users["module"]
        token = auth_users.create_trust_request("testuser", "UA", "IP")
        auth_users.resolve_trust_request(token, "approved")
        row = auth_users.resolve_trust_request(token, "rejected")
        assert row is None

    def test_has_active_request(self, isolated_auth_users):
        auth_users = isolated_auth_users["module"]
        assert not auth_users.has_active_trust_request("testuser")
        auth_users.create_trust_request("testuser", "UA", "IP")
        assert auth_users.has_active_trust_request("testuser")

    def test_get_approved_request(self, isolated_auth_users):
        auth_users = isolated_auth_users["module"]
        token = auth_users.create_trust_request("testuser", "UA", "IP")
        auth_users.resolve_trust_request(token, "approved")

        row = auth_users.get_approved_trust_request("testuser")
        assert row is not None
        assert row["username"] == "testuser"

    def test_get_approved_returns_none_when_pending(self, isolated_auth_users):
        auth_users = isolated_auth_users["module"]
        auth_users.create_trust_request("testuser", "UA", "IP")
        row = auth_users.get_approved_trust_request("testuser")
        assert row is None

    def test_delete_request(self, isolated_auth_users):
        auth_users = isolated_auth_users["module"]
        token = auth_users.create_trust_request("testuser", "UA", "IP")
        assert auth_users.delete_trust_request(token)
        assert auth_users.get_trust_status(token) is None

    def test_delete_unknown_returns_false(self, isolated_auth_users):
        auth_users = isolated_auth_users["module"]
        assert not auth_users.delete_trust_request("nonexistent")


class TestHmacSignatures:
    def test_make_action_url_contains_token_and_sig(self, isolated_auth_users):
        auth_users = isolated_auth_users["module"]
        url = auth_users.make_action_url("https://example.com", "test-token", "approve")
        assert "test-token" in url
        assert "approve" in url
        assert "sig=" in url

    def test_verify_valid_signature(self, isolated_auth_users):
        auth_users = isolated_auth_users["module"]
        url = auth_users.make_action_url("https://example.com", "test-token", "approve")
        sig = url.split("sig=")[1]
        assert auth_users.verify_action_sig("test-token", "approve", sig)

    def test_verify_invalid_signature(self, isolated_auth_users):
        auth_users = isolated_auth_users["module"]
        assert not auth_users.verify_action_sig("token", "approve", "invalid-sig")

    def test_verify_wrong_action_fails(self, isolated_auth_users):
        auth_users = isolated_auth_users["module"]
        url = auth_users.make_action_url("https://example.com", "test-token", "approve")
        sig = url.split("sig=")[1]
        # Try to use approve signature for reject action
        assert not auth_users.verify_action_sig("test-token", "reject", sig)


class TestHtpasswdMigration:
    def test_load_parses_file(self, isolated_auth_users):
        auth_users = isolated_auth_users["module"]
        temp_dir = isolated_auth_users["temp_dir"]
        htpasswd_path = Path(temp_dir) / ".htpasswd"
        htpasswd_path.write_text("user1:$apr1$hash1\nuser2:$apr1$hash2\n")

        result = auth_users._load_htpasswd(str(htpasswd_path))
        assert "user1" in result
        assert "user2" in result
        assert result["user1"] == "$apr1$hash1"

    def test_load_ignores_comments(self, isolated_auth_users):
        auth_users = isolated_auth_users["module"]
        temp_dir = isolated_auth_users["temp_dir"]
        htpasswd_path = Path(temp_dir) / ".htpasswd"
        htpasswd_path.write_text("# Comment\nuser1:$apr1$hash1\n")

        result = auth_users._load_htpasswd(str(htpasswd_path))
        assert len(result) == 1
        assert "user1" in result

    def test_load_returns_empty_for_missing_file(self, isolated_auth_users):
        auth_users = isolated_auth_users["module"]
        result = auth_users._load_htpasswd("/nonexistent/path")
        assert result == {}
