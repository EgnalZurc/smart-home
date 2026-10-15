"""Unit tests for the thermal_analysis module.

Covers the ThermalBuffer ring buffer, segment classification/summarisation,
and the public ``analyze`` curve metrics (rates, time-to-target, and the
outdoor-temperature efficiency breakdown).
"""

import pytest
from thermal_analysis import (
    MIN_SEGMENT_SAMPLES,
    ThermalBuffer,
    ThermalSample,
    analyze,
)


def _series(
    start_ts: float,
    temps: list[float],
    setpoint: float,
    mode: str,
    state: str = "modulating",
    step_s: float = 60.0,
    outdoor: float | None = None,
) -> list[ThermalSample]:
    """Build a chronological sample list, one per ``step_s`` seconds."""
    return [
        ThermalSample(
            timestamp=start_ts + i * step_s,
            average_temp=t,
            setpoint=setpoint,
            state=state,
            mode=mode,
            outdoor_temp=outdoor,
        )
        for i, t in enumerate(temps)
    ]


# ── ThermalBuffer ──────────────────────────────────────────────────────────


class TestThermalBuffer:
    def test_add_and_snapshot_preserve_order(self):
        buf = ThermalBuffer(maxlen=10)
        buf.add(ThermalSample(1.0, 25.0, 24.0, "modulating", "cool"))
        buf.add(ThermalSample(2.0, 24.5, 24.0, "modulating", "cool"))
        snap = buf.snapshot()
        assert [s.timestamp for s in snap] == [1.0, 2.0]

    def test_none_temperature_is_ignored(self):
        buf = ThermalBuffer()
        buf.add(ThermalSample(1.0, None, 24.0, "off", "cool"))
        assert len(buf) == 0

    def test_ring_buffer_drops_oldest(self):
        buf = ThermalBuffer(maxlen=2)
        for i in range(5):
            buf.add(ThermalSample(float(i), 25.0, 24.0, "modulating", "cool"))
        snap = buf.snapshot()
        assert len(snap) == 2
        assert [s.timestamp for s in snap] == [3.0, 4.0]

    def test_clear(self):
        buf = ThermalBuffer()
        buf.add(ThermalSample(1.0, 25.0, 24.0, "modulating", "cool"))
        buf.clear()
        assert len(buf) == 0

    def test_snapshot_is_a_copy(self):
        buf = ThermalBuffer()
        buf.add(ThermalSample(1.0, 25.0, 24.0, "modulating", "cool"))
        snap = buf.snapshot()
        buf.add(ThermalSample(2.0, 24.0, 24.0, "modulating", "cool"))
        # The earlier snapshot must not see the later append.
        assert len(snap) == 1


# ── analyze: empty / insufficient data ──────────────────────────────────────


class TestAnalyzeEmpty:
    def test_empty_input(self):
        result = analyze([])
        assert result["heating_rate"] is None
        assert result["cooling_rate"] is None
        assert result["avg_time_to_target"] == {
            "heating": None,
            "cooling": None,
            "overall": None,
        }
        assert result["efficiency_by_outdoor_temp"] == {}
        assert result["sample_count"] == 0
        assert result["segment_count"] == 0

    def test_segment_too_short_in_samples_is_ignored(self):
        # Fewer than MIN_SEGMENT_SAMPLES → no segment.
        temps = [26.0, 25.5][: MIN_SEGMENT_SAMPLES - 1]
        samples = _series(0.0, temps, setpoint=24.0, mode="cool")
        result = analyze(samples)
        assert result["segment_count"] == 0
        assert result["cooling_rate"] is None

    def test_segment_too_short_in_time_is_ignored(self):
        # Enough samples but spanning < MIN_SEGMENT_SECONDS.
        samples = _series(
            0.0, [26.0, 25.0, 24.5, 24.0], setpoint=24.0, mode="cool", step_s=10.0
        )
        result = analyze(samples)
        assert result["segment_count"] == 0

    def test_flat_segment_below_delta_is_ignored(self):
        # Temperature barely moves → below MIN_SEGMENT_DELTA_C.
        samples = _series(
            0.0, [24.05, 24.0, 24.02, 24.01, 24.0], setpoint=24.0, mode="cool"
        )
        result = analyze(samples)
        assert result["segment_count"] == 0


# ── analyze: cooling / heating rates ────────────────────────────────────────


class TestAnalyzeRates:
    def test_cooling_rate_is_negative(self):
        # 28 → 24 over 4 minutes = -1.0 °C/min.
        samples = _series(
            0.0, [28.0, 27.0, 26.0, 25.0, 24.0], setpoint=24.0, mode="cool"
        )
        result = analyze(samples)
        assert result["cooling_rate"] == pytest.approx(-1.0)
        assert result["heating_rate"] is None
        assert result["segment_count"] == 1

    def test_heating_rate_is_positive(self):
        # 18 → 22 over 4 minutes = +1.0 °C/min.
        samples = _series(
            0.0, [18.0, 19.0, 20.0, 21.0, 22.0], setpoint=22.0, mode="heat"
        )
        result = analyze(samples)
        assert result["heating_rate"] == pytest.approx(1.0)
        assert result["cooling_rate"] is None

    def test_time_to_target_cooling(self):
        # Reaches within 0.3 of setpoint (24.0) at the last sample (t=240s=4min).
        samples = _series(
            0.0, [28.0, 27.0, 26.0, 25.0, 24.0], setpoint=24.0, mode="cool"
        )
        result = analyze(samples)
        assert result["avg_time_to_target"]["cooling"] == pytest.approx(4.0)
        assert result["avg_time_to_target"]["overall"] == pytest.approx(4.0)

    def test_time_to_target_none_when_not_reached(self):
        # Temperature never gets within tolerance of the setpoint.
        samples = _series(
            0.0, [30.0, 29.0, 28.5, 28.0, 27.5], setpoint=24.0, mode="cool"
        )
        result = analyze(samples)
        assert result["avg_time_to_target"]["cooling"] is None
        assert result["cooling_rate"] is not None  # rate still computed

    def test_rates_averaged_across_multiple_segments(self):
        # Two cooling runs separated by an off period; rates -1.0 and -0.5.
        seg1 = _series(0.0, [28.0, 27.0, 26.0, 25.0, 24.0], 24.0, "cool")
        off = [ThermalSample(300.0, 24.0, 24.0, "off", "cool")]
        seg2 = _series(400.0, [27.0, 26.5, 26.0, 25.5, 25.0], 25.0, "cool")
        result = analyze(seg1 + off + seg2)
        assert result["segment_count"] == 2
        # Mean of -1.0 and -0.5 = -0.75.
        assert result["cooling_rate"] == pytest.approx(-0.75)


# ── analyze: segmentation boundaries ────────────────────────────────────────


class TestSegmentation:
    def test_off_state_breaks_segment(self):
        samples = (
            _series(0.0, [28.0, 27.0, 26.0], 24.0, "cool")
            + [ThermalSample(180.0, 25.5, 24.0, "off", "cool")]
            + _series(240.0, [25.0, 24.5, 24.0], 24.0, "cool")
        )
        result = analyze(samples)
        assert result["segment_count"] == 2

    def test_direction_change_breaks_segment(self):
        cooling = _series(0.0, [28.0, 27.0, 26.0, 25.0], 24.0, "cool")
        heating = _series(240.0, [20.0, 21.0, 22.0, 23.0], 24.0, "heat")
        result = analyze(cooling + heating)
        assert result["segment_count"] == 2
        assert result["cooling_rate"] is not None
        assert result["heating_rate"] is not None

    def test_cooldown_state_is_not_active(self):
        samples = _series(0.0, [28.0, 27.0, 26.0, 25.0], 24.0, "cool", state="cooldown")
        result = analyze(samples)
        assert result["segment_count"] == 0


# ── analyze: efficiency by outdoor temperature ──────────────────────────────


class TestEfficiencyByOutdoor:
    def test_buckets_by_outdoor_temp(self):
        warm = _series(0.0, [30.0, 29.0, 28.0, 27.0, 26.0], 26.0, "cool", outdoor=32.0)
        # An off sample forces a segment break so the two runs are analysed
        # independently rather than merged into one averaged segment.
        gap = [ThermalSample(300.0, 26.0, 26.0, "off", "cool")]
        mild = _series(
            600.0, [28.0, 27.0, 26.0, 25.0, 24.0], 24.0, "cool", outdoor=22.0
        )
        result = analyze(warm + gap + mild)
        eff = result["efficiency_by_outdoor_temp"]
        assert "30-35" in eff
        assert "20-25" in eff
        assert eff["30-35"]["cooling_rate"] == pytest.approx(-1.0)
        assert eff["20-25"]["cooling_rate"] == pytest.approx(-1.0)
        assert eff["30-35"]["segment_count"] == 1

    def test_segment_without_outdoor_is_excluded_from_buckets(self):
        samples = _series(0.0, [28.0, 27.0, 26.0, 25.0, 24.0], 24.0, "cool")
        result = analyze(samples)
        assert result["efficiency_by_outdoor_temp"] == {}
        assert result["cooling_rate"] is not None  # still in overall rate

    def test_buckets_sorted_by_lower_bound(self):
        hot = _series(0.0, [30.0, 29.0, 28.0, 27.0], 27.0, "cool", outdoor=38.0)
        gap = [ThermalSample(300.0, 27.0, 27.0, "off", "cool")]
        cold = _series(600.0, [28.0, 27.0, 26.0, 25.0], 25.0, "cool", outdoor=12.0)
        result = analyze(hot + gap + cold)
        labels = list(result["efficiency_by_outdoor_temp"].keys())
        assert labels == sorted(labels, key=lambda s: float(s.split("-")[0]))
