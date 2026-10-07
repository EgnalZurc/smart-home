"""Unit tests for user_profiles.py - profile and permission management."""

import shutil
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def isolated_user_profiles():
    """Create isolated user_profiles module with temp database."""
    import sys

    # Clear all profile-related modules to get fresh imports
    for mod in list(sys.modules.keys()):
        if mod.startswith("profiles") or mod == "user_profiles":
            del sys.modules[mod]

    # Import after cleanup
    import profiles.db as profiles_db
    import user_profiles

    temp_dir = tempfile.mkdtemp()
    db_path = str(Path(temp_dir) / "test_profiles.db")

    # Store originals
    orig_db = profiles_db.AUTH_DB_PATH

    # Set test path (profiles.db is the actual storage)
    profiles_db.AUTH_DB_PATH = db_path

    # Initialize schema and builtins
    profiles_db._ensure_builtin_profiles()

    yield {"module": user_profiles, "db_path": db_path, "temp_dir": temp_dir}

    # Restore
    profiles_db.AUTH_DB_PATH = orig_db
    shutil.rmtree(temp_dir, ignore_errors=True)


class TestBuiltinProfiles:
    def test_builtin_profiles_exist(self, isolated_user_profiles):
        up = isolated_user_profiles["module"]
        profiles = up.get_all_profiles()

        # Should have 4 built-in profiles
        assert len(profiles) >= 4
        assert "super-0000-0000-0000-000000000000" in profiles
        assert "familia-all-0000-0000-000000000001" in profiles

    def test_super_profile_is_protected(self, isolated_user_profiles):
        up = isolated_user_profiles["module"]
        super_id = "super-0000-0000-0000-000000000000"
        profile = up.get_profile_by_id(super_id)

        assert profile is not None
        assert profile["protected"] is True
        assert profile["level"] == 0

    def test_familia_all_not_protected(self, isolated_user_profiles):
        up = isolated_user_profiles["module"]
        fam_id = "familia-all-0000-0000-000000000001"
        profile = up.get_profile_by_id(fam_id)

        assert profile is not None
        assert profile["protected"] is False


class TestGetProfile:
    def test_get_by_id(self, isolated_user_profiles):
        up = isolated_user_profiles["module"]
        profile = up.get_profile_by_id("super-0000-0000-0000-000000000000")

        assert profile is not None
        assert profile["name"] == "SUPER"
        assert profile["level"] == 0

    def test_get_by_id_unknown(self, isolated_user_profiles):
        up = isolated_user_profiles["module"]
        profile = up.get_profile_by_id("nonexistent-uuid")
        assert profile is None

    def test_get_by_name(self, isolated_user_profiles):
        up = isolated_user_profiles["module"]
        profile = up.get_profile_by_name("SUPER")

        assert profile is not None
        assert profile["id"] == "super-0000-0000-0000-000000000000"

    def test_get_by_name_unknown(self, isolated_user_profiles):
        up = isolated_user_profiles["module"]
        profile = up.get_profile_by_name("NONEXISTENT")
        assert profile is None


class TestCreateProfile:
    def test_create_returns_uuid(self, isolated_user_profiles):
        up = isolated_user_profiles["module"]
        profile_id = up.create_profile("TEST_PROFILE", 2, "Test description")

        assert profile_id is not None
        assert len(profile_id) == 36  # UUID format

    def test_create_stores_in_db(self, isolated_user_profiles):
        up = isolated_user_profiles["module"]
        profile_id = up.create_profile("NEW_PROFILE", 1, "Description")

        profile = up.get_profile_by_id(profile_id)
        assert profile["name"] == "NEW_PROFILE"
        assert profile["level"] == 1
        assert profile["description"] == "Description"
        assert profile["protected"] is False

    def test_create_invalid_level_raises(self, isolated_user_profiles):
        up = isolated_user_profiles["module"]

        with pytest.raises(ValueError, match="Level must be 0-3"):
            up.create_profile("BAD_LEVEL", 5, "")

    def test_create_duplicate_name_raises(self, isolated_user_profiles):
        up = isolated_user_profiles["module"]
        up.create_profile("UNIQUE", 1, "")

        with pytest.raises(ValueError, match="already exists"):
            up.create_profile("UNIQUE", 2, "")


class TestUpdateProfile:
    def test_update_name(self, isolated_user_profiles):
        up = isolated_user_profiles["module"]
        profile_id = up.create_profile("OLD_NAME", 1, "")

        up.update_profile(profile_id, name="NEW_NAME")

        profile = up.get_profile_by_id(profile_id)
        assert profile["name"] == "NEW_NAME"

    def test_update_level(self, isolated_user_profiles):
        up = isolated_user_profiles["module"]
        profile_id = up.create_profile("LEVEL_TEST", 1, "")

        up.update_profile(profile_id, level=2)

        profile = up.get_profile_by_id(profile_id)
        assert profile["level"] == 2

    def test_update_description(self, isolated_user_profiles):
        up = isolated_user_profiles["module"]
        profile_id = up.create_profile("DESC_TEST", 1, "Old")

        up.update_profile(profile_id, description="New description")

        profile = up.get_profile_by_id(profile_id)
        assert profile["description"] == "New description"

    def test_update_protected_raises(self, isolated_user_profiles):
        up = isolated_user_profiles["module"]
        super_id = "super-0000-0000-0000-000000000000"

        with pytest.raises(ValueError, match="Cannot modify protected"):
            up.update_profile(super_id, name="HACKED")

    def test_update_nonexistent_raises(self, isolated_user_profiles):
        up = isolated_user_profiles["module"]

        with pytest.raises(ValueError, match="not found"):
            up.update_profile("nonexistent", name="Test")

    def test_update_invalid_level_raises(self, isolated_user_profiles):
        up = isolated_user_profiles["module"]
        profile_id = up.create_profile("LEVEL_RANGE", 1, "")

        with pytest.raises(ValueError, match="Level must be 0-3"):
            up.update_profile(profile_id, level=10)

    def test_update_duplicate_name_raises(self, isolated_user_profiles):
        up = isolated_user_profiles["module"]
        up.create_profile("EXISTING", 1, "")
        profile_id = up.create_profile("ORIGINAL", 2, "")

        with pytest.raises(ValueError, match="already exists"):
            up.update_profile(profile_id, name="EXISTING")


class TestDeleteProfile:
    def test_delete_custom_profile(self, isolated_user_profiles):
        up = isolated_user_profiles["module"]
        profile_id = up.create_profile("TO_DELETE", 1, "")

        up.delete_profile(profile_id)

        assert up.get_profile_by_id(profile_id) is None

    def test_delete_protected_raises(self, isolated_user_profiles):
        up = isolated_user_profiles["module"]
        super_id = "super-0000-0000-0000-000000000000"

        with pytest.raises(ValueError, match="Cannot delete protected"):
            up.delete_profile(super_id)

    def test_delete_builtin_raises(self, isolated_user_profiles):
        up = isolated_user_profiles["module"]
        # FAMILIA_ALL is not protected but is builtin
        fam_id = "familia-all-0000-0000-000000000001"

        with pytest.raises(ValueError, match="Cannot delete built-in"):
            up.delete_profile(fam_id)

    def test_delete_nonexistent_raises(self, isolated_user_profiles):
        up = isolated_user_profiles["module"]

        with pytest.raises(ValueError, match="not found"):
            up.delete_profile("nonexistent-uuid")


class TestUserProfiles:
    def test_get_user_profiles_default(self, isolated_user_profiles):
        up = isolated_user_profiles["module"]

        profiles = up.get_user_profiles("newuser")

        # Should return default profile
        assert profiles == [up.DEFAULT_PROFILE_ID]

    def test_set_user_profiles(self, isolated_user_profiles):
        up = isolated_user_profiles["module"]
        super_id = "super-0000-0000-0000-000000000000"
        fam_id = "familia-all-0000-0000-000000000001"

        up.set_user_profiles("testuser", [super_id, fam_id])

        profiles = up.get_user_profiles("testuser")
        assert super_id in profiles
        assert fam_id in profiles

    def test_set_user_profiles_replaces(self, isolated_user_profiles):
        up = isolated_user_profiles["module"]
        super_id = "super-0000-0000-0000-000000000000"
        fam_id = "familia-all-0000-0000-000000000001"

        up.set_user_profiles("testuser", [super_id])
        up.set_user_profiles("testuser", [fam_id])

        profiles = up.get_user_profiles("testuser")
        assert profiles == [fam_id]

    def test_set_invalid_profile_raises(self, isolated_user_profiles):
        up = isolated_user_profiles["module"]

        with pytest.raises(ValueError, match="Unknown profile ID"):
            up.set_user_profiles("testuser", ["invalid-uuid"])

    def test_add_user_profile(self, isolated_user_profiles):
        up = isolated_user_profiles["module"]
        super_id = "super-0000-0000-0000-000000000000"
        fam_id = "familia-all-0000-0000-000000000001"

        up.set_user_profiles("testuser", [fam_id])
        up.add_user_profile("testuser", super_id)

        profiles = up.get_user_profiles("testuser")
        assert super_id in profiles
        assert fam_id in profiles

    def test_add_invalid_profile_raises(self, isolated_user_profiles):
        up = isolated_user_profiles["module"]

        with pytest.raises(ValueError, match="Unknown profile ID"):
            up.add_user_profile("testuser", "invalid-uuid")

    def test_remove_user_profile(self, isolated_user_profiles):
        up = isolated_user_profiles["module"]
        super_id = "super-0000-0000-0000-000000000000"
        fam_id = "familia-all-0000-0000-000000000001"

        up.set_user_profiles("testuser", [super_id, fam_id])
        up.remove_user_profile("testuser", super_id)

        profiles = up.get_user_profiles("testuser")
        assert super_id not in profiles
        assert fam_id in profiles

    def test_get_user_profiles_detailed(self, isolated_user_profiles):
        up = isolated_user_profiles["module"]
        super_id = "super-0000-0000-0000-000000000000"

        up.set_user_profiles("testuser", [super_id])

        detailed = up.get_user_profiles_detailed("testuser")
        assert len(detailed) == 1
        assert detailed[0]["id"] == super_id
        assert detailed[0]["name"] == "SUPER"


class TestEffectivePermissions:
    def test_effective_level_single_profile(self, isolated_user_profiles):
        up = isolated_user_profiles["module"]
        super_id = "super-0000-0000-0000-000000000000"

        up.set_user_profiles("admin", [super_id])

        level = up.get_effective_level("admin")
        assert level == 0

    def test_effective_level_multiple_profiles_uses_min(self, isolated_user_profiles):
        up = isolated_user_profiles["module"]
        super_id = "super-0000-0000-0000-000000000000"  # level 0
        gamer_id = "gamer-0000-0000-0000-000000000003"  # level 3

        up.set_user_profiles("mixeduser", [super_id, gamer_id])

        level = up.get_effective_level("mixeduser")
        assert level == 0  # Minimum of 0 and 3

    def test_is_super_true_for_level_0(self, isolated_user_profiles):
        up = isolated_user_profiles["module"]
        super_id = "super-0000-0000-0000-000000000000"

        up.set_user_profiles("admin", [super_id])

        assert up.is_super("admin") is True

    def test_is_super_false_for_higher_level(self, isolated_user_profiles):
        up = isolated_user_profiles["module"]
        gamer_id = "gamer-0000-0000-0000-000000000003"

        up.set_user_profiles("player", [gamer_id])

        assert up.is_super("player") is False


class TestLegacyCompatibility:
    def test_get_profile_key(self, isolated_user_profiles):
        up = isolated_user_profiles["module"]
        super_id = "super-0000-0000-0000-000000000000"

        up.set_user_profiles("admin", [super_id])

        key = up.get_profile_key("admin")
        assert key == "SUPER"

    def test_get_profile_key_default(self, isolated_user_profiles):
        up = isolated_user_profiles["module"]

        key = up.get_profile_key("newuser")
        assert key == "FAMILIA_PRINCIPAL"

    def test_get_profile_returns_dict(self, isolated_user_profiles):
        up = isolated_user_profiles["module"]
        super_id = "super-0000-0000-0000-000000000000"

        up.set_user_profiles("admin", [super_id])

        profile = up.get_profile("admin")
        assert "level" in profile
        assert profile["level"] == 0
        assert "show_config_apps" in profile
        assert profile["show_config_apps"] is True


class TestUserInfo:
    def test_get_user_info_includes_apps(self, isolated_user_profiles):
        up = isolated_user_profiles["module"]
        super_id = "super-0000-0000-0000-000000000000"

        up.set_user_profiles("admin", [super_id])

        info = up.get_user_info("admin")
        assert info["username"] == "admin"
        assert info["is_admin"] is True
        assert "apps" in info
        assert len(info["apps"]) > 0

    def test_get_user_info_includes_external_services(self, isolated_user_profiles):
        up = isolated_user_profiles["module"]
        super_id = "super-0000-0000-0000-000000000000"

        up.set_user_profiles("admin", [super_id])

        info = up.get_user_info("admin")
        assert "external_services" in info


class TestAppPermissions:
    def test_can_view_super_sees_all(self, isolated_user_profiles):
        up = isolated_user_profiles["module"]

        # Level 0 should see everything
        assert up._can_view(0, {"min_level": 0, "max_level": 0}) is True
        assert up._can_view(0, {"min_level": 0, "max_level": 1}) is True
        assert up._can_view(0, {"min_level": 3, "max_level": 3}) is True

    def test_can_view_respects_range(self, isolated_user_profiles):
        up = isolated_user_profiles["module"]

        # Level 1 user
        assert up._can_view(1, {"min_level": 0, "max_level": 1}) is True
        assert up._can_view(1, {"min_level": 0, "max_level": 0}) is False  # SUPER only
        assert up._can_view(1, {"min_level": 3, "max_level": 3}) is False  # GAMER only

    def test_app_permissions_returns_visible_apps(self, isolated_user_profiles):
        up = isolated_user_profiles["module"]
        super_id = "super-0000-0000-0000-000000000000"

        up.set_user_profiles("admin", [super_id])

        apps = up.app_permissions("admin")
        assert len(apps) > 0
        assert all("key" in app for app in apps)

    def test_visible_external_services(self, isolated_user_profiles):
        up = isolated_user_profiles["module"]
        super_id = "super-0000-0000-0000-000000000000"

        up.set_user_profiles("admin", [super_id])

        services = up.visible_external_services("admin")
        assert len(services) > 0
        assert all("key" in svc for svc in services)
