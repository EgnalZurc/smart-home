"""Unit tests for the alert engine: threshold logic, anti-flapping and delivery.

The engine is exercised with a real (temp-path) :class:`AlertStore` so the
SQLite persistence / rehydration path is covered, a hand-driven ring buffer so
sustained-window logic is deterministic, and a stub notifier so Telegram calls
are asserted without hitting the network.
"""

from __future__ import annotations

import pytest
from alert_store import AlertStore
from alerts import (
    AlertEngine,
    Comparison,
    Scope,
    Severity,
    Threshold,
    _percentile,
    default_thresholds,
)
from storage import RingBuffer


class StubNotifier:
    """Records every message instead of sending it, so tests can assert on them."""

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self.messages: list[str] = []

    def send(self, message: str, **_kwargs):
        self.messages.append(message)
        return type("R", (), {"success": True})()


@pytest.fixture
def store(tmp_path):
    return AlertStore(str(tmp_path / "alerts.db"))


@pytest.fixture
def ring():
    return RingBuffer(maxlen=240)


def _engine(ring, store, notifier=None, thresholds=None):
    eng = AlertEngine(ring, store, notifier=notifier, thresholds=thresholds)
    eng.load_state()
    return eng


# ── Default threshold set matches the design ──────────────────────────────────
def test_default_thresholds_cover_design_rules():
    rules = default_thresholds()
    assert set(rules) == {
        "host_ram",
        "host_swap",
        "host_temp",
        "host_disk",
        "container_mem",
        "service_online",
        "service_latency",
    }
    assert rules["host_ram"].value == 90.0
    assert rules["host_ram"].severity is Severity.CRITICAL
    assert rules["host_ram"].sustained_s == 300
    assert rules["host_temp"].value == 75.0
    assert rules["host_temp"].critical_value == 80.0
    assert rules["host_disk"].sustained_s == 0
    assert rules["service_online"].count_ticks == 3
    assert rules["service_latency"].aggregate == "p95"


# ── Single-sample threshold (disk) ────────────────────────────────────────────
def test_host_disk_fires_on_single_sample_over_90(ring, store):
    notifier = StubNotifier()
    eng = _engine(ring, store, notifier)
    ring.add("host.disk.percent", "", 92.0, ts=1000)
    outcome = eng.evaluate_tick(now=1000)
    assert len(outcome.fired) == 1
    assert outcome.fired[0].rule_key == "host_disk"
    assert outcome.fired[0].severity is Severity.WARNING
    assert len(notifier.messages) == 1


def test_host_disk_no_fire_under_threshold(ring, store):
    eng = _engine(ring, store, StubNotifier())
    ring.add("host.disk.percent", "", 80.0, ts=1000)
    assert eng.evaluate_tick(now=1000).fired == []


# ── Sustained threshold (RAM over 5 min) ──────────────────────────────────────
def test_host_ram_requires_sustained_breach(ring, store):
    eng = _engine(ring, store, StubNotifier())
    # 300 s window: samples spanning the window all above 90.
    for ts in range(1000, 1301, 30):
        ring.add("host.ram.percent", "", 95.0, ts=ts)
    outcome = eng.evaluate_tick(now=1300)
    assert len(outcome.fired) == 1
    assert outcome.fired[0].rule_key == "host_ram"


def test_host_ram_transient_spike_does_not_fire(ring, store):
    eng = _engine(ring, store, StubNotifier())
    # Most of the window is fine; a dip below threshold resets the sustained check.
    ring.add("host.ram.percent", "", 95.0, ts=1000)
    ring.add("host.ram.percent", "", 50.0, ts=1030)  # dip
    ring.add("host.ram.percent", "", 95.0, ts=1300)
    assert eng.evaluate_tick(now=1300).fired == []


# ── Two-tier severity (temp warn vs critical) ─────────────────────────────────
def _fill_window(ring, metric, value, start=1000, span=120, step=30):
    for ts in range(start, start + span + 1, step):
        ring.add(metric, "", value, ts=ts)


def test_host_temp_warning_between_75_and_80(ring, store):
    eng = _engine(ring, store, StubNotifier())
    _fill_window(ring, "host.temp.celsius", 77.0)
    outcome = eng.evaluate_tick(now=1120)
    assert outcome.fired[0].severity is Severity.WARNING


def test_host_temp_critical_over_80(ring, store):
    eng = _engine(ring, store, StubNotifier())
    _fill_window(ring, "host.temp.celsius", 82.0)
    outcome = eng.evaluate_tick(now=1120)
    assert outcome.fired[0].severity is Severity.CRITICAL


# ── count_ticks (service offline for 3 consecutive ticks) ─────────────────────
def test_service_online_needs_three_consecutive_ticks(ring, store):
    eng = _engine(ring, store, StubNotifier())
    # Tick 1 and 2: offline, no fire yet.
    ring.add("service.ac.online", "ac", 0.0, ts=1000)
    assert eng.evaluate_tick(now=1000).fired == []
    ring.add("service.ac.online", "ac", 0.0, ts=1030)
    assert eng.evaluate_tick(now=1030).fired == []
    # Tick 3: still offline → fire critical.
    ring.add("service.ac.online", "ac", 0.0, ts=1060)
    outcome = eng.evaluate_tick(now=1060)
    assert len(outcome.fired) == 1
    assert outcome.fired[0].severity is Severity.CRITICAL
    assert outcome.fired[0].label == "ac"


def test_service_online_counter_resets_on_recovery(ring, store):
    eng = _engine(ring, store, StubNotifier())
    ring.add("service.ac.online", "ac", 0.0, ts=1000)
    eng.evaluate_tick(now=1000)
    ring.add("service.ac.online", "ac", 0.0, ts=1030)
    eng.evaluate_tick(now=1030)
    # Recovery resets the counter.
    ring.add("service.ac.online", "ac", 1.0, ts=1060)
    eng.evaluate_tick(now=1060)
    # Two more offline ticks should NOT fire yet (needs 3 fresh).
    ring.add("service.ac.online", "ac", 0.0, ts=1090)
    eng.evaluate_tick(now=1090)
    ring.add("service.ac.online", "ac", 0.0, ts=1120)
    assert eng.evaluate_tick(now=1120).fired == []


# ── p95 latency rule ──────────────────────────────────────────────────────────
def test_service_latency_p95_over_3000_fires(ring, store):
    eng = _engine(ring, store, StubNotifier())
    # 18 fast + 2 slow over 20 samples: nearest-rank p95 (index 18 of 0..19)
    # lands on a slow sample, so the p95 exceeds 3000 ms and the rule fires.
    for i in range(18):
        ring.add("service.ac.latency_ms", "ac", 100.0, ts=1000 + i * 30)
    ring.add("service.ac.latency_ms", "ac", 5000.0, ts=1000 + 18 * 30)
    ring.add("service.ac.latency_ms", "ac", 6000.0, ts=1000 + 19 * 30)
    outcome = eng.evaluate_tick(now=1000 + 19 * 30)
    assert len(outcome.fired) == 1
    assert outcome.fired[0].rule_key == "service_latency"


def test_service_latency_single_spike_below_p95_no_fire(ring, store):
    # One slow sample among 19 fast ones: the p95 stays fast, so a transient
    # spike must NOT fire the latency rule (this is the point of using p95).
    eng = _engine(ring, store, StubNotifier())
    for i in range(19):
        ring.add("service.ac.latency_ms", "ac", 100.0, ts=1000 + i * 30)
    ring.add("service.ac.latency_ms", "ac", 9000.0, ts=1000 + 19 * 30)
    assert eng.evaluate_tick(now=1000 + 19 * 30).fired == []


def test_service_latency_p95_under_threshold_no_fire(ring, store):
    eng = _engine(ring, store, StubNotifier())
    for i in range(20):
        ring.add("service.ac.latency_ms", "ac", 100.0, ts=1000 + i * 30)
    assert eng.evaluate_tick(now=1000 + 19 * 30).fired == []


# ── Per-label fan-out (containers) ────────────────────────────────────────────
def test_container_mem_fans_out_per_label(ring, store):
    eng = _engine(ring, store, StubNotifier())
    for ts in range(1000, 1301, 30):
        ring.add("container.mem.percent", "portfolio-monitor", 90.0, ts=ts)
        ring.add("container.mem.percent", "ac-service", 10.0, ts=ts)
    outcome = eng.evaluate_tick(now=1300)
    fired_labels = {a.label for a in outcome.fired}
    assert fired_labels == {"portfolio-monitor"}


# ═══════════════════════════════════════════════════════════════════════════════
# Anti-flapping state machine
# ═══════════════════════════════════════════════════════════════════════════════
def test_fires_once_then_suppresses(ring, store):
    notifier = StubNotifier()
    eng = _engine(ring, store, notifier)
    ring.add("host.disk.percent", "", 95.0, ts=1000)
    first = eng.evaluate_tick(now=1000)
    assert len(first.fired) == 1
    # Still breaching on the next tick → NO new fire (suppressed).
    ring.add("host.disk.percent", "", 96.0, ts=1030)
    second = eng.evaluate_tick(now=1030)
    assert second.fired == []
    assert len(second.active) == 1
    # Only one Telegram message was sent across both ticks.
    assert len(notifier.messages) == 1


def test_sends_resolved_when_condition_clears(ring, store):
    notifier = StubNotifier()
    eng = _engine(ring, store, notifier)
    ring.add("host.disk.percent", "", 95.0, ts=1000)
    eng.evaluate_tick(now=1000)
    # Clears below threshold → one resolved event + message.
    ring.add("host.disk.percent", "", 50.0, ts=1030)
    outcome = eng.evaluate_tick(now=1030)
    assert len(outcome.resolved) == 1
    assert outcome.resolved[0].rule_key == "host_disk"
    assert outcome.active == []
    # Two messages total: one firing, one resolved.
    assert len(notifier.messages) == 2
    assert "RESOLVED" in notifier.messages[1]


def test_can_refire_after_resolution(ring, store):
    notifier = StubNotifier()
    eng = _engine(ring, store, notifier)
    ring.add("host.disk.percent", "", 95.0, ts=1000)
    eng.evaluate_tick(now=1000)
    ring.add("host.disk.percent", "", 50.0, ts=1030)
    eng.evaluate_tick(now=1030)
    # Breach again → fires a second time (new incident).
    ring.add("host.disk.percent", "", 95.0, ts=1060)
    outcome = eng.evaluate_tick(now=1060)
    assert len(outcome.fired) == 1


def test_batches_multiple_breaches_into_one_message(ring, store):
    notifier = StubNotifier()
    eng = _engine(ring, store, notifier)
    ring.add("host.disk.percent", "", 95.0, ts=1000)
    for ts in range(1000, 1301, 30):
        ring.add("host.ram.percent", "", 95.0, ts=ts)
    outcome = eng.evaluate_tick(now=1300)
    assert len(outcome.fired) == 2
    # Both breaches land in a single Telegram message (rate-limit friendly).
    assert len(notifier.messages) == 1
    assert notifier.messages[0].count("\n") == 1


# ── Persistence / restart (anti-spam across restart) ──────────────────────────
def test_active_alerts_persist_across_restart(ring, store, tmp_path):
    notifier = StubNotifier()
    eng = _engine(ring, store, notifier)
    ring.add("host.disk.percent", "", 95.0, ts=1000)
    eng.evaluate_tick(now=1000)
    assert len(notifier.messages) == 1

    # Simulate a restart: a brand-new engine on the SAME store rehydrates the
    # active set and must NOT re-fire the still-breaching alert.
    ring2 = RingBuffer(maxlen=240)
    ring2.add("host.disk.percent", "", 95.0, ts=1030)
    notifier2 = StubNotifier()
    eng2 = _engine(ring2, store, notifier2)
    assert len(eng2.active_alerts()) == 1  # rehydrated
    outcome = eng2.evaluate_tick(now=1030)
    assert outcome.fired == []  # suppressed across restart
    assert notifier2.messages == []


def test_history_records_fired_and_resolved(ring, store):
    eng = _engine(ring, store, StubNotifier())
    ring.add("host.disk.percent", "", 95.0, ts=1000)
    eng.evaluate_tick(now=1000)
    ring.add("host.disk.percent", "", 50.0, ts=1030)
    eng.evaluate_tick(now=1030)
    events = store.history(days=1, now=1030)
    kinds = sorted(e["event"] for e in events)
    assert kinds == ["fired", "resolved"]


# ── Delivery edge cases ───────────────────────────────────────────────────────
def test_no_notifier_does_not_crash(ring, store):
    eng = _engine(ring, store, notifier=None)
    ring.add("host.disk.percent", "", 95.0, ts=1000)
    outcome = eng.evaluate_tick(now=1000)
    assert len(outcome.fired) == 1  # fires + persists even with no notifier


def test_disabled_rule_never_fires(ring, store):
    thresholds = default_thresholds()
    thresholds["host_disk"].enabled = False
    eng = _engine(ring, store, StubNotifier(), thresholds=thresholds)
    ring.add("host.disk.percent", "", 99.0, ts=1000)
    assert eng.evaluate_tick(now=1000).fired == []


# ── Thresholds runtime API ────────────────────────────────────────────────────
def test_set_thresholds_patches_value(ring, store):
    eng = _engine(ring, store, StubNotifier())
    eng.set_thresholds({"host_disk": {"value": 50.0}})
    ring.add("host.disk.percent", "", 60.0, ts=1000)  # above new 50, below old 90
    assert len(eng.evaluate_tick(now=1000).fired) == 1


def test_set_thresholds_unknown_key_raises(ring, store):
    eng = _engine(ring, store, StubNotifier())
    with pytest.raises(KeyError):
        eng.set_thresholds({"nope": {"value": 1}})


def test_set_thresholds_unknown_field_raises(ring, store):
    eng = _engine(ring, store, StubNotifier())
    with pytest.raises(KeyError):
        eng.set_thresholds({"host_disk": {"bogus": 1}})


def test_set_thresholds_converts_enum_fields(ring, store):
    eng = _engine(ring, store, StubNotifier())
    out = eng.set_thresholds(
        {"host_disk": {"comparison": "lt", "severity": "critical"}}
    )
    rule = next(r for r in out if r["key"] == "host_disk")
    assert rule["comparison"] == "lt"
    assert rule["severity"] == "critical"


def test_get_thresholds_serialises_all_rules(ring, store):
    eng = _engine(ring, store, StubNotifier())
    out = eng.get_thresholds()
    assert len(out) == 7
    assert all("key" in r and "value" in r for r in out)


# ── Percentile helper ─────────────────────────────────────────────────────────
def test_percentile_basic():
    assert _percentile([], 95) == 0.0
    assert _percentile([5.0], 95) == 5.0
    vals = [float(i) for i in range(1, 101)]  # 1..100
    assert _percentile(vals, 95) == 95.0  # nearest-rank: round(0.95*99)=94 -> vals[94]


def test_threshold_dataclass_roundtrip():
    t = Threshold(
        key="x",
        metric="m",
        comparison=Comparison.GT,
        value=1.0,
        severity=Severity.WARNING,
        scope=Scope.HOST,
    )
    d = t.to_dict()
    assert d["key"] == "x"
    assert d["comparison"] == "gt"
    assert d["severity"] == "warning"
    assert d["scope"] == "host"
