"""Daily humidity analysis scheduler (HUM-0).

Runs every 24h, reads sensor history, computes humidity statistics,
and appends a daily snapshot to /app/data/humidity_analysis.json.
Keeps 21 days of snapshots for the 3-week study period.

After 3 weeks, review the data to decide whether a humidifier is needed.
Decision criteria:
  - If mean < 38% or fraction_below_40 > 0.70 consistently -> implement humidifier
  - If values stay >= 38-40% -> no action needed
"""

import json
import logging
import os
import statistics
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

HUMIDITY_ANALYSIS_FILE = os.environ.get(
    "HUMIDITY_ANALYSIS_FILE", "/app/data/humidity_analysis.json"
)
MAX_SNAPSHOTS = 21          # 3-week study window (one snapshot per day)
LOW_THRESHOLD  = 40.0       # Below this = dry (target: should be rare)
HIGH_THRESHOLD = 55.0       # Above this = humid (not expected, but tracked)
STUDY_DAYS     = 21         # Study duration
ANALYSIS_INTERVAL_H = 24    # Frequency of snapshots in hours


def analyse_humidity(mqtt_handler) -> dict | None:
    """Compute humidity statistics from all sensor history in memory."""
    with mqtt_handler._lock:
        readings_by_sensor = {
            name: [(r.humidity, r.timestamp) for r in readings if r.humidity is not None]
            for name, readings in mqtt_handler.history.items()
            if readings
        }

    all_values = [h for pairs in readings_by_sensor.values() for h, _ in pairs]
    if not all_values:
        logger.warning("[humidity_analysis] No humidity readings available")
        return None

    n = len(all_values)
    sorted_vals = sorted(all_values)

    def percentile(data, p):
        idx = (len(data) - 1) * p / 100
        lo = int(idx)
        hi = min(lo + 1, len(data) - 1)
        return round(data[lo] + (data[hi] - data[lo]) * (idx - lo), 2)

    # Per-sensor stats
    per_sensor = {}
    for name, pairs in readings_by_sensor.items():
        vals = [h for h, _ in pairs]
        if vals:
            per_sensor[name] = {
                "n": len(vals),
                "mean": round(statistics.mean(vals), 2),
                "min": round(min(vals), 2),
                "max": round(max(vals), 2),
                "p25": percentile(sorted(vals), 25),
                "p75": percentile(sorted(vals), 75),
            }

    return {
        "date":                  datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "timestamp":             round(time.time(), 1),
        "sample_count":          n,
        "sensors":               list(readings_by_sensor.keys()),
        "mean":                  round(statistics.mean(all_values), 2),
        "median":                round(statistics.median(all_values), 2),
        "min":                   round(min(all_values), 2),
        "max":                   round(max(all_values), 2),
        "stdev":                 round(statistics.stdev(all_values), 2) if n > 1 else 0,
        "p10":                   percentile(sorted_vals, 10),
        "p25":                   percentile(sorted_vals, 25),
        "p75":                   percentile(sorted_vals, 75),
        "p90":                   percentile(sorted_vals, 90),
        "fraction_below_40":     round(sum(1 for v in all_values if v < LOW_THRESHOLD)  / n, 4),
        "fraction_above_55":     round(sum(1 for v in all_values if v > HIGH_THRESHOLD) / n, 4),
        "per_sensor":            per_sensor,
        # Derived recommendation signal for easy review
        "humidifier_needed_signal": (
            statistics.mean(all_values) < 38.0
            or sum(1 for v in all_values if v < LOW_THRESHOLD) / n > 0.65
        ),
    }


def load_snapshots(filepath: str) -> list:
    path = Path(filepath)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("[humidity_analysis] Could not read analysis file: %s", e)
        return []


def save_snapshots(snapshots: list, filepath: str) -> None:
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshots, ensure_ascii=False, indent=2), encoding="utf-8")


def append_snapshot(snapshot: dict, filepath: str = HUMIDITY_ANALYSIS_FILE) -> None:
    """Append today's snapshot. Keeps max MAX_SNAPSHOTS entries (one per day)."""
    snapshots = load_snapshots(filepath)

    # Replace existing entry for today if already present
    today = snapshot["date"]
    snapshots = [s for s in snapshots if s.get("date") != today]
    snapshots.append(snapshot)

    # Keep only the most recent MAX_SNAPSHOTS days
    snapshots = sorted(snapshots, key=lambda s: s["date"])[-MAX_SNAPSHOTS:]
    save_snapshots(snapshots, filepath)
    logger.info(
        "[humidity_analysis] Snapshot saved for %s ? mean=%.1f%%, "
        "below_40=%.0f%%, signal=%s (%d/%d days stored)",
        today,
        snapshot["mean"],
        snapshot["fraction_below_40"] * 100,
        "YES" if snapshot["humidifier_needed_signal"] else "no",
        len(snapshots),
        MAX_SNAPSHOTS,
    )


def get_summary(filepath: str = HUMIDITY_ANALYSIS_FILE) -> dict | None:
    """Return a summary of the study so far for the API."""
    snapshots = load_snapshots(filepath)
    if not snapshots:
        return None

    means = [s["mean"] for s in snapshots]
    below40_fractions = [s["fraction_below_40"] for s in snapshots]
    signals = [s.get("humidifier_needed_signal", False) for s in snapshots]

    return {
        "days_collected":       len(snapshots),
        "study_duration_days":  STUDY_DAYS,
        "date_first":           snapshots[0]["date"],
        "date_last":            snapshots[-1]["date"],
        "overall_mean":         round(statistics.mean(means), 2),
        "avg_fraction_below_40": round(statistics.mean(below40_fractions), 4),
        "days_signal_yes":      sum(signals),
        "recommendation":       (
            "HUMIDIFIER RECOMMENDED"
            if sum(signals) >= len(snapshots) * 0.6
            else "Monitor more days"
            if len(snapshots) < STUDY_DAYS
            else "No action needed"
        ),
        "snapshots": snapshots,
    }


class HumidityAnalysisScheduler:
    """Background thread that runs daily humidity analysis."""

    def __init__(
        self,
        mqtt_handler,
        interval_seconds: int = ANALYSIS_INTERVAL_H * 3600,
        grace_period_seconds: int = 300,   # 5 min after boot before first run
    ):
        self._mqtt   = mqtt_handler
        self._interval     = interval_seconds
        self._grace        = grace_period_seconds
        self._running      = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="humidity-analysis")
        self._thread.start()
        logger.info(
            "[humidity_analysis] Scheduler started ? runs every %dh, grace=%ds",
            self._interval // 3600, self._grace
        )

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    def run_now(self) -> None:
        """Trigger an immediate analysis (e.g. from an API endpoint)."""
        self._run_once()

    def _loop(self) -> None:
        time.sleep(self._grace)
        if self._running:
            self._run_once()
        while self._running:
            time.sleep(self._interval)
            if self._running:
                self._run_once()

    def _run_once(self) -> None:
        logger.info("[humidity_analysis] Running daily analysis...")
        try:
            snapshot = analyse_humidity(self._mqtt)
            if snapshot:
                append_snapshot(snapshot)
        except Exception as exc:
            logger.error("[humidity_analysis] Analysis failed: %s", exc, exc_info=True)
