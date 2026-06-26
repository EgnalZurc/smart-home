"""Unit tests for humidity_analysis.py (HUM-0) - hourly samples + daily consolidation."""
import json
import os
import tempfile
import time
import threading
from unittest.mock import MagicMock
import pytest
from humidity_analysis import (
    _collect_sample, _build_daily_snapshot, append_snapshot,
    get_summary, _load_json, MAX_SNAPSHOTS, STUDY_DAYS
)


def _make_mqtt(humidity_values: list):
    from mqtt_handler import SensorReading
    now = time.time()
    m = MagicMock()
    m._lock = threading.Lock()
    m.history = {
        "sensor1": [SensorReading(25.0, h, 80, now - i * 60)
                    for i, h in enumerate(humidity_values)],
    }
    return m


def _make_sample(date: str, hour: int, mean: float, n: int = 50) -> dict:
    return {
        "timestamp": time.time(),
        "date": date,
        "hour": hour,
        "mean": mean,
        "min": mean - 2,
        "max": mean + 2,
        "sample_n": n,
        "sensors": ["s1"],
    }


class TestCollectSample:
    def test_returns_correct_fields(self):
        mqtt = _make_mqtt([38, 39, 40, 41, 42])
        result = _collect_sample(mqtt)
        assert result is not None
        for f in ("timestamp", "date", "hour", "mean", "min", "max", "sample_n"):
            assert f in result

    def test_mean_correct(self):
        mqtt = _make_mqtt([40, 40, 40])
        result = _collect_sample(mqtt)
        assert result["mean"] == 40.0

    def test_returns_none_when_no_data(self):
        m = MagicMock()
        m._lock = threading.Lock()
        m.history = {"s1": []}
        assert _collect_sample(m) is None


class TestBuildDailySnapshot:
    def test_consolidates_multiple_hours(self):
        samples = [_make_sample("2026-07-01", h, 38.0 + h * 0.1) for h in range(24)]
        snap = _build_daily_snapshot("2026-07-01", samples)
        assert snap is not None
        assert snap["hours_sampled"] == 24
        assert snap["date"] == "2026-07-01"

    def test_ignores_other_dates(self):
        samples = (
            [_make_sample("2026-07-01", h, 39.0) for h in range(12)] +
            [_make_sample("2026-07-02", h, 45.0) for h in range(12)]
        )
        snap = _build_daily_snapshot("2026-07-01", samples)
        assert snap["hours_sampled"] == 12

    def test_fraction_below_40_hourly(self):
        # 6 hours below 40, 6 hours at/above 40
        samples = (
            [_make_sample("2026-07-01", h, 37.0) for h in range(6)] +
            [_make_sample("2026-07-01", h+6, 42.0) for h in range(6)]
        )
        snap = _build_daily_snapshot("2026-07-01", samples)
        assert snap["fraction_below_40"] == 0.5

    def test_signal_true_when_mean_low(self):
        samples = [_make_sample("2026-07-01", h, 35.0) for h in range(8)]
        snap = _build_daily_snapshot("2026-07-01", samples)
        assert snap["humidifier_needed_signal"] is True

    def test_signal_false_when_ok(self):
        samples = [_make_sample("2026-07-01", h, 45.0) for h in range(8)]
        snap = _build_daily_snapshot("2026-07-01", samples)
        assert snap["humidifier_needed_signal"] is False

    def test_returns_none_for_missing_date(self):
        samples = [_make_sample("2026-07-01", h, 39.0) for h in range(5)]
        assert _build_daily_snapshot("2026-07-02", samples) is None

    def test_hourly_pattern_present(self):
        samples = [_make_sample("2026-07-01", h, 38.0 + h * 0.2) for h in range(4)]
        snap = _build_daily_snapshot("2026-07-01", samples)
        assert "hourly_pattern" in snap
        assert len(snap["hourly_pattern"]) == 4


class TestAppendSnapshot:
    def _base_snap(self, date, mean=39.0, frac=0.6, signal=False):
        return {
            "date": date, "mean": mean, "min": 35.0, "max": 45.0,
            "p25": 37.0, "p75": 41.0, "fraction_below_40": frac,
            "fraction_above_55": 0.0, "humidifier_needed_signal": signal,
            "timestamp": time.time(), "hours_sampled": 12,
            "sensors": [], "hourly_pattern": {},
        }

    def test_saves_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = os.path.join(tmp, "test.json")
            append_snapshot(self._base_snap("2026-07-01"), f)
            loaded = _load_json(f)
            assert len(loaded) == 1

    def test_replaces_same_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = os.path.join(tmp, "test.json")
            append_snapshot(self._base_snap("2026-07-01", mean=39.0), f)
            append_snapshot(self._base_snap("2026-07-01", mean=42.0), f)
            loaded = _load_json(f)
            assert len(loaded) == 1
            assert loaded[0]["mean"] == 42.0

    def test_keeps_max_snapshots(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = os.path.join(tmp, "test.json")
            for i in range(MAX_SNAPSHOTS + 5):
                append_snapshot(self._base_snap(f"2026-07-{i+1:02d}"), f)
            loaded = _load_json(f)
            assert len(loaded) <= MAX_SNAPSHOTS


class TestGetSummary:
    def _snap(self, date, mean, frac, signal):
        return {
            "date": date, "mean": mean, "fraction_below_40": frac,
            "humidifier_needed_signal": signal, "timestamp": time.time(),
            "hours_sampled": 12, "sensors": [], "min": 35.0, "max": 45.0,
            "p25": 37.0, "p75": 41.0, "fraction_above_55": 0.0, "hourly_pattern": {},
        }

    def test_none_when_no_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            assert get_summary(os.path.join(tmp, "x.json")) is None

    def test_monitor_when_few_days(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = os.path.join(tmp, "t.json")
            for i in range(3):
                append_snapshot(self._snap(f"2026-07-{i+1:02d}", 39.0, 0.6, False), f)
            assert "Monitor" in get_summary(f)["recommendation"]

    def test_humidifier_when_many_signals(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = os.path.join(tmp, "t.json")
            for i in range(21):
                append_snapshot(self._snap(f"2026-07-{i+1:02d}", 35.0, 0.8, True), f)
            assert "HUMIDIFIER" in get_summary(f)["recommendation"]
