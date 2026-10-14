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

from config import (
    DB_PATH,
    ENERGY_RETENTION_DAYS,
    POWER_RETENTION_DAYS,
)

try:
    from smart_home_common.sqlite_helpers import SqliteHelper
except ImportError:  # pragma: no cover - import fallback outside the container
    import sys
    from pathlib import Path

    _repo_root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(_repo_root / "libs" / "smart_home_common" / "src"))
    from smart_home_common.sqlite_helpers import SqliteHelper

logger = logging.getLogger(__name__)


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
