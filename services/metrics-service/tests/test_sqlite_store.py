"""Unit tests for the SQLite store (sqlite_store.py): write, series, summary, prune."""

from __future__ import annotations

import pytest
from sqlite_store import SqliteStore


@pytest.fixture
def store(tmp_path):
    return SqliteStore(str(tmp_path / "metrics.db"))


def test_write_rollup_and_count(store):
    n = store.write_rollup(
        1000,
        [("host.ram.percent", "", 60.0, 72.0), ("host.cpu.percent", "", 10.0, 40.0)],
    )
    assert n == 2
    assert store.count() == 2


def test_write_rollup_empty_is_noop(store):
    assert store.write_rollup(1000, []) == 0
    assert store.count() == 0


def test_write_rollup_replace_on_conflict(store):
    store.write_rollup(1000, [("m", "", 1.0, 2.0)])
    store.write_rollup(1000, [("m", "", 5.0, 9.0)])  # same (ts, metric, label)
    rows = store.series("m")
    assert len(rows) == 1
    assert rows[0]["value"] == 5.0
    assert rows[0]["value_max"] == 9.0


def test_series_time_range_and_order(store):
    for ts in (3000, 1000, 2000):
        store.write_rollup(ts, [("m", "", float(ts), float(ts))])
    rows = store.series("m", since=1500, until=3000)
    assert [r["ts"] for r in rows] == [2000, 3000]


def test_series_label_isolation(store):
    store.write_rollup(1000, [("container.mem.percent", "svc1", 40.0, 50.0)])
    store.write_rollup(1000, [("container.mem.percent", "svc2", 80.0, 90.0)])
    rows = store.series("container.mem.percent", "svc1")
    assert len(rows) == 1
    assert rows[0]["value"] == 40.0


def test_summary_aggregates_min_avg_max(store):
    store.write_rollup(1000, [("m", "", 10.0, 20.0)])
    store.write_rollup(2000, [("m", "", 30.0, 60.0)])
    rows = store.summary(since=0)
    assert len(rows) == 1
    row = rows[0]
    assert row["metric"] == "m"
    assert row["min"] == 10.0
    assert row["avg"] == 20.0  # (10+30)/2
    assert row["max"] == 60.0  # max of value_max
    assert row["count"] == 2


def test_summary_respects_since(store):
    store.write_rollup(1000, [("m", "", 10.0, 10.0)])
    store.write_rollup(5000, [("m", "", 50.0, 50.0)])
    rows = store.summary(since=3000)
    assert len(rows) == 1
    assert rows[0]["min"] == 50.0


def test_prune_deletes_old_rows(store):
    now = 100_000_000
    old = now - 40 * 24 * 3600  # 40 days ago, beyond 30-day retention
    recent = now - 5 * 24 * 3600
    store.write_rollup(old, [("m", "", 1.0, 1.0)])
    store.write_rollup(recent, [("m", "", 2.0, 2.0)])
    deleted = store.prune(now=now, retention_days=30)
    assert deleted == 1
    rows = store.series("m")
    assert [r["ts"] for r in rows] == [recent]


def test_prune_nothing_to_delete(store):
    now = 100_000_000
    store.write_rollup(now - 3600, [("m", "", 1.0, 1.0)])
    assert store.prune(now=now, retention_days=30) == 0
