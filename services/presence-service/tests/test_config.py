"""Tests for configuration validation, especially MQTT topic security."""

import pytest
from config import validate_mqtt_topic


class TestMqttTopicValidation:
    """MQTT topic validation to prevent topic injection attacks."""

    # ─────────────────────────────────────────────────────────────────────────
    # Valid topics (no wildcards)
    # ─────────────────────────────────────────────────────────────────────────
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

    # ─────────────────────────────────────────────────────────────────────────
    # Invalid characters (always rejected)
    # ─────────────────────────────────────────────────────────────────────────
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

    # ─────────────────────────────────────────────────────────────────────────
    # Wildcards rejected when allow_wildcards=False (publish topics)
    # ─────────────────────────────────────────────────────────────────────────
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

    # ─────────────────────────────────────────────────────────────────────────
    # Wildcards allowed when allow_wildcards=True (subscription topics)
    # ─────────────────────────────────────────────────────────────────────────
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

    # ─────────────────────────────────────────────────────────────────────────
    # Edge cases
    # ─────────────────────────────────────────────────────────────────────────
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
