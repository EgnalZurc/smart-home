"""Unit tests for humidity_analysis.py (HUM-0) - seasonal analysis."""
import json
import os
import tempfile
import time
import threading
from unittest.mock import MagicMock
import pytest
from humidity_analysis import (
    _collect_sample, _build_daily_snapshot, append_snapshot,
    get_summary, get_season, _load_json, _season_summary,
    SEASON_ORDER,
)


def _make_mqtt(humidity_values):
    from mqtt_handler import SensorReading
    now = time.time()
    m = MagicMock()
    m._lock = threading.Lock()
    m.history = {
        "sensor1": [SensorReading(25.0, h, 80, now - i * 60)
                    for i, h in enumerate(humidity_values)],
    }
    return m


def _make_sample(date, hour, mean, n=50):
    return {
        "timestamp": time.time(), "date": date, "hour": hour,
        "mean": mean, "min": mean - 2, "max": mean + 2,
        "sample_n": n, "sensors": ["s1"],
    }


def _snap(date, mean=39.0, frac=0.6, signal=False):
    return {
        "date": date, "season": get_season(date),
        "mean": mean, "min": 35.0, "max": 45.0,
        "p25": 37.0, "p75": 41.0,
        "fraction_below_40": frac, "fraction_above_55": 0.0,
        "humidifier_needed_signal": signal,
        "timestamp": time.time(), "hours_sampled": 12,
        "sensors": [], "hourly_pattern": {},
    }


class TestGetSeason:
    def test_july_is_summer(self):      assert get_season("2026-07-15") == "summer"
    def test_january_is_winter(self):   assert get_season("2026-01-10") == "winter"
    def test_december_is_winter(self):  assert get_season("2026-12-25") == "winter"
    def test_april_is_spring(self):     assert get_season("2026-04-20") == "spring"
    def test_october_is_autumn(self):   assert get_season("2026-10-05") == "autumn"


class TestCollectSample:
    def test_returns_correct_fields(self):
        mqtt = _make_mqtt([38, 39, 40, 41, 42])
        result = _collect_sample(mqtt)
        assert result is not None
        for f in ("timestamp", "date", "hour", "mean", "min", "max", "sample_n"):
            assert f in result

    def test_mean_correct(self):
        mqtt = _make_mqtt([40, 40, 40])
        assert _collect_sample(mqtt)["mean"] == 40.0

    def test_excludes_ac_virtual_sensor(self):
        from mqtt_handler import SensorReading
        now = time.time()
        m = MagicMock()
        m._lock = threading.Lock()
        m.history = {
            "sensor1": [SensorReading(25.0, 40, 80, now)],
            "AC":       [SensorReading(20.0, None, None, now)],
        }
        result = _collect_sample(m)
        assert result is not None

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
        assert snap["season"] == "summer"

    def test_season_field_present(self):
        samples = [_make_sample("2026-01-15", h, 38.0) for h in range(4)]
        snap = _build_daily_snapshot("2026-01-15", samples)
        assert snap["season"] == "winter"

    def test_signal_true_when_mean_low(self):
        samples = [_make_sample("2026-07-01", h, 35.0) for h in range(8)]
        assert _build_daily_snapshot("2026-07-01", samples)["humidifier_needed_signal"] is True

    def test_signal_false_when_ok(self):
        samples = [_make_sample("2026-07-01", h, 45.0) for h in range(8)]
        assert _build_daily_snapshot("2026-07-01", samples)["humidifier_needed_signal"] is False

    def test_returns_none_for_missing_date(self):
        samples = [_make_sample("2026-07-01", h, 39.0) for h in range(5)]
        assert _build_daily_snapshot("2026-07-02", samples) is None

    def test_hourly_pattern_present(self):
        samples = [_make_sample("2026-07-01", h, 38.0 + h * 0.2) for h in range(4)]
        snap = _build_daily_snapshot("2026-07-01", samples)
        assert "hourly_pattern" in snap


class TestAppendSnapshot:
    def test_saves_with_season(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = os.path.join(tmp, "t.json")
            append_snapshot(_snap("2026-07-01"), f)
            loaded = _load_json(f)
            assert loaded[0]["season"] == "summer"

    def test_replaces_same_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = os.path.join(tmp, "t.json")
            append_snapshot(_snap("2026-07-01", mean=39.0), f)
            append_snapshot(_snap("2026-07-01", mean=42.0), f)
            loaded = _load_json(f)
            assert len(loaded) == 1
            assert loaded[0]["mean"] == 42.0

    def test_no_max_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = os.path.join(tmp, "t.json")
            for i in range(30):
                append_snapshot(_snap(f"2026-07-{i+1:02d}"), f)
            assert len(_load_json(f)) == 30

    def test_sorted_by_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = os.path.join(tmp, "t.json")
            append_snapshot(_snap("2026-07-05"), f)
            append_snapshot(_snap("2026-07-01"), f)
            loaded = _load_json(f)
            assert loaded[0]["date"] == "2026-07-01"


class TestSeasonSummary:
    def test_empty_seasons_return_no_data(self):
        result = _season_summary([])
        for key in SEASON_ORDER:
            assert result[key]["recommendation"] == "no_data"

    def test_summer_recommended_with_many_signals(self):
        snaps = [_snap(f"2026-07-{i+1:02d}", mean=35.0, frac=0.8, signal=True) for i in range(10)]
        result = _season_summary(snaps)
        assert result["summer"]["recommendation"] == "recommended"

    def test_summer_not_needed_with_no_signals(self):
        snaps = [_snap(f"2026-07-{i+1:02d}", mean=48.0, frac=0.1, signal=False) for i in range(10)]
        result = _season_summary(snaps)
        assert result["summer"]["recommendation"] == "not_needed"

    def test_insufficient_data_when_few_days(self):
        snaps = [_snap("2026-07-01", mean=35.0, frac=0.8, signal=True)]
        result = _season_summary(snaps)
        assert result["summer"]["recommendation"] == "insufficient_data"

    def test_season_counts(self):
        snaps = (
            [_snap(f"2026-07-{i+1:02d}") for i in range(5)] +
            [_snap(f"2026-01-{i+1:02d}") for i in range(3)]
        )
        result = _season_summary(snaps)
        assert result["summer"]["days"] == 5
        assert result["winter"]["days"] == 3

    def test_all_four_seasons_present(self):
        result = _season_summary([])
        assert set(result.keys()) == set(SEASON_ORDER)


class TestGetSummary:
    def test_none_when_no_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            assert get_summary(os.path.join(tmp, "x.json")) is None

    def test_summary_has_seasons_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = os.path.join(tmp, "t.json")
            for i in range(3):
                append_snapshot(_snap(f"2026-07-{i+1:02d}", signal=False), f)
            summary = get_summary(f)
            assert "seasons" in summary
            assert "total_days" in summary

    def test_migration_adds_season_to_old_snapshots(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = os.path.join(tmp, "t.json")
            old_snap = {"date": "2026-07-01", "mean": 38.0, "fraction_below_40": 0.5,
                        "humidifier_needed_signal": False, "timestamp": time.time(),
                        "hours_sampled": 12, "sensors": [], "min": 35.0, "max": 45.0,
                        "p25": 37.0, "p75": 41.0, "fraction_above_55": 0.0, "hourly_pattern": {}}
            import json as _json
            open(f, "w").write(_json.dumps([old_snap]))
            summary = get_summary(f)
            assert summary["seasons"]["summer"]["days"] == 1

