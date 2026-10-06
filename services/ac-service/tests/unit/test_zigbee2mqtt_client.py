"""Unit tests for Zigbee2MQTTClient.

Tests the MQTT client that discovers temperature sensors
from Zigbee2MQTT bridge.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from zigbee2mqtt_client import Zigbee2MQTTClient


class TestZigbee2MQTTClientInit:
    """Tests for Zigbee2MQTTClient initialization."""

    def test_default_values(self):
        """Should initialize with default values."""
        client = Zigbee2MQTTClient("localhost")

        assert client.mqtt_broker == "localhost"
        assert client.mqtt_port == 1883
        assert client.timeout == 10.0
        assert client.devices == []
        assert client.response_received is False

    def test_custom_port_and_timeout(self):
        """Should accept custom port and timeout."""
        client = Zigbee2MQTTClient("broker.local", mqtt_port=1884, timeout=30.0)

        assert client.mqtt_broker == "broker.local"
        assert client.mqtt_port == 1884
        assert client.timeout == 30.0


class TestZigbee2MQTTClientCallbacks:
    """Tests for MQTT callback methods."""

    def test_on_connect_subscribes_to_devices(self):
        """Should subscribe to devices topic on connect."""
        client = Zigbee2MQTTClient("localhost")
        mock_mqtt_client = MagicMock()

        # Simulate successful connection
        client._on_connect(mock_mqtt_client, None, None, 0)

        mock_mqtt_client.subscribe.assert_called_once_with("zigbee2mqtt/bridge/devices")

    def test_on_connect_error_does_not_subscribe(self):
        """Should not subscribe on connection error."""
        client = Zigbee2MQTTClient("localhost")
        mock_mqtt_client = MagicMock()

        # Simulate failed connection (rc != 0)
        client._on_connect(mock_mqtt_client, None, None, 5)

        mock_mqtt_client.subscribe.assert_not_called()

    def test_on_message_parses_devices(self):
        """Should parse device list from message."""
        client = Zigbee2MQTTClient("localhost")

        devices = [
            {"friendly_name": "sensor1", "type": "EndDevice"},
            {"friendly_name": "sensor2", "type": "Router"},
        ]

        mock_msg = MagicMock()
        mock_msg.topic = "zigbee2mqtt/bridge/devices"
        mock_msg.payload = json.dumps(devices).encode()

        client._on_message(None, None, mock_msg)

        assert len(client.devices) == 2
        assert client.response_received is True

    def test_on_message_ignores_wrong_topic(self):
        """Should ignore messages from wrong topic."""
        client = Zigbee2MQTTClient("localhost")

        mock_msg = MagicMock()
        mock_msg.topic = "zigbee2mqtt/other/topic"
        mock_msg.payload = b'{"data": "test"}'

        client._on_message(None, None, mock_msg)

        assert client.devices == []
        assert client.response_received is False

    def test_on_message_handles_invalid_json(self):
        """Should handle invalid JSON gracefully."""
        client = Zigbee2MQTTClient("localhost")

        mock_msg = MagicMock()
        mock_msg.topic = "zigbee2mqtt/bridge/devices"
        mock_msg.payload = b"not valid json"

        # Should not raise
        client._on_message(None, None, mock_msg)

        assert client.devices == []


class TestZigbee2MQTTClientGetDevices:
    """Tests for get_devices method."""

    def test_get_devices_returns_list(self):
        """Should return device list from MQTT."""
        client = Zigbee2MQTTClient("localhost", timeout=1.0)

        devices = [
            {"friendly_name": "sensor1", "ieee_address": "0x1234"},
            {"friendly_name": "sensor2", "ieee_address": "0x5678"},
        ]

        with patch("paho.mqtt.client.Client") as MockClient:
            mock_instance = MagicMock()
            MockClient.return_value = mock_instance

            # Simulate connection and message reception
            def trigger_connect(*args, **kwargs):
                # Call on_connect callback
                mock_instance.on_connect(mock_instance, None, None, 0, None)

            def trigger_message(*args, **kwargs):
                # Simulate receiving devices after loop_start
                client.devices = devices
                client.response_received = True

            mock_instance.connect.side_effect = trigger_connect
            mock_instance.loop_start.side_effect = trigger_message

            result = client.get_devices()

        assert result == devices

    def test_get_devices_timeout_raises(self):
        """Should raise exception on timeout."""
        client = Zigbee2MQTTClient("localhost", timeout=0.1)

        with patch("paho.mqtt.client.Client") as MockClient:
            mock_instance = MagicMock()
            MockClient.return_value = mock_instance

            # Don't set response_received, causing timeout
            with pytest.raises(Exception) as exc_info:
                client.get_devices()

            assert "Timeout" in str(exc_info.value)

    def test_get_devices_connection_error(self):
        """Should raise on connection error."""
        client = Zigbee2MQTTClient("localhost")

        with patch("paho.mqtt.client.Client") as MockClient:
            mock_instance = MagicMock()
            MockClient.return_value = mock_instance
            mock_instance.connect.side_effect = Exception("Connection refused")

            with pytest.raises(Exception) as exc_info:
                client.get_devices()

            assert "Connection refused" in str(exc_info.value)


class TestZigbee2MQTTClientDiscoverSensors:
    """Tests for discover_temperature_sensors method."""

    def test_discovers_temperature_sensors(self):
        """Should return only temperature sensor names."""
        client = Zigbee2MQTTClient("localhost", timeout=0.5)

        devices = [
            {
                "friendly_name": "Coordinator",
                "type": "Coordinator",
            },
            {
                "friendly_name": "TempSensor1",
                "type": "EndDevice",
                "definition": {
                    "exposes": [{"property": "temperature"}],
                },
            },
            {
                "friendly_name": "Switch1",
                "type": "Router",
                "definition": {
                    "exposes": [{"property": "state"}],
                },
            },
            {
                "friendly_name": "TempSensor2",
                "type": "EndDevice",
                "definition": {
                    "exposes": [
                        {"property": "temperature"},
                        {"property": "humidity"},
                    ],
                },
            },
        ]

        with patch.object(client, "get_devices", return_value=devices):
            sensors = client.discover_temperature_sensors()

        assert len(sensors) == 2
        assert "TempSensor1" in sensors
        assert "TempSensor2" in sensors
        assert "Coordinator" not in sensors
        assert "Switch1" not in sensors

    def test_discovers_climate_devices(self):
        """Should discover climate devices with temperature feature."""
        client = Zigbee2MQTTClient("localhost", timeout=0.5)

        devices = [
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
                    ],
                },
            },
        ]

        with patch.object(client, "get_devices", return_value=devices):
            sensors = client.discover_temperature_sensors()

        assert "Thermostat" in sensors

    def test_ignores_devices_without_definition(self):
        """Should ignore devices without definition."""
        client = Zigbee2MQTTClient("localhost", timeout=0.5)

        devices = [
            {
                "friendly_name": "Unknown",
                "type": "EndDevice",
                # No 'definition' key
            },
        ]

        with patch.object(client, "get_devices", return_value=devices):
            sensors = client.discover_temperature_sensors()

        assert sensors == []

    def test_returns_empty_on_error(self):
        """Should return empty list on error (graceful degradation)."""
        client = Zigbee2MQTTClient("localhost", timeout=0.5)

        with patch.object(
            client, "get_devices", side_effect=Exception("Network error")
        ):
            sensors = client.discover_temperature_sensors()

        assert sensors == []

    def test_ignores_devices_without_friendly_name(self):
        """Should ignore devices without friendly_name."""
        client = Zigbee2MQTTClient("localhost", timeout=0.5)

        devices = [
            {
                # No friendly_name
                "type": "EndDevice",
                "definition": {
                    "exposes": [{"property": "temperature"}],
                },
            },
        ]

        with patch.object(client, "get_devices", return_value=devices):
            sensors = client.discover_temperature_sensors()

        assert sensors == []
