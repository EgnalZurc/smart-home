"""Humidity analysis scheduler for 3-week humidifier study (HUM-0).

Architecture:
- Runs every SAMPLE_INTERVAL_H (default: 1h) to collect an hourly sample
- Each sample captures the current sensor readings in memory
- Hourly samples for the current day are accumulated in-memory and on disk
- At end of day (00:00-01:00), consolidates all hourly samples into one
  daily snapshot that truly represents the full 24h distribution
- Keeps 21 daily snapshots (3 weeks) in /app/data/humidity_analysis.json
- Keeps last 72 hourly samples in /app/data/humidity_hourly.json (rolling)

This avoids the bias of reading at a single time of day (afternoons are
more humid, nights drier - a single daily reading would miss this variation).
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

HUMIDITY_ANALYSIS_FILE = os.environ.get("HUMIDITY_ANALYSIS_FILE", "/app/data/humidity_analysis.json")
HUMIDITY_HOURLY_FILE   = os.environ.get("HUMIDITY_HOURLY_FILE",   "/app/data/humidity_hourly.json")
MAX_SNAPSHOTS          = 21     # 3-week daily study
MAX_HOURLY_SAMPLES     = 72     # Rolling window: last 72 hours stored on disk
SAMPLE_INTERVAL_H      = 1      # Collect a sample every hour
LOW_THRESHOLD          = 40.0   # Below this = dry
HIGH_THRESHOLD         = 55.0   # Above this = humid
STUDY_DAYS             = 21


# ?? Helpers ???????????????????????????????????????????????????????????????????

def _percentile(sorted_data: list, p: float) -> float:
    if not sorted_data:
        return 0.0
    idx = (len(sorted_data) - 1) * p / 100
    lo, hi = int(idx), min(int(idx) + 1, len(sorted_data) - 1)
    return round(sorted_data[lo] + (sorted_data[hi] - sorted_data[lo]) * (idx - lo), 2)


def _load_json(filepath: str) -> list:
    path = Path(filepath)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("[humidity] Could not read %s: %s", filepath, e)
        return []


def _save_json(data, filepath: str) -> None:
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ?? Core analysis ?????????????????????????????????????????????????????????????

def _collect_sample(mqtt_handler) -> dict | None:
    """Read current sensor data and return a timestamped humidity sample."""
    with mqtt_handler._lock:
        readings = {
            name: [r.humidity for r in rlist if r.humidity is not None]
            for name, rlist in mqtt_handler.history.items()
            if rlist
        }

    all_values = [h for vals in readings.values() for h in vals]
    if not all_values:
        return None

    now = datetime.now(timezone.utc)
    return {
        "timestamp":   round(time.time(), 1),
        "date":        now.strftime("%Y-%m-%d"),
        "hour":        now.hour,
        "mean":        round(statistics.mean(all_values), 2),
        "min":         round(min(all_values), 2),
        "max":         round(max(all_values), 2),
        "sample_n":    len(all_values),
        "sensors":     list(readings.keys()),
    }


def _build_daily_snapshot(date: str, hourly_samples: list) -> dict | None:
    """Consolidate hourly samples for a given date into one daily snapshot."""
    day_samples = [s for s in hourly_samples if s["date"] == date]
    if not day_samples:
        return None

    # Weighted by sample_n to give more weight to hours with more data
    all_means  = [s["mean"] for s in day_samples]
    weights    = [s["sample_n"] for s in day_samples]
    total_w    = sum(weights)
    w_mean     = round(sum(m * w for m, w in zip(all_means, weights)) / total_w, 2)

    all_mins   = [s["min"] for s in day_samples]
    all_maxs   = [s["max"] for s in day_samples]

    # Hourly distribution
    sorted_means = sorted(all_means)
    n = len(sorted_means)

    # Fraction of hours below / above thresholds (hour-level, not reading-level)
    frac_below = round(sum(1 for m in all_means if m < LOW_THRESHOLD)  / n, 4)
    frac_above = round(sum(1 for m in all_means if m > HIGH_THRESHOLD) / n, 4)

    # Hourly pattern: {hour: mean}
    hourly_pattern = {str(s["hour"]): s["mean"] for s in day_samples}

    return {
        "date":                   date,
        "timestamp":              round(time.time(), 1),
        "hours_sampled":          n,
        "sensors":                day_samples[0]["sensors"],
        "mean":                   w_mean,
        "min":                    round(min(all_mins), 2),
        "max":                    round(max(all_maxs), 2),
        "p25":                    _percentile(sorted_means, 25),
        "p75":                    _percentile(sorted_means, 75),
        "fraction_below_40":      frac_below,
        "fraction_above_55":      frac_above,
        "hourly_pattern":         hourly_pattern,
        "humidifier_needed_signal": (
            w_mean < 38.0 or frac_below > 0.65
        ),
    }


# ?? Persistence ????????????????????????????????????????????????????????????????

def _append_hourly_sample(sample: dict) -> None:
    samples = _load_json(HUMIDITY_HOURLY_FILE)
    samples.append(sample)
    samples = samples[-MAX_HOURLY_SAMPLES:]
    _save_json(samples, HUMIDITY_HOURLY_FILE)


def append_snapshot(snapshot: dict, filepath: str = HUMIDITY_ANALYSIS_FILE) -> None:
    snapshots = _load_json(filepath)
    date = snapshot["date"]
    snapshots = [s for s in snapshots if s.get("date") != date]
    snapshots.append(snapshot)
    snapshots = sorted(snapshots, key=lambda s: s["date"])[-MAX_SNAPSHOTS:]
    _save_json(snapshots, filepath)
    logger.info(
        "[humidity] Daily snapshot saved for %s ? mean=%.1f%%, hours=%d, "
        "below_40=%.0f%%, signal=%s (%d/%d days stored)",
        date, snapshot["mean"], snapshot["hours_sampled"],
        snapshot["fraction_below_40"] * 100,
        "YES" if snapshot["humidifier_needed_signal"] else "no",
        len(snapshots), MAX_SNAPSHOTS,
    )


# ?? Public API helpers ?????????????????????????????????????????????????????????

def get_summary(filepath: str = HUMIDITY_ANALYSIS_FILE) -> dict | None:
    snapshots = _load_json(filepath)
    if not snapshots:
        return None

    means    = [s["mean"] for s in snapshots]
    fracs    = [s["fraction_below_40"] for s in snapshots]
    signals  = [s.get("humidifier_needed_signal", False) for s in snapshots]

    return {
        "days_collected":        len(snapshots),
        "study_duration_days":   STUDY_DAYS,
        "date_first":            snapshots[0]["date"],
        "date_last":             snapshots[-1]["date"],
        "overall_mean":          round(statistics.mean(means), 2),
        "avg_fraction_below_40": round(statistics.mean(fracs), 4),
        "days_signal_yes":       sum(signals),
        "recommendation": (
            "HUMIDIFIER RECOMMENDED"
            if sum(signals) >= len(snapshots) * 0.6
            else "Monitor more days"
            if len(snapshots) < STUDY_DAYS
            else "No action needed"
        ),
        "snapshots": snapshots,
    }


# ?? Scheduler ??????????????????????????????????????????????????????????????????

class HumidityAnalysisScheduler:
    """
    Runs every SAMPLE_INTERVAL_H hours.
    - Each run: collects one hourly sample from current sensor data
    - At day boundary (hour 0): consolidates previous day's samples
      into a single daily snapshot covering all 24 hours
    """

    def __init__(
        self,
        mqtt_handler,
        sample_interval_seconds: int = SAMPLE_INTERVAL_H * 3600,
        grace_period_seconds:    int = 120,
    ):
        self._mqtt     = mqtt_handler
        self._interval = sample_interval_seconds
        self._grace    = grace_period_seconds
        self._running  = False
        self._thread: threading.Thread | None = None
        self._last_consolidated_date: str | None = None

    def start(self) -> None:
        self._running = True
        self._thread  = threading.Thread(
            target=self._loop, daemon=True, name="humidity-analysis"
        )
        self._thread.start()
        logger.info(
            "[humidity] Scheduler started ? samples every %dh, grace=%ds",
            self._interval // 3600, self._grace,
        )

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    def run_now(self) -> None:
        """Trigger an immediate sample + optional consolidation (for API/testing)."""
        self._collect_and_consolidate()

    def _loop(self) -> None:
        time.sleep(self._grace)
        if self._running:
            self._collect_and_consolidate()
        while self._running:
            time.sleep(self._interval)
            if self._running:
                self._collect_and_consolidate()

    def _collect_and_consolidate(self) -> None:
        now  = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")

        # 1. Collect hourly sample
        try:
            sample = _collect_sample(self._mqtt)
            if sample:
                _append_hourly_sample(sample)
                logger.info(
                    "[humidity] Hourly sample collected ? %s %02dh mean=%.1f%%",
                    today, now.hour, sample["mean"],
                )
        except Exception as exc:
            logger.error("[humidity] Sample collection failed: %s", exc, exc_info=True)

        # 2. At hour 0 (midnight), consolidate the previous day into a daily snapshot
        if now.hour == 0 and self._last_consolidated_date != today:
            yesterday = (now.replace(hour=0, minute=0, second=0, microsecond=0)
                         .replace(day=now.day - 1 if now.day > 1 else 1)
                         .strftime("%Y-%m-%d"))
            self._consolidate_day(yesterday)
            self._last_consolidated_date = today

    def _consolidate_day(self, date: str) -> None:
        """Build and save the daily snapshot for a given date."""
        try:
            hourly_samples = _load_json(HUMIDITY_HOURLY_FILE)
            snapshot = _build_daily_snapshot(date, hourly_samples)
            if snapshot:
                append_snapshot(snapshot)
            else:
                logger.warning("[humidity] No hourly samples found for %s, skipping", date)
        except Exception as exc:
            logger.error("[humidity] Consolidation failed for %s: %s", date, exc, exc_info=True)
