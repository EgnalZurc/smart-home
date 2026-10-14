"""Unit tests for the learning analysis module."""

from datetime import datetime, timezone

from learning import (
    ACTIVE_STATES,
    MIN_RECORDS_FOR_ANALYSIS,
    _pearson,
    analyze_history,
)


def _ts(hour: int, day: int = 1) -> float:
    """Build an epoch timestamp at a given UTC hour."""
    dt = datetime(2026, 1, day, hour, 0, 0, tzinfo=timezone.utc)
    return dt.timestamp()


def _record(hour: int, state: str, temp: float, setpoint: float, day: int = 1) -> dict:
    return {
        "timestamp": _ts(hour, day),
        "average_temp": temp,
        "state": state,
        "setpoint": setpoint,
        "active_sensors": 3,
    }


class TestPearson:
    """Tests for the Pearson helper."""

    def test_perfect_positive_correlation(self):
        assert _pearson([1.0, 2.0, 3.0], [2.0, 4.0, 6.0]) == 1.0

    def test_perfect_negative_correlation(self):
        assert _pearson([1.0, 2.0, 3.0], [6.0, 4.0, 2.0]) == -1.0

    def test_zero_variance_returns_none(self):
        assert _pearson([5.0, 5.0, 5.0], [1.0, 2.0, 3.0]) is None

    def test_too_few_points_returns_none(self):
        assert _pearson([1.0], [2.0]) is None

    def test_mismatched_lengths_returns_none(self):
        assert _pearson([1.0, 2.0], [1.0]) is None


class TestAnalyzeHistory:
    """Tests for the top-level analyze_history function."""

    def test_empty_history_not_enough_data(self):
        result = analyze_history([])
        assert result["enough_data"] is False
        assert result["sample_size"] == 0
        assert result["recommendations"] == []
        assert result["patterns"]["frequent_hours"] == []
        assert result["patterns"]["preferred_setpoints"]["samples"] == 0

    def test_none_history_handled(self):
        result = analyze_history(None)
        assert result["enough_data"] is False
        assert result["sample_size"] == 0

    def test_below_threshold_has_no_recommendations(self):
        records = [_record(18, "cooling_max", 27.0, 24.0)]
        assert len(records) < MIN_RECORDS_FOR_ANALYSIS
        result = analyze_history(records)
        assert result["enough_data"] is False
        assert result["recommendations"] == []

    def test_frequent_hour_detection(self):
        # Three activations at 18h, one at 9h -> 18h ranks first.
        records = [
            _record(18, "cooling_max", 27.0, 24.0),
            _record(18, "modulating", 26.0, 24.0),
            _record(18, "cooling_max", 27.5, 23.0),
            _record(9, "cooling_max", 25.0, 24.0),
        ]
        result = analyze_history(records)
        hours = result["patterns"]["frequent_hours"]
        assert hours[0] == {"hour": 18, "count": 3}
        assert {"hour": 9, "count": 1} in hours

    def test_inactive_states_excluded_from_hours(self):
        records = [
            _record(18, "off", 27.0, 24.0),
            _record(18, "cooldown", 27.0, 24.0),
            _record(18, "system_off", 27.0, 24.0),
        ]
        result = analyze_history(records)
        assert result["patterns"]["frequent_hours"] == []

    def test_preferred_setpoints(self):
        records = [
            _record(18, "cooling_max", 27.0, 22.0),
            _record(19, "modulating", 26.0, 24.0),
            _record(20, "cooling_max", 27.0, 23.0),
        ]
        result = analyze_history(records)
        sp = result["patterns"]["preferred_setpoints"]
        assert sp["min"] == 22.0
        assert sp["max"] == 24.0
        assert sp["average"] == 23.0
        assert sp["samples"] == 3

    def test_temp_setpoint_correlation_present(self):
        records = [
            _record(18, "cooling_max", 25.0, 22.0),
            _record(19, "cooling_max", 27.0, 24.0),
            _record(20, "cooling_max", 29.0, 26.0),
        ]
        result = analyze_history(records)
        corr = result["correlations"]["temperature_vs_setpoint"]
        # Perfectly positively correlated in this synthetic series.
        assert corr["temp_vs_setpoint"] == 1.0
        assert corr["samples"] == 3

    def test_activity_ratio(self):
        records = [
            _record(18, "cooling_max", 27.0, 24.0),
            _record(19, "off", 25.0, 24.0),
        ]
        result = analyze_history(records)
        activity = result["correlations"]["activity"]
        assert activity["active_records"] == 1
        assert activity["total_records"] == 2
        assert activity["active_ratio"] == 0.5

    def test_recommendations_generated_when_enough_data(self):
        records = [
            _record(18, "cooling_max", 27.0, 24.0),
            _record(18, "cooling_max", 27.0, 24.0),
            _record(18, "cooling_max", 27.0, 24.0),
        ]
        result = analyze_history(records)
        assert result["enough_data"] is True
        types = {rec["type"] for rec in result["recommendations"]}
        assert "frequent_hour" in types
        assert "preferred_setpoint" in types
        # All records active -> high_usage recommendation present.
        assert "high_usage" in types
        for rec in result["recommendations"]:
            assert rec["message"]
            assert rec["message_en"]

    def test_frequent_hour_recommendation_mentions_top_hour(self):
        records = [_record(7, "cooling_max", 27.0, 24.0) for _ in range(3)]
        result = analyze_history(records)
        freq = next(
            r for r in result["recommendations"] if r["type"] == "frequent_hour"
        )
        assert "07:00" in freq["message"]
        assert "07:00" in freq["message_en"]

    def test_no_high_usage_recommendation_when_mostly_idle(self):
        records = [
            _record(18, "cooling_max", 27.0, 24.0),
            _record(19, "off", 25.0, 24.0),
            _record(20, "off", 25.0, 24.0),
            _record(21, "off", 25.0, 24.0),
        ]
        result = analyze_history(records)
        types = {rec["type"] for rec in result["recommendations"]}
        assert "high_usage" not in types

    def test_records_with_missing_fields_are_skipped(self):
        records = [
            {"timestamp": None, "state": "cooling_max", "setpoint": 24.0,
             "average_temp": 27.0, "active_sensors": 3},
            {"timestamp": _ts(18), "state": "cooling_max", "setpoint": None,
             "average_temp": 27.0, "active_sensors": 3},
            _record(18, "cooling_max", 27.0, 24.0),
        ]
        # Should not raise despite the partial records.
        result = analyze_history(records)
        assert result["sample_size"] == 3

    def test_active_states_constant_covers_known_states(self):
        assert "cooling_max" in ACTIVE_STATES
        assert "modulating" in ACTIVE_STATES
        assert "off" not in ACTIVE_STATES
