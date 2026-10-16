"""Unit tests for the energy-monitor consumption alert engine (alerts.py)."""

from __future__ import annotations

import datetime as _dt

import pytest
from alerts import AlertEngine
from database import EnergyStore

# Fixed reference time: 2023-06-15 12:30:00 UTC.
_NOW = 1_686_832_200
_MONTH_START = int(_dt.datetime(2023, 6, 1, tzinfo=_dt.timezone.utc).timestamp())
_DAY = 24 * 3600


class _CapturingNotifier:
    """Stand-in notifier that records sent messages instead of calling Telegram."""

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self.sent: list[str] = []

    def send(self, message: str):
        self.sent.append(message)


@pytest.fixture
def store(tmp_path):
    return EnergyStore(str(tmp_path / "energy.db"))


def test_disabled_engine_is_noop(store):
    engine = AlertEngine(store, enabled=False, notifier=_CapturingNotifier())
    assert engine.evaluate(now=_NOW) == []
    assert store.recent_alerts() == []


def test_power_spike_fires_once(store):
    # Latest sample over the default 3500 W threshold.
    store.write_power(_NOW - 60, [("ch0", 2000.0, 4200.0, 230.0, 0.9)])
    notifier = _CapturingNotifier()
    engine = AlertEngine(store, enabled=True, notifier=notifier)

    events = engine.evaluate(now=_NOW)
    fired = [e for e in events if e["rule_key"] == "power_spike"]
    assert len(fired) == 1
    assert fired[0]["state"] == "fired"
    assert len(notifier.sent) >= 1

    # Second evaluation with the same state emits no new power_spike event.
    events2 = engine.evaluate(now=_NOW)
    assert not [e for e in events2 if e["rule_key"] == "power_spike"]


def test_power_spike_resolves(store):
    store.write_power(_NOW - 120, [("ch0", 2000.0, 4200.0, 230.0, 0.9)])
    notifier = _CapturingNotifier()
    engine = AlertEngine(store, enabled=True, notifier=notifier)
    engine.evaluate(now=_NOW - 60)  # fires

    # New latest sample back under threshold → resolve on next tick.
    store.write_power(_NOW, [("ch0", 1000.0, 500.0, 230.0, 0.9)])
    events = engine.evaluate(now=_NOW + 60)
    resolved = [
        e for e in events if e["rule_key"] == "power_spike" and e["state"] == "resolved"
    ]
    assert len(resolved) == 1
    # Audit trail holds both the fired and resolved events.
    states = {
        a["state"] for a in store.recent_alerts() if a["rule_key"] == "power_spike"
    }
    assert states == {"fired", "resolved"}


def test_monthly_budget_fires_over_threshold(store):
    # Build > 400 kWh month-to-date to cross the default monthly threshold.
    store.write_energy(_MONTH_START, [("ch0", 0.0)])
    store.write_energy(_MONTH_START + _DAY, [("ch0", 450_000.0)])  # 450 kWh
    engine = AlertEngine(store, enabled=True, notifier=_CapturingNotifier())
    events = engine.evaluate(now=_NOW)
    monthly = [e for e in events if e["rule_key"] == "monthly_budget"]
    assert monthly and monthly[0]["state"] == "fired"
    assert monthly[0]["severity"] == "critical"


def test_under_threshold_first_observation_is_silent(store):
    # Readings well under budget: first evaluation must NOT emit a resolved event.
    store.write_energy(_MONTH_START, [("ch0", 0.0)])
    store.write_energy(_MONTH_START + _DAY, [("ch0", 1000.0)])  # 1 kWh
    engine = AlertEngine(store, enabled=True, notifier=_CapturingNotifier())
    events = engine.evaluate(now=_NOW)
    assert not [e for e in events if e["state"] == "resolved"]


def test_delivery_skipped_when_notifier_disabled(store):
    store.write_power(_NOW, [("ch0", 2000.0, 4200.0, 230.0, 0.9)])
    notifier = _CapturingNotifier(enabled=False)
    engine = AlertEngine(store, enabled=True, notifier=notifier)
    engine.evaluate(now=_NOW)
    # Event still persisted, but nothing sent.
    assert store.recent_alerts()
    assert notifier.sent == []
