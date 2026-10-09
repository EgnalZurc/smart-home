"""Tests for smart_home_common.clients.zigbee — Zigbee2MQTT client.

All MQTT interaction is mocked; no real broker connection is made.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from smart_home_common.clients.zigbee import Zigbee2MQTTClient

MQTT_PATH = "smart_home_common.clients.zigbee.mqtt"

# A representative payload for the zigbee2mqtt/bridge/devices topic.
SAMPLE_DEVICES = [
    {
        "friendly_name": "Coordinator",
        "ieee_address": "0x00000000",
        "type": "Coordinator",
    },
    {
        "friendly_name": "sensor_salon",
        "ieee_address": "0x0001",
        "type": "EndDevice",
        "manufacturer": "Aqara",
        "model_id": "WSDCGQ11LM",
        "definition": {
            "exposes": [
                {"property": "temperature"},
                {"property": "humidity"},
            ]
        },
    },
    {
        "friendly_name": "enchufe_cocina",
        "ieee_address": "0x0002",
        "type": "Router",
        "definition": {"exposes": [{"property": "state"}]},
    },
]


def _make_msg(topic: str, payload) -> MagicMock:
    """Builds a fake MQTT message object with topic and byte payload."""
    msg = MagicMock()
    msg.topic = topic
    if isinstance(payload, (bytes, bytearray)):
        msg.payload = payload
    else:
        msg.payload = json.dumps(payload).encode()
    return msg


class TestInit:
    """Tests for client initialization."""

    def test_defaults(self):
        client = Zigbee2MQTTClient("mosquitto")
        assert client.mqtt_broker == "mosquitto"
        assert client.mqtt_port == 1883
        assert client.timeout == 10.0
        assert client.username is None
        assert client.password is None
        assert client.devices == []
        assert client.response_received is False

    def test_custom_values(self):
        client = Zigbee2MQTTClient("broker.local", mqtt_port=8883, timeout=5.0)
        assert client.mqtt_broker == "broker.local"
        assert client.mqtt_port == 8883
        assert client.timeout == 5.0

    def test_with_credentials(self):
        client = Zigbee2MQTTClient(
            "mosquitto",
            username="testuser",
            password="testpass",
        )
        assert client.username == "testuser"
        assert client.password == "testpass"


class TestCallbacks:
    """Tests for the internal MQTT callbacks."""

    def test_on_connect_success_subscribes(self):
        client = Zigbee2MQTTClient("mosquitto")
        fake_client = MagicMock()
        client._on_connect(fake_client, None, None, 0)
        fake_client.subscribe.assert_called_once_with("zigbee2mqtt/bridge/devices")

    def test_on_connect_failure_does_not_subscribe(self):
        client = Zigbee2MQTTClient("mosquitto")
        fake_client = MagicMock()
        client._on_connect(fake_client, None, None, 5)
        fake_client.subscribe.assert_not_called()

    def test_on_message_devices_topic_sets_state(self):
        client = Zigbee2MQTTClient("mosquitto")
        msg = _make_msg("zigbee2mqtt/bridge/devices", SAMPLE_DEVICES)
        client._on_message(None, None, msg)
        assert client.devices == SAMPLE_DEVICES
        assert client.response_received is True

    def test_on_message_other_topic_ignored(self):
        client = Zigbee2MQTTClient("mosquitto")
        msg = _make_msg("zigbee2mqtt/some/other", SAMPLE_DEVICES)
        client._on_message(None, None, msg)
        assert client.devices == []
        assert client.response_received is False

    def test_on_message_invalid_json_does_not_crash(self):
        client = Zigbee2MQTTClient("mosquitto")
        msg = _make_msg("zigbee2mqtt/bridge/devices", b"not-json{")
        client._on_message(None, None, msg)
        # Error is swallowed; state is left untouched.
        assert client.devices == []
        assert client.response_received is False


class TestGetDevices:
    """Tests for get_devices — connect, publish, subscribe and disconnect."""

    @patch(MQTT_PATH)
    def test_connect_publish_and_disconnect(self, mock_mqtt):
        """A successful round trip connects, publishes the request, and cleans up."""
        fake_client = mock_mqtt.Client.return_value
        client = Zigbee2MQTTClient("mosquitto", timeout=1.0)

        # Simulate the broker delivering the devices payload as soon as the
        # background loop starts, so the polling wait returns immediately.
        def deliver_devices():
            client.response_received = True
            client.devices = SAMPLE_DEVICES

        fake_client.loop_start.side_effect = deliver_devices

        result = client.get_devices()

        assert result == SAMPLE_DEVICES
        fake_client.connect.assert_called_once_with("mosquitto", 1883, 60)
        fake_client.loop_start.assert_called_once()
        fake_client.publish.assert_called_once_with("zigbee2mqtt/bridge/request/devices", "")
        # Callbacks are wired up.
        assert fake_client.on_connect == client._on_connect
        assert fake_client.on_message == client._on_message
        # Cleanup always runs.
        fake_client.loop_stop.assert_called_once()
        fake_client.disconnect.assert_called_once()

    @patch(MQTT_PATH)
    def test_connect_with_credentials(self, mock_mqtt):
        """Credentials are set when provided."""
        fake_client = mock_mqtt.Client.return_value
        client = Zigbee2MQTTClient(
            "mosquitto",
            timeout=1.0,
            username="testuser",
            password="testpass",
        )

        def deliver_devices():
            client.response_received = True
            client.devices = SAMPLE_DEVICES

        fake_client.loop_start.side_effect = deliver_devices

        client.get_devices()

        fake_client.username_pw_set.assert_called_once_with("testuser", "testpass")

    @patch(MQTT_PATH)
    def test_connect_without_credentials(self, mock_mqtt):
        """Credentials are not set when not provided."""
        fake_client = mock_mqtt.Client.return_value
        client = Zigbee2MQTTClient("mosquitto", timeout=1.0)

        def deliver_devices():
            client.response_received = True
            client.devices = SAMPLE_DEVICES

        fake_client.loop_start.side_effect = deliver_devices

        client.get_devices()

        fake_client.username_pw_set.assert_not_called()

    @patch(MQTT_PATH)
    def test_timeout_raises_and_cleans_up(self, mock_mqtt):
        """No response within the timeout raises and still disconnects."""
        fake_client = mock_mqtt.Client.return_value
        client = Zigbee2MQTTClient("mosquitto", timeout=0.2)

        with pytest.raises(Exception, match="Timeout"):
            client.get_devices()

        fake_client.loop_stop.assert_called_once()
        fake_client.disconnect.assert_called_once()

    @patch(MQTT_PATH)
    def test_connect_error_propagates_and_cleans_up(self, mock_mqtt):
        """A connection failure propagates and the finally block still runs."""
        fake_client = mock_mqtt.Client.return_value
        fake_client.connect.side_effect = ConnectionError("broker down")
        client = Zigbee2MQTTClient("mosquitto", timeout=0.2)

        with pytest.raises(ConnectionError, match="broker down"):
            client.get_devices()

        fake_client.loop_stop.assert_called_once()
        fake_client.disconnect.assert_called_once()


class TestDiscoverTemperatureSensors:
    """Tests for discover_temperature_sensors."""

    def test_filters_temperature_sensors(self):
        client = Zigbee2MQTTClient("mosquitto")
        with patch.object(client, "get_devices", return_value=SAMPLE_DEVICES):
            sensors = client.discover_temperature_sensors()
        # Only the Aqara sensor exposes temperature; coordinator and plug excluded.
        assert sensors == ["sensor_salon"]

    def test_climate_feature_detected(self):
        client = Zigbee2MQTTClient("mosquitto")
        devices = [
            {
                "friendly_name": "termostato",
                "type": "EndDevice",
                "definition": {
                    "exposes": [
                        {
                            "type": "climate",
                            "features": [{"property": "temperature"}],
                        }
                    ]
                },
            }
        ]
        with patch.object(client, "get_devices", return_value=devices):
            sensors = client.discover_temperature_sensors()
        assert sensors == ["termostato"]

    def test_coordinator_is_skipped(self):
        client = Zigbee2MQTTClient("mosquitto")
        devices = [{"friendly_name": "Coordinator", "type": "Coordinator"}]
        with patch.object(client, "get_devices", return_value=devices):
            sensors = client.discover_temperature_sensors()
        assert sensors == []

    def test_device_without_definition_is_skipped(self):
        client = Zigbee2MQTTClient("mosquitto")
        devices = [{"friendly_name": "orphan", "type": "EndDevice"}]
        with patch.object(client, "get_devices", return_value=devices):
            sensors = client.discover_temperature_sensors()
        assert sensors == []

    def test_sensor_without_friendly_name_is_skipped(self):
        client = Zigbee2MQTTClient("mosquitto")
        devices = [
            {
                "type": "EndDevice",
                "definition": {"exposes": [{"property": "temperature"}]},
            }
        ]
        with patch.object(client, "get_devices", return_value=devices):
            sensors = client.discover_temperature_sensors()
        assert sensors == []

    def test_get_devices_error_returns_empty_list(self):
        client = Zigbee2MQTTClient("mosquitto")
        with patch.object(client, "get_devices", side_effect=Exception("broker down")):
            sensors = client.discover_temperature_sensors()
        # Discovery degrades gracefully so the system can fall back to manual config.
        assert sensors == []
