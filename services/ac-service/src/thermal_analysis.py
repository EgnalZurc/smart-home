"""Thermal analysis — heating and cooling curves.

Derives the AC unit's thermal behaviour from a time series of temperature
samples: how fast the room heats or cools, how long it takes to reach the
target setpoint, and how that performance varies with the outdoor
temperature.

Design
------
The controller already keeps an in-memory ``HistoryRecord`` list (timestamp,
average_temp, state, setpoint, active_sensors) but those records carry neither
the heat/cool direction nor the outdoor temperature, both of which the
analysis needs. Rather than widen ``HistoryRecord`` (persisted and consumed by
other code paths), this module owns its own lightweight ``ThermalSample`` ring
buffer that the service appends to on every control tick. The buffer is pure
in-memory state — if the process restarts the curves simply rebuild as new
samples arrive.

The analysis is a pure function over a list of samples, so it is trivially
unit-testable without MQTT, MELCloud or a running control loop.

A "segment" is a maximal run of consecutive samples during which the AC is on
and driving in a single direction (cooling or heating). Within a segment the
rate of change is ``(temp_end - temp_start) / minutes`` and the time-to-target
is the elapsed time until the measured temperature first reaches the setpoint
(within ``TARGET_TOLERANCE_C``). Segments shorter than ``MIN_SEGMENT_SAMPLES``
or ``MIN_SEGMENT_SECONDS`` are ignored as noise.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass

__all__ = [
    "ACTIVE_STATES",
    "TARGET_TOLERANCE_C",
    "MIN_SEGMENT_DELTA_C",
    "MIN_SEGMENT_SAMPLES",
    "MIN_SEGMENT_SECONDS",
    "OUTDOOR_BUCKET_WIDTH_C",
    "DEFAULT_BUFFER_SIZE",
    "ThermalSample",
    "SegmentStats",
    "ThermalBuffer",
    "analyze",
]

# ── Tunables ──────────────────────────────────────────────────────────────────

# AC controller states in which the unit is actively driving the temperature.
# "modulating"/"cooling_max"/"manual" mean the compressor is (or may be) on;
# "off"/"cooldown"/"system_off"/"error" mean it is not driving.
ACTIVE_STATES: frozenset[str] = frozenset({"cooling_max", "modulating", "manual"})

# A measured temperature within this many °C of the setpoint counts as "at
# target" for the time-to-target calculation.
TARGET_TOLERANCE_C: float = 0.3

# Minimum movement away from target (°C) for a segment to count as a real
# heating/cooling run rather than sensor jitter around the setpoint.
MIN_SEGMENT_DELTA_C: float = 0.2

# Minimum size of a segment to be considered meaningful.
MIN_SEGMENT_SAMPLES: int = 3
MIN_SEGMENT_SECONDS: float = 120.0

# Width of each outdoor-temperature bucket (°C) for the efficiency breakdown.
OUTDOOR_BUCKET_WIDTH_C: float = 5.0

# Default ring-buffer capacity (one sample per control tick).
DEFAULT_BUFFER_SIZE: int = 2000


@dataclass(frozen=True)
class ThermalSample:
    """A single point in the thermal time series.

    Attributes:
        timestamp: Unix epoch seconds of the sample.
        average_temp: Mean indoor temperature across active sensors, or None
            when no sensor data is available (sample is then not usable).
        setpoint: AC target setpoint at this instant.
        state: Controller state value (see :data:`ACTIVE_STATES`).
        mode: AC direction, ``"cool"`` or ``"heat"``.
        outdoor_temp: Outdoor temperature if known, else None.
    """

    timestamp: float
    average_temp: float | None
    setpoint: float
    state: str
    mode: str
    outdoor_temp: float | None = None


@dataclass
class _Segment:
    """An internal, in-progress or completed driving run."""

    direction: str  # "cooling" or "heating"
    samples: list[ThermalSample]


@dataclass(frozen=True)
class SegmentStats:
    """Summary of one completed cooling/heating run."""

    direction: str  # "cooling" or "heating"
    rate_c_per_min: float  # signed: negative when cooling, positive when heating
    duration_min: float
    temp_start: float
    temp_end: float
    reached_target: bool
    time_to_target_min: float | None
    outdoor_temp: float | None


class ThermalBuffer:
    """Thread-safe ring buffer of thermal samples.

    The control loop appends one sample per tick from any thread while the API
    reads the full snapshot from the request thread, so access is guarded by a
    lock. The buffer never grows past ``maxlen``; the oldest samples are
    dropped first.
    """

    _samples: deque[ThermalSample]
    _lock: threading.Lock

    def __init__(self, maxlen: int = DEFAULT_BUFFER_SIZE) -> None:
        self._samples = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def add(self, sample: ThermalSample) -> None:
        """Append one sample (ignored if it carries no temperature)."""
        if sample.average_temp is None:
            return
        with self._lock:
            self._samples.append(sample)

    def snapshot(self) -> list[ThermalSample]:
        """Return a shallow copy of the current samples, oldest first."""
        with self._lock:
            return list(self._samples)

    def clear(self) -> None:
        """Drop all buffered samples."""
        with self._lock:
            self._samples.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._samples)


# ── Segmentation ────────────────────────────────────────────────────────────


def _classify_direction(sample: ThermalSample) -> str | None:
    """Return 'cooling'/'heating' for a driving sample, else None.

    A sample drives the temperature only when the controller is in an active
    state and the temperature is on the far side of the setpoint from target.
    Direction follows the AC mode: ``heat`` warms the room, ``cool`` cools it.
    """
    if sample.state not in ACTIVE_STATES:
        return None
    if sample.average_temp is None:
        return None
    if sample.mode == "heat":
        return "heating"
    if sample.mode == "cool":
        return "cooling"
    return None


def _split_segments(samples: list[ThermalSample]) -> list[_Segment]:
    """Group consecutive same-direction active samples into segments."""
    segments: list[_Segment] = []
    current: _Segment | None = None

    for sample in samples:
        direction = _classify_direction(sample)
        if direction is None:
            current = None
            continue
        if current is None or current.direction != direction:
            current = _Segment(direction=direction, samples=[sample])
            segments.append(current)
        else:
            current.samples.append(sample)

    return segments


def _summarise_segment(segment: _Segment) -> SegmentStats | None:
    """Compute stats for one segment, or None if it is too small/noisy."""
    samples = segment.samples
    if len(samples) < MIN_SEGMENT_SAMPLES:
        return None

    first = samples[0]
    last = samples[-1]
    # average_temp is guaranteed non-None for active, classified samples.
    temp_start = first.average_temp
    temp_end = last.average_temp
    assert temp_start is not None and temp_end is not None

    duration_s = last.timestamp - first.timestamp
    if duration_s < MIN_SEGMENT_SECONDS:
        return None

    delta = temp_end - temp_start
    if abs(delta) < MIN_SEGMENT_DELTA_C:
        return None

    duration_min = duration_s / 60.0
    rate = delta / duration_min

    reached_target, time_to_target_min = _time_to_target(samples)
    outdoor = _segment_outdoor_temp(samples)

    return SegmentStats(
        direction=segment.direction,
        rate_c_per_min=rate,
        duration_min=duration_min,
        temp_start=temp_start,
        temp_end=temp_end,
        reached_target=reached_target,
        time_to_target_min=time_to_target_min,
        outdoor_temp=outdoor,
    )


def _time_to_target(samples: list[ThermalSample]) -> tuple[bool, float | None]:
    """Elapsed minutes until temp first reaches the setpoint (±tolerance).

    Returns (reached, minutes). ``reached`` is False when the segment ends
    before the temperature gets within tolerance of the setpoint, in which
    case minutes is None.
    """
    start_ts = samples[0].timestamp
    for sample in samples:
        if sample.average_temp is None:
            continue
        if abs(sample.average_temp - sample.setpoint) <= TARGET_TOLERANCE_C:
            return True, (sample.timestamp - start_ts) / 60.0
    return False, None


def _segment_outdoor_temp(samples: list[ThermalSample]) -> float | None:
    """Mean outdoor temperature across the samples that reported one."""
    values = [s.outdoor_temp for s in samples if s.outdoor_temp is not None]
    if not values:
        return None
    return sum(values) / len(values)


def _outdoor_bucket_label(temp: float) -> str:
    """Return a stable bucket label like '20-25' for an outdoor temperature."""
    import math

    width = OUTDOOR_BUCKET_WIDTH_C
    low = math.floor(temp / width) * width
    high = low + width
    # Render without trailing '.0' when the bounds are whole numbers.
    low_s = f"{low:g}"
    high_s = f"{high:g}"
    return f"{low_s}-{high_s}"


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


# ── Public API ────────────────────────────────────────────────────────────────


def analyze(samples: list[ThermalSample]) -> dict[str, object]:
    """Analyse a thermal time series into heating/cooling curve metrics.

    Args:
        samples: Chronological list of :class:`ThermalSample`. Order is
            assumed oldest-first; the caller (``ThermalBuffer.snapshot``)
            guarantees this.

    Returns:
        A JSON-serialisable dict with:
          - ``heating_rate``: mean °C/min while heating (positive), or None.
          - ``cooling_rate``: mean °C/min while cooling (negative), or None.
          - ``avg_time_to_target``: mean minutes to reach the setpoint across
            segments that reached it, split into ``heating`` / ``cooling`` /
            ``overall`` (each possibly None).
          - ``efficiency_by_outdoor_temp``: per outdoor-temperature-bucket mean
            heating and cooling rates, keyed by a label like ``"20-25"``.
          - ``sample_count`` / ``segment_count``: diagnostics.
    """
    segments = _split_segments(samples)
    stats = [s for s in (_summarise_segment(seg) for seg in segments) if s is not None]

    heating = [s for s in stats if s.direction == "heating"]
    cooling = [s for s in stats if s.direction == "cooling"]

    heating_rate = _mean([s.rate_c_per_min for s in heating])
    cooling_rate = _mean([s.rate_c_per_min for s in cooling])

    heating_ttt = _mean(
        [s.time_to_target_min for s in heating if s.time_to_target_min is not None]
    )
    cooling_ttt = _mean(
        [s.time_to_target_min for s in cooling if s.time_to_target_min is not None]
    )
    overall_ttt = _mean(
        [s.time_to_target_min for s in stats if s.time_to_target_min is not None]
    )

    efficiency = _efficiency_by_outdoor(stats)

    return {
        "heating_rate": _round(heating_rate),
        "cooling_rate": _round(cooling_rate),
        "avg_time_to_target": {
            "heating": _round(heating_ttt),
            "cooling": _round(cooling_ttt),
            "overall": _round(overall_ttt),
        },
        "efficiency_by_outdoor_temp": efficiency,
        "sample_count": len(samples),
        "segment_count": len(stats),
    }


def _efficiency_by_outdoor(stats: list[SegmentStats]) -> dict[str, dict[str, object]]:
    """Group segment rates into outdoor-temperature buckets.

    Each bucket reports the mean heating and cooling rate observed while the
    outdoor temperature fell in that range, plus how many segments contributed.
    Segments without an outdoor reading are skipped (they cannot be bucketed).
    """
    buckets: dict[str, dict[str, list[float]]] = {}
    for s in stats:
        if s.outdoor_temp is None:
            continue
        label = _outdoor_bucket_label(s.outdoor_temp)
        bucket = buckets.setdefault(label, {"heating": [], "cooling": []})
        bucket[s.direction].append(s.rate_c_per_min)

    result: dict[str, dict[str, object]] = {}
    for label in sorted(buckets, key=_bucket_sort_key):
        heating_rates = buckets[label]["heating"]
        cooling_rates = buckets[label]["cooling"]
        result[label] = {
            "heating_rate": _round(_mean(heating_rates)),
            "cooling_rate": _round(_mean(cooling_rates)),
            "segment_count": len(heating_rates) + len(cooling_rates),
        }
    return result


def _bucket_sort_key(label: str) -> float:
    """Sort bucket labels numerically by their lower bound."""
    try:
        return float(label.split("-")[0])
    except (ValueError, IndexError):
        return float("inf")


def _round(value: float | None, ndigits: int = 3) -> float | None:
    return round(value, ndigits) if value is not None else None
