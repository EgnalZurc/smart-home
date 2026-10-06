"""Unit tests for auth profile system with level-based permissions."""

import os
import sys
import tempfile
from unittest.mock import MagicMock, patch

import pytest

# Mock passlib before any import that triggers auth.py
_mock_passlib = MagicMock()
_mock_passlib.hash.apr_md5_crypt.verify.return_value = True
sys.modules.setdefault("passlib", _mock_passlib)
sys.modules.setdefault("passlib.hash", _mock_passlib.hash)

# Mock python-multipart before auth_routes import (needed for FastAPI Form)
_mock_multipart = MagicMock()
sys.modules.setdefault("multipart", _mock_multipart)
sys.modules.setdefault("python_multipart", _mock_multipart)


def _tmp_db_path(tmp_dir):
    """Return a writable temporary SQLite path."""
    return os.path.join(tmp_dir, "test_auth.db")


# ── Built-in Profiles ─────────────────────────────────────────────────────────


class TestBuiltinProfiles:
    def test_super_has_level_0(self):
        import user_profiles

        assert user_profiles.BUILTIN_PROFILES["SUPER"]["level"] == 0

    def test_familia_all_has_level_1(self):
        import user_profiles

        assert user_profiles.BUILTIN_PROFILES["FAMILIA_ALL"]["level"] == 1

    def test_familia_principal_has_level_1(self):
        import user_profiles

        assert user_profiles.BUILTIN_PROFILES["FAMILIA_PRINCIPAL"]["level"] == 1

    def test_gamer_has_level_3(self):
        import user_profiles

        assert user_profiles.BUILTIN_PROFILES["GAMER"]["level"] == 3

    def test_default_profile_is_familia_principal(self):
        import user_profiles

        assert user_profiles._DEFAULT_PROFILE == "FAMILIA_PRINCIPAL"

    def test_builtin_profiles_marked_as_builtin(self):
        import user_profiles

        for name, profile in user_profiles.BUILTIN_PROFILES.items():
            assert profile.get("builtin") is True, f"{name} should be marked builtin"


# ── APP_REGISTRY ──────────────────────────────────────────────────────────────


class TestAppRegistry:
    def test_ac_has_view_level_1(self):
        import user_profiles

        ac = next(a for a in user_profiles.APP_REGISTRY if a["key"] == "ac")
        assert ac["view_level"] == 1

    def test_zigbee_requires_level_0(self):
        import user_profiles

        zigbee = next(a for a in user_profiles.APP_REGISTRY if a["key"] == "zigbee")
        assert zigbee["view_level"] == 0

    def test_passwords_requires_level_0(self):
        import user_profiles

        passwords = next(
            a for a in user_profiles.APP_REGISTRY if a["key"] == "passwords"
        )
        assert passwords["view_level"] == 0

    def test_valheim_has_view_level_3(self):
        """Valheim should be visible to GAMER (level 3)."""
        import user_profiles

        valheim = next(a for a in user_profiles.APP_REGISTRY if a["key"] == "valheim")
        assert valheim["view_level"] == 3

    def test_portfolio_requires_level_0(self):
        import user_profiles

        portfolio = next(
            a for a in user_profiles.APP_REGISTRY if a["key"] == "portfolio"
        )
        assert portfolio["view_level"] == 0

    def test_all_keys_unique(self):
        import user_profiles

        keys = [a["key"] for a in user_profiles.APP_REGISTRY]
        assert len(keys) == len(set(keys))


# ── Permission Levels ─────────────────────────────────────────────────────────


class TestPermissionLevels:
    def test_level_0_sees_everything(self):
        """Level 0 (SUPER) should see all apps."""
        import user_profiles

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(user_profiles, "AUTH_DB_PATH", _tmp_db_path(tmp)):
                # Simulate level 0 user
                with patch.object(user_profiles, "get_effective_level", return_value=0):
                    apps = user_profiles.app_permissions("admin")
        app_keys = [a["key"] for a in apps]
        assert "zigbee" in app_keys
        assert "passwords" in app_keys
        assert "portfolio" in app_keys
        assert "valheim" in app_keys
        assert "ac" in app_keys

    def test_level_1_sees_standard_apps(self):
        """Level 1 (FAMILIA) should see standard apps but not admin-only."""
        import user_profiles

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(user_profiles, "AUTH_DB_PATH", _tmp_db_path(tmp)):
                with patch.object(user_profiles, "get_effective_level", return_value=1):
                    apps = user_profiles.app_permissions("family")
        app_keys = [a["key"] for a in apps]
        assert "ac" in app_keys
        assert "vacaciones" in app_keys
        assert "valheim" in app_keys  # level 3, so level 1 can see it
        assert "zigbee" not in app_keys  # level 0 only
        assert "passwords" not in app_keys  # level 0 only

    def test_level_3_sees_only_gamer_apps(self):
        """Level 3 (GAMER) should only see valheim."""
        import user_profiles

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(user_profiles, "AUTH_DB_PATH", _tmp_db_path(tmp)):
                with patch.object(user_profiles, "get_effective_level", return_value=3):
                    apps = user_profiles.app_permissions("gamer")
        app_keys = [a["key"] for a in apps]
        assert "valheim" in app_keys
        assert "ac" not in app_keys  # level 1 only
        assert "zigbee" not in app_keys  # level 0 only


# ── Multi-Profile Support ─────────────────────────────────────────────────────


class TestMultiProfile:
    def test_set_and_get_multiple_profiles(self):
        import user_profiles

        with tempfile.TemporaryDirectory() as tmp:
            db_path = _tmp_db_path(tmp)
            with patch.object(user_profiles, "AUTH_DB_PATH", db_path):
                user_profiles.set_user_profiles("testuser", ["GAMER", "FAMILIA_ALL"])
                profiles = user_profiles.get_user_profiles("testuser")
                assert "GAMER" in profiles
                assert "FAMILIA_ALL" in profiles

    def test_effective_level_is_minimum(self):
        """Effective level should be the minimum (most permissive) across profiles."""
        import user_profiles

        with tempfile.TemporaryDirectory() as tmp:
            db_path = _tmp_db_path(tmp)
            with patch.object(user_profiles, "AUTH_DB_PATH", db_path):
                # GAMER=3, FAMILIA_ALL=1 → effective should be 1
                user_profiles.set_user_profiles("testuser", ["GAMER", "FAMILIA_ALL"])
                level = user_profiles.get_effective_level("testuser")
                assert level == 1

    def test_add_profile_to_user(self):
        import user_profiles

        with tempfile.TemporaryDirectory() as tmp:
            db_path = _tmp_db_path(tmp)
            with patch.object(user_profiles, "AUTH_DB_PATH", db_path):
                user_profiles.set_user_profiles("testuser", ["GAMER"])
                user_profiles.add_user_profile("testuser", "FAMILIA_PRINCIPAL")
                profiles = user_profiles.get_user_profiles("testuser")
                assert "GAMER" in profiles
                assert "FAMILIA_PRINCIPAL" in profiles

    def test_remove_profile_from_user(self):
        import user_profiles

        with tempfile.TemporaryDirectory() as tmp:
            db_path = _tmp_db_path(tmp)
            with patch.object(user_profiles, "AUTH_DB_PATH", db_path):
                user_profiles.set_user_profiles("testuser", ["GAMER", "FAMILIA_ALL"])
                user_profiles.remove_user_profile("testuser", "GAMER")
                profiles = user_profiles.get_user_profiles("testuser")
                assert "GAMER" not in profiles
                assert "FAMILIA_ALL" in profiles

    def test_get_default_for_unknown_user(self):
        import user_profiles

        with tempfile.TemporaryDirectory() as tmp:
            db_path = _tmp_db_path(tmp)
            with patch.object(user_profiles, "AUTH_DB_PATH", db_path):
                profiles = user_profiles.get_user_profiles("unknownuser")
                assert profiles == ["FAMILIA_PRINCIPAL"]


# ── is_super helper ───────────────────────────────────────────────────────────


class TestIsSuperHelper:
    def test_is_super_returns_true_for_level_0(self):
        import user_profiles

        with tempfile.TemporaryDirectory() as tmp:
            db_path = _tmp_db_path(tmp)
            with patch.object(user_profiles, "AUTH_DB_PATH", db_path):
                user_profiles.set_user_profiles("admin", ["SUPER"])
                assert user_profiles.is_super("admin") is True

    def test_is_super_returns_false_for_level_1(self):
        import user_profiles

        with tempfile.TemporaryDirectory() as tmp:
            db_path = _tmp_db_path(tmp)
            with patch.object(user_profiles, "AUTH_DB_PATH", db_path):
                user_profiles.set_user_profiles("family", ["FAMILIA_ALL"])
                assert user_profiles.is_super("family") is False

    def test_is_super_returns_false_for_gamer(self):
        import user_profiles

        with tempfile.TemporaryDirectory() as tmp:
            db_path = _tmp_db_path(tmp)
            with patch.object(user_profiles, "AUTH_DB_PATH", db_path):
                user_profiles.set_user_profiles("gamer", ["GAMER"])
                assert user_profiles.is_super("gamer") is False


# ── Custom Profiles ───────────────────────────────────────────────────────────


class TestCustomProfiles:
    def test_create_custom_profile(self):
        import user_profiles

        with tempfile.TemporaryDirectory() as tmp:
            db_path = _tmp_db_path(tmp)
            with patch.object(user_profiles, "AUTH_DB_PATH", db_path):
                user_profiles.create_profile("CUSTOM", 2, "Test profile")
                all_profiles = user_profiles.get_all_profiles()
                assert "CUSTOM" in all_profiles
                assert all_profiles["CUSTOM"]["level"] == 2
                assert all_profiles["CUSTOM"]["builtin"] is False

    def test_cannot_create_builtin_name(self):
        import user_profiles

        with tempfile.TemporaryDirectory() as tmp:
            db_path = _tmp_db_path(tmp)
            with patch.object(user_profiles, "AUTH_DB_PATH", db_path):
                with pytest.raises(ValueError):
                    user_profiles.create_profile("SUPER", 1, "Cannot override")

    def test_delete_custom_profile(self):
        import user_profiles

        with tempfile.TemporaryDirectory() as tmp:
            db_path = _tmp_db_path(tmp)
            with patch.object(user_profiles, "AUTH_DB_PATH", db_path):
                user_profiles.create_profile("TODELETE", 2, "Will be deleted")
                user_profiles.delete_profile("TODELETE")
                all_profiles = user_profiles.get_all_profiles()
                assert "TODELETE" not in all_profiles

    def test_cannot_delete_builtin(self):
        import user_profiles

        with tempfile.TemporaryDirectory() as tmp:
            db_path = _tmp_db_path(tmp)
            with patch.object(user_profiles, "AUTH_DB_PATH", db_path):
                with pytest.raises(ValueError):
                    user_profiles.delete_profile("SUPER")

    def test_update_custom_profile(self):
        import user_profiles

        with tempfile.TemporaryDirectory() as tmp:
            db_path = _tmp_db_path(tmp)
            with patch.object(user_profiles, "AUTH_DB_PATH", db_path):
                user_profiles.create_profile("TOUPDATE", 2, "Original")
                user_profiles.update_profile("TOUPDATE", level=1, description="Updated")
                all_profiles = user_profiles.get_all_profiles()
                assert all_profiles["TOUPDATE"]["level"] == 1
                assert all_profiles["TOUPDATE"]["description"] == "Updated"

    def test_cannot_update_builtin(self):
        import user_profiles

        with tempfile.TemporaryDirectory() as tmp:
            db_path = _tmp_db_path(tmp)
            with patch.object(user_profiles, "AUTH_DB_PATH", db_path):
                with pytest.raises(ValueError):
                    user_profiles.update_profile("SUPER", level=3)


# ── Legacy Compatibility ──────────────────────────────────────────────────────


class TestLegacyCompatibility:
    def test_set_profile_single(self):
        """Legacy set_profile should work with single profile."""
        import user_profiles

        with tempfile.TemporaryDirectory() as tmp:
            db_path = _tmp_db_path(tmp)
            with patch.object(user_profiles, "AUTH_DB_PATH", db_path):
                user_profiles.set_profile("testuser", "GAMER")
                profiles = user_profiles.get_user_profiles("testuser")
                assert profiles == ["GAMER"]

    def test_get_profile_returns_dict(self):
        """Legacy get_profile should return a dict with level info."""
        import user_profiles

        with tempfile.TemporaryDirectory() as tmp:
            db_path = _tmp_db_path(tmp)
            with patch.object(user_profiles, "AUTH_DB_PATH", db_path):
                user_profiles.set_user_profiles("testuser", ["SUPER"])
                profile = user_profiles.get_profile("testuser")
                assert "level" in profile
                assert profile["level"] == 0
                assert profile["show_config_apps"] is True  # level 0 only

    def test_profiles_alias_exists(self):
        """PROFILES alias should exist for backward compatibility."""
        import user_profiles

        assert hasattr(user_profiles, "PROFILES")
        assert "SUPER" in user_profiles.PROFILES


# ── _require_super in auth_routes ─────────────────────────────────────────────


class TestRequireSuperFunction:
    def test_raises_401_when_no_user(self):
        import auth as auth_core
        from api.auth_routes import _require_super
        from fastapi import HTTPException

        mock_request = MagicMock()
        with patch.object(auth_core, "get_current_user", return_value=None):
            with pytest.raises(HTTPException) as exc_info:
                _require_super(mock_request)
        assert exc_info.value.status_code == 401

    def test_raises_403_when_not_level_0(self):
        import auth as auth_core
        import user_profiles
        from api.auth_routes import _require_super
        from fastapi import HTTPException

        mock_request = MagicMock()
        with patch.object(auth_core, "get_current_user", return_value="virchi"):
            with patch.object(user_profiles, "is_super", return_value=False):
                with pytest.raises(HTTPException) as exc_info:
                    _require_super(mock_request)
        assert exc_info.value.status_code == 403

    def test_returns_username_when_super(self):
        import auth as auth_core
        import user_profiles
        from api.auth_routes import _require_super

        mock_request = MagicMock()
        with patch.object(auth_core, "get_current_user", return_value="egnal"):
            with patch.object(user_profiles, "is_super", return_value=True):
                result = _require_super(mock_request)
        assert result == "egnal"
