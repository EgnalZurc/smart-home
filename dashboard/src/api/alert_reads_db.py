"""Persistence for per-user alert read/dismiss tracking.

Alerts surfaced by the unified feed (:mod:`api.alerts`) are shared across the
whole household, but whether a given alert has been *seen* is per user. This
module stores that state in the same SQLite database the auth/profile system
uses (``AUTH_DB_PATH``), reusing the shared connection-management helpers from
:mod:`smart_home_common.sqlite_helpers` so WAL side-files are always released
(no leaked handles / cross-test state — see ``dashboard/src/profiles/db.py``).

Design notes
------------
* ``AUTH_DB_PATH`` is read at call time (not import time) so the late injection
  performed by ``main.py``'s lifespan still takes effect, exactly like
  :mod:`profiles.db`.
* The schema is created lazily via the ``init`` hook on every connection open
  (idempotent ``CREATE TABLE IF NOT EXISTS``), so there is no separate
  initialisation step to wire into the app lifespan.
* ``(user_id, alert_key)`` is UNIQUE: marking an already-read alert simply
  refreshes its ``read_at`` timestamp instead of inserting a duplicate.
"""

import logging
import sqlite3
from contextlib import AbstractContextManager
from datetime import datetime, timezone

from smart_home_common.sqlite_helpers import sqlite_connection

logger = logging.getLogger(__name__)

# Injected from main.py's lifespan (same value as the auth/profile stores).
# Read at call time so late injection takes effect.
AUTH_DB_PATH: str = "/app/data/auth.db"


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Create the ``alert_reads`` table if it does not yet exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS alert_reads (
            id        INTEGER PRIMARY KEY,
            user_id   TEXT NOT NULL,
            alert_key TEXT NOT NULL,
            read_at   TEXT NOT NULL,
            UNIQUE(user_id, alert_key)
        )
    """)


def _db() -> AbstractContextManager[sqlite3.Connection]:
    """Yield a schema-ensured connection, committing and always closing it.

    Reads ``AUTH_DB_PATH`` at call time so main.py's late injection is honoured.
    """
    return sqlite_connection(AUTH_DB_PATH, init=_ensure_schema)


def mark_alert_read(user_id: str, alert_key: str) -> None:
    """Mark ``alert_key`` as read for ``user_id``.

    Idempotent: re-marking an already-read alert refreshes its ``read_at``
    timestamp rather than creating a duplicate row.

    Args:
        user_id: The authenticated username the read state belongs to.
        alert_key: Stable identifier of the alert being marked read.
    """
    read_at = datetime.now(timezone.utc).isoformat()
    with _db() as conn:
        conn.execute(
            """
            INSERT INTO alert_reads (user_id, alert_key, read_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, alert_key)
            DO UPDATE SET read_at = excluded.read_at
            """,
            (user_id, alert_key, read_at),
        )
    logger.info("Marked alert %r as read for user %r", alert_key, user_id)


def get_read_alerts(user_id: str) -> list[str]:
    """Return the list of ``alert_key`` values ``user_id`` has marked read.

    Args:
        user_id: The authenticated username to look up.

    Returns:
        A list of alert keys, most recently read first.
    """
    with _db() as conn:
        rows = conn.execute(
            "SELECT alert_key FROM alert_reads WHERE user_id = ? ORDER BY read_at DESC",
            (user_id,),
        ).fetchall()
    return [row["alert_key"] for row in rows]


def is_alert_read(user_id: str, alert_key: str) -> bool:
    """Return whether ``user_id`` has marked ``alert_key`` as read.

    Args:
        user_id: The authenticated username to look up.
        alert_key: The alert identifier to check.

    Returns:
        ``True`` if a read record exists, ``False`` otherwise.
    """
    with _db() as conn:
        row = conn.execute(
            "SELECT 1 FROM alert_reads WHERE user_id = ? AND alert_key = ? LIMIT 1",
            (user_id, alert_key),
        ).fetchone()
    return row is not None
