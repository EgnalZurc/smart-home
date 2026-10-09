"""Tests for smart_home_common.mqtt.handler — MQTT sensor handler.

All MQTT interaction is mocked; no real broker connection is made.
"""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from smart_home_common.mqtt.handler import MqttHandler, SensorReading, PERSIST_FILE


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sensor_names():
    return ["sensor_salon", "sensor_bedroom"]


@pytest.fixture
def handler(sensor_names, tmp_path, monkeypatch):
    """Creates an MqttHandler with no persisted data."""
    persist_file = tmp_path / "sensor_readings.json"
    monkeypatch.setenv("SENSOR_PERSIST_FILE", str(persist_file))
    # Reimport to pick up the env change
    import smart_home_common.mqtt.handler as handler_module
    monkeypatch.setattr(handler_module, "PERSIST_FILE", str(persist_file))
    return MqttHandler(
        broker="mosquitto",
        port=1883,
        sensor_names=sensor_names,
        connect_retries=3,
        retry_delay=0.01,
    )


@pytest.fixture
def persist_file(tmp_path, monkeypatch):
    """Provides a temporary persistence file path and patches the module."""
    file_path = tmp_path / "sensor_readings.json"
    import smart_home_common.mqtt.handler as handler_module
    monkeypatch.setattr(handler_module, "PERSIST_FILE", str(file_path))
    return file_path


def _make_msg(topic: str, payload: dict | bytes) -> MagicMock:
    """Builds a fake MQTT message object with topic and byte payload."""
    msg = MagicMock()
    msg.topic = topic
    if isinstance(payload, (bytes, bytearray)):
        msg.payload = payload
    else:
        msg.payload = json.dumps(payload).encode()
    return msg


# ---------------------------------------------------------------------------
# SensorReading tests
# ---------------------------------------------------------------------------

class TestSensorReading:
    """Tests for the SensorReading dataclass."""

    def test_init_with_all_values(self):
        reading = SensorReading(
            temperature=22.5,
            humidity=55.0,
            battery=80,
            timestamp=1000.0,
        )
        assert reading.temperature == 22.5
        assert reading.humidity == 55.0
        assert reading.battery == 80
        assert reading.timestamp == 1000.0

    def test_init_with_none_values(self):
        reading = SensorReading(
            temperature=20.0,
            humidity=None,
            battery=None,
            timestamp=2000.0,
        )
        assert reading.temperature == 20.0
        assert reading.humidity is None
        assert reading.battery is None

    def test_to_dict(self):
        reading = SensorReading(
            temperature=22.5,
            humidity=55.0,
            battery=80,
            timestamp=1000.0,
        )
        d = reading.to_dict()
        assert d == {
            "temperature": 22.5,
            "humidity": 55.0,
            "battery": 80,
            "timestamp": 1000.0,
        }

    def test_from_dict(self):
        d = {
            "temperature": 23.0,
            "humidity": 60.0,
            "battery": 75,
            "timestamp": 1500.0,
        }
        reading = SensorReading.from_dict(d)
        assert reading.temperature == 23.0
        assert reading.humidity == 60.0
        assert reading.battery == 75
        assert reading.timestamp == 1500.0

    def test_round_trip(self):
        original = SensorReading(21.0, 45.0, 90, 1234.5)
        reconstructed = SensorReading.from_dict(original.to_dict())
        assert reconstructed.temperature == original.temperature
        assert reconstructed.humidity == original.humidity
        assert reconstructed.battery == original.battery
        assert reconstructed.timestamp == original.timestamp


# ---------------------------------------------------------------------------
# MqttHandler initialization tests
# ---------------------------------------------------------------------------

class TestMqttHandlerInit:
    """Tests for MqttHandler initialization."""

    def test_default_values(self, persist_file):
        handler = MqttHandler(
            broker="mosquitto",
            port=1883,
            sensor_names=["sensor1"],
        )
        assert handler.broker == "mosquitto"
        assert handler.port == 1883
        assert handler.sensor_names == ["sensor1"]
        assert handler.connect_retries == 30
        assert handler.retry_delay == 2
        assert handler.keepalive == 60
        assert handler.max_history == 200
        assert handler.readings == {}
        assert handler.history == {}
        assert handler._connected is False

    def test_custom_values(self, persist_file):
        handler = MqttHandler(
            broker="broker.local",
            port=8883,
            sensor_names=["a", "b"],
            connect_retries=5,
            retry_delay=1,
            keepalive=30,
            max_history=100,
        )
        assert handler.broker == "broker.local"
        assert handler.port == 8883
        assert handler.connect_retries == 5
        assert handler.retry_delay == 1
        assert handler.keepalive == 30
        assert handler.max_history == 100

    def test_auth_credentials(self, persist_file):
        handler = MqttHandler(
            broker="mosquitto",
            port=1883,
            sensor_names=["sensor1"],
            username="testuser",
            password="testpass",
        )
        assert handler.username == "testuser"
        assert handler.password == "testpass"

    def test_auth_credentials_default_none(self, persist_file):
        handler = MqttHandler(
            broker="mosquitto",
            port=1883,
            sensor_names=["sensor1"],
        )
        assert handler.username is None
        assert handler.password is None


# ---------------------------------------------------------------------------
# Persistence tests
# ---------------------------------------------------------------------------

class TestPersistence:
    """Tests for disk load/save functionality."""

    def test_load_from_disk_no_file(self, persist_file):
        """No file exists — handler starts with empty state."""
        handler = MqttHandler("mosquitto", 1883, ["sensor1"])
        assert handler.readings == {}
        assert handler.history == {}

    def test_load_from_disk_new_format(self, persist_file):
        """New format: list of readings per sensor."""
        data = {
            "sensor1": [
                {"temperature": 20.0, "humidity": 50.0, "battery": 90, "timestamp": 1000.0},
                {"temperature": 21.0, "humidity": 51.0, "battery": 89, "timestamp": 2000.0},
            ]
        }
        persist_file.write_text(json.dumps(data), encoding="utf-8")

        handler = MqttHandler("mosquitto", 1883, ["sensor1"])
        assert "sensor1" in handler.history
        assert len(handler.history["sensor1"]) == 2
        assert handler.readings["sensor1"].temperature == 21.0  # Last reading

    def test_load_from_disk_old_format_migration(self, persist_file):
        """Old format: single dict per sensor — gets migrated."""
        data = {
            "sensor1": {"temperature": 22.0, "humidity": 55.0, "battery": 80, "timestamp": 1500.0}
        }
        persist_file.write_text(json.dumps(data), encoding="utf-8")

        handler = MqttHandler("mosquitto", 1883, ["sensor1"])
        assert "sensor1" in handler.readings
        assert handler.readings["sensor1"].temperature == 22.0
        assert len(handler.history["sensor1"]) == 1

    def test_load_from_disk_skips_unknown_sensors(self, persist_file):
        """Sensors not in sensor_names are skipped (except AC)."""
        data = {
            "sensor1": [{"temperature": 20.0, "humidity": 50.0, "battery": 90, "timestamp": 1000.0}],
            "unknown_sensor": [{"temperature": 25.0, "humidity": 60.0, "battery": 70, "timestamp": 1000.0}],
        }
        persist_file.write_text(json.dumps(data), encoding="utf-8")

        handler = MqttHandler("mosquitto", 1883, ["sensor1"])
        assert "sensor1" in handler.history
        assert "unknown_sensor" not in handler.history

    def test_load_from_disk_always_loads_ac(self, persist_file):
        """AC virtual sensor is always loaded regardless of sensor_names."""
        data = {
            "AC": [{"temperature": 24.0, "humidity": None, "battery": None, "timestamp": 1000.0}],
        }
        persist_file.write_text(json.dumps(data), encoding="utf-8")

        handler = MqttHandler("mosquitto", 1883, ["sensor1"])
        assert "AC" in handler.history

    def test_load_from_disk_truncates_to_max_history(self, persist_file):
        """History is truncated to max_history on load."""
        data = {
            "sensor1": [
                {"temperature": float(i), "humidity": 50.0, "battery": 90, "timestamp": float(i)}
                for i in range(300)
            ]
        }
        persist_file.write_text(json.dumps(data), encoding="utf-8")

        handler = MqttHandler("mosquitto", 1883, ["sensor1"], max_history=100)
        assert len(handler.history["sensor1"]) == 100
        # Should keep the last 100
        assert handler.history["sensor1"][0].temperature == 200.0

    def test_load_from_disk_handles_corrupt_json(self, persist_file, caplog):
        """Corrupt JSON file is handled gracefully."""
        persist_file.write_text("not valid json {", encoding="utf-8")

        handler = MqttHandler("mosquitto", 1883, ["sensor1"])
        assert handler.readings == {}
        assert "Error loading data from disk" in caplog.text

    def test_save_to_disk(self, persist_file):
        """Save writes history to disk."""
        handler = MqttHandler("mosquitto", 1883, ["sensor1"])
        reading = SensorReading(21.0, 50.0, 85, time.time())
        handler.history["sensor1"] = [reading]

        handler._save_to_disk()

        saved_data = json.loads(persist_file.read_text(encoding="utf-8"))
        assert "sensor1" in saved_data
        assert saved_data["sensor1"][0]["temperature"] == 21.0


# ---------------------------------------------------------------------------
# Connection lifecycle tests
# ---------------------------------------------------------------------------

class TestConnectionLifecycle:
    """Tests for start/stop and connection callbacks."""

    @patch("smart_home_common.mqtt.handler.mqtt.Client")
    def test_start_connects_and_starts_loop(self, mock_client_class, persist_file):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        handler = MqttHandler("mosquitto", 1883, ["sensor1"], connect_retries=1)
        handler.start()

        mock_client.connect.assert_called_once_with("mosquitto", 1883, 60)
        mock_client.loop_start.assert_called_once()
        assert mock_client.on_connect == handler._on_connect
        assert mock_client.on_message == handler._on_message
        assert mock_client.on_disconnect == handler._on_disconnect

    @patch("smart_home_common.mqtt.handler.mqtt.Client")
    def test_start_sets_credentials_when_provided(self, mock_client_class, persist_file):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        handler = MqttHandler(
            "mosquitto", 1883, ["sensor1"],
            connect_retries=1,
            username="testuser",
            password="testpass",
        )
        handler.start()

        mock_client.username_pw_set.assert_called_once_with("testuser", "testpass")
        mock_client.connect.assert_called_once()

    @patch("smart_home_common.mqtt.handler.mqtt.Client")
    def test_start_skips_credentials_when_not_provided(self, mock_client_class, persist_file):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        handler = MqttHandler("mosquitto", 1883, ["sensor1"], connect_retries=1)
        handler.start()

        mock_client.username_pw_set.assert_not_called()

    @patch("smart_home_common.mqtt.handler.mqtt.Client")
    def test_start_retries_on_failure(self, mock_client_class, persist_file):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        # Fail twice, succeed on third
        mock_client.connect.side_effect = [
            ConnectionError("fail1"),
            ConnectionError("fail2"),
            None,
        ]

        handler = MqttHandler(
            "mosquitto", 1883, ["sensor1"], connect_retries=3, retry_delay=0.01
        )
        handler.start()

        assert mock_client.connect.call_count == 3
        mock_client.loop_start.assert_called_once()

    @patch("smart_home_common.mqtt.handler.time.sleep")
    @patch("smart_home_common.mqtt.handler.mqtt.Client")
    def test_start_uses_exponential_backoff(self, mock_client_class, mock_sleep, persist_file):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        # Fail 4 times, succeed on 5th
        mock_client.connect.side_effect = [
            ConnectionError("fail1"),
            ConnectionError("fail2"),
            ConnectionError("fail3"),
            ConnectionError("fail4"),
            None,
        ]

        handler = MqttHandler(
            "mosquitto", 1883, ["sensor1"], connect_retries=5, retry_delay=1
        )
        handler.start()

        # Verify exponential backoff: 1, 2, 4, 8 seconds
        assert mock_sleep.call_count == 4
        sleep_calls = [call[0][0] for call in mock_sleep.call_args_list]
        assert sleep_calls == [1, 2, 4, 8]

    @patch("smart_home_common.mqtt.handler.mqtt.Client")
    def test_start_raises_after_max_retries(self, mock_client_class, persist_file):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.connect.side_effect = ConnectionError("always fails")

        handler = MqttHandler(
            "mosquitto", 1883, ["sensor1"], connect_retries=3, retry_delay=0.01
        )

        with pytest.raises(ConnectionError, match="Could not connect"):
            handler.start()

        assert mock_client.connect.call_count == 3

    @patch("smart_home_common.mqtt.handler.mqtt.Client")
    def test_stop_saves_and_disconnects(self, mock_client_class, persist_file):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        handler = MqttHandler("mosquitto", 1883, ["sensor1"])
        handler._client = mock_client

        handler.stop()

        mock_client.loop_stop.assert_called_once()
        mock_client.disconnect.assert_called_once()

    def test_on_connect_success_subscribes(self, persist_file):
        handler = MqttHandler("mosquitto", 1883, ["sensor1"])
        handler._error_tracker = None  # Simulates state before start() sets tracker
        fake_client = MagicMock()

        handler._on_connect(fake_client, None, None, 0, None)

        assert handler._connected is True
        fake_client.subscribe.assert_called_once_with("zigbee2mqtt/+")

    def test_on_connect_with_error_tracker(self, persist_file):
        handler = MqttHandler("mosquitto", 1883, ["sensor1"])
        handler._error_tracker = MagicMock()
        fake_client = MagicMock()

        handler._on_connect(fake_client, None, None, 0, None)

        handler._error_tracker.clear.assert_called_once_with("mqtt_disconnected")

    def test_on_disconnect_sets_not_connected(self, persist_file):
        handler = MqttHandler("mosquitto", 1883, ["sensor1"])
        handler._error_tracker = None  # Simulates state before start() sets tracker
        handler._connected = True

        handler._on_disconnect(None, None, None, 1, None)

        assert handler._connected is False

    def test_on_disconnect_with_error_tracker(self, persist_file):
        handler = MqttHandler("mosquitto", 1883, ["sensor1"])
        handler._error_tracker = MagicMock()
        handler._connected = True

        handler._on_disconnect(None, None, None, 1, None)

        handler._error_tracker.register.assert_called_once_with(
            "mqtt_disconnected", "error", "Disconnected from MQTT broker", "mqtt"
        )


# ---------------------------------------------------------------------------
# Message handling tests
# ---------------------------------------------------------------------------

class TestOnMessage:
    """Tests for _on_message callback."""

    def test_processes_valid_sensor_message(self, persist_file):
        handler = MqttHandler("mosquitto", 1883, ["sensor_salon"])
        msg = _make_msg(
            "zigbee2mqtt/sensor_salon",
            {"temperature": 22.5, "humidity": 55.0, "battery": 80},
        )

        handler._on_message(None, None, msg)

        assert "sensor_salon" in handler.readings
        assert handler.readings["sensor_salon"].temperature == 22.5
        assert handler.readings["sensor_salon"].humidity == 55.0
        assert handler.readings["sensor_salon"].battery == 80

    def test_ignores_unknown_sensor(self, persist_file):
        handler = MqttHandler("mosquitto", 1883, ["sensor_salon"])
        msg = _make_msg(
            "zigbee2mqtt/unknown_sensor",
            {"temperature": 22.5, "humidity": 55.0, "battery": 80},
        )

        handler._on_message(None, None, msg)

        assert "unknown_sensor" not in handler.readings

    def test_ignores_message_without_temperature(self, persist_file):
        handler = MqttHandler("mosquitto", 1883, ["sensor_salon"])
        msg = _make_msg(
            "zigbee2mqtt/sensor_salon",
            {"humidity": 55.0, "battery": 80},  # No temperature
        )

        handler._on_message(None, None, msg)

        assert "sensor_salon" not in handler.readings

    def test_ignores_short_topic(self, persist_file):
        handler = MqttHandler("mosquitto", 1883, ["sensor_salon"])
        msg = _make_msg("zigbee2mqtt", {"temperature": 22.5})

        handler._on_message(None, None, msg)

        assert handler.readings == {}

    def test_handles_default_humidity_and_battery(self, persist_file):
        handler = MqttHandler("mosquitto", 1883, ["sensor_salon"])
        msg = _make_msg(
            "zigbee2mqtt/sensor_salon",
            {"temperature": 22.5},  # No humidity or battery
        )

        handler._on_message(None, None, msg)

        assert handler.readings["sensor_salon"].humidity == 0.0
        assert handler.readings["sensor_salon"].battery == 0

    def test_adds_to_history(self, persist_file):
        handler = MqttHandler("mosquitto", 1883, ["sensor_salon"])
        msg = _make_msg(
            "zigbee2mqtt/sensor_salon",
            {"temperature": 22.5, "humidity": 55.0, "battery": 80},
        )

        handler._on_message(None, None, msg)

        assert "sensor_salon" in handler.history
        assert len(handler.history["sensor_salon"]) == 1

    def test_history_fifo_truncation(self, persist_file):
        handler = MqttHandler("mosquitto", 1883, ["sensor_salon"], max_history=3)

        for i in range(5):
            msg = _make_msg(
                "zigbee2mqtt/sensor_salon",
                {"temperature": float(i), "humidity": 50.0, "battery": 80},
            )
            handler._on_message(None, None, msg)

        assert len(handler.history["sensor_salon"]) == 3
        # Should keep the last 3 (temps 2, 3, 4)
        temps = [r.temperature for r in handler.history["sensor_salon"]]
        assert temps == [2.0, 3.0, 4.0]

    def test_handles_invalid_json(self, persist_file, caplog):
        handler = MqttHandler("mosquitto", 1883, ["sensor_salon"])
        msg = _make_msg("zigbee2mqtt/sensor_salon", b"not valid json")

        handler._on_message(None, None, msg)

        assert handler.readings == {}
        assert "Error processing message" in caplog.text

    def test_persists_to_disk_after_message(self, persist_file):
        handler = MqttHandler("mosquitto", 1883, ["sensor_salon"])
        msg = _make_msg(
            "zigbee2mqtt/sensor_salon",
            {"temperature": 22.5, "humidity": 55.0, "battery": 80},
        )

        handler._on_message(None, None, msg)

        # Verify file was written
        assert persist_file.exists()
        saved_data = json.loads(persist_file.read_text(encoding="utf-8"))
        assert "sensor_salon" in saved_data


# ---------------------------------------------------------------------------
# AC temperature recording tests
# ---------------------------------------------------------------------------

class TestRecordAcTemp:
    """Tests for record_ac_temp method."""

    def test_records_ac_temperature(self, persist_file):
        handler = MqttHandler("mosquitto", 1883, ["sensor1"])

        handler.record_ac_temp(24.5)

        assert "AC" in handler.history
        assert len(handler.history["AC"]) == 1
        assert handler.history["AC"][0].temperature == 24.5
        assert handler.history["AC"][0].humidity is None
        assert handler.history["AC"][0].battery is None

    def test_ac_history_fifo_truncation(self, persist_file):
        handler = MqttHandler("mosquitto", 1883, ["sensor1"], max_history=3)

        for i in range(5):
            handler.record_ac_temp(float(20 + i))

        assert len(handler.history["AC"]) == 3
        temps = [r.temperature for r in handler.history["AC"]]
        assert temps == [22.0, 23.0, 24.0]

    def test_persists_to_disk(self, persist_file):
        handler = MqttHandler("mosquitto", 1883, ["sensor1"])

        handler.record_ac_temp(25.0)

        saved_data = json.loads(persist_file.read_text(encoding="utf-8"))
        assert "AC" in saved_data
        assert saved_data["AC"][0]["temperature"] == 25.0


# ---------------------------------------------------------------------------
# Reading retrieval tests
# ---------------------------------------------------------------------------

class TestGetActiveReadings:
    """Tests for get_active_readings method."""

    def test_returns_recent_readings(self, persist_file):
        handler = MqttHandler("mosquitto", 1883, ["sensor1", "sensor2"])
        now = time.time()
        handler.readings["sensor1"] = SensorReading(22.0, 50.0, 80, now - 100)
        handler.readings["sensor2"] = SensorReading(23.0, 55.0, 75, now - 200)

        active = handler.get_active_readings(max_age_seconds=600)

        assert "sensor1" in active
        assert "sensor2" in active

    def test_filters_old_readings(self, persist_file):
        handler = MqttHandler("mosquitto", 1883, ["sensor1", "sensor2"])
        now = time.time()
        handler.readings["sensor1"] = SensorReading(22.0, 50.0, 80, now - 100)
        handler.readings["sensor2"] = SensorReading(23.0, 55.0, 75, now - 700)  # Too old

        active = handler.get_active_readings(max_age_seconds=600)

        assert "sensor1" in active
        assert "sensor2" not in active

    def test_returns_empty_when_no_readings(self, persist_file):
        handler = MqttHandler("mosquitto", 1883, ["sensor1"])

        active = handler.get_active_readings()

        assert active == {}


class TestGetAverageTemperature:
    """Tests for get_average_temperature method."""

    def test_calculates_average(self, persist_file):
        handler = MqttHandler("mosquitto", 1883, ["sensor1", "sensor2"])
        now = time.time()
        handler.readings["sensor1"] = SensorReading(20.0, 50.0, 80, now)
        handler.readings["sensor2"] = SensorReading(24.0, 55.0, 75, now)

        avg = handler.get_average_temperature()

        assert avg == 22.0

    def test_returns_none_when_no_active_readings(self, persist_file):
        handler = MqttHandler("mosquitto", 1883, ["sensor1"])

        avg = handler.get_average_temperature()

        assert avg is None


class TestGetAverageHumidity:
    """Tests for get_average_humidity method."""

    def test_calculates_average(self, persist_file):
        handler = MqttHandler("mosquitto", 1883, ["sensor1", "sensor2"])
        now = time.time()
        handler.readings["sensor1"] = SensorReading(20.0, 50.0, 80, now)
        handler.readings["sensor2"] = SensorReading(24.0, 60.0, 75, now)

        avg = handler.get_average_humidity()

        assert avg == 55.0

    def test_returns_none_when_no_active_readings(self, persist_file):
        handler = MqttHandler("mosquitto", 1883, ["sensor1"])

        avg = handler.get_average_humidity()

        assert avg is None


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------

class TestIsConnected:
    """Tests for is_connected property."""

    def test_returns_false_initially(self, persist_file):
        handler = MqttHandler("mosquitto", 1883, ["sensor1"])
        assert handler.is_connected is False

    def test_returns_true_when_connected(self, persist_file):
        handler = MqttHandler("mosquitto", 1883, ["sensor1"])
        handler._connected = True
        assert handler.is_connected is True


# ---------------------------------------------------------------------------
# Error tracker tests
# ---------------------------------------------------------------------------

class TestSetErrorTracker:
    """Tests for set_error_tracker method."""

    def test_sets_error_tracker(self, persist_file):
        handler = MqttHandler("mosquitto", 1883, ["sensor1"])
        tracker = MagicMock()

        handler.set_error_tracker(tracker)

        assert handler._error_tracker == tracker
