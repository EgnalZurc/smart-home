"""Consumption alert engine for energy-monitor (design §8).

Evaluates the whole-home total against the thresholds in ``config`` and persists
a fired/resolved event to the ``energy_alerts`` audit trail whenever a rule
crosses its boundary. Delivery is best-effort via the shared
``smart_home_common.telegram.TelegramNotifier`` (no-op when unconfigured).

The engine is edge-triggered: it keeps the last known state per rule in memory
so a sustained over-budget condition fires once (and resolves once), instead of
spamming on every evaluation tick. State is intentionally in-process — the audit
trail in SQLite is the durable record.

Alert Rules
-----------
Three configurable rules, each disabled when its threshold is set to 0:

* ``power_spike`` (ENERGY_POWER_ALERT_W, default: 3500W)
    Fires when the latest 1-minute ``power_max`` exceeds the threshold.
    Useful for detecting appliance anomalies or overload conditions.

* ``daily_budget`` (ENERGY_DAILY_KWH_ALERT, default: 20 kWh)
    Fires when day-to-date consumption exceeds the daily energy budget.
    Helps track daily usage against a target.

    **Limitation**: Day-to-date consumption is derived from
    ``consumption_by_period('day', 1)``, which returns the current UTC
    calendar day bucket. Near midnight UTC the "today" value may include
    consumption that a local-timezone user considers yesterday's, or vice
    versa. This is a known edge case; explicit time-zone alignment is not
    implemented. For users in timezones far from UTC, the daily budget
    alert may fire or resolve a few hours earlier/later than expected on
    calendar boundaries.

* ``monthly_budget`` (ENERGY_MONTHLY_KWH_ALERT, default: 400 kWh)
    Fires when month-to-date consumption exceeds the monthly energy budget.
    Severity is 'critical' (vs 'warning' for other rules).

Configuration
-------------
Thresholds are read from environment variables at import time (see config.py):
  - ``ENERGY_POWER_ALERT_W``: Power spike threshold in watts
  - ``ENERGY_DAILY_KWH_ALERT``: Daily budget threshold in kWh
  - ``ENERGY_MONTHLY_KWH_ALERT``: Monthly budget threshold in kWh

Set any threshold to 0 or a negative value to disable that rule entirely.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Protocol

from config import (
    ALERTS_ENABLED,
    DAILY_KWH_ALERT,
    MONTHLY_KWH_ALERT,
    POWER_ALERT_W,
)
from database import EnergyStore


# ── Notifier protocol for type safety ─────────────────────────────────────────
class Notifier(Protocol):
    """Protocol for alert message delivery (structural typing)."""

    enabled: bool

    def send(self, message: str) -> None:
        """Send a message. May raise OSError or RuntimeError on failure."""
        ...


# Runtime import of the real notifier; falls back to None outside the container.
_TelegramNotifier: type[Notifier] | None
try:
    from smart_home_common.telegram import TelegramNotifier as _TelegramNotifier
except ImportError:  # pragma: no cover - import fallback outside the container
    _TelegramNotifier = None

logger: logging.Logger = logging.getLogger(__name__)

__all__ = ["AlertEngine", "Notifier"]

# ── Alert rule type aliases (internal) ────────────────────────────────────────
# Each rule is represented as (rule_key, severity, current_value, threshold).
_AlertRule = tuple[str, str, float, float]


class AlertEngine:
    """Edge-triggered consumption alert evaluator.

    Monitors energy consumption against configurable thresholds and emits
    state-change events (fired/resolved) when boundaries are crossed.
    Events are persisted to the SQLite audit trail and optionally delivered
    via Telegram.

    The engine uses edge-triggering: a sustained over-budget condition fires
    only once, and resolves only once when the value drops back below the
    threshold. This prevents alert spam during prolonged threshold violations.

    Attributes:
        store: The EnergyStore instance for reading metrics and persisting alerts.
        enabled: Whether alert evaluation is active.
        notifier: Optional TelegramNotifier for delivery (None disables delivery).

    Example:
        >>> engine = AlertEngine(store, enabled=True)
        >>> events = engine.evaluate()  # Check all rules, emit transitions
        >>> for event in events:
        ...     print(f"{event['rule_key']}: {event['state']}")
    """

    def __init__(
        self,
        store: EnergyStore,
        *,
        enabled: bool = ALERTS_ENABLED,
        notifier: Any = None,
    ) -> None:
        """Initialize the alert engine.

        Args:
            store: EnergyStore instance for reading metrics and persisting alerts.
            enabled: Whether to evaluate alerts. When False, evaluate() is a no-op.
            notifier: Optional notifier for message delivery. If None and
                TelegramNotifier is available, one is created from environment
                variables.
        """
        self._store = store
        self._enabled = enabled
        # Lazily build a notifier from env unless one is injected (tests inject).
        if notifier is not None:
            self._notifier = notifier
        elif _TelegramNotifier is not None:
            self._notifier = _TelegramNotifier.from_env()
        else:  # pragma: no cover - lib missing outside container
            self._notifier = None
        # rule_key -> "fired" | "ok"; absence means "never evaluated".
        self._state: dict[str, str] = {}

    @property
    def store(self) -> EnergyStore:
        """The EnergyStore used for reading metrics and persisting alerts."""
        return self._store

    @property
    def enabled(self) -> bool:
        """Whether alert evaluation is active."""
        return self._enabled

    @property
    def notifier(self) -> Notifier | None:
        """The notifier used for alert delivery, or None if delivery is disabled."""
        return self._notifier

    def _rules(self, now: int) -> list[_AlertRule]:
        """Build the list of active alert rules with current values.

        Args:
            now: Current Unix timestamp for time-based calculations.

        Returns:
            List of tuples ``(rule_key, severity, current_value, threshold)``
            for each rule whose threshold is > 0 and has a measurable value.
        """
        rules: list[_AlertRule] = []

        if POWER_ALERT_W > 0:
            latest = self._latest_power_max(now)
            if latest is not None:
                rules.append(("power_spike", "warning", latest, POWER_ALERT_W))

        stats = self._store.stats(now=now)
        # Day-to-date is the last (in-progress) daily bucket.
        if DAILY_KWH_ALERT > 0:
            daily = self._store.consumption_by_period("day", 1, now=now)
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
        """Return the newest 1-min ``power_max`` across channels, or ``None``.

        Args:
            now: Current Unix timestamp (unused but kept for API consistency).

        Returns:
            The maximum power_max value from the most recent timestamp in
            power_samples, or None if no samples exist.
        """
        with self._store._db.connect() as conn:  # noqa: SLF001 - same package
            row = conn.execute(
                "SELECT MAX(power_max) AS pmax FROM power_samples "
                "WHERE ts = (SELECT MAX(ts) FROM power_samples)"
            ).fetchone()
        if row is None or row["pmax"] is None:
            return None
        return float(row["pmax"])

    def evaluate(self, now: int | None = None) -> list[dict[str, object]]:
        """Evaluate all rules once; persist/send any state transitions.

        Checks each configured alert rule against current values. When a rule
        crosses its threshold boundary (in either direction), the transition
        is recorded to the audit trail and optionally delivered via Telegram.

        Args:
            now: Unix timestamp for evaluation. Defaults to current time.

        Returns:
            List of transition events emitted this tick. Each event is a dict
            with keys: rule_key, state ('fired'/'resolved'), severity, value,
            threshold. Returns empty list when nothing changed or engine is
            disabled.

        Note:
            Notification delivery failures are logged but never raised to the
            caller. The audit trail is always persisted regardless of delivery
            success. This ensures that alert state transitions are recorded
            even when Telegram is unavailable or misconfigured.
        """
        if not self._enabled:
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
            self._store.record_alert(
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
        """Build a human-readable alert message.

        Args:
            rule_key: The alert rule identifier (e.g., 'power_spike').
            value: The current measured value that triggered the transition.
            threshold: The configured threshold for this rule.
            state: Either 'fired' (threshold exceeded) or 'resolved' (back under).

        Returns:
            A formatted message string suitable for notification delivery,
            including an emoji prefix, the rule label, current value and threshold.
        """
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
        """Best-effort Telegram delivery; never raises into the caller.

        Attempts to send the message via the configured notifier. Failures are
        logged at WARNING level but swallowed to ensure alert processing
        continues even when delivery infrastructure is unavailable.

        Args:
            message: The formatted alert message to send.

        Note:
            This method catches OSError and RuntimeError from the notifier.
            Other exception types would propagate (but TelegramNotifier only
            raises these two categories for network/config issues).
        """
        if self._notifier is None or not getattr(self._notifier, "enabled", False):
            return
        try:
            self._notifier.send(message)
        except (
            OSError,
            RuntimeError,
        ) as exc:  # pragma: no cover - defensive, delivery best-effort
            logger.warning("alert delivery failed: %s", exc)
