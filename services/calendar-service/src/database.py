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


class Calendar:
    """DTO for a calendar row."""

    __slots__ = (
        "id",
        "label",
        "person_id",
        "colour",
        "enabled",
        "sync_token",
        "last_sync",
    )

    def __init__(self, row: sqlite3.Row) -> None:
        self.id: str = row["id"]
        self.label: str = row["label"]
        self.person_id: str | None = row["person_id"]
        self.colour: str | None = row["colour"]
        self.enabled: bool = bool(row["enabled"])
        self.sync_token: str | None = row["sync_token"]
        self.last_sync: int | None = row["last_sync"]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "person_id": self.person_id,
            "colour": self.colour,
            "enabled": self.enabled,
            "sync_token": self.sync_token,
            "last_sync": self.last_sync,
        }


class ReminderRule:
    """DTO for a reminder_rules row."""

    __slots__ = ("id", "scope", "scope_id", "offset_s", "enabled")

    def __init__(self, row: sqlite3.Row) -> None:
        self.id: int = row["id"]
        self.scope: str = row["scope"]
        self.scope_id: str | None = row["scope_id"]
        self.offset_s: int = row["offset_s"]
        self.enabled: bool = bool(row["enabled"])

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "scope": self.scope,
            "scope_id": self.scope_id,
            "offset_s": self.offset_s,
            "enabled": self.enabled,
        }


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

    # ── Calendars CRUD ───────────────────────────────────────────────────────
    def get_enabled_calendars(self) -> list[Calendar]:
        """Return all calendars with enabled=1."""
        with self._db.connect() as conn:
            rows = conn.execute("SELECT * FROM calendars WHERE enabled = 1").fetchall()
        return [Calendar(r) for r in rows]

    def get_all_calendars(self) -> list[Calendar]:
        """Return all calendars including disabled ones."""
        with self._db.connect() as conn:
            rows = conn.execute("SELECT * FROM calendars").fetchall()
        return [Calendar(r) for r in rows]

    def upsert_calendar(
        self,
        id: str,
        label: str,
        person_id: str | None = None,
        enabled: bool = True,
    ) -> None:
        """Insert or update a calendar entry."""
        with self._db.connect() as conn:
            conn.execute(
                """
                INSERT INTO calendars (id, label, person_id, enabled)
                VALUES (:id, :label, :person_id, :enabled)
                ON CONFLICT(id) DO UPDATE SET
                    label = excluded.label,
                    person_id = excluded.person_id,
                    enabled = excluded.enabled
                """,
                {
                    "id": id,
                    "label": label,
                    "person_id": person_id,
                    "enabled": 1 if enabled else 0,
                },
            )

    def update_sync_token(self, calendar_id: str, sync_token: str) -> None:
        """Update the sync_token and last_sync timestamp for a calendar."""
        with self._db.connect() as conn:
            conn.execute(
                """
                UPDATE calendars
                SET sync_token = ?, last_sync = ?
                WHERE id = ?
                """,
                (sync_token, int(time.time()), calendar_id),
            )

    def set_calendar_enabled(self, calendar_id: str, enabled: bool) -> None:
        """Enable or disable a calendar."""
        with self._db.connect() as conn:
            conn.execute(
                "UPDATE calendars SET enabled = ? WHERE id = ?",
                (1 if enabled else 0, calendar_id),
            )

    # ── Reminder Rules CRUD ──────────────────────────────────────────────────
    def get_all_rules(self) -> list[ReminderRule]:
        """Return all reminder rules."""
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM reminder_rules WHERE enabled = 1"
            ).fetchall()
        return [ReminderRule(r) for r in rows]

    def get_rules_for_event(self, event: dict) -> list[ReminderRule]:
        """Return applicable rules for an event (person > calendar > global priority).

        Looks up rules in order of specificity:
        1. Person-specific rules (scope='person', scope_id=event.person_id)
        2. Calendar-specific rules (scope='calendar', scope_id=event.calendar_id)
        3. Global rules (scope='global', scope_id IS NULL)

        Returns the most specific set found (first non-empty).
        """
        person_id = event.get("person_id")
        calendar_id = event.get("calendar_id")

        with self._db.connect() as conn:
            # Try person-specific first
            if person_id:
                rows = conn.execute(
                    """
                    SELECT * FROM reminder_rules
                    WHERE enabled = 1 AND scope = 'person' AND scope_id = ?
                    """,
                    (person_id,),
                ).fetchall()
                if rows:
                    return [ReminderRule(r) for r in rows]

            # Try calendar-specific
            if calendar_id:
                rows = conn.execute(
                    """
                    SELECT * FROM reminder_rules
                    WHERE enabled = 1 AND scope = 'calendar' AND scope_id = ?
                    """,
                    (calendar_id,),
                ).fetchall()
                if rows:
                    return [ReminderRule(r) for r in rows]

            # Fall back to global
            rows = conn.execute(
                """
                SELECT * FROM reminder_rules
                WHERE enabled = 1 AND scope = 'global' AND scope_id IS NULL
                """
            ).fetchall()
            return [ReminderRule(r) for r in rows]

    def add_rule(self, scope: str, scope_id: str | None, offset_s: int) -> int:
        """Add a reminder rule. Returns the new rule's id."""
        with self._db.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO reminder_rules (scope, scope_id, offset_s, enabled)
                VALUES (?, ?, ?, 1)
                """,
                (scope, scope_id, offset_s),
            )
            return cursor.lastrowid or 0

    def delete_rule(self, rule_id: int) -> bool:
        """Delete a reminder rule by id. Returns True if deleted."""
        with self._db.connect() as conn:
            rowcount = conn.execute(
                "DELETE FROM reminder_rules WHERE id = ?", (rule_id,)
            ).rowcount
        return rowcount > 0

    def seed_default_rules(self, offsets: list[int] | None = None) -> int:
        """Create global reminder rules if none exist.

        Default offsets: 86400 (24h), 7200 (2h), 1800 (30min).
        Returns the number of rules created.
        """
        if offsets is None:
            offsets = [86400, 7200, 1800]

        with self._db.connect() as conn:
            existing = conn.execute(
                "SELECT COUNT(*) AS n FROM reminder_rules WHERE scope = 'global'"
            ).fetchone()
            if existing["n"] > 0:
                return 0

            created = 0
            for offset_s in offsets:
                conn.execute(
                    """
                    INSERT INTO reminder_rules (scope, scope_id, offset_s, enabled)
                    VALUES ('global', NULL, ?, 1)
                    """,
                    (offset_s,),
                )
                created += 1
            return created

    # ── Reminders Sent (dedup ledger) ────────────────────────────────────────
    def try_record_reminder(
        self, event_uid: str, offset_s: int, event_start: int
    ) -> bool:
        """Attempt to record a sent reminder. Returns True if inserted, False if exists.

        Uses UNIQUE(event_uid, offset_s, event_start) for hard dedup (§5.2).
        """
        with self._db.connect() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO reminders_sent (event_uid, offset_s, event_start, sent_ts, ok)
                    VALUES (?, ?, ?, ?, 1)
                    """,
                    (event_uid, offset_s, event_start, int(time.time())),
                )
                return True
            except sqlite3.IntegrityError:
                return False

    def prune_old_reminders(self, retention_days: int = 90) -> int:
        """Delete reminder records older than retention_days. Returns count deleted."""
        cutoff = int(time.time()) - retention_days * 24 * 3600
        with self._db.connect() as conn:
            rowcount = conn.execute(
                "DELETE FROM reminders_sent WHERE sent_ts < ?", (cutoff,)
            ).rowcount
        if rowcount:
            logger.info("Pruned %d old reminder records", rowcount)
        return rowcount

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

    def get_events_in_reminder_window(
        self, now: int | None = None, max_offset_s: int = 86400
    ) -> list[dict]:
        """Return events with start_ts between now and now+max_offset.

        Used by the reminder tick loop to find events needing reminders soon.
        """
        now = int(time.time()) if now is None else now
        window_end = now + max_offset_s
        with self._db.connect() as conn:
            rows = conn.execute(
                """
                SELECT uid, calendar_id, google_id, title, description, location,
                       start_ts, end_ts, all_day, person_id, status
                FROM events
                WHERE status = 'confirmed' AND start_ts >= ? AND start_ts <= ?
                ORDER BY start_ts ASC
                """,
                (now, window_end),
            ).fetchall()
        return [dict(r) for r in rows]

    def clear_calendar_events(self, calendar_id: str) -> int:
        """Delete all events for a calendar (for full sync). Returns count deleted."""
        with self._db.connect() as conn:
            rowcount = conn.execute(
                "DELETE FROM events WHERE calendar_id = ?", (calendar_id,)
            ).rowcount
        if rowcount:
            logger.info("Cleared %d events from calendar %s", rowcount, calendar_id)
        return rowcount

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
