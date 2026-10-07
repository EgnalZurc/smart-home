"""Tests for profiles/constants.py."""

import pytest


class TestBuiltinProfiles:
    """Tests for built-in profile definitions."""

    def test_builtin_profiles_exist(self):
        """Built-in profiles should be defined."""
        from profiles.constants import BUILTIN_PROFILES

        assert len(BUILTIN_PROFILES) == 4
        assert "super-0000-0000-0000-000000000000" in BUILTIN_PROFILES
        assert "familia-all-0000-0000-000000000001" in BUILTIN_PROFILES
        assert "familia-principal-0000-000000000002" in BUILTIN_PROFILES
        assert "gamer-0000-0000-0000-000000000003" in BUILTIN_PROFILES

    def test_super_is_protected(self):
        """SUPER profile should be protected."""
        from profiles.constants import BUILTIN_PROFILES

        super_profile = BUILTIN_PROFILES["super-0000-0000-0000-000000000000"]
        assert super_profile["protected"] is True
        assert super_profile["level"] == 0
        assert super_profile["name"] == "SUPER"

    def test_gamer_level(self):
        """GAMER profile should have level 3."""
        from profiles.constants import BUILTIN_PROFILES

        gamer = BUILTIN_PROFILES["gamer-0000-0000-0000-000000000003"]
        assert gamer["level"] == 3
        assert gamer["protected"] is False

    def test_default_profile_id_is_familia_principal(self):
        """Default profile should be FAMILIA_PRINCIPAL."""
        from profiles.constants import BUILTIN_PROFILES, DEFAULT_PROFILE_ID

        assert DEFAULT_PROFILE_ID == "familia-principal-0000-000000000002"
        assert DEFAULT_PROFILE_ID in BUILTIN_PROFILES

    def test_builtin_name_to_id_mapping(self):
        """Name to ID mapping should be consistent."""
        from profiles.constants import BUILTIN_NAME_TO_ID, BUILTIN_PROFILES

        for profile_id, profile in BUILTIN_PROFILES.items():
            name = profile["name"]
            assert BUILTIN_NAME_TO_ID[name] == profile_id


class TestAppRegistry:
    """Tests for app registry."""

    def test_app_registry_not_empty(self):
        """App registry should have entries."""
        from profiles.constants import APP_REGISTRY

        assert len(APP_REGISTRY) >= 5

    def test_apps_have_required_fields(self):
        """All apps should have key, min_level, max_level."""
        from profiles.constants import APP_REGISTRY

        for app in APP_REGISTRY:
            assert "key" in app
            assert "min_level" in app
            assert "max_level" in app
            assert 0 <= app["min_level"] <= 3
            assert 0 <= app["max_level"] <= 3

    def test_valheim_is_gamer_only(self):
        """Valheim should be level 3 (GAMER only, plus SUPER)."""
        from profiles.constants import APP_REGISTRY

        valheim = next(app for app in APP_REGISTRY if app["key"] == "valheim")
        assert valheim["min_level"] == 3
        assert valheim["max_level"] == 3

    def test_zigbee_is_super_only(self):
        """Zigbee should be SUPER only (level 0)."""
        from profiles.constants import APP_REGISTRY

        zigbee = next(app for app in APP_REGISTRY if app["key"] == "zigbee")
        assert zigbee["min_level"] == 0
        assert zigbee["max_level"] == 0


class TestExternalServices:
    """Tests for external services."""

    def test_external_services_not_empty(self):
        """External services should be defined."""
        from profiles.constants import EXTERNAL_SERVICES

        assert len(EXTERNAL_SERVICES) >= 1

    def test_services_have_required_fields(self):
        """All services should have key, min_level, max_level, url."""
        from profiles.constants import EXTERNAL_SERVICES

        for svc in EXTERNAL_SERVICES:
            assert "key" in svc
            assert "min_level" in svc
            assert "max_level" in svc
            assert "url" in svc
