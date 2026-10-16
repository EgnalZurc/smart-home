"""AC usage learning module.

Derives simple usage insights from the controller action history using
basic descriptive statistics — no machine learning.

The controller keeps an in-memory history of records shaped like:

    {
        "timestamp": float,        # epoch seconds (UTC)
        "average_temp": float|None,# average room temperature at that tick
        "state": str,              # controller state (e.g. "cooling_max")
        "setpoint": float,         # commanded setpoint
        "active_sensors": int,     # number of sensors reporting
    }

From that stream we infer:

  * Patterns      — frequent on-hours and preferred setpoint temperatures.
  * Correlations  — relationship between room temperature and setpoint, plus
                    the share of time the AC spent actively running.
  * Recommendations — short human-readable hints derived from the patterns
                    (e.g. "you usually turn it on around 18:00").

All functions are pure (no I/O) so they can be unit-tested in isolation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, TypedDict

# Controller states that mean the AC is actively producing cold air.
# "off", "cooldown", "system_off" and "error" are considered inactive.
ACTIVE_STATES: frozenset[str] = frozenset(
    {"cooling_max", "cooling_mid", "modulating", "forced_on", "manual"}
)

# Minimum number of history records required before we attempt any analysis.
MIN_RECORDS_FOR_ANALYSIS: int = 3


class HourPattern(TypedDict):
    """Hour pattern entry."""

    hour: int
    count: int


class SetpointStats(TypedDict):
    """Setpoint statistics."""

    average: float | None
    min: float | None
    max: float | None
    samples: int


class CorrelationResult(TypedDict):
    """Temperature vs setpoint correlation result."""

    temp_vs_setpoint: float | None
    samples: int


class ActivityStats(TypedDict):
    """Activity ratio statistics."""

    active_ratio: float | None
    active_records: int
    total_records: int


class Recommendation(TypedDict):
    """A recommendation entry."""

    type: str
    message: str
    message_en: str


class PatternsDict(TypedDict):
    """Patterns section of analysis result."""

    frequent_hours: list[HourPattern]
    preferred_setpoints: SetpointStats


class CorrelationsDict(TypedDict):
    """Correlations section of analysis result."""

    temperature_vs_setpoint: CorrelationResult
    activity: ActivityStats


class LearningResult(TypedDict):
    """Full learning analysis result."""

    enough_data: bool
    sample_size: int
    patterns: PatternsDict
    correlations: CorrelationsDict
    recommendations: list[Recommendation]


def _record_hour(timestamp: float) -> int:
    """Return the local-UTC hour (0-23) for an epoch timestamp."""
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).hour


def _mean(values: list[float]) -> float | None:
    """Arithmetic mean, or None for an empty list."""
    if not values:
        return None
    return sum(values) / len(values)


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    """Pearson correlation coefficient between two equal-length series.

    Returns None if fewer than two paired points exist or if either series has
    zero variance (correlation undefined).
    """
    n = len(xs)
    if n < 2 or len(ys) != n:
        return None

    mean_x = sum(xs) / n
    mean_y = sum(ys) / n

    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)

    if var_x == 0 or var_y == 0:
        return None

    return cov / (var_x * var_y) ** 0.5


def _detect_hour_patterns(records: list[dict[str, Any]]) -> list[HourPattern]:
    """Count how often the AC was active per hour-of-day.

    Returns a list sorted by descending activation count, each entry::

        {"hour": 18, "count": 12}
    """
    counts: dict[int, int] = {}
    for rec in records:
        if rec.get("state") not in ACTIVE_STATES:
            continue
        ts = rec.get("timestamp")
        if ts is None:
            continue
        hour = _record_hour(ts)
        counts[hour] = counts.get(hour, 0) + 1

    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [{"hour": hour, "count": count} for hour, count in ranked]


def _preferred_setpoints(records: list[dict[str, Any]]) -> SetpointStats:
    """Summarise the setpoints the AC ran at while active."""
    setpoints = [
        rec["setpoint"]
        for rec in records
        if rec.get("state") in ACTIVE_STATES and rec.get("setpoint") is not None
    ]
    if not setpoints:
        return {"average": None, "min": None, "max": None, "samples": 0}

    avg = _mean(setpoints)
    return {
        "average": round(avg, 2) if avg is not None else None,
        "min": round(min(setpoints), 2),
        "max": round(max(setpoints), 2),
        "samples": len(setpoints),
    }


def _temp_setpoint_correlation(records: list[dict[str, Any]]) -> CorrelationResult:
    """Correlate room temperature against commanded setpoint while active."""
    temps: list[float] = []
    setpoints: list[float] = []
    for rec in records:
        if rec.get("state") not in ACTIVE_STATES:
            continue
        temp = rec.get("average_temp")
        setpoint = rec.get("setpoint")
        if temp is None or setpoint is None:
            continue
        temps.append(temp)
        setpoints.append(setpoint)

    coefficient = _pearson(temps, setpoints)
    return {
        "temp_vs_setpoint": round(coefficient, 3) if coefficient is not None else None,
        "samples": len(temps),
    }


def _activity_ratio(records: list[dict[str, Any]]) -> ActivityStats:
    """Share of history records in which the AC was actively running."""
    total = len(records)
    if total == 0:
        return {"active_ratio": None, "active_records": 0, "total_records": 0}

    active = sum(1 for rec in records if rec.get("state") in ACTIVE_STATES)
    return {
        "active_ratio": round(active / total, 3),
        "active_records": active,
        "total_records": total,
    }


def _build_recommendations(
    hour_patterns: list[HourPattern],
    setpoints: SetpointStats,
    activity: ActivityStats,
) -> list[Recommendation]:
    """Turn raw patterns into short, human-readable hints (ES + EN)."""
    recommendations: list[Recommendation] = []

    if hour_patterns:
        top_hour = hour_patterns[0]["hour"]
        recommendations.append(
            {
                "type": "frequent_hour",
                "message": f"Sueles encender el AC alrededor de las {top_hour:02d}:00.",
                "message_en": f"You usually turn the AC on around {top_hour:02d}:00.",
            }
        )

    if setpoints.get("average") is not None:
        avg = setpoints["average"]
        recommendations.append(
            {
                "type": "preferred_setpoint",
                "message": f"Tu temperatura preferida ronda los {avg:.1f}°C.",
                "message_en": f"Your preferred temperature is around {avg:.1f}°C.",
            }
        )

    ratio = activity.get("active_ratio")
    if ratio is not None and ratio >= 0.5:
        pct = round(ratio * 100)
        recommendations.append(
            {
                "type": "high_usage",
                "message": (
                    f"El AC ha estado activo el {pct}% del tiempo registrado; "
                    "considera subir la consigna para ahorrar energía."
                ),
                "message_en": (
                    f"The AC was active {pct}% of the recorded time; "
                    "consider raising the setpoint to save energy."
                ),
            }
        )

    return recommendations


def analyze_history(records: list[dict[str, Any]]) -> LearningResult:
    """Produce the full learning report from controller history.

    Args:
        records: list of history dicts as returned by
            ``ACController.get_history``.

    Returns:
        A JSON-serialisable dict with ``enough_data``, ``patterns``,
        ``correlations`` and ``recommendations`` keys.
    """
    records = records or []
    enough = len(records) >= MIN_RECORDS_FOR_ANALYSIS

    hour_patterns = _detect_hour_patterns(records)
    setpoints = _preferred_setpoints(records)
    correlation = _temp_setpoint_correlation(records)
    activity = _activity_ratio(records)

    recommendations = (
        _build_recommendations(hour_patterns, setpoints, activity) if enough else []
    )

    return {
        "enough_data": enough,
        "sample_size": len(records),
        "patterns": {
            "frequent_hours": hour_patterns,
            "preferred_setpoints": setpoints,
        },
        "correlations": {
            "temperature_vs_setpoint": correlation,
            "activity": activity,
        },
        "recommendations": recommendations,
    }
