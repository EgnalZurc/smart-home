"""Unit tests for MqttHandler.

Tests the MQTT handler that manages sensor readings
and maintains connection with the Zigbee2MQTT broker.
"""

import json
import time
from unittest.mock import MagicMock, patch

from smart_home_common.mqtt.handler import MqttHandler, SensorReading


class TestSensorReading:
    """Tests for SensorReading class."""

    def test_init_stores_values(self):
        """Should store all sensor values."""
        reading = SensorReading(
            temperature=25.5,
            humidity=60.0,
            battery=95,
            timestamp=1234567890.0,
        )

        assert reading.temperature == 25.5
        assert reading.humidity == 60.0
        assert reading.battery == 95
        assert reading.timestamp == 1234567890.0

    def test_to_dict(self):
        """to_dict should return dictionary representation."""
        reading = SensorReading(
            temperature=24.0,
            humidity=55.0,
            battery=80,
            timestamp=9999999999.0,
        )

        data = reading.to_dict()

        assert data["temperature"] == 24.0
        assert data["humidity"] == 55.0
        assert data["battery"] == 80
        assert data["timestamp"] == 9999999999.0

    def test_from_dict(self):
        """from_dict should create reading from dictionary."""
        data = {
            "temperature": 26.5,
            "humidity": 70.0,
            "battery": 50,
            "timestamp": 1111111111.0,
        }

        reading = SensorReading.from_dict(data)

        assert reading.temperature == 26.5
        assert reading.humidity == 70.0
        assert reading.battery == 50
        assert reading.timestamp == 1111111111.0

    def test_roundtrip(self):
        """to_dict and from_dict should be reversible."""
        original = SensorReading(
            temperature=23.0,
            humidity=45.0,
            battery=100,
            timestamp=time.time(),
        )

        data = original.to_dict()
        restored = SensorReading.from_dict(data)

        assert restored.temperature == original.temperature
        assert restored.humidity == original.humidity
        assert restored.battery == original.battery
        assert restored.timestamp == original.timestamp


class TestMqttHandlerInit:
    """Tests for MqttHandler initialization."""

    def test_init_stores_config(self, tmp_path):
        """Should store configuration values."""
        persist_file = tmp_path / "sensors.json"

        with patch("smart_home_common.mqtt.handler.PERSIST_FILE", str(persist_file)):
            handler = MqttHandler(
                broker="localhost",
                port=1883,
                sensor_names=["sensor1", "sensor2"],
                connect_retries=10,
                retry_delay=1,
                keepalive=30,
                max_history=100,
            )

        assert handler.broker == "localhost"
        assert handler.port == 1883
        assert handler.sensor_names == ["sensor1", "sensor2"]
        assert handler.connect_retries == 10
        assert handler.retry_delay == 1
        assert handler.keepalive == 30
        assert handler.max_history == 100

    def test_init_loads_persisted_data(self, tmp_path):
        """Should load persisted sensor data on init."""
        persist_file = tmp_path / "sensors.json"

        data = {
            "sensor1": [
                {
                    "temperature": 25.0,
                    "humidity": 50.0,
                    "battery": 90,
                    "timestamp": 1000.0,
                },
                {
                    "temperature": 26.0,
                    "humidity": 55.0,
                    "battery": 89,
                    "timestamp": 2000.0,
                },
            ]
        }
        persist_file.write_text(json.dumps(data), encoding="utf-8")

        with patch("smart_home_common.mqtt.handler.PERSIST_FILE", str(persist_file)):
            handler = MqttHandler(
                broker="localhost",
                port=1883,
                sensor_names=["sensor1"],
            )

        assert "sensor1" in handler.readings
        assert handler.readings["sensor1"].temperature == 26.0  # Last reading
        assert len(handler.history["sensor1"]) == 2


class TestMqttHandlerCallbacks:
    """Tests for MQTT callback methods."""

    def test_on_connect_subscribes(self, tmp_path):
        """Should subscribe to sensor topics on connect."""
        persist_file = tmp_path / "sensors.json"

        with patch("smart_home_common.mqtt.handler.PERSIST_FILE", str(persist_file)):
            handler = MqttHandler(
                broker="localhost",
                port=1883,
                sensor_names=["sensor1"],
            )

        # Initialize _error_tracker as it would be in production (via start())
        handler._error_tracker = None

        mock_client = MagicMock()
        handler._on_connect(mock_client, None, None, 0, None)

        mock_client.subscribe.assert_called_once_with("zigbee2mqtt/+")
        assert handler._connected is True

    def test_on_connect_clears_error(self, tmp_path):
        """Should clear mqtt_disconnected error on connect."""
        persist_file = tmp_path / "sensors.json"

        with patch("smart_home_common.mqtt.handler.PERSIST_FILE", str(persist_file)):
            handler = MqttHandler(
                broker="localhost",
                port=1883,
                sensor_names=[],
            )

        mock_tracker = MagicMock()
        handler.set_error_tracker(mock_tracker)

        handler._on_connect(MagicMock(), None, None, 0, None)

        mock_tracker.clear.assert_called_with("mqtt_disconnected")

    def test_on_disconnect_sets_flag(self, tmp_path):
        """Should set connected flag to False on disconnect."""
        persist_file = tmp_path / "sensors.json"

        with patch("smart_home_common.mqtt.handler.PERSIST_FILE", str(persist_file)):
            handler = MqttHandler(
                broker="localhost",
                port=1883,
                sensor_names=[],
            )

        handler._connected = True
        handler._error_tracker = (
            None  # Initialize as it would be before set_error_tracker()
        )
        handler._on_disconnect(MagicMock(), None, None, 0, None)

        assert handler._connected is False

    def test_on_disconnect_registers_error(self, tmp_path):
        """Should register error on disconnect."""
        persist_file = tmp_path / "sensors.json"

        with patch("smart_home_common.mqtt.handler.PERSIST_FILE", str(persist_file)):
            handler = MqttHandler(
                broker="localhost",
                port=1883,
                sensor_names=[],
            )

        mock_tracker = MagicMock()
        handler.set_error_tracker(mock_tracker)

        handler._on_disconnect(MagicMock(), None, None, 0, None)

        mock_tracker.register.assert_called_once()
        call_args = mock_tracker.register.call_args
        assert call_args[0][0] == "mqtt_disconnected"

    def test_on_message_processes_sensor_data(self, tmp_path):
        """Should process sensor data from message."""
        persist_file = tmp_path / "sensors.json"

        with patch("smart_home_common.mqtt.handler.PERSIST_FILE", str(persist_file)):
            handler = MqttHandler(
                broker="localhost",
                port=1883,
                sensor_names=["TempSensor1"],
            )

        mock_msg = MagicMock()
        mock_msg.topic = "zigbee2mqtt/TempSensor1"
        mock_msg.payload = json.dumps(
            {
                "temperature": 24.5,
                "humidity": 55.0,
                "battery": 95,
            }
        ).encode()

        handler._on_message(None, None, mock_msg)

        assert "TempSensor1" in handler.readings
        assert handler.readings["TempSensor1"].temperature == 24.5
        assert handler.readings["TempSensor1"].humidity == 55.0
        assert handler.readings["TempSensor1"].battery == 95

    def test_on_message_ignores_unknown_sensor(self, tmp_path):
        """Should ignore messages from unknown sensors."""
        persist_file = tmp_path / "sensors.json"

        with patch("smart_home_common.mqtt.handler.PERSIST_FILE", str(persist_file)):
            handler = MqttHandler(
                broker="localhost",
                port=1883,
                sensor_names=["KnownSensor"],
            )

        mock_msg = MagicMock()
        mock_msg.topic = "zigbee2mqtt/UnknownSensor"
        mock_msg.payload = json.dumps({"temperature": 25.0}).encode()

        handler._on_message(None, None, mock_msg)

        assert "UnknownSensor" not in handler.readings

    def test_on_message_ignores_no_temperature(self, tmp_path):
        """Should ignore messages without temperature."""
        persist_file = tmp_path / "sensors.json"

        with patch("smart_home_common.mqtt.handler.PERSIST_FILE", str(persist_file)):
            handler = MqttHandler(
                broker="localhost",
                port=1883,
                sensor_names=["Sensor1"],
            )

        mock_msg = MagicMock()
        mock_msg.topic = "zigbee2mqtt/Sensor1"
        mock_msg.payload = json.dumps({"humidity": 50.0}).encode()  # No temperature

        handler._on_message(None, None, mock_msg)

        assert "Sensor1" not in handler.readings

    def test_on_message_handles_invalid_json(self, tmp_path):
        """Should handle invalid JSON gracefully."""
        persist_file = tmp_path / "sensors.json"

        with patch("smart_home_common.mqtt.handler.PERSIST_FILE", str(persist_file)):
            handler = MqttHandler(
                broker="localhost",
                port=1883,
                sensor_names=["Sensor1"],
            )

        mock_msg = MagicMock()
        mock_msg.topic = "zigbee2mqtt/Sensor1"
        mock_msg.payload = b"not json"

        # Should not raise
        handler._on_message(None, None, mock_msg)


class TestMqttHandlerHistory:
    """Tests for history management."""

    def test_history_limited_to_max(self, tmp_path):
        """Should limit history to max_history entries."""
        persist_file = tmp_path / "sensors.json"

        with patch("smart_home_common.mqtt.handler.PERSIST_FILE", str(persist_file)):
            handler = MqttHandler(
                broker="localhost",
                port=1883,
                sensor_names=["Sensor1"],
                max_history=5,
            )

        # Add more readings than max_history
        for i in range(10):
            mock_msg = MagicMock()
            mock_msg.topic = "zigbee2mqtt/Sensor1"
            mock_msg.payload = json.dumps(
                {
                    "temperature": 20.0 + i,
                    "humidity": 50.0,
                    "battery": 100,
                }
            ).encode()
            handler._on_message(None, None, mock_msg)

        assert len(handler.history["Sensor1"]) == 5
        # Should keep most recent
        assert handler.history["Sensor1"][-1].temperature == 29.0


class TestMqttHandlerAverages:
    """Tests for average calculations."""

    def test_get_average_temperature(self, tmp_path):
        """Should calculate average temperature from active sensors."""
        persist_file = tmp_path / "sensors.json"
        now = time.time()

        with patch("smart_home_common.mqtt.handler.PERSIST_FILE", str(persist_file)):
            handler = MqttHandler(
                broker="localhost",
                port=1883,
                sensor_names=["S1", "S2", "S3"],
            )

        # Add readings
        handler.readings["S1"] = SensorReading(24.0, 50.0, 90, now)
        handler.readings["S2"] = SensorReading(26.0, 60.0, 80, now)
        handler.readings["S3"] = SensorReading(25.0, 55.0, 70, now)

        avg = handler.get_average_temperature(max_age_seconds=600)

        assert avg == 25.0  # (24 + 26 + 25) / 3

    def test_get_average_temperature_excludes_old(self, tmp_path):
        """Should exclude sensors with old readings."""
        persist_file = tmp_path / "sensors.json"
        now = time.time()

        with patch("smart_home_common.mqtt.handler.PERSIST_FILE", str(persist_file)):
            handler = MqttHandler(
                broker="localhost",
                port=1883,
                sensor_names=["S1", "S2"],
            )

        handler.readings["S1"] = SensorReading(24.0, 50.0, 90, now)
        handler.readings["S2"] = SensorReading(30.0, 60.0, 80, now - 1000)  # Old

        avg = handler.get_average_temperature(max_age_seconds=600)

        assert avg == 24.0  # Only S1 is active

    def test_get_average_temperature_returns_none_if_empty(self, tmp_path):
        """Should return None if no active sensors."""
        persist_file = tmp_path / "sensors.json"

        with patch("smart_home_common.mqtt.handler.PERSIST_FILE", str(persist_file)):
            handler = MqttHandler(
                broker="localhost",
                port=1883,
                sensor_names=[],
            )

        avg = handler.get_average_temperature()

        assert avg is None

    def test_get_average_humidity(self, tmp_path):
        """Should calculate average humidity."""
        persist_file = tmp_path / "sensors.json"
        now = time.time()

        with patch("smart_home_common.mqtt.handler.PERSIST_FILE", str(persist_file)):
            handler = MqttHandler(
                broker="localhost",
                port=1883,
                sensor_names=["S1", "S2"],
            )

        handler.readings["S1"] = SensorReading(24.0, 40.0, 90, now)
        handler.readings["S2"] = SensorReading(26.0, 60.0, 80, now)

        avg = handler.get_average_humidity()

        assert avg == 50.0  # (40 + 60) / 2


class TestMqttHandlerActiveReadings:
    """Tests for get_active_readings method."""

    def test_get_active_readings_filters_by_age(self, tmp_path):
        """Should only return readings within max_age."""
        persist_file = tmp_path / "sensors.json"
        now = time.time()

        with patch("smart_home_common.mqtt.handler.PERSIST_FILE", str(persist_file)):
            handler = MqttHandler(
                broker="localhost",
                port=1883,
                sensor_names=["S1", "S2", "S3"],
            )

        handler.readings["S1"] = SensorReading(24.0, 50.0, 90, now)
        handler.readings["S2"] = SensorReading(25.0, 55.0, 80, now - 100)  # 100s old
        handler.readings["S3"] = SensorReading(26.0, 60.0, 70, now - 1000)  # 1000s old

        active = handler.get_active_readings(max_age_seconds=600)

        assert len(active) == 2
        assert "S1" in active
        assert "S2" in active
        assert "S3" not in active


class TestMqttHandlerRecordAcTemp:
    """Tests for record_ac_temp method."""

    def test_record_ac_temp_adds_to_history(self, tmp_path):
        """Should add AC room temp to history."""
        persist_file = tmp_path / "sensors.json"

        with patch("smart_home_common.mqtt.handler.PERSIST_FILE", str(persist_file)):
            handler = MqttHandler(
                broker="localhost",
                port=1883,
                sensor_names=[],
            )

        handler.record_ac_temp(23.5)

        assert "AC" in handler.history
        assert len(handler.history["AC"]) == 1
        assert handler.history["AC"][0].temperature == 23.5

    def test_record_ac_temp_limits_history(self, tmp_path):
        """Should limit AC history to max_history."""
        persist_file = tmp_path / "sensors.json"

        with patch("smart_home_common.mqtt.handler.PERSIST_FILE", str(persist_file)):
            handler = MqttHandler(
                broker="localhost",
                port=1883,
                sensor_names=[],
                max_history=3,
            )

        for temp in [20.0, 21.0, 22.0, 23.0, 24.0]:
            handler.record_ac_temp(temp)

        assert len(handler.history["AC"]) == 3
        assert handler.history["AC"][-1].temperature == 24.0


class TestMqttHandlerIsConnected:
    """Tests for is_connected property."""

    def test_is_connected_returns_flag(self, tmp_path):
        """Should return connection flag value."""
        persist_file = tmp_path / "sensors.json"

        with patch("smart_home_common.mqtt.handler.PERSIST_FILE", str(persist_file)):
            handler = MqttHandler(
                broker="localhost",
                port=1883,
                sensor_names=[],
            )

        assert handler.is_connected is False

        handler._connected = True
        assert handler.is_connected is True
