"""Durable alert state: the ``alerts`` active table + ``alert_history`` audit log.

Persisting the active-alert set is what makes anti-flapping survive a restart
(design §7.3): on boot the :class:`~alerts.AlertEngine` rehydrates from
:meth:`AlertStore.load_active` so an already-firing alert is not re-sent.

Two tables, both via ``smart_home_common.sqlite_helpers.SqliteHelper`` (WAL +
guaranteed close), stored in the same ``metrics.db`` as the time series:

    alerts(fingerprint PK, rule_key, label, severity, value, message, fired_at,
           resolved_at)                -- resolved_at IS NULL ⇒ currently firing
    alert_history(id PK, fingerprint, rule_key, label, severity, value, event, ts)
"""

from __future__ import annotations

import logging
import sqlite3
import time

from config import DB_PATH

try:
    from smart_home_common.sqlite_helpers import SqliteHelper
except ImportError:  # pragma: no cover - import fallback outside the container
    import sys
    from pathlib import Path

    _repo_root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(_repo_root / "libs" / "smart_home_common" / "src"))
    from smart_home_common.sqlite_helpers import SqliteHelper

logger = logging.getLogger(__name__)


def _ensure_alert_schema(conn: sqlite3.Connection) -> None:
    """Create the alerts + alert_history tables if they do not exist."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS alerts (
            fingerprint TEXT    PRIMARY KEY,
            rule_key    TEXT    NOT NULL,
            label       TEXT    NOT NULL DEFAULT '',
            severity    TEXT    NOT NULL,
            value       REAL    NOT NULL,
            message     TEXT    NOT NULL,
            fired_at    INTEGER NOT NULL,
            resolved_at INTEGER
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS alert_history (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            fingerprint TEXT    NOT NULL,
            rule_key    TEXT    NOT NULL,
            label       TEXT    NOT NULL DEFAULT '',
            severity    TEXT    NOT NULL,
            value       REAL    NOT NULL,
            event       TEXT    NOT NULL,   -- 'fired' | 'resolved'
            ts          INTEGER NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_alert_history_ts ON alert_history(ts)")


class AlertStore:
    """SQLite-backed persistence for active alerts and the alert audit trail."""

    def __init__(self, db_path: str = DB_PATH) -> None:
        self.db_path = db_path
        self._db = SqliteHelper(db_path, init=_ensure_alert_schema)

    # ── Active set ────────────────────────────────────────────────────────────
    def load_active(self) -> list:
        """Return all currently-firing alerts (``resolved_at IS NULL``).

        Imports :class:`alerts.ActiveAlert` lazily to avoid a circular import
        (``alerts`` imports this module's instance, not the class).
        """
        from alerts import ActiveAlert, Severity

        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT fingerprint, rule_key, label, severity, value, message, "
                "fired_at, resolved_at FROM alerts WHERE resolved_at IS NULL"
            ).fetchall()
        return [
            ActiveAlert(
                fingerprint=r["fingerprint"],
                rule_key=r["rule_key"],
                label=r["label"],
                severity=Severity(r["severity"]),
                value=r["value"],
                message=r["message"],
                fired_at=r["fired_at"],
                resolved_at=r["resolved_at"],
            )
            for r in rows
        ]

    def upsert_active(self, alert) -> None:
        """Insert or update an active alert row (fingerprint is the PK)."""
        with self._db.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO alerts "
                "(fingerprint, rule_key, label, severity, value, message, "
                "fired_at, resolved_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    alert.fingerprint,
                    alert.rule_key,
                    alert.label,
                    alert.severity.value,
                    alert.value,
                    alert.message,
                    alert.fired_at,
                    alert.resolved_at,
                ),
            )

    def resolve_active(self, fingerprint: str, resolved_at: int) -> None:
        """Mark an active alert resolved (keeps the row for a short audit grace).

        We clear it from the active table so ``load_active`` won't rehydrate it;
        the enduring record lives in ``alert_history``.
        """
        with self._db.connect() as conn:
            conn.execute("DELETE FROM alerts WHERE fingerprint = ?", (fingerprint,))

    # ── History ────────────────────────────────────────────────────────────────
    def record_history(self, alert, event: str, ts: int) -> None:
        """Append a ``fired``/``resolved`` event to the audit trail."""
        with self._db.connect() as conn:
            conn.execute(
                "INSERT INTO alert_history "
                "(fingerprint, rule_key, label, severity, value, event, ts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    alert.fingerprint,
                    alert.rule_key,
                    alert.label,
                    alert.severity.value,
                    alert.value,
                    event,
                    ts,
                ),
            )

    def history(self, days: int = 7, now: int | None = None) -> list[dict]:
        """Return alert-history events in the last ``days`` (newest first)."""
        now = int(time.time()) if now is None else now
        since = now - days * 24 * 3600
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT fingerprint, rule_key, label, severity, value, event, ts "
                "FROM alert_history WHERE ts >= ? ORDER BY ts DESC",
                (since,),
            ).fetchall()
        return [
            {
                "fingerprint": r["fingerprint"],
                "rule_key": r["rule_key"],
                "label": r["label"],
                "severity": r["severity"],
                "value": r["value"],
                "event": r["event"],
                "ts": r["ts"],
            }
            for r in rows
        ]

    def prune_history(self, days: int = 90, now: int | None = None) -> int:
        """Delete history rows older than ``days``; returns rows deleted."""
        now = int(time.time()) if now is None else now
        cutoff = now - days * 24 * 3600
        with self._db.connect() as conn:
            cur = conn.execute("DELETE FROM alert_history WHERE ts < ?", (cutoff,))
            deleted = cur.rowcount
        if deleted:
            logger.info("Pruned %d alert_history rows older than %dd", deleted, days)
        return deleted
