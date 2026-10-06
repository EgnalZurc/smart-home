"""Unit tests for auth profile system with ID-based profiles."""

import os
import sys
import tempfile
from unittest.mock import MagicMock

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

        super_id = "super-0000-0000-0000-000000000000"
        assert user_profiles.BUILTIN_PROFILES[super_id]["level"] == 0

    def test_familia_all_has_level_1(self):
        import user_profiles

        fam_id = "familia-all-0000-0000-000000000001"
        assert user_profiles.BUILTIN_PROFILES[fam_id]["level"] == 1

    def test_familia_principal_has_level_1(self):
        import user_profiles

        fam_id = "familia-principal-0000-000000000002"
        assert user_profiles.BUILTIN_PROFILES[fam_id]["level"] == 1

    def test_gamer_has_level_3(self):
        import user_profiles

        gamer_id = "gamer-0000-0000-0000-000000000003"
        assert user_profiles.BUILTIN_PROFILES[gamer_id]["level"] == 3

    def testDEFAULT_PROFILE_ID_is_familia_principal(self):
        import user_profiles

        assert (
            user_profiles.DEFAULT_PROFILE_ID == "familia-principal-0000-000000000002"
        )

    def test_only_super_is_protected(self):
        """Only SUPER should be protected, others can be edited."""
        import user_profiles

        super_id = "super-0000-0000-0000-000000000000"
        assert user_profiles.BUILTIN_PROFILES[super_id]["protected"] is True

        # Other profiles can be edited (protected=False)
        for pid, profile in user_profiles.BUILTIN_PROFILES.items():
            if pid != super_id:
                assert profile["protected"] is False, (
                    f"{profile['name']} should be editable (protected=False)"
                )

    def test_builtin_profiles_have_names(self):
        """All built-in profiles must have name field."""
        import user_profiles

        for pid, profile in user_profiles.BUILTIN_PROFILES.items():
            assert "name" in profile, f"Profile {pid} missing name"
            assert profile["name"], f"Profile {pid} has empty name"


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


# ── Profile CRUD with Database ────────────────────────────────────────────────


class TestProfileCRUD:
    def test_get_all_profiles_includes_builtins(self):
        """get_all_profiles should return all built-in profiles."""
        import user_profiles

        with tempfile.TemporaryDirectory() as tmp:
            user_profiles.AUTH_DB_PATH = _tmp_db_path(tmp)
            user_profiles._ensure_builtin_profiles()

            profiles = user_profiles.get_all_profiles()

            # Should have all 4 built-in profiles
            assert len(profiles) >= 4
            # Check SUPER exists
            super_id = "super-0000-0000-0000-000000000000"
            assert super_id in profiles
            assert profiles[super_id]["name"] == "SUPER"

    def test_create_profile_returns_id(self):
        """create_profile should return the new profile's UUID."""
        import user_profiles

        with tempfile.TemporaryDirectory() as tmp:
            user_profiles.AUTH_DB_PATH = _tmp_db_path(tmp)
            user_profiles._ensure_builtin_profiles()

            profile_id = user_profiles.create_profile("TEST_PROFILE", 2, "Test desc")

            assert profile_id is not None
            assert len(profile_id) == 36  # UUID format

            # Verify it's retrievable
            profile = user_profiles.get_profile_by_id(profile_id)
            assert profile["name"] == "TEST_PROFILE"
            assert profile["level"] == 2
            assert profile["description"] == "Test desc"

    def test_update_profile_name(self):
        """Should be able to update profile name."""
        import user_profiles

        with tempfile.TemporaryDirectory() as tmp:
            user_profiles.AUTH_DB_PATH = _tmp_db_path(tmp)
            user_profiles._ensure_builtin_profiles()

            # Create a profile
            pid = user_profiles.create_profile("ORIGINAL", 1, "Original")

            # Update name
            user_profiles.update_profile(pid, name="RENAMED")

            profile = user_profiles.get_profile_by_id(pid)
            assert profile["name"] == "RENAMED"

    def test_update_profile_level(self):
        """Should be able to update profile level."""
        import user_profiles

        with tempfile.TemporaryDirectory() as tmp:
            user_profiles.AUTH_DB_PATH = _tmp_db_path(tmp)
            user_profiles._ensure_builtin_profiles()

            pid = user_profiles.create_profile("LEVEL_TEST", 1, "Test")
            user_profiles.update_profile(pid, level=3)

            profile = user_profiles.get_profile_by_id(pid)
            assert profile["level"] == 3

    def test_cannot_update_protected_profile(self):
        """Should not be able to update SUPER profile."""
        import user_profiles

        with tempfile.TemporaryDirectory() as tmp:
            user_profiles.AUTH_DB_PATH = _tmp_db_path(tmp)
            user_profiles._ensure_builtin_profiles()

            super_id = "super-0000-0000-0000-000000000000"
            with pytest.raises(ValueError, match="protected"):
                user_profiles.update_profile(super_id, level=1)

    def test_can_update_editable_builtin_profile(self):
        """Should be able to update FAMILIA_ALL, GAMER, etc."""
        import user_profiles

        with tempfile.TemporaryDirectory() as tmp:
            user_profiles.AUTH_DB_PATH = _tmp_db_path(tmp)
            user_profiles._ensure_builtin_profiles()

            gamer_id = "gamer-0000-0000-0000-000000000003"
            user_profiles.update_profile(gamer_id, description="Updated description")

            profile = user_profiles.get_profile_by_id(gamer_id)
            assert profile["description"] == "Updated description"

    def test_delete_custom_profile(self):
        """Should be able to delete custom profiles."""
        import user_profiles

        with tempfile.TemporaryDirectory() as tmp:
            user_profiles.AUTH_DB_PATH = _tmp_db_path(tmp)
            user_profiles._ensure_builtin_profiles()

            pid = user_profiles.create_profile("TO_DELETE", 1, "Delete me")
            assert user_profiles.get_profile_by_id(pid) is not None

            user_profiles.delete_profile(pid)
            assert user_profiles.get_profile_by_id(pid) is None

    def test_cannot_delete_builtin_profile(self):
        """Should not be able to delete built-in profiles."""
        import user_profiles

        with tempfile.TemporaryDirectory() as tmp:
            user_profiles.AUTH_DB_PATH = _tmp_db_path(tmp)
            user_profiles._ensure_builtin_profiles()

            gamer_id = "gamer-0000-0000-0000-000000000003"
            with pytest.raises(ValueError, match="built-in"):
                user_profiles.delete_profile(gamer_id)


# ── User-Profile Assignment ───────────────────────────────────────────────────


class TestUserProfiles:
    def test_get_user_profiles_returns_default(self):
        """Users without assigned profiles get the default."""
        import user_profiles

        with tempfile.TemporaryDirectory() as tmp:
            user_profiles.AUTH_DB_PATH = _tmp_db_path(tmp)
            user_profiles._ensure_builtin_profiles()

            profiles = user_profiles.get_user_profiles("newuser")
            assert profiles == [user_profiles.DEFAULT_PROFILE_ID]

    def test_set_user_profiles(self):
        """Should be able to assign profiles to a user."""
        import user_profiles

        with tempfile.TemporaryDirectory() as tmp:
            user_profiles.AUTH_DB_PATH = _tmp_db_path(tmp)
            user_profiles._ensure_builtin_profiles()

            super_id = "super-0000-0000-0000-000000000000"
            gamer_id = "gamer-0000-0000-0000-000000000003"

            user_profiles.set_user_profiles("testuser", [super_id, gamer_id])
            profiles = user_profiles.get_user_profiles("testuser")

            assert super_id in profiles
            assert gamer_id in profiles

    def test_add_user_profile(self):
        """Should be able to add a profile to a user."""
        import user_profiles

        with tempfile.TemporaryDirectory() as tmp:
            user_profiles.AUTH_DB_PATH = _tmp_db_path(tmp)
            user_profiles._ensure_builtin_profiles()

            fam_id = "familia-principal-0000-000000000002"
            gamer_id = "gamer-0000-0000-0000-000000000003"

            user_profiles.set_user_profiles("adduser", [fam_id])
            user_profiles.add_user_profile("adduser", gamer_id)

            profiles = user_profiles.get_user_profiles("adduser")
            assert gamer_id in profiles
            assert fam_id in profiles

    def test_remove_user_profile(self):
        """Should be able to remove a profile from a user."""
        import user_profiles

        with tempfile.TemporaryDirectory() as tmp:
            user_profiles.AUTH_DB_PATH = _tmp_db_path(tmp)
            user_profiles._ensure_builtin_profiles()

            super_id = "super-0000-0000-0000-000000000000"
            gamer_id = "gamer-0000-0000-0000-000000000003"

            user_profiles.set_user_profiles("removeuser", [super_id, gamer_id])
            user_profiles.remove_user_profile("removeuser", gamer_id)

            profiles = user_profiles.get_user_profiles("removeuser")
            assert gamer_id not in profiles
            assert super_id in profiles


# ── Effective Level Calculation ───────────────────────────────────────────────


class TestEffectiveLevel:
    def test_super_user_has_level_0(self):
        """User with SUPER profile should have level 0."""
        import user_profiles

        with tempfile.TemporaryDirectory() as tmp:
            user_profiles.AUTH_DB_PATH = _tmp_db_path(tmp)
            user_profiles._ensure_builtin_profiles()

            super_id = "super-0000-0000-0000-000000000000"
            user_profiles.set_user_profiles("admin", [super_id])

            assert user_profiles.get_effective_level("admin") == 0

    def test_multiple_profiles_uses_minimum(self):
        """Effective level is the minimum across all profiles."""
        import user_profiles

        with tempfile.TemporaryDirectory() as tmp:
            user_profiles.AUTH_DB_PATH = _tmp_db_path(tmp)
            user_profiles._ensure_builtin_profiles()

            super_id = "super-0000-0000-0000-000000000000"  # level 0
            gamer_id = "gamer-0000-0000-0000-000000000003"  # level 3

            user_profiles.set_user_profiles("multiuser", [super_id, gamer_id])

            # Should be 0 (minimum of 0 and 3)
            assert user_profiles.get_effective_level("multiuser") == 0

    def test_is_super_returns_true_for_level_0(self):
        """is_super should return True for users with level 0."""
        import user_profiles

        with tempfile.TemporaryDirectory() as tmp:
            user_profiles.AUTH_DB_PATH = _tmp_db_path(tmp)
            user_profiles._ensure_builtin_profiles()

            super_id = "super-0000-0000-0000-000000000000"
            user_profiles.set_user_profiles("superuser", [super_id])

            assert user_profiles.is_super("superuser") is True

    def test_is_super_returns_false_for_non_admin(self):
        """is_super should return False for regular users."""
        import user_profiles

        with tempfile.TemporaryDirectory() as tmp:
            user_profiles.AUTH_DB_PATH = _tmp_db_path(tmp)
            user_profiles._ensure_builtin_profiles()

            fam_id = "familia-principal-0000-000000000002"
            user_profiles.set_user_profiles("normaluser", [fam_id])

            assert user_profiles.is_super("normaluser") is False


# ── User Info API ─────────────────────────────────────────────────────────────


class TestUserInfo:
    def test_get_user_info_includes_profiles(self):
        """get_user_info should include detailed profile info."""
        import user_profiles

        with tempfile.TemporaryDirectory() as tmp:
            user_profiles.AUTH_DB_PATH = _tmp_db_path(tmp)
            user_profiles._ensure_builtin_profiles()

            super_id = "super-0000-0000-0000-000000000000"
            user_profiles.set_user_profiles("infouser", [super_id])

            info = user_profiles.get_user_info("infouser")

            assert info["username"] == "infouser"
            assert info["effective_level"] == 0
            assert info["is_admin"] is True
            assert len(info["profiles"]) >= 1
            assert info["profiles"][0]["name"] == "SUPER"

    def test_get_user_info_includes_apps(self):
        """get_user_info should include permitted apps."""
        import user_profiles

        with tempfile.TemporaryDirectory() as tmp:
            user_profiles.AUTH_DB_PATH = _tmp_db_path(tmp)
            user_profiles._ensure_builtin_profiles()

            super_id = "super-0000-0000-0000-000000000000"
            user_profiles.set_user_profiles("appuser", [super_id])

            info = user_profiles.get_user_info("appuser")

            # SUPER should see all apps
            app_keys = [a["key"] for a in info["apps"]]
            assert "ac" in app_keys
            assert "zigbee" in app_keys
            assert "passwords" in app_keys
