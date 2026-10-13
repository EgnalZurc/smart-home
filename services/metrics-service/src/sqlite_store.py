"""Tier-2 durable storage: SQLite rolled-up metrics with 30-day retention.

Uses ``smart_home_common.sqlite_helpers.SqliteHelper`` for WAL + guaranteed
connection close (see design §4.2). The schema is a narrow/long table so pruning
and time-range queries stay simple:

    metrics(ts, metric, label, value, value_max)

- ``ts``        : unix epoch seconds, rollup bucket start
- ``value``     : 5-min average
- ``value_max`` : 5-min max (preserves spikes that averaging hides)
"""

from __future__ import annotations

import logging
import sqlite3
import time

from config import DB_PATH, RETENTION_DAYS

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
    """Create the metrics table + index if they do not exist."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS metrics (
            ts        INTEGER NOT NULL,
            metric    TEXT    NOT NULL,
            label     TEXT    NOT NULL DEFAULT '',
            value     REAL    NOT NULL,
            value_max REAL,
            PRIMARY KEY (ts, metric, label)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_metrics_metric_ts ON metrics(metric, label, ts)"
    )


class SqliteStore:
    """Durable rolled-up metric store backed by SQLite."""

    def __init__(self, db_path: str = DB_PATH) -> None:
        self.db_path = db_path
        self._db = SqliteHelper(db_path, init=_ensure_schema)

    # ── Writes ────────────────────────────────────────────────────────────────
    def write_rollup(self, ts: int, rows: list[tuple[str, str, float, float]]) -> int:
        """Insert one rollup bucket.

        Args:
            ts: Bucket start (unix seconds).
            rows: List of ``(metric, label, value_avg, value_max)``.

        Returns:
            Number of rows written.
        """
        if not rows:
            return 0
        params = [(ts, metric, label, avg, mx) for (metric, label, avg, mx) in rows]
        with self._db.connect() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO metrics "
                "(ts, metric, label, value, value_max) VALUES (?, ?, ?, ?, ?)",
                params,
            )
        return len(params)

    # ── Reads ─────────────────────────────────────────────────────────────────
    def series(
        self,
        metric: str,
        label: str = "",
        *,
        since: int | None = None,
        until: int | None = None,
    ) -> list[dict[str, float | int]]:
        """Return rolled-up points for one series, time-ranged.

        Each point is ``{"ts", "value", "value_max"}`` in ascending ts order.
        """
        query = (
            "SELECT ts, value, value_max FROM metrics WHERE metric = ? AND label = ?"
        )
        args: list[object] = [metric, label]
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
            {"ts": r["ts"], "value": r["value"], "value_max": r["value_max"]}
            for r in rows
        ]

    def summary(self, since: int, until: int | None = None) -> list[dict[str, object]]:
        """Return min/avg/max per ``(metric, label)`` over ``[since, until]``.

        p95 is not computed in SQL (would need a window function); callers that
        want percentiles use the ring buffer for recent windows. This serves the
        rollup-backed longer windows (24h/7d/30d) with avg/max/min.
        """
        query = (
            "SELECT metric, label, MIN(value) AS vmin, AVG(value) AS vavg, "
            "MAX(COALESCE(value_max, value)) AS vmax, COUNT(*) AS n "
            "FROM metrics WHERE ts >= ?"
        )
        args: list[object] = [since]
        if until is not None:
            query += " AND ts <= ?"
            args.append(until)
        query += " GROUP BY metric, label"
        with self._db.connect() as conn:
            rows = conn.execute(query, args).fetchall()
        return [
            {
                "metric": r["metric"],
                "label": r["label"],
                "min": r["vmin"],
                "avg": r["vavg"],
                "max": r["vmax"],
                "count": r["n"],
            }
            for r in rows
        ]

    # ── Retention ───────────────────────────────────────────────────────────────
    def prune(
        self, now: int | None = None, retention_days: int = RETENTION_DAYS
    ) -> int:
        """Delete rows older than ``retention_days`` and checkpoint the WAL.

        Returns the number of rows deleted.
        """
        now = int(time.time()) if now is None else now
        cutoff = now - retention_days * 24 * 3600
        with self._db.connect() as conn:
            cur = conn.execute("DELETE FROM metrics WHERE ts < ?", (cutoff,))
            deleted = cur.rowcount
            try:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except sqlite3.Error as exc:  # pragma: no cover - best-effort
                logger.warning("wal_checkpoint failed: %s", exc)
        if deleted:
            logger.info("Pruned %d metric rows older than %dd", deleted, retention_days)
        return deleted

    def count(self) -> int:
        """Return the total number of rows (used by tests / diagnostics)."""
        with self._db.connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM metrics").fetchone()
        return int(row["n"])
