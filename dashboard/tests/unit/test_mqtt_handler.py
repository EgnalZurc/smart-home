"""Unit tests for mqtt_handler.py - MQTT sensor management."""

import json
import shutil
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def temp_persist_file():
    """Create temporary persist file."""
    temp_dir = tempfile.mkdtemp()
    persist_file = str(Path(temp_dir) / "sensor_readings.json")
    yield persist_file
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def mqtt_handler(temp_persist_file):
    """Create MqttHandler with mocked MQTT client."""
    with patch.dict("os.environ", {"SENSOR_PERSIST_FILE": temp_persist_file}):
        with patch("mqtt_handler.mqtt.Client") as mock_client:
            from mqtt_handler import MqttHandler

            handler = MqttHandler(
                broker="localhost",
                port=1883,
                sensor_names=["sensor1", "sensor2"],
                connect_retries=1,
                retry_delay=0,
            )
            handler._client = mock_client.return_value
            yield handler


class TestSensorReading:
    def test_init(self):
        from mqtt_handler import SensorReading

        reading = SensorReading(
            temperature=23.5, humidity=65.0, battery=95, timestamp=1234567890.0
        )

        assert reading.temperature == 23.5
        assert reading.humidity == 65.0
        assert reading.battery == 95
        assert reading.timestamp == 1234567890.0

    def test_to_dict(self):
        from mqtt_handler import SensorReading

        reading = SensorReading(
            temperature=23.5, humidity=65.0, battery=95, timestamp=1234567890.0
        )
        d = reading.to_dict()

        assert d["temperature"] == 23.5
        assert d["humidity"] == 65.0
        assert d["battery"] == 95
        assert d["timestamp"] == 1234567890.0

    def test_from_dict(self):
        from mqtt_handler import SensorReading

        d = {
            "temperature": 23.5,
            "humidity": 65.0,
            "battery": 95,
            "timestamp": 1234567890.0,
        }
        reading = SensorReading.from_dict(d)

        assert reading.temperature == 23.5
        assert reading.humidity == 65.0
        assert reading.battery == 95


class TestMqttHandlerInit:
    def test_init_sets_attributes(self, temp_persist_file):
        with patch.dict("os.environ", {"SENSOR_PERSIST_FILE": temp_persist_file}):
            with patch("mqtt_handler.mqtt.Client"):
                from mqtt_handler import MqttHandler

                handler = MqttHandler(
                    broker="test-broker",
                    port=1884,
                    sensor_names=["s1", "s2"],
                    max_history=100,
                )

                assert handler.broker == "test-broker"
                assert handler.port == 1884
                assert handler.sensor_names == ["s1", "s2"]
                assert handler.max_history == 100


class TestMqttHandlerCallbacks:
    def test_on_message_parses_sensor(self, mqtt_handler):
        msg = MagicMock()
        msg.topic = "zigbee2mqtt/sensor1"
        msg.payload = json.dumps(
            {"temperature": 24.5, "humidity": 60.0, "battery": 85}
        ).encode()

        mqtt_handler._on_message(None, None, msg)

        assert "sensor1" in mqtt_handler.readings
        assert mqtt_handler.readings["sensor1"].temperature == 24.5
        assert mqtt_handler.readings["sensor1"].humidity == 60.0

    def test_on_message_ignores_unknown_sensor(self, mqtt_handler):
        msg = MagicMock()
        msg.topic = "zigbee2mqtt/unknown_sensor"
        msg.payload = json.dumps({"temperature": 24.5}).encode()

        mqtt_handler._on_message(None, None, msg)

        assert "unknown_sensor" not in mqtt_handler.readings

    def test_on_message_handles_json_error(self, mqtt_handler):
        msg = MagicMock()
        msg.topic = "zigbee2mqtt/sensor1"
        msg.payload = b"not valid json"

        # Should not raise
        mqtt_handler._on_message(None, None, msg)

    def test_on_message_limits_history(self, mqtt_handler):
        mqtt_handler.max_history = 3
        mqtt_handler.history.clear()

        for i in range(10):
            msg = MagicMock()
            msg.topic = "zigbee2mqtt/sensor1"
            msg.payload = json.dumps({"temperature": 20.0 + i, "humidity": 50}).encode()
            mqtt_handler._on_message(None, None, msg)

        assert len(mqtt_handler.history.get("sensor1", [])) <= 3


class TestRecordAcTemp:
    def test_records_temperature(self, mqtt_handler):
        mqtt_handler.record_ac_temp(25.5)

        assert "AC" in mqtt_handler.history
        assert len(mqtt_handler.history["AC"]) == 1
        assert mqtt_handler.history["AC"][0].temperature == 25.5

    def test_limits_history(self, mqtt_handler):
        mqtt_handler.max_history = 3

        for i in range(10):
            mqtt_handler.record_ac_temp(20.0 + i)

        assert len(mqtt_handler.history["AC"]) <= 3


class TestGetActiveReadings:
    def test_returns_recent_readings(self, mqtt_handler):
        from mqtt_handler import SensorReading

        now = time.time()
        mqtt_handler.readings["sensor1"] = SensorReading(
            temperature=22.0, humidity=50.0, battery=90, timestamp=now - 100
        )

        active = mqtt_handler.get_active_readings(max_age_seconds=600)

        assert "sensor1" in active
        assert active["sensor1"].temperature == 22.0

    def test_excludes_old_readings(self, mqtt_handler):
        from mqtt_handler import SensorReading

        now = time.time()
        mqtt_handler.readings["sensor1"] = SensorReading(
            temperature=22.0, humidity=50.0, battery=90, timestamp=now - 1000
        )

        active = mqtt_handler.get_active_readings(max_age_seconds=600)

        assert "sensor1" not in active


class TestAverages:
    def test_get_average_temperature(self, mqtt_handler):
        from mqtt_handler import SensorReading

        now = time.time()
        # Clear and set fresh data
        mqtt_handler.readings.clear()
        mqtt_handler.readings["sensor1"] = SensorReading(
            temperature=20.0, humidity=50.0, battery=90, timestamp=now
        )
        mqtt_handler.readings["sensor2"] = SensorReading(
            temperature=24.0, humidity=50.0, battery=90, timestamp=now
        )

        avg = mqtt_handler.get_average_temperature()

        assert avg == 22.0  # (20 + 24) / 2

    def test_get_average_temperature_none_when_empty(self, mqtt_handler):
        mqtt_handler.readings.clear()
        avg = mqtt_handler.get_average_temperature()
        assert avg is None

    def test_get_average_humidity(self, mqtt_handler):
        from mqtt_handler import SensorReading

        now = time.time()
        mqtt_handler.readings.clear()
        mqtt_handler.readings["sensor1"] = SensorReading(
            temperature=20.0, humidity=40.0, battery=90, timestamp=now
        )
        mqtt_handler.readings["sensor2"] = SensorReading(
            temperature=24.0, humidity=60.0, battery=90, timestamp=now
        )

        avg = mqtt_handler.get_average_humidity()

        assert avg == 50.0  # (40 + 60) / 2

    def test_get_average_humidity_none_when_empty(self, mqtt_handler):
        mqtt_handler.readings.clear()
        avg = mqtt_handler.get_average_humidity()
        assert avg is None


class TestConnectionStatus:
    def test_is_connected_property(self, mqtt_handler):
        mqtt_handler._connected = True
        assert mqtt_handler.is_connected is True

        mqtt_handler._connected = False
        assert mqtt_handler.is_connected is False


class TestErrorTracker:
    def test_set_error_tracker(self, mqtt_handler):
        tracker = MagicMock()
        mqtt_handler.set_error_tracker(tracker)

        assert mqtt_handler._error_tracker is tracker

    def test_on_connect_clears_error(self, mqtt_handler):
        tracker = MagicMock()
        mqtt_handler.set_error_tracker(tracker)

        mqtt_handler._on_connect(MagicMock(), None, None, 0, None)

        tracker.clear.assert_called_with("mqtt_disconnected")

    def test_on_disconnect_registers_error(self, mqtt_handler):
        tracker = MagicMock()
        mqtt_handler.set_error_tracker(tracker)

        mqtt_handler._on_disconnect(None, None, None, 0, None)

        tracker.register.assert_called()


class TestStartStop:
    def test_start_connects(self, mqtt_handler):
        mqtt_handler._client.connect.return_value = None

        mqtt_handler.start()

        mqtt_handler._client.connect.assert_called_once()
        mqtt_handler._client.loop_start.assert_called_once()

    def test_start_retries_on_failure(self, temp_persist_file):
        with patch.dict("os.environ", {"SENSOR_PERSIST_FILE": temp_persist_file}):
            with patch("mqtt_handler.mqtt.Client") as mock_client_class:
                mock_client = MagicMock()
                mock_client.connect.side_effect = ConnectionError("Test")
                mock_client_class.return_value = mock_client

                from mqtt_handler import MqttHandler

                handler = MqttHandler(
                    broker="localhost",
                    port=1883,
                    sensor_names=["s1"],
                    connect_retries=2,
                    retry_delay=0,
                )

                with pytest.raises(ConnectionError):
                    handler.start()

                assert mock_client.connect.call_count == 2

    def test_stop_saves_and_disconnects(self, mqtt_handler):
        mqtt_handler._client = MagicMock()

        mqtt_handler.stop()

        mqtt_handler._client.loop_stop.assert_called_once()
        mqtt_handler._client.disconnect.assert_called_once()
