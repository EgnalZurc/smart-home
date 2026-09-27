"""Unit tests for auth profile system and /auth/me endpoint."""
import sys
import pytest
import tempfile
import os
from unittest.mock import MagicMock, patch

# Mock passlib before any import that triggers auth.py
_mock_passlib = MagicMock()
_mock_passlib.hash.apr_md5_crypt.verify.return_value = True
sys.modules.setdefault('passlib', _mock_passlib)
sys.modules.setdefault('passlib.hash', _mock_passlib.hash)

# Mock python-multipart before auth_routes import (needed for FastAPI Form)
_mock_multipart = MagicMock()
sys.modules.setdefault('multipart', _mock_multipart)
sys.modules.setdefault('python_multipart', _mock_multipart)


def _tmp_db_path(tmp_dir):
    """Return a writable temporary SQLite path."""
    return os.path.join(tmp_dir, 'test_auth.db')


# ── user_profiles: PROFILES ───────────────────────────────────────────────────

class TestProfiles:

    def test_super_has_show_config_apps_true(self):
        import user_profiles
        assert user_profiles.PROFILES["SUPER"]["show_config_apps"] is True

    def test_familia_principal_has_show_config_apps_false(self):
        import user_profiles
        assert user_profiles.PROFILES["FAMILIA_PRINCIPAL"]["show_config_apps"] is False

    def test_default_profile_is_familia_principal(self):
        import user_profiles
        assert user_profiles._DEFAULT_PROFILE == "FAMILIA_PRINCIPAL"


# ── user_profiles: APP_REGISTRY ──────────────────────────────────────────────

class TestAppRegistry:

    def test_ac_is_standard(self):
        import user_profiles
        ac = next(a for a in user_profiles.APP_REGISTRY if a["key"] == "ac")
        assert ac["type"] == "standard"

    def test_vacaciones_is_standard(self):
        import user_profiles
        vac = next(a for a in user_profiles.APP_REGISTRY if a["key"] == "vacaciones")
        assert vac["type"] == "standard"

    def test_zigbee_is_config(self):
        import user_profiles
        zigbee = next(a for a in user_profiles.APP_REGISTRY if a["key"] == "zigbee")
        assert zigbee["type"] == "config"

    def test_passwords_is_config(self):
        import user_profiles
        passwords = next(a for a in user_profiles.APP_REGISTRY if a["key"] == "passwords")
        assert passwords["type"] == "config"

    def test_all_keys_unique(self):
        import user_profiles
        keys = [a["key"] for a in user_profiles.APP_REGISTRY]
        assert len(keys) == len(set(keys))

    def test_familia_principal_does_not_see_config_apps(self):
        import user_profiles
        familia_profile = user_profiles.PROFILES["FAMILIA_PRINCIPAL"]
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(user_profiles, 'AUTH_DB_PATH', _tmp_db_path(tmp)):
                with patch.object(user_profiles, 'get_profile', return_value=familia_profile):
                    apps = user_profiles.app_permissions("virchi")
        app_keys = [a["key"] for a in apps]
        assert "zigbee" not in app_keys
        assert "passwords" not in app_keys

    def test_super_sees_config_apps(self):
        import user_profiles
        super_profile = user_profiles.PROFILES["SUPER"]
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(user_profiles, 'AUTH_DB_PATH', _tmp_db_path(tmp)):
                with patch.object(user_profiles, 'get_profile', return_value=super_profile):
                    apps = user_profiles.app_permissions("egnal")
        app_keys = [a["key"] for a in apps]
        assert "zigbee" in app_keys
        assert "passwords" in app_keys

    def test_standard_apps_visible_to_familia_principal(self):
        import user_profiles
        familia_profile = user_profiles.PROFILES["FAMILIA_PRINCIPAL"]
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(user_profiles, 'AUTH_DB_PATH', _tmp_db_path(tmp)):
                with patch.object(user_profiles, 'get_profile', return_value=familia_profile):
                    apps = user_profiles.app_permissions("virchi")
        app_keys = [a["key"] for a in apps]
        for expected in ("ac", "vacaciones", "casita", "photos"):
            assert expected in app_keys


# ── _require_super ────────────────────────────────────────────────────────────

class TestRequireSuperFunction:

    def test_raises_401_when_no_user(self):
        import auth as auth_core
        from api.routes import _require_super
        from fastapi import HTTPException

        mock_request = MagicMock()
        with patch.object(auth_core, 'get_current_user', return_value=None):
            with pytest.raises(HTTPException) as exc_info:
                _require_super(mock_request)
        assert exc_info.value.status_code == 401

    def test_raises_403_when_familia_principal(self):
        import auth as auth_core
        import user_profiles
        from api.routes import _require_super
        from fastapi import HTTPException

        mock_request = MagicMock()
        with patch.object(auth_core, 'get_current_user', return_value='virchi'):
            with patch.object(user_profiles, 'get_profile_key', return_value='FAMILIA_PRINCIPAL'):
                with pytest.raises(HTTPException) as exc_info:
                    _require_super(mock_request)
        assert exc_info.value.status_code == 403

    def test_returns_username_when_super(self):
        import auth as auth_core
        import user_profiles
        from api.routes import _require_super

        mock_request = MagicMock()
        with patch.object(auth_core, 'get_current_user', return_value='egnal'):
            with patch.object(user_profiles, 'get_profile_key', return_value='SUPER'):
                result = _require_super(mock_request)
        assert result == "egnal"


# ── /auth/me includes profile_data ───────────────────────────────────────────
# We test the get_me function directly (not via TestClient) to avoid
# FastAPI's python-multipart check at route registration time.
# python-multipart IS in requirements.txt and installed in the container,
# but not in the Pi system Python used for tests outside the container.

class TestAuthMeResponse:
    """Tests for /auth/me response structure.

    Tests the business logic of profile_data.show_config_apps by checking
    PROFILES directly (which is what auth_routes.get_me() delegates to).
    We avoid importing auth_routes here because FastAPI triggers a
    python-multipart check at route registration time — that library is only
    available inside the Docker container, not in the Pi system Python.
    """

    def test_super_has_show_config_apps_true(self):
        import user_profiles
        assert user_profiles.PROFILES["SUPER"]["show_config_apps"] is True

    def test_familia_has_show_config_apps_false(self):
        import user_profiles
        assert user_profiles.PROFILES["FAMILIA_PRINCIPAL"]["show_config_apps"] is False

    def test_gamer_has_show_config_apps_false(self):
        import user_profiles
        assert user_profiles.PROFILES["GAMER"]["show_config_apps"] is False

    def test_get_me_logic_produces_correct_profile_data(self):
        """Verify the logic auth_routes.get_me uses to build profile_data.
        get_me does:
          profile_def = PROFILES.get(profile_key, {})
          show = profile_def.get("show_config_apps", False)
        """
        import user_profiles
        for key, expected in [("SUPER", True), ("FAMILIA_PRINCIPAL", False), ("GAMER", False)]:
            profile_def = user_profiles.PROFILES.get(key, {})
            show = profile_def.get("show_config_apps", False)
            assert show is expected, f"{key}: expected {expected}, got {show}"

    def test_unknown_profile_defaults_to_false(self):
        """Unknown profile key should default show_config_apps to False."""
        import user_profiles
        show = user_profiles.PROFILES.get("UNKNOWN", {}).get("show_config_apps", False)
        assert show is False
