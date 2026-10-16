"""Tier-2 durable storage: SQLite power + energy time-series with retention.

Implements the schema from the design document
(``docs/designs/energy-monitor-design.md`` §4.2). Uses
``smart_home_common.sqlite_helpers.SqliteHelper`` for WAL + guaranteed
connection close, same as ``metrics-service``.

Two tables, because power (a gauge) and energy (a monotonic counter) have
different semantics (design §4.2 / §4.3):

- ``power_samples``   : 1-min rollup — avg + max preserve spikes.
- ``energy_readings`` : hourly snapshot of the raw cumulative Wh counter;
  deltas are derived on read so missed polls / downtime stay correct.
- ``energy_alerts``   : fired/resolved audit trail.

This scaffold provides schema creation, a minimal write/read for each table and
retention pruning. The full collector/alert logic lands in later tasks.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from datetime import datetime, timedelta, timezone

from config import (
    ALERT_RETENTION_DAYS,
    DB_PATH,
    ENERGY_RETENTION_DAYS,
    POWER_RETENTION_DAYS,
)

# Supported aggregation periods for ``consumption_by_period`` (design §4.3).
VALID_PERIODS = ("hour", "day", "week", "month")

try:
    from smart_home_common.sqlite_helpers import SqliteHelper
except ImportError:  # pragma: no cover - import fallback outside the container
    import sys
    from pathlib import Path

    _repo_root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(_repo_root / "libs" / "smart_home_common" / "src"))
    from smart_home_common.sqlite_helpers import SqliteHelper

logger: logging.Logger = logging.getLogger(__name__)


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Create the energy tables + indexes if they do not exist (design §4.2)."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS power_samples (
            ts        INTEGER NOT NULL,
            channel   TEXT    NOT NULL,
            power_avg REAL    NOT NULL,
            power_max REAL,
            voltage   REAL,
            pf        REAL,
            PRIMARY KEY (ts, channel)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_power_channel_ts ON power_samples(channel, ts)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS energy_readings (
            ts        INTEGER NOT NULL,
            channel   TEXT    NOT NULL,
            energy_wh REAL    NOT NULL,
            PRIMARY KEY (ts, channel)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_energy_channel_ts ON energy_readings(channel, ts)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS energy_alerts (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            ts       INTEGER NOT NULL,
            rule_key TEXT    NOT NULL,
            channel  TEXT    NOT NULL DEFAULT '',
            severity TEXT    NOT NULL,
            state    TEXT    NOT NULL,
            value    REAL,
            message  TEXT
        )
        """
    )


def _floor_to_period(dt: datetime, period: str) -> datetime:
    """Return the start of the calendar period containing ``dt`` (UTC).

    Buckets are calendar-aligned so "day" means local-midnight-to-midnight in
    UTC, "week" starts Monday 00:00, and "month" starts on the 1st. This keeps
    period labels human-meaningful (design §4.3) rather than rolling windows.
    """
    if period == "hour":
        return dt.replace(minute=0, second=0, microsecond=0)
    if period == "day":
        return dt.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "week":
        midnight = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        return midnight - timedelta(days=midnight.weekday())
    if period == "month":
        return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    raise ValueError(f"unknown period: {period!r}")


def _advance_period(dt: datetime, period: str) -> datetime:
    """Return the start of the period immediately following ``dt``'s bucket."""
    if period == "hour":
        return dt + timedelta(hours=1)
    if period == "day":
        return dt + timedelta(days=1)
    if period == "week":
        return dt + timedelta(weeks=1)
    if period == "month":
        # Month length varies; step to the 1st of the next month.
        year, month = dt.year, dt.month
        if month == 12:
            return dt.replace(year=year + 1, month=1)
        return dt.replace(month=month + 1)
    raise ValueError(f"unknown period: {period!r}")


def _period_starts(now: int, period: str, count: int) -> list[int]:
    """Return the ``count`` most recent period-start unix timestamps, ascending.

    The last element is the bucket containing ``now``; earlier elements are the
    preceding buckets. All computed in UTC.
    """
    current = _floor_to_period(datetime.fromtimestamp(now, tz=timezone.utc), period)
    starts: list[datetime] = [current]
    for _ in range(count - 1):
        # Walk backwards one calendar period at a time.
        prev_boundary = current - timedelta(seconds=1)
        current = _floor_to_period(prev_boundary, period)
        starts.append(current)
    starts.reverse()
    return [int(s.timestamp()) for s in starts]


class EnergyStore:
    """Durable power + energy store backed by SQLite."""

    def __init__(self, db_path: str = DB_PATH) -> None:
        self.db_path = db_path
        self._db = SqliteHelper(db_path, init=_ensure_schema)

    # ── Writes ──────────────────────────────────────────────────────────────
    def write_power(
        self,
        ts: int,
        rows: list[tuple[str, float, float | None, float | None, float | None]],
    ) -> int:
        """Insert one 1-min power rollup bucket.

        Args:
            ts: Bucket start (unix seconds).
            rows: ``(channel, power_avg, power_max, voltage, pf)`` tuples.

        Returns:
            Number of rows written.
        """
        if not rows:
            return 0
        params = [(ts, ch, avg, mx, v, pf) for (ch, avg, mx, v, pf) in rows]
        with self._db.connect() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO power_samples "
                "(ts, channel, power_avg, power_max, voltage, pf) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                params,
            )
        return len(params)

    def write_energy(self, ts: int, rows: list[tuple[str, float]]) -> int:
        """Snapshot the cumulative Wh counter per channel.

        Args:
            ts: Snapshot time (unix seconds, top of the hour).
            rows: ``(channel, energy_wh)`` tuples (raw monotonic counter).

        Returns:
            Number of rows written.
        """
        if not rows:
            return 0
        params = [(ts, ch, wh) for (ch, wh) in rows]
        with self._db.connect() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO energy_readings (ts, channel, energy_wh) "
                "VALUES (?, ?, ?)",
                params,
            )
        return len(params)

    # ── Reads ───────────────────────────────────────────────────────────────
    def power_series(
        self,
        channel: str,
        *,
        since: int | None = None,
        until: int | None = None,
    ) -> list[dict[str, float | int | None]]:
        """Return 1-min power points for one channel, time-ranged (ascending)."""
        query = (
            "SELECT ts, power_avg, power_max, voltage, pf FROM power_samples "
            "WHERE channel = ?"
        )
        args: list[object] = [channel]
        if since is not None:
            query += " AND ts >= ?"
            args.append(since)
        if until is not None:
            query += " AND ts <= ?"
            args.append(until)
        query += " ORDER BY ts ASC"
        with self._db.connect() as conn:
            rows = conn.execute(query, args).fetchall()
        return [
            {
                "ts": r["ts"],
                "power_avg": r["power_avg"],
                "power_max": r["power_max"],
                "voltage": r["voltage"],
                "pf": r["pf"],
            }
            for r in rows
        ]

    def energy_series(
        self,
        channel: str,
        *,
        since: int | None = None,
        until: int | None = None,
    ) -> list[dict[str, float | int]]:
        """Return hourly cumulative-Wh snapshots for one channel (ascending)."""
        query = "SELECT ts, energy_wh FROM energy_readings WHERE channel = ?"
        args: list[object] = [channel]
        if since is not None:
            query += " AND ts >= ?"
            args.append(since)
        if until is not None:
            query += " AND ts <= ?"
            args.append(until)
        query += " ORDER BY ts ASC"
        with self._db.connect() as conn:
            rows = conn.execute(query, args).fetchall()
        return [{"ts": r["ts"], "energy_wh": r["energy_wh"]} for r in rows]

    # ── Retention (design §4.4) ───────────────────────────────────────────────
    def prune(self, now: int | None = None) -> dict[str, int]:
        """Delete rows past retention per table and checkpoint the WAL.

        Returns a mapping ``{table: rows_deleted}``.
        """
        now = int(time.time()) if now is None else now
        power_cutoff = now - POWER_RETENTION_DAYS * 24 * 3600
        energy_cutoff = now - ENERGY_RETENTION_DAYS * 24 * 3600
        alert_cutoff = now - ALERT_RETENTION_DAYS * 24 * 3600
        deleted: dict[str, int] = {}
        with self._db.connect() as conn:
            cur = conn.execute(
                "DELETE FROM power_samples WHERE ts < ?", (power_cutoff,)
            )
            deleted["power_samples"] = cur.rowcount
            cur = conn.execute(
                "DELETE FROM energy_readings WHERE ts < ?", (energy_cutoff,)
            )
            deleted["energy_readings"] = cur.rowcount
            cur = conn.execute(
                "DELETE FROM energy_alerts WHERE ts < ?", (alert_cutoff,)
            )
            deleted["energy_alerts"] = cur.rowcount
            try:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except sqlite3.Error as exc:  # pragma: no cover - best-effort
                logger.warning("wal_checkpoint failed: %s", exc)
        total = sum(deleted.values())
        if total:
            logger.info("Pruned %d energy rows past retention", total)
        return deleted

    def count(self) -> int:
        """Return the total row count across the time-series tables.

        Used by the health check (DB liveness) and tests/diagnostics.
        """
        with self._db.connect() as conn:
            power = conn.execute("SELECT COUNT(*) AS n FROM power_samples").fetchone()
            energy = conn.execute(
                "SELECT COUNT(*) AS n FROM energy_readings"
            ).fetchone()
        return int(power["n"]) + int(energy["n"])

    # ── Aggregation (design §4.3) ─────────────────────────────────────────────
    def _cumulative_at(
        self, conn: sqlite3.Connection, channel: str | None, boundary: int
    ) -> float | None:
        """Return the cumulative Wh at ``boundary`` (newest reading at/before it).

        ``channel=None`` sums the latest reading of every channel seen at or
        before the boundary (whole-home total). Returns ``None`` when there is
        no reading yet, so the caller can tell "no data" from "zero consumed".
        """
        if channel is not None:
            row = conn.execute(
                "SELECT energy_wh FROM energy_readings "
                "WHERE channel = ? AND ts <= ? ORDER BY ts DESC LIMIT 1",
                (channel, boundary),
            ).fetchone()
            return None if row is None else float(row["energy_wh"])

        # Whole-home total: for each channel take its newest reading <= boundary.
        rows = conn.execute(
            """
            SELECT channel, energy_wh FROM energy_readings AS e
            WHERE ts <= ? AND ts = (
                SELECT MAX(ts) FROM energy_readings
                WHERE channel = e.channel AND ts <= ?
            )
            """,
            (boundary, boundary),
        ).fetchall()
        if not rows:
            return None
        return float(sum(r["energy_wh"] for r in rows))

    def consumption_by_period(
        self,
        period: str,
        count: int = 24,
        *,
        channel: str | None = None,
        now: int | None = None,
    ) -> list[dict[str, float | int | None]]:
        """Return consumption (Wh) per calendar period, oldest → newest.

        Consumption of a period is the delta of the monotonic cumulative counter
        across the period boundaries: ``cumulative(next_start) −
        cumulative(this_start)``. Deriving from the counter (rather than summing
        samples) keeps totals correct across missed polls / downtime.

        Args:
            period: One of ``hour``, ``day``, ``week``, ``month``.
            count: Number of most-recent periods to return (clamped to 1..1000).
            channel: Specific channel, or ``None`` for the whole-home total.
            now: Reference unix time (defaults to current time); testable.

        Returns:
            A list of ``{period_start, period, consumption_wh, consumption_kwh}``
            dicts. ``consumption_wh`` is ``None`` when a period has insufficient
            readings to compute a delta.
        """
        if period not in VALID_PERIODS:
            raise ValueError(f"period must be one of {VALID_PERIODS}, got {period!r}")
        count = max(1, min(int(count), 1000))
        now = int(time.time()) if now is None else now

        starts = _period_starts(now, period, count)
        out: list[dict[str, float | int | None]] = []
        with self._db.connect() as conn:
            for start in starts:
                next_start = int(
                    _advance_period(
                        datetime.fromtimestamp(start, tz=timezone.utc), period
                    ).timestamp()
                )
                # End of the window is "now" for the in-progress bucket.
                end = min(next_start, now)
                base = self._cumulative_at(conn, channel, start)
                tip = self._cumulative_at(conn, channel, end)
                if base is None or tip is None:
                    wh: float | None = None
                else:
                    wh = max(0.0, round(tip - base, 3))
                out.append(
                    {
                        "period_start": start,
                        "period": period,
                        "consumption_wh": wh,
                        "consumption_kwh": None
                        if wh is None
                        else round(wh / 1000.0, 4),
                    }
                )
        return out

    def stats(self, now: int | None = None) -> dict[str, float | int | None]:
        """Return month-to-date consumption statistics (whole-home total).

        Computes, over the current calendar month's daily buckets:
          * ``total_kwh``    — month-to-date energy.
          * ``avg_daily_kwh``— mean of completed days (excludes today).
          * ``peak_daily_kwh`` + ``peak_day``— highest daily consumption.
          * ``peak_power_w`` — maximum 1-min power sample this month.

        Returns ``None`` for a metric when there is not enough data yet.
        """
        now = int(time.time()) if now is None else now
        now_dt = datetime.fromtimestamp(now, tz=timezone.utc)
        month_start = int(_floor_to_period(now_dt, "month").timestamp())
        days_elapsed = now_dt.day  # 1-based day of month, == number of day buckets

        daily = self.consumption_by_period("day", days_elapsed, now=now)
        values = [
            d["consumption_kwh"] for d in daily if d["consumption_kwh"] is not None
        ]
        total_kwh = round(sum(values), 4) if values else None

        # Completed days exclude the in-progress final bucket (today).
        completed = values[:-1] if len(values) > 1 else []
        avg_daily_kwh = round(sum(completed) / len(completed), 4) if completed else None

        peak_daily_kwh: float | None = None
        peak_day: int | None = None
        for d in daily:
            v = d["consumption_kwh"]
            if v is not None and (peak_daily_kwh is None or v > peak_daily_kwh):
                peak_daily_kwh = v
                peak_day = int(d["period_start"])

        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT MAX(power_max) AS pmax FROM power_samples WHERE ts >= ?",
                (month_start,),
            ).fetchone()
        peak_power_w = (
            None if row is None or row["pmax"] is None else float(row["pmax"])
        )

        return {
            "month_start": month_start,
            "days_elapsed": days_elapsed,
            "total_kwh": total_kwh,
            "avg_daily_kwh": avg_daily_kwh,
            "peak_daily_kwh": peak_daily_kwh,
            "peak_day": peak_day,
            "peak_power_w": peak_power_w,
        }

    # ── Alerts (design §8) ────────────────────────────────────────────────────
    def record_alert(
        self,
        rule_key: str,
        severity: str,
        state: str,
        *,
        channel: str = "",
        value: float | None = None,
        message: str | None = None,
        ts: int | None = None,
    ) -> int:
        """Persist one alert event to the audit trail; return its row id."""
        ts = int(time.time()) if ts is None else ts
        with self._db.connect() as conn:
            cur = conn.execute(
                "INSERT INTO energy_alerts "
                "(ts, rule_key, channel, severity, state, value, message) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ts, rule_key, channel, severity, state, value, message),
            )
            return int(cur.lastrowid)

    def recent_alerts(self, limit: int = 50) -> list[dict[str, object]]:
        """Return the most recent alert events, newest first."""
        limit = max(1, min(int(limit), 500))
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT id, ts, rule_key, channel, severity, state, value, message "
                "FROM energy_alerts ORDER BY ts DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                "id": r["id"],
                "ts": r["ts"],
                "rule_key": r["rule_key"],
                "channel": r["channel"],
                "severity": r["severity"],
                "state": r["state"],
                "value": r["value"],
                "message": r["message"],
            }
            for r in rows
        ]
