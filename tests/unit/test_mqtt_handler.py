"""Unit tests for mqtt_handler.py"""
import json, time
from unittest.mock import MagicMock, patch
import pytest
from mqtt_handler import MqttHandler, SensorReading


class TestSensorReading:
    def test_to_dict_round_trip(self):
        r = SensorReading(temperature=25.5, humidity=40, battery=80, timestamp=1000.0)
        d = r.to_dict()
        r2 = SensorReading.from_dict(d)
        assert r2.temperature == 25.5
        assert r2.humidity == 40
        assert r2.battery == 80
        assert r2.timestamp == 1000.0

    def test_from_dict_requires_all_fields(self):
        # from_dict uses exact keys, test valid full dict
        d = {"temperature": 22.0, "humidity": 40, "battery": 80, "timestamp": 500.0}
        r = SensorReading.from_dict(d)
        assert r.temperature == 22.0


class TestOnMessage:
    def _make_handler(self, sensor_names):
        with patch("mqtt_handler.mqtt"):
            with patch.object(MqttHandler, "_load_from_disk"):
                h = MqttHandler("localhost", 1883, sensor_names, max_history=5)
                h._connected = True
                h._error_tracker = None
                return h

    def _make_msg(self, topic, payload_dict):
        msg = MagicMock()
        msg.topic = topic
        msg.payload = json.dumps(payload_dict).encode()
        return msg

    def test_processes_valid_message(self):
        h = self._make_handler(["Salon"])
        with patch.object(h, "_save_to_disk"):
            msg = self._make_msg("zigbee2mqtt/Salon",
                                  {"temperature": 25.0, "humidity": 40, "battery": 90})
            h._on_message(None, None, msg)
        assert "Salon" in h.readings
        assert h.readings["Salon"].temperature == 25.0

    def test_ignores_unknown_sensor(self):
        h = self._make_handler(["Salon"])
        with patch.object(h, "_save_to_disk"):
            msg = self._make_msg("zigbee2mqtt/Unknown", {"temperature": 25.0})
            h._on_message(None, None, msg)
        assert "Unknown" not in h.readings

    def test_trims_history_to_max(self):
        h = self._make_handler(["Salon"])
        with patch.object(h, "_save_to_disk"):
            for i in range(10):
                msg = self._make_msg("zigbee2mqtt/Salon",
                                      {"temperature": float(i), "humidity": 40})
                h._on_message(None, None, msg)
        assert len(h.history["Salon"]) <= 5

    def test_ignores_message_without_temperature(self):
        h = self._make_handler(["Salon"])
        msg = self._make_msg("zigbee2mqtt/Salon", {"humidity": 40})
        h._on_message(None, None, msg)
        assert "Salon" not in h.readings


class TestGetActiveReadings:
    def _make_handler_with_reading(self, age_seconds):
        with patch("mqtt_handler.mqtt"):
            with patch.object(MqttHandler, "_load_from_disk"):
                h = MqttHandler("localhost", 1883, ["Salon"], max_history=200)
                h._error_tracker = None
                ts = time.time() - age_seconds
                h.readings["Salon"] = SensorReading(25.0, 40, 80, ts)
                return h

    def test_fresh_reading_is_active(self):
        h = self._make_handler_with_reading(age_seconds=60)
        active = h.get_active_readings(max_age_seconds=3600)
        assert "Salon" in active

    def test_stale_reading_not_active(self):
        h = self._make_handler_with_reading(age_seconds=4000)
        active = h.get_active_readings(max_age_seconds=3600)
        assert "Salon" not in active

    def test_average_temperature_with_active(self):
        with patch("mqtt_handler.mqtt"):
            with patch.object(MqttHandler, "_load_from_disk"):
                h = MqttHandler("localhost", 1883, ["s1", "s2"], max_history=200)
                h._error_tracker = None
                now = time.time()
                h.readings["s1"] = SensorReading(24.0, 40, 80, now)
                h.readings["s2"] = SensorReading(26.0, 40, 80, now)
                avg = h.get_average_temperature(max_age_seconds=3600)
                assert avg == 25.0

    def test_average_returns_none_when_no_active(self):
        with patch("mqtt_handler.mqtt"):
            with patch.object(MqttHandler, "_load_from_disk"):
                h = MqttHandler("localhost", 1883, ["s1"], max_history=200)
                h._error_tracker = None
                assert h.get_average_temperature(max_age_seconds=3600) is None


class TestRecordAcTemp:
    """Tests for AC room temperature hourly recording (AC-CHART)."""

    def _make_handler(self):
        with patch("mqtt_handler.mqtt"):
            with patch.object(MqttHandler, "_load_from_disk"):
                h = MqttHandler("localhost", 1883, ["s1"], max_history=200)
                h._error_tracker = None
                return h

    def test_record_ac_temp_adds_to_history(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SENSOR_PERSIST_FILE", str(tmp_path / "sensor.json"))
        import mqtt_handler as mh
        monkeypatch.setattr(mh, "PERSIST_FILE", str(tmp_path / "sensor.json"))
        h = self._make_handler()
        h.record_ac_temp(24.5)
        assert "AC" in h.history
        assert len(h.history["AC"]) == 1
        assert h.history["AC"][0].temperature == 24.5
        assert h.history["AC"][0].humidity is None
        assert h.history["AC"][0].battery is None

    def test_record_ac_temp_persists_to_disk(self, tmp_path, monkeypatch):
        import json, mqtt_handler as mh
        persist = tmp_path / "sensor.json"
        monkeypatch.setattr(mh, "PERSIST_FILE", str(persist))
        h = self._make_handler()
        h.record_ac_temp(22.0)
        data = json.loads(persist.read_text(encoding="utf-8"))
        assert "AC" in data
        assert data["AC"][0]["temperature"] == 22.0

    def test_record_ac_temp_respects_max_history(self, tmp_path, monkeypatch):
        import mqtt_handler as mh
        monkeypatch.setattr(mh, "PERSIST_FILE", str(tmp_path / "sensor.json"))
        h = self._make_handler()
        h.max_history = 5
        for i in range(10):
            h.record_ac_temp(20.0 + i)
        assert len(h.history["AC"]) == 5

    def test_ac_sensor_loaded_from_disk(self, tmp_path, monkeypatch):
        """AC entries persisted on disk are loaded even though AC not in sensor_names."""
        import json, mqtt_handler as mh
        persist = tmp_path / "sensor.json"
        monkeypatch.setattr(mh, "PERSIST_FILE", str(persist))
        # Write pre-existing AC data
        persist.write_text(json.dumps({
            "AC": [{"temperature": 23.0, "humidity": None, "battery": None, "timestamp": 1000.0}]
        }), encoding="utf-8")
        with patch("mqtt_handler.mqtt"):
            h = MqttHandler("localhost", 1883, ["s1"], max_history=200)
            h._error_tracker = None
        assert "AC" in h.history
        assert h.history["AC"][0].temperature == 23.0
