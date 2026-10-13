"""Integration tests for the metrics-service HTTP API.

These exercise the FastAPI routes directly against the in-process app using
``httpx.ASGITransport`` WITHOUT triggering the lifespan (so the real collector
background tasks are not started). The module-level ``collector`` singleton's
ring buffer / store are populated manually per test.
"""

from __future__ import annotations

import time

import httpx
import main
import pytest
from sqlite_store import SqliteStore
from storage import RingBuffer


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Swap the module-level collector's storage for test-local instances so
    # tests do not touch the production DB path or share ring state.
    monkeypatch.setattr(main.collector, "ring", RingBuffer(maxlen=240))
    monkeypatch.setattr(main.collector, "store", SqliteStore(str(tmp_path / "m.db")))
    monkeypatch.setattr(main.collector, "last_tick_ts", time.monotonic())
    transport = httpx.ASGITransport(app=main.app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_health_reports_db_ok_and_tick_age(client):
    async with client as c:
        resp = await c.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["online"] is True
    assert body["service"] == "metrics-service"
    assert body["db_ok"] is True
    assert body["collector_last_tick_age_s"] is not None


async def test_health_alias_matches(client):
    async with client as c:
        resp = await c.get("/api/health/metrics")
    assert resp.status_code == 200
    assert resp.json()["service"] == "metrics-service"


async def test_health_db_ok_false_when_store_broken(client, monkeypatch):
    class BrokenStore:
        def count(self):
            raise RuntimeError("db gone")

    monkeypatch.setattr(main.collector, "store", BrokenStore())
    async with client as c:
        resp = await c.get("/health")
    assert resp.json()["db_ok"] is False


async def test_latest_returns_ring_contents(client):
    main.collector.ring.add("host.ram.percent", "", 61.2, ts=1000)
    async with client as c:
        resp = await c.get("/api/metrics/latest")
    assert resp.status_code == 200
    series = resp.json()["series"]
    assert series["host.ram.percent|"]["value"] == 61.2


async def test_series_hi_from_ring(client):
    for i in range(3):
        main.collector.ring.add("host.cpu.percent", "", float(i), ts=100 + i)
    async with client as c:
        resp = await c.get(
            "/api/metrics/series",
            params={"metric": "host.cpu.percent", "resolution": "hi"},
        )
    body = resp.json()
    assert body["resolution"] == "hi"
    assert body["points"] == [
        {"ts": 100, "value": 0.0},
        {"ts": 101, "value": 1.0},
        {"ts": 102, "value": 2.0},
    ]


async def test_series_rollup_from_sqlite(client):
    main.collector.store.write_rollup(5000, [("host.ram.percent", "", 60.0, 72.0)])
    async with client as c:
        resp = await c.get(
            "/api/metrics/series",
            params={"metric": "host.ram.percent", "resolution": "rollup"},
        )
    body = resp.json()
    assert body["resolution"] == "rollup"
    assert body["points"][0]["ts"] == 5000
    assert body["points"][0]["value"] == 60.0
    assert body["points"][0]["value_max"] == 72.0


async def test_series_relative_since(client):
    now = int(time.time())
    main.collector.ring.add("m", "", 1.0, ts=now - 7200)  # 2h ago (excluded)
    main.collector.ring.add("m", "", 2.0, ts=now - 60)  # 1m ago (included)
    async with client as c:
        resp = await c.get(
            "/api/metrics/series",
            params={"metric": "m", "since": "-1h"},
        )
    pts = resp.json()["points"]
    assert [p["value"] for p in pts] == [2.0]


async def test_series_invalid_since_returns_400(client):
    async with client as c:
        resp = await c.get(
            "/api/metrics/series", params={"metric": "m", "since": "-5x"}
        )
    assert resp.status_code == 400


async def test_series_invalid_resolution_rejected(client):
    async with client as c:
        resp = await c.get(
            "/api/metrics/series", params={"metric": "m", "resolution": "weekly"}
        )
    assert resp.status_code == 422


async def test_summary_aggregates(client):
    now = int(time.time())
    main.collector.store.write_rollup(now - 100, [("host.ram.percent", "", 60.0, 70.0)])
    main.collector.store.write_rollup(now - 50, [("host.ram.percent", "", 80.0, 90.0)])
    async with client as c:
        resp = await c.get("/api/metrics/summary", params={"window": "24h"})
    body = resp.json()
    assert body["window"] == "24h"
    row = next(r for r in body["metrics"] if r["metric"] == "host.ram.percent")
    assert row["min"] == 60.0
    assert row["avg"] == 70.0
    assert row["max"] == 90.0


async def test_summary_invalid_window_rejected(client):
    async with client as c:
        resp = await c.get("/api/metrics/summary", params={"window": "99y"})
    assert resp.status_code == 422
