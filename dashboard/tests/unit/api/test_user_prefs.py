"""Unit tests for user preferences (dark-mode persistence).

Covers both layers:
- The persistence helpers in ``auth_users`` (``get_user_preferences`` /
  ``set_user_preferences`` and the ``dark_mode`` schema column + migration).
- The two endpoints in ``api.user_prefs`` (``GET`` / ``POST
  /api/user/preferences``).

The root ``temp_auth_db`` fixture points ``auth_users.AUTH_DB_PATH`` at a fresh
per-test SQLite database, so each test starts from an empty users table.
"""

from unittest.mock import MagicMock, patch

import auth_users
import pytest

from api.user_prefs import (
    Preferences,
    get_preferences,
    router,
    update_preferences,
)


def make_mock_request():
    """Create a minimal mock FastAPI request."""
    return MagicMock()


# ---------------------------------------------------------------------------
# Persistence layer: schema + get/set helpers
# ---------------------------------------------------------------------------
class TestDarkModeSchema:
    def test_new_user_defaults_to_dark_mode(self, temp_auth_db):
        auth_users.create_user("alice", "pw")
        prefs = auth_users.get_user_preferences("alice")
        assert prefs == {"dark_mode": True}

    def test_users_table_has_dark_mode_column(self, temp_auth_db):
        auth_users.create_user("alice", "pw")
        with auth_users._get_db() as conn:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
        assert "dark_mode" in cols

    def test_migration_adds_column_to_legacy_table(self, temp_auth_db):
        # Simulate a pre-existing users table WITHOUT the dark_mode column.
        from smart_home_common.sqlite_helpers import open_connection

        conn = open_connection(auth_users.AUTH_DB_PATH)
        conn.execute("""
            CREATE TABLE users (
                id            TEXT PRIMARY KEY,
                username      TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                display_name  TEXT NOT NULL DEFAULT '',
                icon          TEXT DEFAULT NULL
            )
        """)
        conn.execute(
            "INSERT INTO users (id, username, password_hash) VALUES ('1', 'legacy', 'h')"
        )
        conn.commit()
        conn.close()

        # Opening via the schema-ensuring helper must run the ALTER migration.
        with auth_users._get_db() as conn:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
        assert "dark_mode" in cols
        # Existing rows get the default (dark).
        assert auth_users.get_user_preferences("legacy") == {"dark_mode": True}


class TestGetSetPreferences:
    def test_set_then_get_false(self, temp_auth_db):
        auth_users.create_user("alice", "pw")
        auth_users.set_user_preferences("alice", False)
        assert auth_users.get_user_preferences("alice") == {"dark_mode": False}

    def test_set_then_get_true(self, temp_auth_db):
        auth_users.create_user("alice", "pw")
        auth_users.set_user_preferences("alice", False)
        auth_users.set_user_preferences("alice", True)
        assert auth_users.get_user_preferences("alice") == {"dark_mode": True}

    def test_preferences_scoped_per_user(self, temp_auth_db):
        auth_users.create_user("alice", "pw")
        auth_users.create_user("bob", "pw")
        auth_users.set_user_preferences("alice", False)
        assert auth_users.get_user_preferences("alice") == {"dark_mode": False}
        # Bob keeps the default.
        assert auth_users.get_user_preferences("bob") == {"dark_mode": True}

    def test_get_unknown_user_returns_default(self, temp_auth_db):
        # No users created — defaults to dark so the UI always has a value.
        assert auth_users.get_user_preferences("ghost") == {"dark_mode": True}

    def test_set_unknown_user_raises(self, temp_auth_db):
        auth_users.create_user("alice", "pw")  # ensure table exists
        with pytest.raises(ValueError):
            auth_users.set_user_preferences("ghost", False)


# ---------------------------------------------------------------------------
# GET /api/user/preferences
# ---------------------------------------------------------------------------
class TestGetPreferencesEndpoint:
    def test_returns_default_dark(self, temp_auth_db):
        auth_users.create_user("alice", "pw")
        request = make_mock_request()
        with patch("api.user_prefs.require_authenticated", return_value="alice"):
            result = get_preferences(request)
        assert result == {"dark_mode": True}

    def test_returns_stored_value(self, temp_auth_db):
        auth_users.create_user("alice", "pw")
        auth_users.set_user_preferences("alice", False)
        request = make_mock_request()
        with patch("api.user_prefs.require_authenticated", return_value="alice"):
            result = get_preferences(request)
        assert result == {"dark_mode": False}

    def test_requires_authentication(self, temp_auth_db):
        from fastapi import HTTPException

        request = make_mock_request()
        with patch(
            "api.user_prefs.require_authenticated",
            side_effect=HTTPException(status_code=401, detail="Not authenticated"),
        ):
            with pytest.raises(HTTPException) as exc:
                get_preferences(request)
            assert exc.value.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/user/preferences
# ---------------------------------------------------------------------------
class TestUpdatePreferencesEndpoint:
    def test_persists_and_returns_new_value(self, temp_auth_db):
        auth_users.create_user("alice", "pw")
        request = make_mock_request()
        body = Preferences(dark_mode=False)
        with patch("api.user_prefs.require_authenticated", return_value="alice"):
            result = update_preferences(body, request)
        assert result == {"dark_mode": False}
        # Verify it was actually written to the DB.
        assert auth_users.get_user_preferences("alice") == {"dark_mode": False}

    def test_toggle_back_to_true(self, temp_auth_db):
        auth_users.create_user("alice", "pw")
        request = make_mock_request()
        with patch("api.user_prefs.require_authenticated", return_value="alice"):
            update_preferences(Preferences(dark_mode=False), request)
            result = update_preferences(Preferences(dark_mode=True), request)
        assert result == {"dark_mode": True}

    def test_requires_authentication(self, temp_auth_db):
        from fastapi import HTTPException

        request = make_mock_request()
        body = Preferences(dark_mode=False)
        with patch(
            "api.user_prefs.require_authenticated",
            side_effect=HTTPException(status_code=401, detail="Not authenticated"),
        ):
            with pytest.raises(HTTPException) as exc:
                update_preferences(body, request)
            assert exc.value.status_code == 401


# ---------------------------------------------------------------------------
# Preferences model validation
# ---------------------------------------------------------------------------
class TestPreferencesModel:
    def test_requires_dark_mode_field(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            Preferences()

    def test_accepts_bool(self):
        assert Preferences(dark_mode=True).dark_mode is True
        assert Preferences(dark_mode=False).dark_mode is False


# ---------------------------------------------------------------------------
# Router wiring
# ---------------------------------------------------------------------------
class TestRouterWiring:
    def test_routes_registered(self):
        paths = {route.path for route in router.routes}
        assert "/api/user/preferences" in paths

    def test_both_methods_present(self):
        methods = set()
        for route in router.routes:
            if route.path == "/api/user/preferences":
                methods |= route.methods
        assert "GET" in methods
        assert "POST" in methods
