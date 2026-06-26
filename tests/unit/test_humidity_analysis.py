"""Unit tests for humidity_analysis.py (HUM-0)."""
import json
import os
import tempfile
import time
from unittest.mock import MagicMock
import pytest
from humidity_analysis import (
    analyse_humidity, append_snapshot, get_summary, load_snapshots, MAX_SNAPSHOTS
)


def _make_mqtt(humidity_values: list):
    """Build a mock MqttHandler with given humidity readings."""
    import threading
    from mqtt_handler import SensorReading
    now = time.time()
    m = MagicMock()
    m._lock = threading.Lock()
    m.history = {
        "sensor1": [SensorReading(25.0, h, 80, now - i * 60) for i, h in enumerate(humidity_values)],
    }
    return m


class TestAnalyseHumidity:
    def test_returns_correct_fields(self):
        mqtt = _make_mqtt([38, 39, 40, 41, 42])
        result = analyse_humidity(mqtt)
        assert result is not None
        for field in ("date", "mean", "min", "max", "p25", "p75",
                      "fraction_below_40", "fraction_above_55",
                      "humidifier_needed_signal", "per_sensor"):
            assert field in result, f"Missing field: {field}"

    def test_mean_calculation(self):
        mqtt = _make_mqtt([40, 40, 40, 40, 40])
        result = analyse_humidity(mqtt)
        assert result["mean"] == 40.0

    def test_fraction_below_40(self):
        # 2 out of 4 readings below 40
        mqtt = _make_mqtt([35, 38, 41, 42])
        result = analyse_humidity(mqtt)
        assert result["fraction_below_40"] == 0.5

    def test_signal_true_when_mean_low(self):
        mqtt = _make_mqtt([30, 31, 32, 33, 34])  # mean=32, well below 38
        result = analyse_humidity(mqtt)
        assert result["humidifier_needed_signal"] is True

    def test_signal_false_when_humidity_ok(self):
        mqtt = _make_mqtt([45, 46, 47, 48, 49])  # all above 40, mean=47
        result = analyse_humidity(mqtt)
        assert result["humidifier_needed_signal"] is False

    def test_returns_none_when_no_data(self):
        import threading
        m = MagicMock()
        m._lock = threading.Lock()
        m.history = {"s1": []}
        assert analyse_humidity(m) is None


class TestAppendSnapshot:
    def test_saves_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = os.path.join(tmp, "test.json")
            snap = {"date": "2026-06-26", "mean": 39.0, "fraction_below_40": 0.6,
                    "humidifier_needed_signal": False, "timestamp": time.time(),
                    "sample_count": 100, "sensors": [], "min": 35.0, "max": 45.0,
                    "median": 39.0, "stdev": 2.0, "p10": 36.0, "p25": 37.0,
                    "p75": 41.0, "p90": 43.0, "fraction_above_55": 0.0, "per_sensor": {}}
            append_snapshot(snap, f)
            loaded = json.loads(open(f).read())
            assert len(loaded) == 1
            assert loaded[0]["date"] == "2026-06-26"

    def test_replaces_same_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = os.path.join(tmp, "test.json")
            base = {"date": "2026-06-26", "mean": 39.0, "fraction_below_40": 0.6,
                    "humidifier_needed_signal": False, "timestamp": time.time(),
                    "sample_count": 100, "sensors": [], "min": 35.0, "max": 45.0,
                    "median": 39.0, "stdev": 2.0, "p10": 36.0, "p25": 37.0,
                    "p75": 41.0, "p90": 43.0, "fraction_above_55": 0.0, "per_sensor": {}}
            append_snapshot(base, f)
            updated = {**base, "mean": 42.0}
            append_snapshot(updated, f)
            loaded = json.loads(open(f).read())
            assert len(loaded) == 1          # not duplicated
            assert loaded[0]["mean"] == 42.0  # updated

    def test_keeps_max_snapshots(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = os.path.join(tmp, "test.json")
            for i in range(MAX_SNAPSHOTS + 5):
                snap = {"date": f"2026-0{i//30+1}-{(i%30)+1:02d}",
                        "mean": 39.0, "fraction_below_40": 0.5,
                        "humidifier_needed_signal": False, "timestamp": time.time(),
                        "sample_count": 10, "sensors": [], "min": 35.0, "max": 45.0,
                        "median": 39.0, "stdev": 2.0, "p10": 36.0, "p25": 37.0,
                        "p75": 41.0, "p90": 43.0, "fraction_above_55": 0.0, "per_sensor": {}}
                append_snapshot(snap, f)
            loaded = json.loads(open(f).read())
            assert len(loaded) <= MAX_SNAPSHOTS


class TestGetSummary:
    def _make_snapshot(self, date, mean, frac_below):
        return {"date": date, "mean": mean, "fraction_below_40": frac_below,
                "humidifier_needed_signal": mean < 38.0 or frac_below > 0.65,
                "timestamp": time.time(), "sample_count": 100,
                "sensors": [], "min": 35.0, "max": 45.0, "median": mean,
                "stdev": 2.0, "p10": 36.0, "p25": 37.0, "p75": 41.0,
                "p90": 43.0, "fraction_above_55": 0.0, "per_sensor": {}}

    def test_returns_none_when_no_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = os.path.join(tmp, "empty.json")
            assert get_summary(f) is None

    def test_recommendation_monitor_when_few_days(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = os.path.join(tmp, "test.json")
            for i in range(3):
                append_snapshot(self._make_snapshot(f"2026-06-{i+1:02d}", 39.0, 0.6), f)
            summary = get_summary(f)
            assert "Monitor" in summary["recommendation"]

    def test_recommendation_humidifier_when_many_signals(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = os.path.join(tmp, "test.json")
            # 21 days all with signal=True (mean < 38)
            for i in range(21):
                append_snapshot(self._make_snapshot(f"2026-{i//30+6:02d}-{(i%30)+1:02d}", 35.0, 0.8), f)
            summary = get_summary(f)
            assert "HUMIDIFIER" in summary["recommendation"]
