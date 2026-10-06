"""Unit tests for auth_users.py - user store and trusted device management."""

import sqlite3
import tempfile
from pathlib import Path

# Import module-level to get access to internal functions
import auth_users
import pytest


@pytest.fixture
def temp_db():
    """Create a fresh temp database for each test."""
    temp_dir = tempfile.mkdtemp()
    db_path = str(Path(temp_dir) / "test_auth.db")
    htpasswd_path = str(Path(temp_dir) / ".htpasswd")

    # Store original values
    orig_db = auth_users.AUTH_DB_PATH
    orig_htpasswd = auth_users.HTPASSWD_PATH
    orig_secret = auth_users.TRUST_SECRET

    # Set test values
    auth_users.AUTH_DB_PATH = db_path
    auth_users.HTPASSWD_PATH = htpasswd_path
    auth_users.TRUST_SECRET = "test-secret-key-for-hmac"

    yield {
        "db_path": db_path,
        "htpasswd_path": htpasswd_path,
        "temp_dir": temp_dir,
    }

    # Restore original values
    auth_users.AUTH_DB_PATH = orig_db
    auth_users.HTPASSWD_PATH = orig_htpasswd
    auth_users.TRUST_SECRET = orig_secret

    # Cleanup
    import shutil

    shutil.rmtree(temp_dir, ignore_errors=True)


class TestCreateUser:
    def test_returns_id(self, temp_db):
        user_id = auth_users.create_user("testuser", "password123", "Test User")
        assert user_id is not None
        assert len(user_id) == 36  # UUID format

    def test_hashes_password(self, temp_db):
        auth_users.create_user("testuser", "password123")

        conn = sqlite3.connect(temp_db["db_path"])
        row = conn.execute(
            "SELECT password_hash FROM users WHERE username = ?", ("testuser",)
        ).fetchone()
        conn.close()

        assert row[0].startswith("$apr1$")

    def test_generates_display_name(self, temp_db):
        user_id = auth_users.create_user("johndoe", "password123")
        user = auth_users.get_user_by_id(user_id)
        assert user["display_name"] == "Johndoe"

    def test_duplicate_raises(self, temp_db):
        auth_users.create_user("testuser", "password123")
        with pytest.raises(ValueError, match="already exists"):
            auth_users.create_user("testuser", "different")


class TestGetUser:
    def test_by_id(self, temp_db):
        user_id = auth_users.create_user("testuser", "password123", "Test")
        user = auth_users.get_user_by_id(user_id)

        assert user["id"] == user_id
        assert user["username"] == "testuser"
        assert user["display_name"] == "Test"
        assert "password_hash" not in user

    def test_by_id_returns_none_for_unknown(self, temp_db):
        user = auth_users.get_user_by_id("nonexistent-uuid")
        assert user is None

    def test_by_username(self, temp_db):
        auth_users.create_user("testuser", "password123")
        user = auth_users.get_user_by_username("testuser")

        assert user["username"] == "testuser"
        assert "password_hash" not in user

    def test_by_username_returns_none(self, temp_db):
        user = auth_users.get_user_by_username("nonexistent")
        assert user is None

    def test_get_all_users(self, temp_db):
        auth_users.create_user("user1", "pass1")
        auth_users.create_user("user2", "pass2")

        users = auth_users.get_all_users()

        assert len(users) == 2
        usernames = [u["username"] for u in users]
        assert "user1" in usernames
        assert "user2" in usernames


class TestUpdateUser:
    def test_display_name(self, temp_db):
        user_id = auth_users.create_user("testuser", "password123")
        auth_users.update_user(user_id, display_name="New Name")

        user = auth_users.get_user_by_id(user_id)
        assert user["display_name"] == "New Name"

    def test_icon(self, temp_db):
        user_id = auth_users.create_user("testuser", "password123")
        auth_users.update_user(user_id, icon="🏠")

        user = auth_users.get_user_by_id(user_id)
        assert user["icon"] == "🏠"

    def test_password(self, temp_db):
        user_id = auth_users.create_user("testuser", "oldpassword")
        auth_users.update_user(user_id, password="newpassword")

        assert auth_users.authenticate_user("testuser", "newpassword")
        assert not auth_users.authenticate_user("testuser", "oldpassword")

    def test_not_found_raises(self, temp_db):
        with pytest.raises(ValueError, match="not found"):
            auth_users.update_user("nonexistent-uuid", display_name="Test")

    def test_no_changes_is_noop(self, temp_db):
        user_id = auth_users.create_user("testuser", "password123")
        # Should not raise
        auth_users.update_user(user_id)


class TestDeleteUser:
    def test_deletes_user(self, temp_db):
        user_id = auth_users.create_user("testuser", "password123")
        auth_users.delete_user(user_id)

        user = auth_users.get_user_by_id(user_id)
        assert user is None

    def test_not_found_raises(self, temp_db):
        with pytest.raises(ValueError, match="not found"):
            auth_users.delete_user("nonexistent-uuid")


class TestAuthenticateUser:
    def test_success(self, temp_db):
        auth_users.create_user("testuser", "correctpassword")
        assert auth_users.authenticate_user("testuser", "correctpassword")

    def test_wrong_password(self, temp_db):
        auth_users.create_user("testuser", "correctpassword")
        assert not auth_users.authenticate_user("testuser", "wrongpassword")

    def test_unknown_user(self, temp_db):
        # Should return False without revealing user doesn't exist
        assert not auth_users.authenticate_user("nonexistent", "anypassword")


class TestUserExists:
    def test_exists(self, temp_db):
        auth_users.create_user("testuser", "password123")
        assert auth_users.user_exists("testuser")
        assert not auth_users.user_exists("nonexistent")


class TestTrustRequests:
    def test_create_returns_token(self, temp_db):
        token = auth_users.create_trust_request(
            "testuser", "Mozilla/5.0", "192.168.1.1"
        )
        assert token is not None
        assert len(token) > 20

    def test_get_status_pending(self, temp_db):
        token = auth_users.create_trust_request("testuser", "UA", "IP")
        status = auth_users.get_trust_status(token)
        assert status == "pending"

    def test_get_status_unknown_token(self, temp_db):
        status = auth_users.get_trust_status("nonexistent-token")
        assert status is None

    def test_resolve_approve(self, temp_db):
        token = auth_users.create_trust_request("testuser", "UA", "IP")
        row = auth_users.resolve_trust_request(token, "approved")

        assert row is not None
        assert row["username"] == "testuser"
        assert auth_users.get_trust_status(token) == "approved"

    def test_resolve_reject(self, temp_db):
        token = auth_users.create_trust_request("testuser", "UA", "IP")
        row = auth_users.resolve_trust_request(token, "rejected")

        assert row is not None
        assert auth_users.get_trust_status(token) == "rejected"

    def test_resolve_invalid_action_raises(self, temp_db):
        token = auth_users.create_trust_request("testuser", "UA", "IP")
        with pytest.raises(ValueError, match="Invalid action"):
            auth_users.resolve_trust_request(token, "invalid")

    def test_resolve_already_processed_returns_none(self, temp_db):
        token = auth_users.create_trust_request("testuser", "UA", "IP")
        auth_users.resolve_trust_request(token, "approved")

        row = auth_users.resolve_trust_request(token, "rejected")
        assert row is None

    def test_has_active_request(self, temp_db):
        assert not auth_users.has_active_trust_request("testuser")
        auth_users.create_trust_request("testuser", "UA", "IP")
        assert auth_users.has_active_trust_request("testuser")

    def test_get_approved_request(self, temp_db):
        token = auth_users.create_trust_request("testuser", "UA", "IP")
        auth_users.resolve_trust_request(token, "approved")

        row = auth_users.get_approved_trust_request("testuser")
        assert row is not None
        assert row["username"] == "testuser"

    def test_get_approved_request_none_when_pending(self, temp_db):
        auth_users.create_trust_request("testuser", "UA", "IP")
        row = auth_users.get_approved_trust_request("testuser")
        assert row is None

    def test_delete_request(self, temp_db):
        token = auth_users.create_trust_request("testuser", "UA", "IP")
        assert auth_users.delete_trust_request(token)
        assert auth_users.get_trust_status(token) is None

    def test_delete_request_returns_false_for_unknown(self, temp_db):
        assert not auth_users.delete_trust_request("nonexistent")


class TestHmacSignatures:
    def test_make_action_url_approve(self, temp_db):
        url = auth_users.make_action_url("https://example.com", "test-token", "approve")
        assert "test-token" in url
        assert "approve" in url
        assert "sig=" in url

    def test_make_action_url_reject(self, temp_db):
        url = auth_users.make_action_url("https://example.com", "test-token", "reject")
        assert "reject" in url

    def test_verify_sig_valid(self, temp_db):
        url = auth_users.make_action_url("https://example.com", "test-token", "approve")
        sig = url.split("sig=")[1]
        assert auth_users.verify_action_sig("test-token", "approve", sig)

    def test_verify_sig_invalid(self, temp_db):
        assert not auth_users.verify_action_sig("token", "approve", "invalid-sig")

    def test_verify_sig_wrong_action(self, temp_db):
        url = auth_users.make_action_url("https://example.com", "test-token", "approve")
        sig = url.split("sig=")[1]
        assert not auth_users.verify_action_sig("test-token", "reject", sig)


class TestHtpasswdMigration:
    def test_load_htpasswd_parses_file(self, temp_db):
        Path(temp_db["htpasswd_path"]).write_text(
            "user1:$apr1$hash1\nuser2:$apr1$hash2\n"
        )

        result = auth_users._load_htpasswd(temp_db["htpasswd_path"])
        assert "user1" in result
        assert "user2" in result
        assert result["user1"] == "$apr1$hash1"

    def test_load_htpasswd_ignores_comments(self, temp_db):
        Path(temp_db["htpasswd_path"]).write_text(
            "# This is a comment\nuser1:$apr1$hash1\n"
        )

        result = auth_users._load_htpasswd(temp_db["htpasswd_path"])
        assert len(result) == 1
        assert "user1" in result

    def test_load_htpasswd_returns_empty_for_missing_file(self, temp_db):
        result = auth_users._load_htpasswd("/nonexistent/path")
        assert result == {}
