"""Tests for profiles/permissions.py."""

from unittest.mock import patch

import pytest


class TestGetEffectiveLevel:
    """Tests for effective level calculation."""

    def test_returns_minimum_level_across_profiles(self):
        """Effective level should be minimum of assigned profiles."""
        with (
            patch("profiles.permissions.get_user_profiles") as mock_profiles,
            patch("profiles.permissions.get_all_profiles") as mock_all,
        ):
            mock_profiles.return_value = ["profile-a", "profile-b"]
            mock_all.return_value = {
                "profile-a": {"name": "A", "level": 2},
                "profile-b": {"name": "B", "level": 1},
            }

            from profiles.permissions import get_effective_level

            level = get_effective_level("testuser")
            assert level == 1  # minimum of 2 and 1

    def test_returns_default_level_when_no_profiles(self):
        """Should return default profile level when user has no profiles."""
        with (
            patch("profiles.permissions.get_user_profiles") as mock_profiles,
            patch("profiles.permissions.get_all_profiles") as mock_all,
        ):
            mock_profiles.return_value = []
            mock_all.return_value = {
                "familia-principal-0000-000000000002": {"level": 1}
            }

            from profiles.permissions import get_effective_level

            level = get_effective_level("testuser")
            assert level == 1


class TestIsSuper:
    """Tests for is_super function."""

    def test_returns_true_for_level_zero(self):
        """is_super should return True for level 0."""
        with patch("profiles.permissions.get_effective_level") as mock:
            mock.return_value = 0

            from profiles.permissions import is_super

            assert is_super("admin") is True

    def test_returns_false_for_non_zero_level(self):
        """is_super should return False for level > 0."""
        with patch("profiles.permissions.get_effective_level") as mock:
            mock.return_value = 1

            from profiles.permissions import is_super

            assert is_super("regular") is False


class TestCanView:
    """Tests for _can_view helper."""

    def test_super_sees_everything(self):
        """Level 0 (SUPER) should see all items."""
        from profiles.permissions import _can_view

        # SUPER sees level 0 only items
        assert _can_view(0, {"min_level": 0, "max_level": 0}) is True
        # SUPER sees level 3 only items
        assert _can_view(0, {"min_level": 3, "max_level": 3}) is True

    def test_level_in_range_can_view(self):
        """User level within range should see item."""
        from profiles.permissions import _can_view

        # Level 1 can see items with range 0-1
        assert _can_view(1, {"min_level": 0, "max_level": 1}) is True
        # Level 1 can see items with range 1-2
        assert _can_view(1, {"min_level": 1, "max_level": 2}) is True

    def test_level_outside_range_cannot_view(self):
        """User level outside range should not see item."""
        from profiles.permissions import _can_view

        # Level 1 cannot see SUPER only items
        assert _can_view(1, {"min_level": 0, "max_level": 0}) is False
        # Level 1 cannot see GAMER only items
        assert _can_view(1, {"min_level": 3, "max_level": 3}) is False


class TestAppPermissions:
    """Tests for app_permissions function."""

    def test_returns_visible_apps(self):
        """Should return apps visible to user."""
        with patch("profiles.permissions.get_effective_level") as mock:
            mock.return_value = 1

            from profiles.permissions import app_permissions

            apps = app_permissions("testuser")

            # Should have family-level apps
            keys = [a["key"] for a in apps]
            assert "ac" in keys
            assert "vacaciones" in keys

            # Should not have SUPER-only apps
            assert "zigbee" not in keys
            assert "portfolio" not in keys

    def test_super_sees_all_apps(self):
        """SUPER should see all apps including admin-only."""
        with patch("profiles.permissions.get_effective_level") as mock:
            mock.return_value = 0

            from profiles.permissions import app_permissions

            apps = app_permissions("admin")
            keys = [a["key"] for a in apps]

            assert "zigbee" in keys
            assert "portfolio" in keys
            assert "valheim" in keys  # Even GAMER-only apps


class TestVisibleExternalServices:
    """Tests for visible_external_services function."""

    def test_family_sees_family_services(self):
        """Family level should see appropriate external services."""
        with patch("profiles.permissions.get_effective_level") as mock:
            mock.return_value = 1

            from profiles.permissions import visible_external_services

            services = visible_external_services("family")
            keys = [s["key"] for s in services]

            # Should see family-accessible services
            assert "ai" in keys
            assert "photos_ext" in keys

            # Should not see SUPER-only services
            assert "passwords_ext" not in keys


class TestGetUserProfilesDetailed:
    """Tests for get_user_profiles_detailed function."""

    def test_returns_full_profile_objects(self):
        """Should return complete profile info for assigned profiles."""
        with (
            patch("profiles.permissions.get_user_profiles") as mock_profiles,
            patch("profiles.permissions.get_all_profiles") as mock_all,
        ):
            mock_profiles.return_value = ["profile-a"]
            mock_all.return_value = {
                "profile-a": {
                    "name": "Test",
                    "level": 1,
                    "description": "Test profile",
                    "protected": False,
                }
            }

            from profiles.permissions import get_user_profiles_detailed

            details = get_user_profiles_detailed("testuser")

            assert len(details) == 1
            assert details[0]["id"] == "profile-a"
            assert details[0]["name"] == "Test"
            assert details[0]["level"] == 1


class TestLegacyCompatibility:
    """Tests for legacy compatibility functions."""

    def test_get_profile_key_returns_name(self):
        """get_profile_key should return profile name."""
        with (
            patch("profiles.permissions.get_user_profiles") as mock_profiles,
            patch("profiles.permissions.get_all_profiles") as mock_all,
        ):
            mock_profiles.return_value = ["profile-a"]
            mock_all.return_value = {
                "profile-a": {"name": "FAMILIA_ALL", "level": 1}
            }

            from profiles.permissions import get_profile_key

            key = get_profile_key("testuser")
            assert key == "FAMILIA_ALL"

    def test_get_profile_returns_dict(self):
        """get_profile should return legacy dict format."""
        with patch("profiles.permissions.get_effective_level") as mock:
            mock.return_value = 1

            from profiles.permissions import get_profile

            profile = get_profile("testuser")

            assert profile["level"] == 1
            assert profile["can_view_level"] == 1
            assert profile["can_edit_level"] == 1
            assert profile["show_config_apps"] is False

    def test_get_profile_super_shows_config(self):
        """get_profile for SUPER should show config apps."""
        with patch("profiles.permissions.get_effective_level") as mock:
            mock.return_value = 0

            from profiles.permissions import get_profile

            profile = get_profile("admin")
            assert profile["show_config_apps"] is True
