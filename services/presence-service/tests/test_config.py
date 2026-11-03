"""Tests for configuration validation, especially MQTT topic security."""

import os

import pytest
from config import VALID_ROUTER_MODES, validate_mqtt_topic


class TestMqttTopicValidation:
    """MQTT topic validation to prevent topic injection attacks."""

    @pytest.mark.parametrize(
        "topic",
        [
            "presence",
            "presence/state",
            "presence/house/occupancy",
            "zigbee2mqtt/motion-sensor-1",
            "home/sensors/temperature_living",
            "a-b_c/d-e_f",
        ],
    )
    def test_valid_topics_pass(self, topic: str) -> None:
        """Valid topics with alphanumeric, slashes, underscores, hyphens pass."""
        assert validate_mqtt_topic(topic, allow_wildcards=False) == topic

    @pytest.mark.parametrize(
        "topic",
        [
            "topic with spaces",
            "topic\twith\ttabs",
            "topic$variable",
            "topic;injection",
            "topic|pipe",
            "topic&and",
            "topic'quote",
            'topic"doublequote',
            "topic`backtick",
            "topic\\backslash",
        ],
    )
    def test_invalid_characters_rejected(self, topic: str) -> None:
        """Topics with special characters are rejected."""
        with pytest.raises(ValueError, match="invalid characters"):
            validate_mqtt_topic(topic, allow_wildcards=False)

    @pytest.mark.parametrize(
        "topic",
        [
            "presence/#",
            "presence/+",
            "#",
            "+",
            "home/+/temperature",
            "sensors/#/data",
        ],
    )
    def test_wildcards_rejected_for_publish(self, topic: str) -> None:
        """Wildcards are rejected for publish topics (injection risk)."""
        with pytest.raises(ValueError, match="wildcards"):
            validate_mqtt_topic(topic, allow_wildcards=False)

    @pytest.mark.parametrize(
        "topic",
        [
            "presence/#",
            "presence/ble/#",
            "#",
            "zigbee2mqtt/+",
            "+/temperature",
            "home/+/status",
            "+",
        ],
    )
    def test_wildcards_allowed_for_subscribe(self, topic: str) -> None:
        """Wildcards are allowed for subscription topics."""
        assert validate_mqtt_topic(topic, allow_wildcards=True) == topic

    def test_empty_topic_rejected(self) -> None:
        """Empty topics are rejected."""
        with pytest.raises(ValueError, match="cannot be empty"):
            validate_mqtt_topic("", allow_wildcards=False)

    def test_leading_slash_allowed(self) -> None:
        """Leading slash is valid (though unusual)."""
        assert (
            validate_mqtt_topic("/home/sensors", allow_wildcards=False)
            == "/home/sensors"
        )

    def test_trailing_slash_allowed(self) -> None:
        """Trailing slash is valid."""
        assert (
            validate_mqtt_topic("home/sensors/", allow_wildcards=False)
            == "home/sensors/"
        )


class TestRouterModeValidation:
    """ROUTER_MODE validation to prevent invalid router polling strategies."""

    def test_valid_router_modes_constant(self) -> None:
        """VALID_ROUTER_MODES contains expected modes."""
        assert "arpsweep" in VALID_ROUTER_MODES
        assert "openwrt_ssh" in VALID_ROUTER_MODES
        assert "fritzbox" in VALID_ROUTER_MODES
        assert "mikrotik" in VALID_ROUTER_MODES
        assert len(VALID_ROUTER_MODES) == 4

    def test_invalid_router_mode_raises(self) -> None:
        """Invalid ROUTER_MODE raises ValueError from validation function."""
        import importlib
        import sys

        if "config" in sys.modules:
            del sys.modules["config"]
        cfg = importlib.import_module("config")

        with pytest.raises(ValueError, match="ROUTER_MODE must be one of"):
            cfg._validate_router_mode("invalid_mode")

    def test_valid_router_modes_accepted_by_validator(self) -> None:
        """Valid ROUTER_MODE values are accepted by the validator."""
        import importlib
        import sys

        if "config" in sys.modules:
            del sys.modules["config"]
        cfg = importlib.import_module("config")

        for mode in ("arpsweep", "openwrt_ssh", "fritzbox", "mikrotik"):
            result = cfg._validate_router_mode(mode)
            assert result == mode


# L2: Night Window Wraparound Tests


class TestNightWindowValidation:
    def test_wraparound_window_accepted(self):
        import importlib
        import sys

        if "config" in sys.modules:
            del sys.modules["config"]
        cfg = importlib.import_module("config")
        assert cfg._validate_night_window("23:00-08:00") == "23:00-08:00"

    def test_invalid_format_rejected(self):
        import importlib
        import sys

        if "config" in sys.modules:
            del sys.modules["config"]
        cfg = importlib.import_module("config")
        with pytest.raises(ValueError, match="HH:MM-HH:MM"):
            cfg._validate_night_window("23:00")

    def test_invalid_hour_rejected(self):
        import importlib
        import sys

        if "config" in sys.modules:
            del sys.modules["config"]
        cfg = importlib.import_module("config")
        with pytest.raises(ValueError, match="invalid time"):
            cfg._validate_night_window("25:00-08:00")


# M1: Router Password Validation Tests


class TestRouterPasswordValidation:
    """Tests for ROUTER_PASSWORD validation based on ROUTER_MODE."""

    def test_empty_password_allowed_for_arpsweep(self, monkeypatch):
        """Empty ROUTER_PASSWORD is allowed when ROUTER_MODE=arpsweep."""
        import importlib
        import sys

        # Clear cached module
        if "config" in sys.modules:
            del sys.modules["config"]

        # Set environment for arpsweep mode with empty password
        monkeypatch.setenv("PRESENCE_ROUTER_MODE", "arpsweep")
        monkeypatch.setenv("ROUTER_PASSWORD", "")

        # Should not raise - arpsweep doesn't need router credentials
        cfg = importlib.import_module("config")
        assert cfg.ROUTER_MODE == "arpsweep"
        assert cfg.ROUTER_PASSWORD == ""

    def test_empty_password_raises_for_ssh_modes(self, monkeypatch):
        """Empty ROUTER_PASSWORD raises RuntimeError for SSH-based modes."""
        import importlib
        import sys

        for mode in ("openwrt_ssh", "fritzbox", "mikrotik"):
            # Clear cached module
            if "config" in sys.modules:
                del sys.modules["config"]

            # Set environment for SSH mode with empty password
            monkeypatch.setenv("PRESENCE_ROUTER_MODE", mode)
            monkeypatch.setenv("ROUTER_PASSWORD", "")

            with pytest.raises(RuntimeError, match="ROUTER_PASSWORD is required"):
                importlib.import_module("config")

    def test_valid_password_accepted_for_all_modes(self, monkeypatch):
        """Valid ROUTER_PASSWORD is accepted for all modes."""
        import importlib
        import sys

        for mode in ("arpsweep", "openwrt_ssh", "fritzbox", "mikrotik"):
            # Clear cached module
            if "config" in sys.modules:
                del sys.modules["config"]

            monkeypatch.setenv("PRESENCE_ROUTER_MODE", mode)
            monkeypatch.setenv("ROUTER_PASSWORD", "secure_password_123")

            cfg = importlib.import_module("config")
            assert cfg.ROUTER_MODE == mode
            assert cfg.ROUTER_PASSWORD == "secure_password_123"


# M2: PEOPLE_SEED JSON Validation Tests


class TestPeopleSeedValidation:
    """Tests for PRESENCE_PEOPLE_SEED JSON validation."""

    def test_empty_seed_returns_empty_list(self, monkeypatch):
        """Empty PRESENCE_PEOPLE_SEED returns empty list."""
        import importlib
        import sys

        if "config" in sys.modules:
            del sys.modules["config"]

        monkeypatch.setenv("PRESENCE_PEOPLE_SEED", "")
        monkeypatch.setenv("PRESENCE_ROUTER_MODE", "arpsweep")  # Avoid password check

        cfg = importlib.import_module("config")
        assert cfg.PEOPLE_SEED == []

    def test_valid_json_array_parsed(self, monkeypatch):
        """Valid JSON array is parsed correctly."""
        import importlib
        import sys

        if "config" in sys.modules:
            del sys.modules["config"]

        seed_json = '[{"id": "person1", "name": "Alice"}]'
        monkeypatch.setenv("PRESENCE_PEOPLE_SEED", seed_json)
        monkeypatch.setenv("PRESENCE_ROUTER_MODE", "arpsweep")

        cfg = importlib.import_module("config")
        assert len(cfg.PEOPLE_SEED) == 1
        assert cfg.PEOPLE_SEED[0]["id"] == "person1"
        assert cfg.PEOPLE_SEED[0]["name"] == "Alice"

    def test_invalid_json_raises_runtime_error(self, monkeypatch):
        """Malformed JSON raises RuntimeError."""
        import importlib
        import sys

        if "config" in sys.modules:
            del sys.modules["config"]

        monkeypatch.setenv("PRESENCE_PEOPLE_SEED", "{not valid json")
        monkeypatch.setenv("PRESENCE_ROUTER_MODE", "arpsweep")

        with pytest.raises(RuntimeError, match="Invalid PRESENCE_PEOPLE_SEED"):
            importlib.import_module("config")

    def test_json_object_instead_of_array_raises(self, monkeypatch):
        """JSON object (not array) raises RuntimeError."""
        import importlib
        import sys

        if "config" in sys.modules:
            del sys.modules["config"]

        monkeypatch.setenv("PRESENCE_PEOPLE_SEED", '{"id": "person1"}')
        monkeypatch.setenv("PRESENCE_ROUTER_MODE", "arpsweep")

        with pytest.raises(RuntimeError, match="must be a JSON array"):
            importlib.import_module("config")

    def test_whitespace_only_seed_returns_empty_list(self, monkeypatch):
        """Whitespace-only PRESENCE_PEOPLE_SEED returns empty list."""
        import importlib
        import sys

        if "config" in sys.modules:
            del sys.modules["config"]

        monkeypatch.setenv("PRESENCE_PEOPLE_SEED", "   ")
        monkeypatch.setenv("PRESENCE_ROUTER_MODE", "arpsweep")

        cfg = importlib.import_module("config")
        assert cfg.PEOPLE_SEED == []
