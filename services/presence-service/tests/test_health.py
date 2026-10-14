"""Integration tests for the presence-service HTTP API (scaffold).

Exercises the FastAPI health routes directly against the in-process app using
``httpx.ASGITransport`` WITHOUT triggering the lifespan. The module-level
``store`` singleton is swapped for a temp-dir-backed instance per test so no
production DB path is touched.
"""

from __future__ import annotations

import httpx
import main
import pytest
from database import PresenceStore


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Swap the module-level store for a test-local instance on a temp DB.
    monkeypatch.setattr(main, "store", PresenceStore(str(tmp_path / "presence.db")))
    transport = httpx.ASGITransport(app=main.app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_health_reports_online_and_db_ok(client):
    async with client as c:
        resp = await c.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["online"] is True
    assert body["service"] == "presence-service"
    assert body["db_ok"] is True
    # Source collectors do not exist in the scaffold → explicit None.
    assert body["router_online"] is None
    assert body["mqtt_online"] is None
    assert body["last_tick_age_s"] is not None


async def test_health_alias_matches(client):
    async with client as c:
        resp = await c.get("/api/health/presence")
    assert resp.status_code == 200
    body = resp.json()
    assert body["service"] == "presence-service"
    assert body["online"] is True


async def test_health_db_ok_false_when_store_broken(client, monkeypatch):
    class BrokenStore:
        def db_ok(self):
            return False

    monkeypatch.setattr(main, "store", BrokenStore())
    async with client as c:
        resp = await c.get("/health")
    assert resp.status_code == 200
    assert resp.json()["db_ok"] is False
