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
    WidgetConfig,
    WidgetConfigPayload,
    get_preferences,
    get_widget_config,
    router,
    update_preferences,
    update_widget_config,
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
            cols = {
                row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()
            }
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
            cols = {
                row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()
            }
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
    @pytest.mark.asyncio
    async def test_returns_default_dark(self, temp_auth_db):
        auth_users.create_user("alice", "pw")
        request = make_mock_request()
        with patch("api.user_prefs.require_authenticated", return_value="alice"):
            result = await get_preferences(request)
        assert result == {"dark_mode": True}

    @pytest.mark.asyncio

    async def test_returns_stored_value(self, temp_auth_db):
        auth_users.create_user("alice", "pw")
        auth_users.set_user_preferences("alice", False)
        request = make_mock_request()
        with patch("api.user_prefs.require_authenticated", return_value="alice"):
            result = await get_preferences(request)
        assert result == {"dark_mode": False}

    @pytest.mark.asyncio

    async def test_requires_authentication(self, temp_auth_db):
        from fastapi import HTTPException

        request = make_mock_request()
        with patch(
            "api.user_prefs.require_authenticated",
            side_effect=HTTPException(status_code=401, detail="Not authenticated"),
        ):
            with pytest.raises(HTTPException) as exc:
                await get_preferences(request)
            assert exc.value.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/user/preferences
# ---------------------------------------------------------------------------
class TestUpdatePreferencesEndpoint:
    @pytest.mark.asyncio
    async def test_persists_and_returns_new_value(self, temp_auth_db):
        auth_users.create_user("alice", "pw")
        request = make_mock_request()
        body = Preferences(dark_mode=False)
        with patch("api.user_prefs.require_authenticated", return_value="alice"):
            result = await update_preferences(body, request)
        assert result == {"dark_mode": False}
        # Verify it was actually written to the DB.
        assert auth_users.get_user_preferences("alice") == {"dark_mode": False}

    @pytest.mark.asyncio

    async def test_toggle_back_to_true(self, temp_auth_db):
        auth_users.create_user("alice", "pw")
        request = make_mock_request()
        with patch("api.user_prefs.require_authenticated", return_value="alice"):
            await update_preferences(Preferences(dark_mode=False), request)
            result = await update_preferences(Preferences(dark_mode=True), request)
        assert result == {"dark_mode": True}

    @pytest.mark.asyncio

    async def test_requires_authentication(self, temp_auth_db):
        from fastapi import HTTPException

        request = make_mock_request()
        body = Preferences(dark_mode=False)
        with patch(
            "api.user_prefs.require_authenticated",
            side_effect=HTTPException(status_code=401, detail="Not authenticated"),
        ):
            with pytest.raises(HTTPException) as exc:
                await update_preferences(body, request)
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


# ═══════════════════════════════════════════════════════════════════════════
# Widget configuration
# ═══════════════════════════════════════════════════════════════════════════


# ---------------------------------------------------------------------------
# Persistence layer: schema + get/set helpers
# ---------------------------------------------------------------------------
class TestWidgetConfigSchema:
    def test_table_created(self, temp_auth_db):
        auth_users.create_user("alice", "pw")
        with auth_users._get_db() as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        assert "user_widget_config" in tables

    def test_table_has_expected_columns(self, temp_auth_db):
        auth_users.create_user("alice", "pw")
        with auth_users._get_db() as conn:
            cols = {
                row[1]
                for row in conn.execute(
                    "PRAGMA table_info(user_widget_config)"
                ).fetchall()
            }
        assert cols == {
            "username",
            "widget_id",
            "visible",
            "position",
            "size",
            "custom_settings",
        }

    def test_migration_adds_table_to_legacy_db(self, temp_auth_db):
        # Simulate a pre-existing DB that only had the users table.
        from smart_home_common.sqlite_helpers import open_connection

        conn = open_connection(auth_users.AUTH_DB_PATH)
        conn.execute("""
            CREATE TABLE users (
                id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL
            )
        """)
        conn.commit()
        conn.close()
        # Opening via the schema-ensuring helper must create the new table.
        with auth_users._get_db() as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        assert "user_widget_config" in tables


class TestGetSetWidgetConfig:
    def test_empty_by_default(self, temp_auth_db):
        auth_users.create_user("alice", "pw")
        assert auth_users.get_widget_config("alice") == []

    def test_set_then_get_roundtrip(self, temp_auth_db):
        auth_users.create_user("alice", "pw")
        auth_users.set_widget_config(
            "alice",
            [
                {
                    "widget_id": "ac",
                    "visible": True,
                    "order": 0,
                    "size": "lg",
                    "custom_settings": {"foo": "bar"},
                },
                {"widget_id": "casita", "visible": False, "order": 1},
            ],
        )
        cfg = auth_users.get_widget_config("alice")
        assert cfg == [
            {
                "widget_id": "ac",
                "visible": True,
                "order": 0,
                "size": "lg",
                "custom_settings": {"foo": "bar"},
            },
            {
                "widget_id": "casita",
                "visible": False,
                "order": 1,
                "size": "md",
                "custom_settings": {},
            },
        ]

    def test_returned_ordered_by_position(self, temp_auth_db):
        auth_users.create_user("alice", "pw")
        auth_users.set_widget_config(
            "alice",
            [
                {"widget_id": "z", "order": 5},
                {"widget_id": "a", "order": 1},
                {"widget_id": "m", "order": 3},
            ],
        )
        ids = [w["widget_id"] for w in auth_users.get_widget_config("alice")]
        assert ids == ["a", "m", "z"]

    def test_order_defaults_to_list_index(self, temp_auth_db):
        auth_users.create_user("alice", "pw")
        auth_users.set_widget_config(
            "alice",
            [{"widget_id": "first"}, {"widget_id": "second"}],
        )
        cfg = auth_users.get_widget_config("alice")
        assert cfg[0]["widget_id"] == "first" and cfg[0]["order"] == 0
        assert cfg[1]["widget_id"] == "second" and cfg[1]["order"] == 1

    def test_set_replaces_previous_layout(self, temp_auth_db):
        auth_users.create_user("alice", "pw")
        auth_users.set_widget_config("alice", [{"widget_id": "old"}])
        auth_users.set_widget_config("alice", [{"widget_id": "new"}])
        ids = [w["widget_id"] for w in auth_users.get_widget_config("alice")]
        assert ids == ["new"]

    def test_scoped_per_user(self, temp_auth_db):
        auth_users.create_user("alice", "pw")
        auth_users.create_user("bob", "pw")
        auth_users.set_widget_config("alice", [{"widget_id": "ac", "visible": False}])
        assert auth_users.get_widget_config("bob") == []
        assert auth_users.get_widget_config("alice")[0]["visible"] is False

    def test_empty_list_clears_layout(self, temp_auth_db):
        auth_users.create_user("alice", "pw")
        auth_users.set_widget_config("alice", [{"widget_id": "ac"}])
        auth_users.set_widget_config("alice", [])
        assert auth_users.get_widget_config("alice") == []

    def test_invalid_size_raises(self, temp_auth_db):
        auth_users.create_user("alice", "pw")
        with pytest.raises(ValueError, match="Invalid size"):
            auth_users.set_widget_config("alice", [{"widget_id": "ac", "size": "xl"}])

    def test_missing_widget_id_raises(self, temp_auth_db):
        auth_users.create_user("alice", "pw")
        with pytest.raises(ValueError, match="widget_id"):
            auth_users.set_widget_config("alice", [{"visible": True}])

    def test_duplicate_widget_id_raises(self, temp_auth_db):
        auth_users.create_user("alice", "pw")
        with pytest.raises(ValueError, match="Duplicate"):
            auth_users.set_widget_config(
                "alice", [{"widget_id": "ac"}, {"widget_id": "ac"}]
            )

    def test_bad_item_leaves_existing_layout_intact(self, temp_auth_db):
        # Validation happens before any DB write, so a bad batch must not wipe
        # the user's previously saved layout.
        auth_users.create_user("alice", "pw")
        auth_users.set_widget_config("alice", [{"widget_id": "ac"}])
        with pytest.raises(ValueError):
            auth_users.set_widget_config(
                "alice", [{"widget_id": "casita", "size": "huge"}]
            )
        ids = [w["widget_id"] for w in auth_users.get_widget_config("alice")]
        assert ids == ["ac"]


# ---------------------------------------------------------------------------
# GET /api/user/widget-config
# ---------------------------------------------------------------------------
class TestGetWidgetConfigEndpoint:
    @pytest.mark.asyncio
    async def test_returns_empty_list_by_default(self, temp_auth_db):
        auth_users.create_user("alice", "pw")
        request = make_mock_request()
        with patch("api.user_prefs.require_authenticated", return_value="alice"):
            result = await get_widget_config(request)
        assert result == {"widgets": []}

    @pytest.mark.asyncio

    async def test_returns_stored_layout(self, temp_auth_db):
        auth_users.create_user("alice", "pw")
        auth_users.set_widget_config("alice", [{"widget_id": "ac", "size": "lg"}])
        request = make_mock_request()
        with patch("api.user_prefs.require_authenticated", return_value="alice"):
            result = await get_widget_config(request)
        assert result["widgets"][0]["widget_id"] == "ac"
        assert result["widgets"][0]["size"] == "lg"

    @pytest.mark.asyncio

    async def test_requires_authentication(self, temp_auth_db):
        from fastapi import HTTPException

        request = make_mock_request()
        with patch(
            "api.user_prefs.require_authenticated",
            side_effect=HTTPException(status_code=401, detail="Not authenticated"),
        ):
            with pytest.raises(HTTPException) as exc:
                await get_widget_config(request)
            assert exc.value.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/user/widget-config
# ---------------------------------------------------------------------------
class TestUpdateWidgetConfigEndpoint:
    @pytest.mark.asyncio
    async def test_persists_and_returns_layout(self, temp_auth_db):
        auth_users.create_user("alice", "pw")
        request = make_mock_request()
        payload = WidgetConfigPayload(
            widgets=[
                WidgetConfig(widget_id="ac", visible=True, order=0, size="lg"),
                WidgetConfig(widget_id="casita", visible=False, order=1),
            ]
        )
        with patch("api.user_prefs.require_authenticated", return_value="alice"):
            result = await update_widget_config(payload, request)
        ids = [w["widget_id"] for w in result["widgets"]]
        assert ids == ["ac", "casita"]
        # Verify it was actually written.
        assert auth_users.get_widget_config("alice") == result["widgets"]

    @pytest.mark.asyncio

    async def test_invalid_size_returns_422(self, temp_auth_db):
        from fastapi import HTTPException

        auth_users.create_user("alice", "pw")
        request = make_mock_request()
        payload = WidgetConfigPayload(widgets=[WidgetConfig(widget_id="ac", size="xl")])
        with patch("api.user_prefs.require_authenticated", return_value="alice"):
            with pytest.raises(HTTPException) as exc:
                await update_widget_config(payload, request)
            assert exc.value.status_code == 422

    @pytest.mark.asyncio

    async def test_requires_authentication(self, temp_auth_db):
        from fastapi import HTTPException

        request = make_mock_request()
        payload = WidgetConfigPayload(widgets=[WidgetConfig(widget_id="ac")])
        with patch(
            "api.user_prefs.require_authenticated",
            side_effect=HTTPException(status_code=401, detail="Not authenticated"),
        ):
            with pytest.raises(HTTPException) as exc:
                await update_widget_config(payload, request)
            assert exc.value.status_code == 401


# ---------------------------------------------------------------------------
# Widget config model validation
# ---------------------------------------------------------------------------
class TestWidgetConfigModel:
    def test_requires_widget_id(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            WidgetConfig()

    def test_rejects_empty_widget_id(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            WidgetConfig(widget_id="")

    def test_defaults(self):
        w = WidgetConfig(widget_id="ac")
        assert w.visible is True
        assert w.order == 0
        assert w.size == "md"
        assert w.custom_settings == {}

    def test_payload_accepts_empty_widget_list(self):
        payload = WidgetConfigPayload(widgets=[])
        assert payload.widgets == []


# ---------------------------------------------------------------------------
# Router wiring (widget-config)
# ---------------------------------------------------------------------------
class TestWidgetConfigRouterWiring:
    def test_route_registered(self):
        paths = {route.path for route in router.routes}
        assert "/api/user/widget-config" in paths

    def test_both_methods_present(self):
        methods = set()
        for route in router.routes:
            if route.path == "/api/user/widget-config":
                methods |= route.methods
        assert "GET" in methods
        assert "POST" in methods
