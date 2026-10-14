"""Integration tests for the energy-monitor HTTP API (scaffold).

Exercises the FastAPI routes directly against the in-process app using
``httpx.ASGITransport`` WITHOUT triggering the lifespan (no background tasks in
the scaffold). The module-level ``store`` singleton is swapped for a temp DB so
tests never touch the production path.
"""

from __future__ import annotations

import httpx
import main
import pytest
from database import EnergyStore


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "store", EnergyStore(str(tmp_path / "energy.db")))
    transport = httpx.ASGITransport(app=main.app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_health_reports_db_ok(client):
    async with client as c:
        resp = await c.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["online"] is True
    assert body["service"] == "energy-monitor"
    assert body["db_ok"] is True
    # Collector/meter liveness is None until the collector task lands.
    assert body["meter_online"] is None
    assert body["collector_last_tick_age_s"] is None


async def test_health_alias_matches(client):
    async with client as c:
        resp = await c.get("/api/health/energy")
    assert resp.status_code == 200
    body = resp.json()
    assert body["service"] == "energy-monitor"
    assert body["db_ok"] is True


async def test_health_db_ok_false_when_store_broken(client, monkeypatch):
    class BrokenStore:
        def count(self):
            raise RuntimeError("db gone")

    monkeypatch.setattr(main, "store", BrokenStore())
    async with client as c:
        resp = await c.get("/health")
    assert resp.status_code == 200
    assert resp.json()["db_ok"] is False


async def test_current_returns_empty_channels_in_scaffold(client):
    async with client as c:
        resp = await c.get("/api/energy/current")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_w"] == 0.0
    assert body["channels"] == {}
    assert body["meter_online"] is None
    assert isinstance(body["ts"], int)


async def test_db_ok_helper_true_and_false(monkeypatch, tmp_path):
    # Direct unit coverage of the _db_ok helper on both branches.
    monkeypatch.setattr(main, "store", EnergyStore(str(tmp_path / "e.db")))
    assert main._db_ok() is True

    class Broken:
        def count(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(main, "store", Broken())
    assert main._db_ok() is False


# ── History endpoint ──────────────────────────────────────────────────────────
async def test_history_empty_defaults_to_day(client):
    async with client as c:
        resp = await c.get("/api/energy/history")
    assert resp.status_code == 200
    body = resp.json()
    assert body["period"] == "day"
    assert body["count"] == 24
    assert len(body["series"]) == 24
    assert all(p["consumption_wh"] is None for p in body["series"])


async def test_history_returns_deltas(client):
    import time as _time

    main.store.write_energy(int(_time.time()) - 7200, [("ch0", 0.0)])
    main.store.write_energy(int(_time.time()) - 3600, [("ch0", 1500.0)])
    async with client as c:
        resp = await c.get("/api/energy/history?period=hour&count=3&channel=ch0")
    assert resp.status_code == 200
    body = resp.json()
    assert body["period"] == "hour"
    assert body["channel"] == "ch0"
    values = [p["consumption_wh"] for p in body["series"] if p["consumption_wh"]]
    assert 1500.0 in values


async def test_history_invalid_period_422(client):
    async with client as c:
        resp = await c.get("/api/energy/history?period=decade")
    assert resp.status_code == 422


async def test_history_count_out_of_range_422(client):
    async with client as c:
        resp = await c.get("/api/energy/history?period=day&count=0")
    assert resp.status_code == 422


# ── Stats endpoint ────────────────────────────────────────────────────────────
async def test_stats_empty_shape(client):
    async with client as c:
        resp = await c.get("/api/energy/stats")
    assert resp.status_code == 200
    body = resp.json()
    for key in (
        "month_start",
        "days_elapsed",
        "total_kwh",
        "avg_daily_kwh",
        "peak_daily_kwh",
        "peak_power_w",
    ):
        assert key in body
    assert body["total_kwh"] is None


# ── Alerts endpoint ───────────────────────────────────────────────────────────
async def test_alerts_empty(client):
    async with client as c:
        resp = await c.get("/api/energy/alerts")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 0
    assert body["alerts"] == []


async def test_alerts_returns_recorded(client):
    main.store.record_alert("daily_budget", "warning", "fired", value=25.0)
    async with client as c:
        resp = await c.get("/api/energy/alerts?limit=10")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["alerts"][0]["rule_key"] == "daily_budget"
