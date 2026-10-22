"""Alert engine: threshold evaluation, anti-flapping state and Telegram delivery.

Runs once per collector tick (design §7.3). For each configured rule it looks at
the hi-resolution ring buffer, decides whether the rule is *breaching* right now
(optionally requiring the breach to be *sustained* over a window), and drives a
small per-alert state machine:

    (no alert) ──breach sustained──▶ ACTIVE  ──fires one Telegram "firing" msg
       ▲                                │
       └────────── clears ──────────────┘  ──fires one Telegram "resolved" msg

Anti-flapping (design §7.3): an alert fires exactly once when it becomes active
and stays suppressed until the condition clears, at which point a single
"resolved" message is sent. The active set is persisted to an ``alerts`` SQLite
table so a service restart does not re-spam already-firing alerts.

Thresholds are runtime-tunable (``GET/PUT /api/metrics/thresholds``); the engine
holds the live set in memory and callers mutate it through :meth:`set_thresholds`.
All Telegram breaches in one tick are batched into a single message to respect
Telegram rate limits.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum

from storage import RingBuffer

logger = logging.getLogger(__name__)


class Severity(str, Enum):
    """Alert severity levels (ordered: critical escalates over warning)."""

    WARNING = "warning"
    CRITICAL = "critical"


class Comparison(str, Enum):
    """How a metric value is compared against a rule threshold."""

    GT = "gt"  # value > threshold is a breach
    LT = "lt"  # value < threshold is a breach


# How a rule maps onto one or more ring-buffer series.
#   HOST     — a single host series (label is always "").
#   PER_LABEL — one series per discovered label (every container / service key)
#               matching the metric; each label is evaluated independently.
class Scope(str, Enum):
    """Whether a rule targets one host series or fans out over labels."""

    HOST = "host"
    PER_LABEL = "per_label"


@dataclass
class Threshold:
    """One alert rule.

    Attributes:
        key: Stable rule identifier (used as the alert fingerprint prefix and the
            key in the thresholds API payload).
        metric: Ring-buffer metric name to evaluate. For ``PER_LABEL`` rules this
            is a *template* with ``{label}`` substituted per series key, because
            service metrics embed the key in the metric name
            (``service.<key>.latency_ms``); for host/container rules it is a plain
            metric name.
        comparison: ``gt`` or ``lt``.
        value: Threshold value for the (first) severity.
        severity: Severity when ``value`` is breached.
        sustained_s: The breach must hold for at least this many seconds of the
            most recent samples (0 = a single sample suffices).
        scope: ``host`` (single series) or ``per_label`` (one per label).
        critical_value: Optional second, higher threshold that escalates to
            CRITICAL (used by the temp rule: warn >75 °C, critical >80 °C).
        aggregate: ``last`` evaluates the latest sample; ``p95`` evaluates the
            95th percentile over the window (used by latency).
        count_ticks: If set, require this many *consecutive* breaching samples
            instead of a time window (used by ``service online == 0`` → 3 ticks).
        enabled: Whether the rule is active.
        unit: Human-readable unit for alert messages.
    """

    key: str
    metric: str
    comparison: Comparison
    value: float
    severity: Severity
    sustained_s: int = 0
    scope: Scope = Scope.HOST
    critical_value: float | None = None
    aggregate: str = "last"  # "last" | "p95"
    count_ticks: int | None = None
    enabled: bool = True
    unit: str = ""

    def to_dict(self) -> dict:
        """Serialise for the thresholds API."""
        return {
            "key": self.key,
            "metric": self.metric,
            "comparison": self.comparison.value,
            "value": self.value,
            "severity": self.severity.value,
            "sustained_s": self.sustained_s,
            "scope": self.scope.value,
            "critical_value": self.critical_value,
            "aggregate": self.aggregate,
            "count_ticks": self.count_ticks,
            "enabled": self.enabled,
            "unit": self.unit,
        }


# ── Default thresholds (design §7.3) ──────────────────────────────────────────
def default_thresholds() -> dict[str, Threshold]:
    """Return the default rule set keyed by rule id (design §7.3)."""
    rules = [
        Threshold(
            key="host_ram",
            metric="host.ram.percent",
            comparison=Comparison.GT,
            value=90.0,
            severity=Severity.CRITICAL,
            sustained_s=300,
            scope=Scope.HOST,
            unit="%",
        ),
        Threshold(
            key="host_swap",
            metric="host.swap.used_mb",
            comparison=Comparison.GT,
            value=500.0,
            severity=Severity.WARNING,
            sustained_s=300,
            scope=Scope.HOST,
            unit="MB",
        ),
        Threshold(
            key="host_temp",
            metric="host.temp.celsius",
            comparison=Comparison.GT,
            value=75.0,
            severity=Severity.WARNING,
            sustained_s=120,
            scope=Scope.HOST,
            critical_value=80.0,
            unit="°C",
        ),
        Threshold(
            key="host_disk",
            metric="host.disk.percent",
            comparison=Comparison.GT,
            value=90.0,
            severity=Severity.WARNING,
            sustained_s=0,  # single sample
            scope=Scope.HOST,
            unit="%",
        ),
        Threshold(
            key="container_mem",
            metric="container.mem.percent",
            comparison=Comparison.GT,
            value=85.0,
            severity=Severity.WARNING,
            sustained_s=300,
            scope=Scope.PER_LABEL,
            unit="%",
        ),
        Threshold(
            key="service_online",
            metric="service.{label}.online",
            comparison=Comparison.LT,
            value=1.0,  # online < 1 → offline
            severity=Severity.CRITICAL,
            scope=Scope.PER_LABEL,
            # 5 ticks × 30s = 150s grace period; tolerates typical deploy restarts
            # (~30-60s) without false alarms while still catching real outages.
            count_ticks=5,
            unit="",
        ),
        Threshold(
            key="service_latency",
            metric="service.{label}.latency_ms",
            comparison=Comparison.GT,
            value=10000.0,
            severity=Severity.WARNING,
            sustained_s=600,
            scope=Scope.PER_LABEL,
            aggregate="p95",
            unit="ms",
        ),
    ]
    return {r.key: r for r in rules}


# ── Alert state ────────────────────────────────────────────────────────────────
@dataclass
class ActiveAlert:
    """A currently-firing alert (one row of the ``alerts`` table)."""

    fingerprint: str
    rule_key: str
    label: str
    severity: Severity
    value: float
    message: str
    fired_at: int
    resolved_at: int | None = None


@dataclass
class EvalResult:
    """Outcome of evaluating one rule against one series."""

    breaching: bool
    severity: Severity | None = None
    value: float | None = None


@dataclass
class TickOutcome:
    """What the engine did this tick (returned for tests / the API)."""

    fired: list[ActiveAlert] = field(default_factory=list)
    resolved: list[ActiveAlert] = field(default_factory=list)
    active: list[ActiveAlert] = field(default_factory=list)


def _percentile(values: list[float], pct: float) -> float:
    """Return the ``pct`` percentile (0–100) of ``values`` (nearest-rank)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, int(round((pct / 100.0) * (len(ordered) - 1)))))
    return ordered[k]


class AlertEngine:
    """Evaluates thresholds each tick and drives Telegram alerts with anti-flap.

    The engine is deliberately decoupled from I/O: the ring buffer and store are
    injected, and the notifier is any object with a ``send(message) -> result``
    method (``libs.notifications.TelegramNotifier``), so tests pass a stub.
    """

    def __init__(
        self,
        ring: RingBuffer,
        store,  # AlertStore (duck-typed to avoid an import cycle in tests)
        notifier=None,
        thresholds: dict[str, Threshold] | None = None,
    ) -> None:
        self.ring = ring
        self.store = store
        self.notifier = notifier
        self.thresholds = thresholds if thresholds is not None else default_thresholds()
        # In-memory mirror of the persisted active set, keyed by fingerprint.
        self._active: dict[str, ActiveAlert] = {}
        # Consecutive-breach tick counters for count_ticks rules.
        self._tick_counts: dict[str, int] = {}
        self._loaded = False

    # ── Persistence bootstrap ────────────────────────────────────────────────
    def load_state(self) -> None:
        """Rehydrate the active-alert set from SQLite (called once at startup)."""
        self._active = {a.fingerprint: a for a in self.store.load_active()}
        self._loaded = True
        logger.info("AlertEngine loaded %d active alert(s)", len(self._active))

    # ── Thresholds API ────────────────────────────────────────────────────────
    def get_thresholds(self) -> list[dict]:
        """Return the current rule set serialised for the API."""
        return [t.to_dict() for t in self.thresholds.values()]

    def set_thresholds(self, updates: dict[str, dict]) -> list[dict]:
        """Patch thresholds at runtime.

        ``updates`` maps a rule key to a dict of fields to override (``value``,
        ``critical_value``, ``sustained_s``, ``enabled``, ``comparison``,
        ``severity``). Unknown keys are ignored; unknown fields raise ``KeyError``
        via the dataclass so callers get a clear 400.
        """
        for key, patch in updates.items():
            rule = self.thresholds.get(key)
            if rule is None:
                raise KeyError(f"unknown threshold key: {key}")
            for field_name, new in patch.items():
                if field_name not in rule.__dataclass_fields__:
                    raise KeyError(f"unknown field '{field_name}' for rule '{key}'")
                if field_name == "comparison":
                    new = Comparison(new)
                elif field_name == "severity":
                    new = Severity(new)
                setattr(rule, field_name, new)
        return self.get_thresholds()

    # ── Evaluation ──────────────────────────────────────────────────────────────
    def _series_values(
        self, metric: str, label: str, window_s: int, now: int
    ) -> list[float]:
        """Return values for a series over the trailing ``window_s`` seconds."""
        since = now - window_s if window_s > 0 else None
        points = self.ring.series(metric, label, since=since)
        return [v for (_, v) in points]

    @staticmethod
    def _breaches(value: float, comparison: Comparison, threshold: float) -> bool:
        if comparison is Comparison.GT:
            return value > threshold
        return value < threshold

    def _evaluate(self, rule: Threshold, label: str, now: int) -> EvalResult:
        """Evaluate one rule for one concrete label."""
        metric = (
            rule.metric.format(label=label) if "{label}" in rule.metric else rule.metric
        )

        # count_ticks rules: require N consecutive breaching latest samples.
        if rule.count_ticks is not None:
            latest = self.ring.series(metric, label)
            if not latest:
                return EvalResult(breaching=False)
            value = latest[-1][1]
            breach = self._breaches(value, rule.comparison, rule.value)
            counter_key = f"{rule.key}:{label}"
            if breach:
                self._tick_counts[counter_key] = (
                    self._tick_counts.get(counter_key, 0) + 1
                )
            else:
                self._tick_counts.pop(counter_key, None)
            if self._tick_counts.get(counter_key, 0) >= rule.count_ticks:
                return EvalResult(True, rule.severity, value)
            return EvalResult(breaching=False)

        values = self._series_values(metric, label, rule.sustained_s, now)
        if not values:
            return EvalResult(breaching=False)

        if rule.aggregate == "p95":
            # The breach is on the p95 over the whole window — one representative
            # number, not a per-sample sustained check.
            agg = _percentile(values, 95.0)
            if self._breaches(agg, rule.comparison, rule.value):
                return EvalResult(True, rule.severity, round(agg, 1))
            return EvalResult(breaching=False)

        # "last"/sustained: EVERY sample in the window must breach, so a transient
        # dip below threshold resets the sustained condition.
        latest_value = values[-1]
        if rule.sustained_s > 0:
            all_breach = all(
                self._breaches(v, rule.comparison, rule.value) for v in values
            )
            if not all_breach:
                return EvalResult(breaching=False)
        else:
            if not self._breaches(latest_value, rule.comparison, rule.value):
                return EvalResult(breaching=False)

        # Determine severity (two-tier escalation for temp-style rules).
        severity = rule.severity
        if rule.critical_value is not None and self._breaches(
            latest_value, rule.comparison, rule.critical_value
        ):
            severity = Severity.CRITICAL
        return EvalResult(True, severity, latest_value)

    def _labels_for(self, rule: Threshold) -> list[str]:
        """Discover the concrete labels a PER_LABEL rule applies to."""
        if rule.scope is Scope.HOST:
            return [""]
        labels: set[str] = set()
        if "{label}" in rule.metric:
            # Service metrics embed the key in the metric name; match on the
            # metric prefix/suffix around the placeholder.
            prefix, suffix = rule.metric.split("{label}", 1)
            # ring.keys() is RingBuffer's own method returning (metric, label)
            # tuples — not a dict, so SIM118 ("key in dict.keys()") is a false
            # positive here.
            for metric_name, label in self.ring.keys():  # noqa: SIM118
                if metric_name.startswith(prefix) and metric_name.endswith(suffix):
                    labels.add(label)
        else:
            # Container metrics share one metric name across labels.
            for metric_name, label in self.ring.keys():  # noqa: SIM118
                if metric_name == rule.metric and label:
                    labels.add(label)
        return sorted(labels)

    # ── Message formatting ────────────────────────────────────────────────────

    # Human-readable descriptions for rule keys (used in alert messages).
    # Maps rule_key -> (firing_template, resolved_template).
    # Templates use {target}, {value}, {unit}, {threshold} placeholders.
    RULE_DESCRIPTIONS: dict[str, tuple[str, str]] = {
        "host_ram": (
            "Uso de RAM en {value}{unit} (máx {threshold}{unit})",
            "Uso de RAM normalizado",
        ),
        "host_swap": (
            "Uso de swap en {value}{unit} (máx {threshold}{unit})",
            "Uso de swap normalizado",
        ),
        "host_temp": (
            "Temperatura en {value}{unit} (máx {threshold}{unit})",
            "Temperatura normalizada",
        ),
        "host_disk": (
            "Disco al {value}{unit} (máx {threshold}{unit})",
            "Espacio en disco normalizado",
        ),
        "container_mem": (
            "Contenedor *{target}* usando {value}{unit} de memoria (máx {threshold}{unit})",
            "Contenedor *{target}*: memoria normalizada",
        ),
        "service_online": (
            "Servicio *{target}* no responde",
            "Servicio *{target}* vuelve a responder",
        ),
        "service_latency": (
            "Servicio *{target}* lento: {value}{unit} (máx {threshold}{unit})",
            "Servicio *{target}* responde con normalidad",
        ),
    }

    @staticmethod
    def _emoji(severity: Severity) -> str:
        return "🔴" if severity is Severity.CRITICAL else "🟠"

    def _format_firing(self, rule: Threshold, label: str, result: EvalResult) -> str:
        target = label or "host"
        templates = self.RULE_DESCRIPTIONS.get(rule.key)
        if templates:
            description = templates[0].format(
                target=target,
                value=result.value,
                unit=rule.unit,
                threshold=rule.value,
            )
        else:
            # Fallback for unknown rules
            name = rule.key.replace("_", " ")
            description = (
                f"{name} ({target}): {result.value}{rule.unit} "
                f"(umbral {rule.value}{rule.unit})"
            )
        return f"{self._emoji(result.severity)} *{result.severity.value.upper()}* — {description}"

    def _format_resolved(self, alert: ActiveAlert) -> str:
        target = alert.label or "host"
        templates = self.RULE_DESCRIPTIONS.get(alert.rule_key)
        if templates:
            description = templates[1].format(target=target)
        else:
            # Fallback for unknown rules
            name = alert.rule_key.replace("_", " ")
            description = f"{name} ({target})"
        return f"✅ *RESOLVED* — {description}"

    # ── Main tick ─────────────────────────────────────────────────────────────
    def evaluate_tick(self, now: int | None = None) -> TickOutcome:
        """Evaluate all rules, update state, and send one batched Telegram message.

        Returns a :class:`TickOutcome` describing what fired/resolved this tick.
        """
        if not self._loaded:
            self.load_state()
        now = int(time.time()) if now is None else now
        outcome = TickOutcome()

        # Fingerprints that breach this tick — anything active and NOT in here
        # has cleared and must be resolved.
        breaching_now: set[str] = set()

        for rule in self.thresholds.values():
            if not rule.enabled:
                continue
            for label in self._labels_for(rule):
                result = self._evaluate(rule, label, now)
                fingerprint = f"{rule.key}:{label}"
                if not result.breaching:
                    continue
                breaching_now.add(fingerprint)
                existing = self._active.get(fingerprint)
                if existing is None:
                    # New breach → fire.
                    alert = ActiveAlert(
                        fingerprint=fingerprint,
                        rule_key=rule.key,
                        label=label,
                        severity=result.severity,
                        value=result.value if result.value is not None else 0.0,
                        message=self._format_firing(rule, label, result),
                        fired_at=now,
                    )
                    self._active[fingerprint] = alert
                    self.store.upsert_active(alert)
                    self.store.record_history(alert, event="fired", ts=now)
                    outcome.fired.append(alert)
                else:
                    # Already active → suppress (anti-flap). Keep latest value.
                    existing.value = (
                        result.value if result.value is not None else existing.value
                    )

        # Resolve any active alert whose condition no longer breaches.
        for fingerprint, alert in list(self._active.items()):
            if fingerprint not in breaching_now:
                alert.resolved_at = now
                self.store.resolve_active(fingerprint, now)
                self.store.record_history(alert, event="resolved", ts=now)
                outcome.resolved.append(alert)
                del self._active[fingerprint]
                self._tick_counts.pop(fingerprint, None)

        outcome.active = list(self._active.values())
        self._notify(outcome)
        return outcome

    # ── Delivery ──────────────────────────────────────────────────────────────
    def _notify(self, outcome: TickOutcome) -> None:
        """Batch all fired/resolved alerts this tick into one Telegram message."""
        if self.notifier is None:
            return
        if not outcome.fired and not outcome.resolved:
            return
        lines: list[str] = []
        for alert in outcome.fired:
            lines.append(alert.message)
        for alert in outcome.resolved:
            lines.append(self._format_resolved(alert))
        message = "\n".join(lines)
        try:
            self.notifier.send(message)
        except Exception:  # pragma: no cover  # noqa: BLE001 - notifier is best-effort
            logger.exception("Telegram alert delivery failed")

    # ── Read helpers for the API ────────────────────────────────────────────────

    # Plain-text descriptions for dashboard titles (no markdown).
    RULE_TITLES: dict[str, tuple[str, str]] = {
        "host_ram": ("RAM: {value}{unit}", "host"),
        "host_swap": ("Swap: {value}{unit}", "host"),
        "host_temp": ("Temperatura: {value}{unit}", "host"),
        "host_disk": ("Disco: {value}{unit}", "host"),
        "container_mem": ("{target}: {value}{unit} memoria", "container"),
        "service_online": ("{target} no responde", "service"),
        "service_latency": ("{target} lento: {value}{unit}", "service"),
    }

    def _alert_title(self, alert: ActiveAlert) -> str:
        """Generate a human-readable title for the unified alerts dashboard.

        Unlike ``message`` (formatted for Telegram with emoji/bold), this is a
        plain-text summary suitable for UI display.
        """
        rule = self.thresholds.get(alert.rule_key)
        target = alert.label or "host"
        unit = rule.unit if rule else ""
        title_info = self.RULE_TITLES.get(alert.rule_key)
        if title_info:
            template, _ = title_info
            return template.format(target=target, value=alert.value, unit=unit)
        # Fallback for unknown rules
        name = alert.rule_key.replace("_", " ").title()
        return f"{name} ({target}): {alert.value}{unit}"

    def dismiss_alert(self, fingerprint: str) -> bool:
        """Manually dismiss an active alert by fingerprint.

        This resolves the alert as if the condition cleared, recording a
        'dismissed' event in the history. The alert will re-fire on the next
        tick if the condition still breaches.

        Returns True if the alert was found and dismissed, False otherwise.
        """
        import time

        alert = self._active.get(fingerprint)
        if alert is None:
            return False

        now = int(time.time())
        alert.resolved_at = now
        self.store.resolve_active(fingerprint, now)
        self.store.record_history(alert, event="dismissed", ts=now)
        del self._active[fingerprint]
        self._tick_counts.pop(fingerprint, None)

        logger.info("Alert %s dismissed manually", fingerprint)
        return True

    def active_alerts(self) -> list[dict]:
        """Return currently-firing alerts for ``GET /api/metrics/alerts``."""
        from datetime import datetime, timezone

        return [
            {
                "fingerprint": a.fingerprint,
                "rule_key": a.rule_key,
                "label": a.label,
                "severity": a.severity.value,
                "value": a.value,
                "message": a.message,
                "fired_at": a.fired_at,
                # Fields expected by the dashboard's unified alerts renderer:
                "title": self._alert_title(a),
                "timestamp": datetime.fromtimestamp(
                    a.fired_at, tz=timezone.utc
                ).isoformat(),
            }
            for a in self._active.values()
        ]
