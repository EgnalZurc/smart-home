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


# ══════════════════════════════════════════════════════════════════════════════
# Threshold edge case tests (audit fix 2026-10-23)
# ══════════════════════════════════════════════════════════════════════════════
class TestThresholdEdgeCases:
    """Tests for exact threshold boundary conditions."""

    def test_power_exactly_at_threshold_does_not_fire(self, store):
        """Power exactly equal to threshold should not fire (> not >=)."""
        # Default POWER_ALERT_W is 3500, so 3500 exactly should NOT fire.
        store.write_power(_NOW, [("ch0", 2000.0, 3500.0, 230.0, 0.9)])
        notifier = _CapturingNotifier()
        engine = AlertEngine(store, enabled=True, notifier=notifier)
        events = engine.evaluate(now=_NOW)
        power_events = [e for e in events if e["rule_key"] == "power_spike"]
        assert len(power_events) == 0
        assert notifier.sent == []

    def test_power_one_watt_over_threshold_fires(self, store):
        """Power just 1W over threshold should fire."""
        store.write_power(_NOW, [("ch0", 2000.0, 3501.0, 230.0, 0.9)])
        notifier = _CapturingNotifier()
        engine = AlertEngine(store, enabled=True, notifier=notifier)
        events = engine.evaluate(now=_NOW)
        power_events = [e for e in events if e["rule_key"] == "power_spike"]
        assert len(power_events) == 1
        assert power_events[0]["state"] == "fired"

    def test_daily_exactly_at_threshold_does_not_fire(self, store):
        """Daily consumption exactly at threshold should not fire."""
        # Set up exactly 20 kWh (default DAILY_KWH_ALERT)
        day_start = _NOW - (_NOW % _DAY)
        store.write_energy(day_start, [("ch0", 0.0)])
        store.write_energy(_NOW, [("ch0", 20_000.0)])  # 20 kWh
        notifier = _CapturingNotifier()
        engine = AlertEngine(store, enabled=True, notifier=notifier)
        events = engine.evaluate(now=_NOW)
        daily_events = [e for e in events if e["rule_key"] == "daily_budget"]
        assert len(daily_events) == 0

    def test_monthly_exactly_at_threshold_does_not_fire(self, store):
        """Monthly consumption exactly at threshold should not fire."""
        # Set up exactly 400 kWh (default MONTHLY_KWH_ALERT)
        store.write_energy(_MONTH_START, [("ch0", 0.0)])
        store.write_energy(_NOW, [("ch0", 400_000.0)])  # 400 kWh
        notifier = _CapturingNotifier()
        engine = AlertEngine(store, enabled=True, notifier=notifier)
        events = engine.evaluate(now=_NOW)
        monthly_events = [e for e in events if e["rule_key"] == "monthly_budget"]
        assert len(monthly_events) == 0

    def test_rapid_oscillation_around_threshold(self, store):
        """Rapid oscillation around threshold fires and resolves correctly."""
        notifier = _CapturingNotifier()
        engine = AlertEngine(store, enabled=True, notifier=notifier)

        # First: over threshold -> fires
        store.write_power(_NOW, [("ch0", 2000.0, 3600.0, 230.0, 0.9)])
        events1 = engine.evaluate(now=_NOW)
        assert any(e["state"] == "fired" for e in events1)

        # Second: under threshold -> resolves
        store.write_power(_NOW + 60, [("ch0", 2000.0, 3400.0, 230.0, 0.9)])
        events2 = engine.evaluate(now=_NOW + 60)
        assert any(e["state"] == "resolved" for e in events2)

        # Third: over again -> fires again
        store.write_power(_NOW + 120, [("ch0", 2000.0, 3600.0, 230.0, 0.9)])
        events3 = engine.evaluate(now=_NOW + 120)
        assert any(e["state"] == "fired" for e in events3)

        # Total events in audit trail should be 3
        all_power = [a for a in store.recent_alerts() if a["rule_key"] == "power_spike"]
        assert len(all_power) == 3


# ══════════════════════════════════════════════════════════════════════════════
# Defensive branch coverage (LOW severity audit findings)
# ══════════════════════════════════════════════════════════════════════════════


class TestAlertDeliveryFailure:
    """LOW#5: Alert delivery failure is logged but doesn't raise (alerts.py:234-239)."""

    def test_delivery_oserror_swallowed(self, store, caplog):
        """OSError during delivery is logged but alert still persisted."""
        import logging

        class FailingNotifier:
            enabled = True

            def send(self, message: str):
                raise OSError("network unreachable")

        store.write_power(_NOW, [("ch0", 2000.0, 4200.0, 230.0, 0.9)])
        engine = AlertEngine(store, enabled=True, notifier=FailingNotifier())

        with caplog.at_level(logging.WARNING):
            events = engine.evaluate(now=_NOW)

        # Alert still fires and is persisted despite delivery failure
        assert len(events) == 1
        assert events[0]["state"] == "fired"
        assert store.recent_alerts()  # Alert was persisted
        assert any("alert delivery failed" in r.message for r in caplog.records)

    def test_delivery_runtimeerror_swallowed(self, store, caplog):
        """RuntimeError during delivery is logged but alert still persisted."""
        import logging

        class FailingNotifier:
            enabled = True

            def send(self, message: str):
                raise RuntimeError("telegram bot token invalid")

        store.write_power(_NOW, [("ch0", 2000.0, 4200.0, 230.0, 0.9)])
        engine = AlertEngine(store, enabled=True, notifier=FailingNotifier())

        with caplog.at_level(logging.WARNING):
            events = engine.evaluate(now=_NOW)

        # Alert still fires and is persisted despite delivery failure
        assert len(events) == 1
        assert store.recent_alerts()
        assert any("alert delivery failed" in r.message for r in caplog.records)
