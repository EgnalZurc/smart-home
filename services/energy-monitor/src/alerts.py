"""Consumption alert engine for energy-monitor (design §8).

Evaluates the whole-home total against the thresholds in ``config`` and persists
a fired/resolved event to the ``energy_alerts`` audit trail whenever a rule
crosses its boundary. Delivery is best-effort via the shared
``smart_home_common.telegram.TelegramNotifier`` (no-op when unconfigured).

The engine is edge-triggered: it keeps the last known state per rule in memory
so a sustained over-budget condition fires once (and resolves once), instead of
spamming on every evaluation tick. State is intentionally in-process — the audit
trail in SQLite is the durable record.

Three rules (any with a threshold <= 0 is skipped):
  * ``power_spike``   — latest 1-min ``power_max`` over ``POWER_ALERT_W``.
  * ``daily_budget``  — day-to-date kWh over ``DAILY_KWH_ALERT``.
  * ``monthly_budget``— month-to-date kWh over ``MONTHLY_KWH_ALERT``.
"""

from __future__ import annotations

import logging
import time

from config import (
    ALERTS_ENABLED,
    DAILY_KWH_ALERT,
    MONTHLY_KWH_ALERT,
    POWER_ALERT_W,
)
from database import EnergyStore

try:
    from smart_home_common.telegram import TelegramNotifier
except ImportError:  # pragma: no cover - import fallback outside the container
    TelegramNotifier = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


class AlertEngine:
    """Edge-triggered consumption alert evaluator."""

    def __init__(
        self,
        store: EnergyStore,
        *,
        enabled: bool = ALERTS_ENABLED,
        notifier=None,
    ) -> None:
        self.store = store
        self.enabled = enabled
        # Lazily build a notifier from env unless one is injected (tests inject).
        if notifier is not None:
            self.notifier = notifier
        elif TelegramNotifier is not None:
            self.notifier = TelegramNotifier.from_env()
        else:  # pragma: no cover - lib missing outside container
            self.notifier = None
        # rule_key -> "fired" | "ok"; absence means "never evaluated".
        self._state: dict[str, str] = {}

    def _rules(self, now: int) -> list[tuple[str, str, float, float]]:
        """Return ``(rule_key, severity, current_value, threshold)`` per rule.

        Rules whose threshold is <= 0 (disabled) are omitted.
        """
        rules: list[tuple[str, str, float, float]] = []

        if POWER_ALERT_W > 0:
            latest = self._latest_power_max(now)
            if latest is not None:
                rules.append(("power_spike", "warning", latest, POWER_ALERT_W))

        stats = self.store.stats(now=now)
        # Day-to-date is the last (in-progress) daily bucket.
        if DAILY_KWH_ALERT > 0:
            daily = self.store.consumption_by_period("day", 1, now=now)
            today = daily[-1]["consumption_kwh"] if daily else None
            if today is not None:
                rules.append(("daily_budget", "warning", today, DAILY_KWH_ALERT))

        if MONTHLY_KWH_ALERT > 0 and stats["total_kwh"] is not None:
            rules.append(
                (
                    "monthly_budget",
                    "critical",
                    float(stats["total_kwh"]),
                    MONTHLY_KWH_ALERT,
                )
            )
        return rules

    def _latest_power_max(self, now: int) -> float | None:
        """Return the newest 1-min ``power_max`` across channels, or ``None``."""
        with self.store._db.connect() as conn:  # noqa: SLF001 - same package
            row = conn.execute(
                "SELECT MAX(power_max) AS pmax FROM power_samples "
                "WHERE ts = (SELECT MAX(ts) FROM power_samples)"
            ).fetchone()
        if row is None or row["pmax"] is None:
            return None
        return float(row["pmax"])

    def evaluate(self, now: int | None = None) -> list[dict[str, object]]:
        """Evaluate all rules once; persist/send any state transitions.

        Returns the list of transition events emitted this tick (empty when
        nothing changed). Disabled engine returns an empty list without touching
        the DB.
        """
        if not self.enabled:
            return []
        now = int(time.time()) if now is None else now
        events: list[dict[str, object]] = []

        for rule_key, severity, value, threshold in self._rules(now):
            over = value > threshold
            new_state = "fired" if over else "ok"
            prev = self._state.get(rule_key)
            self._state[rule_key] = new_state
            if prev == new_state:
                continue  # No edge → no event.
            # Suppress the initial "ok" (first observation under threshold).
            if prev is None and new_state == "ok":
                continue

            state = "fired" if over else "resolved"
            message = self._format(rule_key, value, threshold, state)
            self.store.record_alert(
                rule_key,
                severity,
                state,
                value=value,
                message=message,
                ts=now,
            )
            self._send(message)
            events.append(
                {
                    "rule_key": rule_key,
                    "state": state,
                    "severity": severity,
                    "value": value,
                    "threshold": threshold,
                }
            )
        return events

    @staticmethod
    def _format(rule_key: str, value: float, threshold: float, state: str) -> str:
        """Build a human-readable alert message."""
        unit = "W" if rule_key == "power_spike" else "kWh"
        verb = "exceeded" if state == "fired" else "back under"
        label = {
            "power_spike": "Power spike",
            "daily_budget": "Daily consumption",
            "monthly_budget": "Monthly consumption",
        }.get(rule_key, rule_key)
        return (
            f"⚡ {label} {verb} threshold: "
            f"{round(value, 2)}{unit} vs {round(threshold, 2)}{unit}"
        )

    def _send(self, message: str) -> None:
        """Best-effort Telegram delivery; never raises into the caller."""
        if self.notifier is None or not getattr(self.notifier, "enabled", False):
            return
        try:
            self.notifier.send(message)
        except Exception as exc:  # pragma: no cover - defensive, delivery best-effort
            logger.warning("alert delivery failed: %s", exc)
