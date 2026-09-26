"""Humidity analysis scheduler for seasonal humidifier study (HUM-0).

Architecture:
- Runs every SAMPLE_INTERVAL_H (default: 1h) to collect an hourly sample
- Each sample captures the current sensor readings
- At midnight, consolidates the day's hourly samples into one daily snapshot
- Snapshots are kept indefinitely, classified by season
- The API returns per-season analysis and recommendations
- Seasons (Northern Hemisphere): Spring=MAM, Summer=JJA, Autumn=SON, Winter=DJF
"""

import json
import logging
import os
import statistics
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

HUMIDITY_ANALYSIS_FILE = os.environ.get("HUMIDITY_ANALYSIS_FILE", "/app/data/humidity_analysis.json")
HUMIDITY_HOURLY_FILE   = os.environ.get("HUMIDITY_HOURLY_FILE",   "/app/data/humidity_hourly.json")
MAX_HOURLY_SAMPLES     = 72     # Rolling window: last 72h on disk
SAMPLE_INTERVAL_H      = 1
LOW_THRESHOLD          = 40.0
HIGH_THRESHOLD         = 55.0

# Season definitions (month -> season key)
MONTH_TO_SEASON = {
    12: "winter", 1: "winter",  2: "winter",
     3: "spring", 4: "spring",  5: "spring",
     6: "summer", 7: "summer",  8: "summer",
     9: "autumn", 10: "autumn", 11: "autumn",
}
SEASON_NAMES_ES = {
    "spring": "Primavera", "summer": "Verano",
    "autumn": "Oto?o",     "winter": "Invierno",
}
SEASON_NAMES_EN = {
    "spring": "Spring", "summer": "Summer",
    "autumn": "Autumn", "winter": "Winter",
}
SEASON_ORDER = ["spring", "summer", "autumn", "winter"]

# Threshold: fraction of days with signal to recommend humidifier
SIGNAL_THRESHOLD = 0.5   # >= 50% of days with signal -> recommend


# -- Helpers ------------------------------------------------------------------

def get_season(date_str: str) -> str:
    """Return season key for a YYYY-MM-DD date string."""
    month = int(date_str[5:7])
    return MONTH_TO_SEASON[month]


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


# -- Core analysis ------------------------------------------------------------

def _collect_sample(mqtt_handler) -> dict | None:
    """Read current sensor data and return a timestamped humidity sample."""
    with mqtt_handler._lock:
        readings = {
            name: [r.humidity for r in rlist if r.humidity is not None]
            for name, rlist in mqtt_handler.history.items()
            if name != "AC" and rlist
        }

    all_values = [h for vals in readings.values() for h in vals]
    if not all_values:
        return None

    now = datetime.now(timezone.utc)
    return {
        "timestamp": round(time.time(), 1),
        "date":      now.strftime("%Y-%m-%d"),
        "hour":      now.hour,
        "mean":      round(statistics.mean(all_values), 2),
        "min":       round(min(all_values), 2),
        "max":       round(max(all_values), 2),
        "sample_n":  len(all_values),
        "sensors":   list(readings.keys()),
    }


def _build_daily_snapshot(date: str, hourly_samples: list) -> dict | None:
    """Consolidate hourly samples for a given date into one daily snapshot."""
    day_samples = [s for s in hourly_samples if s["date"] == date]
    if not day_samples:
        return None

    all_means = [s["mean"] for s in day_samples]
    weights   = [s["sample_n"] for s in day_samples]
    total_w   = sum(weights)
    w_mean    = round(sum(m * w for m, w in zip(all_means, weights)) / total_w, 2)
    n         = len(day_samples)

    sorted_means = sorted(all_means)
    frac_below   = round(sum(1 for m in all_means if m < LOW_THRESHOLD)  / n, 4)
    frac_above   = round(sum(1 for m in all_means if m > HIGH_THRESHOLD) / n, 4)
    hourly_pattern = {str(s["hour"]): s["mean"] for s in day_samples}

    return {
        "date":                   date,
        "season":                 get_season(date),
        "timestamp":              round(time.time(), 1),
        "hours_sampled":          n,
        "sensors":                day_samples[0]["sensors"],
        "mean":                   w_mean,
        "min":                    round(min(s["min"] for s in day_samples), 2),
        "max":                    round(max(s["max"] for s in day_samples), 2),
        "p25":                    _percentile(sorted_means, 25),
        "p75":                    _percentile(sorted_means, 75),
        "fraction_below_40":      frac_below,
        "fraction_above_55":      frac_above,
        "hourly_pattern":         hourly_pattern,
        "humidifier_needed_signal": (w_mean < 38.0 or frac_below > 0.65),
    }


# -- Persistence --------------------------------------------------------------

def _append_hourly_sample(sample: dict) -> None:
    samples = _load_json(HUMIDITY_HOURLY_FILE)
    samples.append(sample)
    samples = samples[-MAX_HOURLY_SAMPLES:]
    _save_json(samples, HUMIDITY_HOURLY_FILE)


def append_snapshot(snapshot: dict, filepath: str = HUMIDITY_ANALYSIS_FILE) -> None:
    """Add or replace a daily snapshot. Kept indefinitely (no max cap)."""
    snapshots = _load_json(filepath)
    date = snapshot["date"]
    # Ensure season field is present (migration: old snapshots may lack it)
    snapshot.setdefault("season", get_season(date))
    snapshots = [s for s in snapshots if s.get("date") != date]
    snapshots.append(snapshot)
    snapshots = sorted(snapshots, key=lambda s: s["date"])
    _save_json(snapshots, filepath)
    logger.info(
        "[humidity] Snapshot saved: %s (%s) mean=%.1f%% h=%d below_40=%.0f%% signal=%s",
        date, snapshot["season"], snapshot["mean"], snapshot["hours_sampled"],
        snapshot["fraction_below_40"] * 100,
        "YES" if snapshot["humidifier_needed_signal"] else "no",
    )


# -- Seasonal analysis --------------------------------------------------------

def _season_summary(snapshots: list) -> dict:
    """Compute per-season statistics from all daily snapshots."""
    seasons = {}
    for season_key in SEASON_ORDER:
        days = [s for s in snapshots if s.get("season") == season_key]
        if not days:
            seasons[season_key] = {
                "season":      season_key,
                "name_es":     SEASON_NAMES_ES[season_key],
                "name_en":     SEASON_NAMES_EN[season_key],
                "days":        0,
                "mean":        None,
                "min":         None,
                "max":         None,
                "avg_fraction_below_40": None,
                "days_signal": 0,
                "recommendation": "no_data",
                "snapshots":   [],
            }
            continue

        means   = [d["mean"] for d in days]
        fracs   = [d["fraction_below_40"] for d in days]
        signals = [d["humidifier_needed_signal"] for d in days]
        n       = len(days)
        signal_count = sum(signals)

        if n < 7:
            rec = "insufficient_data"
        elif signal_count / n >= SIGNAL_THRESHOLD:
            rec = "recommended"
        else:
            rec = "not_needed"

        seasons[season_key] = {
            "season":                 season_key,
            "name_es":                SEASON_NAMES_ES[season_key],
            "name_en":                SEASON_NAMES_EN[season_key],
            "days":                   n,
            "mean":                   round(statistics.mean(means), 2),
            "min":                    round(min(d["min"] for d in days), 2),
            "max":                    round(max(d["max"] for d in days), 2),
            "avg_fraction_below_40":  round(statistics.mean(fracs), 4),
            "days_signal":            signal_count,
            "recommendation":         rec,
            "snapshots":              days,
        }
    return seasons


def get_summary(filepath: str = HUMIDITY_ANALYSIS_FILE) -> dict | None:
    """Return the full seasonal summary. Returns None if no data."""
    snapshots = _load_json(filepath)
    if not snapshots:
        return None

    # Ensure all snapshots have season field (migration)
    for s in snapshots:
        s.setdefault("season", get_season(s["date"]))

    seasons = _season_summary(snapshots)
    total_days = len(snapshots)

    return {
        "total_days":    total_days,
        "date_first":    snapshots[0]["date"],
        "date_last":     snapshots[-1]["date"],
        "seasons":       seasons,
        "snapshots":     snapshots,
    }


# -- Scheduler ----------------------------------------------------------------

class HumidityAnalysisScheduler:
    """
    Runs every SAMPLE_INTERVAL_H hours.
    - Collects one hourly sample each run
    - At midnight, consolidates previous day into a daily snapshot
    - Data is kept indefinitely, classified by season
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
            "[humidity] Scheduler started - samples every %dh, grace=%ds",
            self._interval // 3600, self._grace,
        )

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    def run_now(self) -> None:
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
        now   = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")

        try:
            sample = _collect_sample(self._mqtt)
            if sample:
                _append_hourly_sample(sample)
                logger.info(
                    "[humidity] Sample: %s %02dh mean=%.1f%%",
                    today, now.hour, sample["mean"],
                )
        except Exception as exc:
            logger.error("[humidity] Sample collection failed: %s", exc, exc_info=True)

        # At midnight: consolidate previous day
        if now.hour == 0 and self._last_consolidated_date != today:
            yesterday = (now.replace(hour=12, minute=0, second=0, microsecond=0)
                         - timedelta(days=1)).strftime("%Y-%m-%d")
            self._consolidate_day(yesterday)
            self._last_consolidated_date = today

    def _consolidate_day(self, date: str) -> None:
        try:
            hourly_samples = _load_json(HUMIDITY_HOURLY_FILE)
            snapshot = _build_daily_snapshot(date, hourly_samples)
            if snapshot:
                append_snapshot(snapshot)
            else:
                logger.warning("[humidity] No samples for %s, skipping", date)
        except Exception as exc:
            logger.error("[humidity] Consolidation failed for %s: %s", date, exc, exc_info=True)
