"""AC command event logging.

Persists every control command sent to the AC (mode changes, manual
parameter updates, config changes) to a SQLite database so the history can
be inspected later for auditing and debugging.

Each entry records:
  - timestamp       (epoch seconds, UTC)
  - command_type    (e.g. "control", "manual", "manual_param", "config")
  - params_json     (JSON blob of the command parameters)
  - success         (whether the command succeeded)
  - error_msg       (error detail when success is False, else NULL)

The database lives next to the controller state file inside the service's
data directory (``AC_DATA_DIR``, default ``/app/data``), which the Dockerfile
creates owned by the non-root ``appuser``.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from smart_home_common.sqlite_helpers import SqliteHelper

logger = logging.getLogger(__name__)

# Database file (inside container, mounted as volume). Mirrors the location
# convention used by state_persistence.STATE_FILE.
_DATA_DIR = os.environ.get("AC_DATA_DIR", "/app/data")
EVENT_LOG_FILE = Path(_DATA_DIR) / "ac_event_log.db"


def _ensure_schema(conn) -> None:
    """Create the command event-log table if it does not exist."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS command_events (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp     REAL    NOT NULL,
            command_type  TEXT    NOT NULL,
            params_json   TEXT    NOT NULL,
            success       INTEGER NOT NULL,
            error_msg     TEXT
        )
        """
    )
    # Index on timestamp so get_history(hours) windowing stays fast as the
    # table grows.
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_command_events_timestamp "
        "ON command_events (timestamp)"
    )


class ACEventLog:
    """Records AC control commands to SQLite and reads them back.

    Thread-safe by construction: every method opens its own short-lived
    connection via :class:`SqliteHelper` (``check_same_thread=False``), so it
    can be called from FastAPI request handlers and background threads alike.
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        """Initialise the event log.

        Args:
            db_path: Override the database location. Defaults to
                :data:`EVENT_LOG_FILE`.
        """
        self.db_path = Path(db_path) if db_path is not None else EVENT_LOG_FILE
        self._db = SqliteHelper(self.db_path, init=_ensure_schema)

    def log_command(
        self,
        command: str,
        params: dict[str, Any] | None,
        result: bool,
        error_msg: str | None = None,
    ) -> bool:
        """Record a single command event.

        Args:
            command: The command type (e.g. ``"control"``, ``"manual"``).
            params: The command parameters; serialised to JSON. ``None`` is
                stored as an empty object.
            result: Whether the command succeeded.
            error_msg: Optional error detail stored when ``result`` is False.

        Returns:
            True if the event was persisted, False on error (logging failures
            must never break the actual command).
        """
        try:
            params_json = json.dumps(params or {}, default=str, sort_keys=True)
            with self._db.connect() as conn:
                conn.execute(
                    """
                    INSERT INTO command_events
                        (timestamp, command_type, params_json, success, error_msg)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        time.time(),
                        command,
                        params_json,
                        1 if result else 0,
                        error_msg,
                    ),
                )
            return True
        except Exception:
            logger.exception("Failed to log AC command event (command=%s)", command)
            return False

    def get_history(self, hours: int = 24) -> list[dict[str, Any]]:
        """Return command events from the last ``hours`` hours, newest first.

        Args:
            hours: Size of the look-back window in hours. Values <= 0 are
                clamped to 1 hour.

        Returns:
            A list of event dicts with keys: ``timestamp``, ``command_type``,
            ``params`` (deserialised dict), ``success`` (bool) and
            ``error_msg``. Returns an empty list on error.
        """
        hours = max(1, hours)
        cutoff = time.time() - hours * 3600
        try:
            with self._db.connect() as conn:
                rows = conn.execute(
                    """
                    SELECT timestamp, command_type, params_json, success, error_msg
                    FROM command_events
                    WHERE timestamp >= ?
                    ORDER BY timestamp DESC, id DESC
                    """,
                    (cutoff,),
                ).fetchall()
        except Exception:
            logger.exception("Failed to read AC command event history")
            return []

        history: list[dict[str, Any]] = []
        for row in rows:
            try:
                params = json.loads(row["params_json"])
            except (TypeError, ValueError):
                params = {}
            history.append(
                {
                    "timestamp": row["timestamp"],
                    "command_type": row["command_type"],
                    "params": params,
                    "success": bool(row["success"]),
                    "error_msg": row["error_msg"],
                }
            )
        return history
