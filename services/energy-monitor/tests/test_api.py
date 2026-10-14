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
