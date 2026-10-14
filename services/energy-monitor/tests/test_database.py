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
    assert deleted == {"power_samples": 0, "energy_readings": 0}
