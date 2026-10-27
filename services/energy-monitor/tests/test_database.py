"""Unit tests for the energy-monitor SQLite store (database.py)."""

from __future__ import annotations

import pytest
from database import EnergyStore


@pytest.fixture
def store(tmp_path):
    return EnergyStore(str(tmp_path / "energy.db"))


def test_write_power_and_count(store):
    n = store.write_power(
        1000,
        [("ch0", 1200.0, 1800.0, 230.0, 0.95), ("ch1", 600.0, 900.0, 230.0, 0.98)],
    )
    assert n == 2
    assert store.count() == 2


def test_write_power_empty_is_noop(store):
    assert store.write_power(1000, []) == 0
    assert store.count() == 0


def test_write_power_replace_on_conflict(store):
    store.write_power(1000, [("ch0", 100.0, 110.0, 230.0, 0.9)])
    store.write_power(1000, [("ch0", 500.0, 900.0, 231.0, 0.92)])  # same (ts, ch)
    rows = store.power_series("ch0")
    assert len(rows) == 1
    assert rows[0]["power_avg"] == 500.0
    assert rows[0]["power_max"] == 900.0


def test_power_series_time_range_and_order(store):
    for ts in (3000, 1000, 2000):
        store.write_power(ts, [("ch0", float(ts), float(ts), None, None)])
    rows = store.power_series("ch0", since=1500, until=3000)
    assert [r["ts"] for r in rows] == [2000, 3000]


def test_power_series_channel_isolation(store):
    store.write_power(1000, [("ch0", 40.0, 50.0, None, None)])
    store.write_power(1000, [("ch1", 80.0, 90.0, None, None)])
    rows = store.power_series("ch0")
    assert len(rows) == 1
    assert rows[0]["power_avg"] == 40.0


def test_write_energy_and_series(store):
    store.write_energy(3600, [("ch0", 123456.0)])
    store.write_energy(7200, [("ch0", 124000.0)])
    rows = store.energy_series("ch0")
    assert [r["energy_wh"] for r in rows] == [123456.0, 124000.0]


def test_write_energy_empty_is_noop(store):
    assert store.write_energy(1000, []) == 0


def test_energy_series_time_range(store):
    store.write_energy(1000, [("ch0", 10.0)])
    store.write_energy(5000, [("ch0", 50.0)])
    rows = store.energy_series("ch0", since=3000)
    assert len(rows) == 1
    assert rows[0]["energy_wh"] == 50.0


def test_count_combines_both_tables(store):
    store.write_power(1000, [("ch0", 1.0, 1.0, None, None)])
    store.write_energy(1000, [("ch0", 100.0)])
    assert store.count() == 2


def test_prune_deletes_old_power_rows(store):
    now = 100_000_000
    old = now - 100 * 24 * 3600  # beyond 90-day power retention
    recent = now - 5 * 24 * 3600
    store.write_power(old, [("ch0", 1.0, 1.0, None, None)])
    store.write_power(recent, [("ch0", 2.0, 2.0, None, None)])
    deleted = store.prune(now=now)
    assert deleted["power_samples"] == 1
    rows = store.power_series("ch0")
    assert [r["ts"] for r in rows] == [recent]


def test_prune_keeps_energy_within_three_years(store):
    now = 100_000_000
    # 200 days old: past 90-day power retention, well within 1095-day energy.
    old = now - 200 * 24 * 3600
    store.write_energy(old, [("ch0", 500.0)])
    deleted = store.prune(now=now)
    assert deleted["energy_readings"] == 0
    assert len(store.energy_series("ch0")) == 1


def test_prune_deletes_very_old_energy_rows(store):
    now = 200_000_000
    old = now - 1200 * 24 * 3600  # beyond 1095-day energy retention
    store.write_energy(old, [("ch0", 10.0)])
    deleted = store.prune(now=now)
    assert deleted["energy_readings"] == 1


def test_prune_nothing_to_delete(store):
    now = 100_000_000
    store.write_power(now - 3600, [("ch0", 1.0, 1.0, None, None)])
    store.write_energy(now - 3600, [("ch0", 1.0)])
    deleted = store.prune(now=now)
    assert deleted == {
        "power_samples": 0,
        "energy_readings": 0,
        "energy_alerts": 0,
    }


# ── Aggregation / consumption-by-period ───────────────────────────────────────
# Fixed reference time: 2023-06-15 12:30:00 UTC (a Thursday).
_NOW = 1_686_832_200


def test_consumption_by_period_invalid_period(store):
    import pytest

    with pytest.raises(ValueError):
        store.consumption_by_period("fortnight", 3, now=_NOW)


def test_consumption_hourly_deltas(store):
    # Three hourly cumulative snapshots on one channel; deltas should be 100/150.
    hour = 3600
    base = _NOW - 3 * hour
    # Align readings to the top of each hour window.
    store.write_energy(base, [("ch0", 1000.0)])
    store.write_energy(base + hour, [("ch0", 1100.0)])
    store.write_energy(base + 2 * hour, [("ch0", 1250.0)])
    series = store.consumption_by_period("hour", 4, channel="ch0", now=_NOW)
    assert len(series) == 4
    assert all(s["period"] == "hour" for s in series)
    # Oldest → newest ordering.
    starts = [s["period_start"] for s in series]
    assert starts == sorted(starts)
    # The buckets with two bounding readings carry the deltas.
    deltas = [s["consumption_wh"] for s in series]
    assert 100.0 in deltas and 150.0 in deltas


def test_consumption_kwh_conversion(store):
    store.write_energy(_NOW - 7200, [("ch0", 0.0)])
    store.write_energy(_NOW - 3600, [("ch0", 2000.0)])
    series = store.consumption_by_period("hour", 3, channel="ch0", now=_NOW)
    with_data = [s for s in series if s["consumption_kwh"] is not None]
    assert any(abs(s["consumption_kwh"] - 2.0) < 1e-6 for s in with_data)


def test_consumption_none_when_no_data(store):
    series = store.consumption_by_period("day", 3, channel="ch0", now=_NOW)
    assert len(series) == 3
    assert all(s["consumption_wh"] is None for s in series)


def test_consumption_count_clamped(store):
    series = store.consumption_by_period("hour", 0, now=_NOW)
    assert len(series) == 1  # clamped to minimum of 1


def test_consumption_whole_home_sums_channels(store):
    # Two channels, each +500 Wh across one hour → whole-home delta 1000 Wh.
    base = _NOW - 3600
    store.write_energy(base, [("ch0", 100.0), ("ch1", 200.0)])
    store.write_energy(_NOW, [("ch0", 600.0), ("ch1", 700.0)])
    series = store.consumption_by_period("hour", 2, now=_NOW)  # channel=None
    totals = [s["consumption_wh"] for s in series if s["consumption_wh"] is not None]
    assert 1000.0 in totals


def test_consumption_monthly_period(store):
    series = store.consumption_by_period("month", 3, now=_NOW)
    assert len(series) == 3
    assert all(s["period"] == "month" for s in series)
    starts = [s["period_start"] for s in series]
    assert starts == sorted(starts)


def test_consumption_weekly_period_starts_monday(store):
    import datetime as _dt

    series = store.consumption_by_period("week", 2, now=_NOW)
    for s in series:
        dt = _dt.datetime.fromtimestamp(s["period_start"], tz=_dt.timezone.utc)
        assert dt.weekday() == 0  # Monday
        assert (dt.hour, dt.minute, dt.second) == (0, 0, 0)


# ── Stats ─────────────────────────────────────────────────────────────────────
def test_stats_empty(store):
    s = store.stats(now=_NOW)
    assert s["total_kwh"] is None
    assert s["avg_daily_kwh"] is None
    assert s["peak_daily_kwh"] is None
    assert s["peak_power_w"] is None
    assert s["days_elapsed"] == 15  # 2023-06-15


def test_stats_total_and_peak(store):
    import datetime as _dt

    month_start = int(_dt.datetime(2023, 6, 1, tzinfo=_dt.timezone.utc).timestamp())
    day = 24 * 3600
    # Daily cumulative readings: +5 kWh day 1, +8 kWh day 2, +3 kWh day 3.
    store.write_energy(month_start, [("ch0", 0.0)])
    store.write_energy(month_start + day, [("ch0", 5000.0)])
    store.write_energy(month_start + 2 * day, [("ch0", 13000.0)])
    store.write_energy(month_start + 3 * day, [("ch0", 16000.0)])
    # A power spike this month.
    store.write_power(month_start + day, [("ch0", 1200.0, 4100.0, 230.0, 0.9)])
    s = store.stats(now=_NOW)
    assert s["total_kwh"] is not None and s["total_kwh"] > 0
    assert s["peak_daily_kwh"] is not None
    assert s["peak_power_w"] == 4100.0


# ── Alerts persistence ────────────────────────────────────────────────────────
def test_record_and_read_alert(store):
    rid = store.record_alert(
        "daily_budget",
        "warning",
        "fired",
        value=22.5,
        message="over budget",
        ts=_NOW,
    )
    assert rid >= 1
    events = store.recent_alerts()
    assert len(events) == 1
    assert events[0]["rule_key"] == "daily_budget"
    assert events[0]["state"] == "fired"
    assert events[0]["value"] == 22.5


def test_recent_alerts_newest_first(store):
    store.record_alert("r", "warning", "fired", ts=_NOW - 10)
    store.record_alert("r", "warning", "resolved", ts=_NOW)
    events = store.recent_alerts()
    assert [e["state"] for e in events] == ["resolved", "fired"]


def test_prune_deletes_old_alerts(store):
    now = 400_000_000
    old = now - 400 * 24 * 3600  # beyond 365-day alert retention
    store.record_alert("r", "warning", "fired", ts=old)
    deleted = store.prune(now=now)
    assert deleted["energy_alerts"] == 1


# ══════════════════════════════════════════════════════════════════════════════
# Defensive branch coverage (LOW severity audit findings)
# ══════════════════════════════════════════════════════════════════════════════


def test_prune_wal_checkpoint_failure_logged(store, monkeypatch, caplog):
    """LOW#3: WAL checkpoint failure is logged but doesn't raise (database.py:178-179)."""
    import logging
    import sqlite3
    from contextlib import contextmanager

    # Make the next PRAGMA wal_checkpoint fail
    original_connect = store._db.connect

    class FailingConnection:
        def __init__(self, real_conn):
            self._real = real_conn
            self._in_context = False

        def __enter__(self):
            self._in_context = True
            self._real.__enter__()
            return self

        def __exit__(self, *args):
            self._in_context = False
            return self._real.__exit__(*args)

        def execute(self, sql, params=()):
            if "wal_checkpoint" in sql.lower():
                raise sqlite3.OperationalError("database is locked")
            return self._real.execute(sql, params)

    @contextmanager
    def failing_connect():
        with original_connect() as conn:
            yield FailingConnection(conn)

    monkeypatch.setattr(store._db, "connect", failing_connect)

    with caplog.at_level(logging.WARNING):
        # Should complete without raising
        deleted = store.prune(now=100_000_000)

    # Prune still returns results even if checkpoint failed
    assert isinstance(deleted, dict)
    assert any("wal_checkpoint failed" in r.message for r in caplog.records)
