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

import hashlib
import logging
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

from config import DB_PATH, RETENTION_DAYS
from models import PresenceEvent

# ── PII Pseudonymization ─────────────────────────────────────────────────────
# MAC addresses are personally identifiable information (PII) that can be used
# to track individuals. To comply with privacy regulations and minimize data
# exposure in case of a breach, we hash MACs before storing or logging them.
#
# The hash is truncated to 16 hex chars (64 bits) which provides:
# - Sufficient uniqueness for device correlation within the household
# - Irreversibility (cannot recover the original MAC)
# - Consistent pseudonymization across the codebase
# - 64 bits of collision resistance (stronger than 48-bit truncation)


def hash_mac(mac: str) -> str:
    """Hash a MAC address for pseudonymized storage/logging.

    Args:
        mac: Raw MAC address in any format (AA:BB:CC:DD:EE:FF, aabbccddeeff, etc.)

    Returns:
        16-character hex string (first 64 bits of SHA-256 hash).

    Note:
        The hash is deterministic so the same MAC always produces the same
        pseudonym, enabling device correlation without storing raw PII.
    """
    # Normalize: lowercase, remove separators
    normalized: str = mac.lower().replace(":", "").replace("-", "").replace(".", "")
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


# ── Input Validation ─────────────────────────────────────────────────────────
_PERSON_ID_PATTERN: re.Pattern[str] = re.compile(
    rf"^[a-zA-Z0-9_-]{{1,{MAX_PERSON_ID_LENGTH}}}$"
)


def validate_person_id(person_id: str) -> str:
    """Validate and return a sanitized person_id.

    Args:
        person_id: The identifier to validate.

    Returns:
        The validated person_id (unchanged if valid).

    Raises:
        ValueError: If person_id contains invalid characters or is too long.
    """
    if not person_id or not _PERSON_ID_PATTERN.match(person_id):
        raise ValueError(
            f"Invalid person_id: must be 1-{MAX_PERSON_ID_LENGTH} alphanumeric chars, "
            "hyphens or underscores"
        )
    return person_id


try:
    from smart_home_common.sqlite_helpers import SqliteHelper
except ImportError:  # pragma: no cover - import fallback outside the container
    import sys

    _repo_root: Path = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(_repo_root / "libs" / "smart_home_common" / "src"))
    from smart_home_common.sqlite_helpers import SqliteHelper

logger: logging.Logger = logging.getLogger(__name__)


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Create the presence tables and indexes if they do not exist.

    Implements the schema from design document §7.2:
    - people: enrolled household members with track flag
    - devices: hashed MAC addresses linked to people
    - beacons: BLE identifiers linked to people
    - zones: motion sensor groupings for room occupancy
    - presence_current: one-row-per-person snapshot surviving restarts
    - transitions: audit trail of state changes with retention policy

    Args:
        conn: An open SQLite connection (WAL mode recommended).

    Note:
        This function is idempotent — safe to call on every startup.
        Indexes are created for efficient time-range and person-filtered queries.
    """
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
            mac_hash  TEXT PRIMARY KEY,
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
        self.db_path: str = db_path
        self._db: SqliteHelper = SqliteHelper(db_path, init=_ensure_schema)

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
        validate_person_id(person_id)
        with self._db.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO presence_current "
                "(person_id, state, confidence, since, last_seen, last_source) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (person_id, state, confidence, since, last_seen, last_source),
            )

    def get_current(self) -> list[dict[str, Any]]:
        """Return the current snapshot for every person (one row each)."""
        with self._db.connect() as conn:
            rows: list[sqlite3.Row] = conn.execute(
                "SELECT person_id, state, confidence, since, last_seen, last_source "
                "FROM presence_current"
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Transition history ──────────────────────────────────────────────────
    def record_transition(self, event: PresenceEvent) -> int:
        """Persist one confirmed transition; return its row id."""
        validate_person_id(event.person_id)
        with self._db.connect() as conn:
            cur: sqlite3.Cursor = conn.execute(
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
    ) -> list[dict[str, Any]]:
        """Return the transition audit trail, optionally filtered.

        Rows are returned newest-first.
        """
        if person_id is not None:
            validate_person_id(person_id)
        query: str = (
            "SELECT id, ts, person_id, from_state, to_state, confidence, source "
            "FROM transitions WHERE 1 = 1"
        )
        args: list[Any] = []
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
            rows: list[sqlite3.Row] = conn.execute(query, args).fetchall()
        return [dict(r) for r in rows]

    # ── Retention ─────────────────────────────────────────────────────────────
    def prune(
        self, now: int | None = None, retention_days: int = RETENTION_DAYS
    ) -> int:
        """Delete transitions older than ``retention_days`` and checkpoint WAL.

        Returns the number of rows deleted.
        """
        now_ts: int = int(time.time()) if now is None else now
        cutoff: int = now_ts - retention_days * 24 * 3600
        with self._db.connect() as conn:
            cur: sqlite3.Cursor = conn.execute(
                "DELETE FROM transitions WHERE ts < ?", (cutoff,)
            )
            deleted: int = cur.rowcount
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
            row: sqlite3.Row | None = conn.execute(
                "SELECT COUNT(*) AS n FROM transitions"
            ).fetchone()
        return int(row["n"]) if row else 0

    def db_ok(self) -> bool:
        """Check if the database is accessible and responding.

        Executes a trivial query to verify the database connection is healthy.
        This is used by the health check endpoint to report database status.

        Returns:
            True if the database responds to a simple count query, False if any
            database-related error occurs (connection failure, corruption, etc.).
        """
        try:
            self.count_transitions()
            return True
        except (sqlite3.Error, OSError) as exc:  # pragma: no cover - defensive
            logger.warning("Database health check failed: %s", exc)
            return False
