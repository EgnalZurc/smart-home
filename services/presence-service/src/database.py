"""Tier-2 durable storage: SQLite presence history + current snapshot.

Uses ``smart_home_common.sqlite_helpers.SqliteHelper`` for WAL + guaranteed
connection close (design §7.2). Schema mirrors the design document: config
tables (people/devices/beacons/zones), a one-row-per-person current snapshot
that survives restart, and a transition audit trail.

This is the scaffold: it owns the schema, the current-snapshot upsert, the
transition insert and the retention prune. The inference engine and the people
CRUD API build on top of it in later tasks.
"""

from __future__ import annotations

import logging
import sqlite3
import time

from config import DB_PATH, RETENTION_DAYS
from models import PresenceEvent

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
    """Create the presence tables + indexes if they do not exist (design §7.2)."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS people (
            id        TEXT PRIMARY KEY,
            name      TEXT NOT NULL,
            track     INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS devices (
            mac       TEXT PRIMARY KEY,
            person_id TEXT NOT NULL REFERENCES people(id),
            label     TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS beacons (
            ble_id    TEXT PRIMARY KEY,
            person_id TEXT NOT NULL REFERENCES people(id),
            label     TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS zones (
            id        TEXT PRIMARY KEY,
            sensors   TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS presence_current (
            person_id   TEXT PRIMARY KEY REFERENCES people(id),
            state       TEXT NOT NULL,
            confidence  REAL NOT NULL,
            since       INTEGER NOT NULL,
            last_seen   INTEGER,
            last_source TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS transitions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          INTEGER NOT NULL,
            person_id   TEXT NOT NULL,
            from_state  TEXT NOT NULL,
            to_state    TEXT NOT NULL,
            confidence  REAL,
            source      TEXT
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_transitions_person_ts "
        "ON transitions(person_id, ts)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_transitions_ts ON transitions(ts)")


class PresenceStore:
    """Durable presence store backed by SQLite (config + snapshot + history)."""

    def __init__(self, db_path: str = DB_PATH) -> None:
        self.db_path = db_path
        self._db = SqliteHelper(db_path, init=_ensure_schema)

    # ── Current snapshot ────────────────────────────────────────────────────
    def upsert_current(
        self,
        person_id: str,
        state: str,
        confidence: float,
        since: int,
        last_seen: int | None = None,
        last_source: str | None = None,
    ) -> None:
        """Insert or replace the current-state snapshot for one person."""
        with self._db.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO presence_current "
                "(person_id, state, confidence, since, last_seen, last_source) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (person_id, state, confidence, since, last_seen, last_source),
            )

    def get_current(self) -> list[dict[str, object]]:
        """Return the current snapshot for every person (one row each)."""
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT person_id, state, confidence, since, last_seen, last_source "
                "FROM presence_current"
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Transition history ──────────────────────────────────────────────────
    def record_transition(self, event: PresenceEvent) -> int:
        """Persist one confirmed transition; return its row id."""
        with self._db.connect() as conn:
            cur = conn.execute(
                "INSERT INTO transitions "
                "(ts, person_id, from_state, to_state, confidence, source) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    event.ts,
                    event.person_id,
                    event.from_state.value,
                    event.to_state.value,
                    event.confidence,
                    event.source,
                ),
            )
            return int(cur.lastrowid or 0)

    def history(
        self,
        person_id: str | None = None,
        *,
        since: int | None = None,
        until: int | None = None,
    ) -> list[dict[str, object]]:
        """Return the transition audit trail, optionally filtered.

        Rows are returned newest-first.
        """
        query = (
            "SELECT id, ts, person_id, from_state, to_state, confidence, source "
            "FROM transitions WHERE 1 = 1"
        )
        args: list[object] = []
        if person_id is not None:
            query += " AND person_id = ?"
            args.append(person_id)
        if since is not None:
            query += " AND ts >= ?"
            args.append(since)
        if until is not None:
            query += " AND ts <= ?"
            args.append(until)
        query += " ORDER BY ts DESC"
        with self._db.connect() as conn:
            rows = conn.execute(query, args).fetchall()
        return [dict(r) for r in rows]

    # ── Retention ─────────────────────────────────────────────────────────────
    def prune(
        self, now: int | None = None, retention_days: int = RETENTION_DAYS
    ) -> int:
        """Delete transitions older than ``retention_days`` and checkpoint WAL.

        Returns the number of rows deleted.
        """
        now = int(time.time()) if now is None else now
        cutoff = now - retention_days * 24 * 3600
        with self._db.connect() as conn:
            cur = conn.execute("DELETE FROM transitions WHERE ts < ?", (cutoff,))
            deleted = cur.rowcount
            try:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except sqlite3.Error as exc:  # pragma: no cover - best-effort
                logger.warning("wal_checkpoint failed: %s", exc)
        if deleted:
            logger.info(
                "Pruned %d transition rows older than %dd", deleted, retention_days
            )
        return deleted

    def count_transitions(self) -> int:
        """Return the total number of transition rows (tests / diagnostics)."""
        with self._db.connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM transitions").fetchone()
        return int(row["n"])

    def db_ok(self) -> bool:
        """Return True if the store answers a trivial query."""
        try:
            self.count_transitions()
            return True
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("db health check failed: %s", exc)
            return False
