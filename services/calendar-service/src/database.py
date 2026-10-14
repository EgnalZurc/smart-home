"""Tier-2 durable storage: SQLite cache of calendar events + reminder ledger.

Uses ``smart_home_common.sqlite_helpers.SqliteHelper`` (WAL + guaranteed close),
same as every other service. Provider-neutral columns so a second calendar
provider could be added later (design §3.2).

Scaffold scope: the schema (all six tables + indexes) and a small set of
primitive accessors (``count``, ``upsert_event``, ``upcoming``, retention
``prune``). The incremental-sync upsert, reminder dedup-insert and people/rules
management land in later tasks; the schema is created in full now so those tasks
only add queries, not migrations.
"""

from __future__ import annotations

import logging
import sqlite3
import time

from config import DB_PATH, EVENT_RETENTION_DAYS, REMINDER_RETENTION_DAYS

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
    """Create all calendar tables + indexes if they do not exist (design §3.2)."""
    # Calendars we sync (config, editable via API).
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS calendars (
            id          TEXT PRIMARY KEY,
            label       TEXT NOT NULL,
            person_id   TEXT,
            colour      TEXT,
            enabled     INTEGER NOT NULL DEFAULT 1,
            sync_token  TEXT,
            last_sync   INTEGER
        )
        """
    )
    # Cached event instances (recurring events already expanded by Google).
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            uid          TEXT PRIMARY KEY,
            calendar_id  TEXT NOT NULL,
            google_id    TEXT NOT NULL,
            title        TEXT NOT NULL,
            description  TEXT,
            location     TEXT,
            start_ts     INTEGER NOT NULL,
            end_ts       INTEGER NOT NULL,
            all_day      INTEGER NOT NULL DEFAULT 0,
            person_id    TEXT,
            status       TEXT NOT NULL DEFAULT 'confirmed',
            etag         TEXT,
            updated_ts   INTEGER NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_events_start ON events(start_ts)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_events_cal_start ON events(calendar_id, start_ts)"
    )
    # People mapping (thin — only reminder routing / widget grouping).
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS people (
            id               TEXT PRIMARY KEY,
            name             TEXT NOT NULL,
            telegram_chat_id TEXT
        )
        """
    )
    # Attendee email → person slug (optional per-attendee routing).
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS attendee_map (
            email       TEXT PRIMARY KEY,
            person_id   TEXT NOT NULL
        )
        """
    )
    # Reminder rules (which offsets to fire, globally or per calendar/person).
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS reminder_rules (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            scope       TEXT NOT NULL,
            scope_id    TEXT,
            offset_s    INTEGER NOT NULL,
            enabled     INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    # History of reminders already sent — the dedup ledger + audit trail.
    # UNIQUE(event_uid, offset_s, event_start) is the hard dedup guarantee (§5.2).
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS reminders_sent (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            event_uid   TEXT NOT NULL,
            offset_s    INTEGER NOT NULL,
            event_start INTEGER NOT NULL,
            sent_ts     INTEGER NOT NULL,
            ok          INTEGER NOT NULL,
            UNIQUE(event_uid, offset_s, event_start)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_reminders_event ON reminders_sent(event_uid)"
    )


class CalendarStore:
    """Durable SQLite store for cached events, calendars and the reminder ledger."""

    def __init__(self, db_path: str = DB_PATH) -> None:
        self.db_path = db_path
        self._db = SqliteHelper(db_path, init=_ensure_schema)

    # ── Health / diagnostics ─────────────────────────────────────────────────
    def count(self) -> int:
        """Return the total number of cached events (used by the health probe)."""
        with self._db.connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()
        return int(row["n"])

    # ── Writes ───────────────────────────────────────────────────────────────
    def upsert_event(self, event: dict) -> None:
        """Insert or replace one cached event instance.

        ``event`` is a plain dict matching the ``events`` columns. The sync loop
        (later task) builds these from expanded Google instances; the primitive
        lives here so the schema and write path are exercised by scaffold tests.
        """
        with self._db.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO events (
                    uid, calendar_id, google_id, title, description, location,
                    start_ts, end_ts, all_day, person_id, status, etag, updated_ts
                ) VALUES (
                    :uid, :calendar_id, :google_id, :title, :description, :location,
                    :start_ts, :end_ts, :all_day, :person_id, :status, :etag, :updated_ts
                )
                """,
                {
                    "uid": event["uid"],
                    "calendar_id": event["calendar_id"],
                    "google_id": event["google_id"],
                    "title": event["title"],
                    "description": event.get("description"),
                    "location": event.get("location"),
                    "start_ts": event["start_ts"],
                    "end_ts": event["end_ts"],
                    "all_day": 1 if event.get("all_day") else 0,
                    "person_id": event.get("person_id"),
                    "status": event.get("status", "confirmed"),
                    "etag": event.get("etag"),
                    "updated_ts": event.get("updated_ts", int(time.time())),
                },
            )

    # ── Reads ────────────────────────────────────────────────────────────────
    def upcoming(self, now: int | None = None, limit: int = 5) -> list[dict]:
        """Return the next ``limit`` confirmed events at or after ``now``.

        Ordered by start time. Powers ``/api/calendar/upcoming`` (widget 1).
        """
        now = int(time.time()) if now is None else now
        with self._db.connect() as conn:
            rows = conn.execute(
                """
                SELECT uid, calendar_id, google_id, title, description, location,
                       start_ts, end_ts, all_day, person_id, status
                FROM events
                WHERE status = 'confirmed' AND start_ts >= ?
                ORDER BY start_ts ASC
                LIMIT ?
                """,
                (now, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Retention (design §3.3) ──────────────────────────────────────────────
    def prune(self, now: int | None = None) -> dict[str, int]:
        """Apply retention and checkpoint the WAL.

        Drops events whose ``end_ts`` is older than ``EVENT_RETENTION_DAYS`` and
        reminder-ledger rows older than ``REMINDER_RETENTION_DAYS``. Returns the
        counts deleted per table.
        """
        now = int(time.time()) if now is None else now
        event_cutoff = now - EVENT_RETENTION_DAYS * 24 * 3600
        reminder_cutoff = now - REMINDER_RETENTION_DAYS * 24 * 3600
        with self._db.connect() as conn:
            ev = conn.execute(
                "DELETE FROM events WHERE end_ts < ?", (event_cutoff,)
            ).rowcount
            rem = conn.execute(
                "DELETE FROM reminders_sent WHERE sent_ts < ?", (reminder_cutoff,)
            ).rowcount
            try:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except sqlite3.Error as exc:  # pragma: no cover - best-effort
                logger.warning("wal_checkpoint failed: %s", exc)
        if ev or rem:
            logger.info("Pruned %d events + %d reminder rows", ev, rem)
        return {"events": ev, "reminders": rem}
