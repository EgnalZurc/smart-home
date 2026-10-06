"""Unit tests for zigbee2mqtt_client.py - Zigbee2MQTT device discovery."""

import json
from unittest.mock import MagicMock, patch

from zigbee2mqtt_client import Zigbee2MQTTClient


class TestZigbee2MQTTClientInit:
    def test_default_values(self):
        client = Zigbee2MQTTClient("localhost")
        assert client.mqtt_broker == "localhost"
        assert client.mqtt_port == 1883
        assert client.timeout == 10.0
        assert client.devices == []
        assert client.response_received is False

    def test_custom_values(self):
        client = Zigbee2MQTTClient("mqtt.local", mqtt_port=1884, timeout=30.0)
        assert client.mqtt_broker == "mqtt.local"
        assert client.mqtt_port == 1884
        assert client.timeout == 30.0


class TestOnConnect:
    def test_successful_connection_subscribes(self):
        client = Zigbee2MQTTClient("localhost")
        mock_mqtt = MagicMock()

        client._on_connect(mock_mqtt, None, None, 0)

        mock_mqtt.subscribe.assert_called_once_with("zigbee2mqtt/bridge/devices")

    def test_failed_connection_logs_error(self):
        client = Zigbee2MQTTClient("localhost")
        mock_mqtt = MagicMock()

        with patch("zigbee2mqtt_client.logger") as mock_logger:
            client._on_connect(mock_mqtt, None, None, 1)  # rc=1 = connection refused

        mock_logger.error.assert_called()


class TestOnMessage:
    def test_parses_devices_json(self):
        client = Zigbee2MQTTClient("localhost")
        mock_msg = MagicMock()
        mock_msg.topic = "zigbee2mqtt/bridge/devices"
        mock_msg.payload = json.dumps(
            [
                {"friendly_name": "sensor1", "ieee_address": "0x00158d0001"},
                {"friendly_name": "sensor2", "ieee_address": "0x00158d0002"},
            ]
        ).encode()

        client._on_message(None, None, mock_msg)

        assert len(client.devices) == 2
        assert client.devices[0]["friendly_name"] == "sensor1"
        assert client.response_received is True

    def test_handles_invalid_json(self):
        client = Zigbee2MQTTClient("localhost")
        mock_msg = MagicMock()
        mock_msg.topic = "zigbee2mqtt/bridge/devices"
        mock_msg.payload = b"not valid json"

        with patch("zigbee2mqtt_client.logger") as mock_logger:
            client._on_message(None, None, mock_msg)

        mock_logger.error.assert_called()
        assert client.devices == []

    def test_ignores_other_topics(self):
        client = Zigbee2MQTTClient("localhost")
        mock_msg = MagicMock()
        mock_msg.topic = "zigbee2mqtt/other/topic"
        mock_msg.payload = b'{"data": "test"}'

        client._on_message(None, None, mock_msg)

        assert client.devices == []
        assert client.response_received is False


class TestGetDevices:
    @patch("zigbee2mqtt_client.mqtt.Client")
    def test_successful_device_fetch(self, mock_mqtt_class):
        mock_client = MagicMock()
        mock_mqtt_class.return_value = mock_client

        client = Zigbee2MQTTClient("localhost", timeout=0.1)

        # Simulate response
        def simulate_connect(*args, **kwargs):
            client.devices = [{"friendly_name": "test", "ieee_address": "0x001"}]
            client.response_received = True

        mock_client.connect.side_effect = simulate_connect

        result = client.get_devices()

        assert len(result) == 1
        assert result[0]["friendly_name"] == "test"
        mock_client.loop_start.assert_called_once()
        mock_client.loop_stop.assert_called_once()
        mock_client.disconnect.assert_called_once()

    @patch("zigbee2mqtt_client.mqtt.Client")
    def test_timeout_raises_exception(self, mock_mqtt_class):
        mock_client = MagicMock()
        mock_mqtt_class.return_value = mock_client

        client = Zigbee2MQTTClient("localhost", timeout=0.1)

        try:
            client.get_devices()
            assert False, "Should have raised exception"
        except Exception as e:
            assert "Timeout" in str(e)

    @patch("zigbee2mqtt_client.mqtt.Client")
    def test_connection_error_raises_exception(self, mock_mqtt_class):
        mock_client = MagicMock()
        mock_client.connect.side_effect = Exception("Connection refused")
        mock_mqtt_class.return_value = mock_client

        client = Zigbee2MQTTClient("localhost")

        try:
            client.get_devices()
            assert False, "Should have raised exception"
        except Exception as e:
            assert "Connection refused" in str(e)


class TestDiscoverTemperatureSensors:
    @patch.object(Zigbee2MQTTClient, "get_devices")
    def test_finds_temperature_sensors(self, mock_get_devices):
        mock_get_devices.return_value = [
            {
                "friendly_name": "Coordinator",
                "type": "Coordinator",
            },
            {
                "friendly_name": "TempSensor1",
                "type": "EndDevice",
                "definition": {
                    "exposes": [{"property": "temperature"}, {"property": "humidity"}]
                },
            },
            {
                "friendly_name": "Switch1",
                "type": "Router",
                "definition": {"exposes": [{"property": "state"}]},
            },
        ]

        client = Zigbee2MQTTClient("localhost")
        sensors = client.discover_temperature_sensors()

        assert sensors == ["TempSensor1"]

    @patch.object(Zigbee2MQTTClient, "get_devices")
    def test_ignores_coordinator(self, mock_get_devices):
        mock_get_devices.return_value = [
            {
                "friendly_name": "Coordinator",
                "type": "Coordinator",
                "definition": {"exposes": [{"property": "temperature"}]},
            }
        ]

        client = Zigbee2MQTTClient("localhost")
        sensors = client.discover_temperature_sensors()

        assert sensors == []

    @patch.object(Zigbee2MQTTClient, "get_devices")
    def test_handles_climate_devices(self, mock_get_devices):
        mock_get_devices.return_value = [
            {
                "friendly_name": "Thermostat",
                "type": "EndDevice",
                "definition": {
                    "exposes": [
                        {
                            "type": "climate",
                            "features": [
                                {"property": "temperature"},
                                {"property": "setpoint"},
                            ],
                        }
                    ]
                },
            }
        ]

        client = Zigbee2MQTTClient("localhost")
        sensors = client.discover_temperature_sensors()

        assert sensors == ["Thermostat"]

    @patch.object(Zigbee2MQTTClient, "get_devices")
    def test_handles_missing_definition(self, mock_get_devices):
        mock_get_devices.return_value = [
            {"friendly_name": "Unknown", "type": "EndDevice"}
        ]

        client = Zigbee2MQTTClient("localhost")
        sensors = client.discover_temperature_sensors()

        assert sensors == []

    @patch.object(Zigbee2MQTTClient, "get_devices")
    def test_returns_empty_on_error(self, mock_get_devices):
        mock_get_devices.side_effect = Exception("Network error")

        client = Zigbee2MQTTClient("localhost")
        sensors = client.discover_temperature_sensors()

        assert sensors == []

    @patch.object(Zigbee2MQTTClient, "get_devices")
    def test_handles_missing_friendly_name(self, mock_get_devices):
        mock_get_devices.return_value = [
            {
                "type": "EndDevice",
                "definition": {"exposes": [{"property": "temperature"}]},
            }
        ]

        client = Zigbee2MQTTClient("localhost")
        sensors = client.discover_temperature_sensors()

        assert sensors == []  # No friendly_name means it's not added
