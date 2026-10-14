"""Integration tests for the energy-monitor HTTP API.

Exercises the FastAPI routes directly against the in-process app using
``httpx.ASGITransport`` WITHOUT triggering the lifespan (so the background poll
loops never start). The module-level ``collector`` is pointed at a temp DB and
has its ring buffer manipulated directly so tests never touch hardware or the
production path.
"""

from __future__ import annotations

import httpx
import main
import pytest
from database import EnergyStore


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(
        main.collector, "store", EnergyStore(str(tmp_path / "energy.db"))
    )
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
    # No poll has run in-test, so collector/meter liveness is "no data yet".
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

    monkeypatch.setattr(main.collector, "store", BrokenStore())
    async with client as c:
        resp = await c.get("/health")
    assert resp.status_code == 200
    assert resp.json()["db_ok"] is False


async def test_current_returns_empty_channels_when_no_data(client):
    async with client as c:
        resp = await c.get("/api/energy/current")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_w"] == 0.0
    assert body["channels"] == {}
    assert body["meter_online"] is None
    assert isinstance(body["ts"], int)


async def test_current_reflects_ring_buffer(client, monkeypatch):
    # Seed the collector's ring buffer with two live channels and mark online.
    monkeypatch.setitem(main.collector.labels, "main:ch0", "General")
    main.collector.ring["main:ch0"].append((1000, 1200.0, 230.0, 0.95))
    main.collector.ring["main:ch1"].append((1000, 300.0, 230.0, 0.9))
    main.collector.meter_online = True
    try:
        async with client as c:
            resp = await c.get("/api/energy/current")
        body = resp.json()
        assert body["meter_online"] is True
        assert body["total_w"] == pytest.approx(1500.0)
        assert body["channels"]["main:ch0"]["power"] == 1200.0
        assert body["channels"]["main:ch0"]["label"] == "General"
        # No inventory label for ch1 → key is used as the fallback label.
        assert body["channels"]["main:ch1"]["label"] == "main:ch1"
    finally:
        main.collector.ring.clear()
        main.collector.meter_online = None


async def test_db_ok_helper_true_and_false(monkeypatch, tmp_path):
    # Direct unit coverage of the _db_ok helper on both branches.
    monkeypatch.setattr(
        main.collector, "store", EnergyStore(str(tmp_path / "e.db"))
    )
    assert main._db_ok() is True

    class Broken:
        def count(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(main.collector, "store", Broken())
    assert main._db_ok() is False
