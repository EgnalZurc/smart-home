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
    """Create a test client with a temporary database.

    Swaps the module-level store for a test-local instance backed by a
    temporary directory so no production DB path is touched.
    """
    monkeypatch.setattr(main, "store", PresenceStore(str(tmp_path / "presence.db")))
    transport = httpx.ASGITransport(app=main.app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_health_reports_online_and_db_ok(client):
    """Test that health endpoint reports online status and DB connectivity."""
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
    """Test that health alias endpoint returns identical information."""
    async with client as c:
        resp = await c.get("/api/health/presence")
    assert resp.status_code == 200
    body = resp.json()
    assert body["service"] == "presence-service"
    assert body["online"] is True


async def test_health_db_ok_false_when_store_broken(client, monkeypatch):
    """Test that health reports db_ok=False when database is unavailable."""

    class BrokenStore:
        """Mock store that always reports database failure."""

        def db_ok(self) -> bool:
            return False

    monkeypatch.setattr(main, "store", BrokenStore())
    async with client as c:
        resp = await c.get("/health")
    assert resp.status_code == 200
    assert resp.json()["db_ok"] is False


async def test_security_headers_present(client):
    """Test that security headers are included in all responses."""
    async with client as c:
        resp = await c.get("/health")
    assert resp.status_code == 200
    # Verify all security headers are present
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert resp.headers.get("Content-Security-Policy") == "default-src 'self'"
    assert resp.headers.get("X-XSS-Protection") == "1; mode=block"
    assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"


async def test_security_headers_on_alias_endpoint(client):
    """Test that security headers are also present on the alias endpoint."""
    async with client as c:
        resp = await c.get("/api/health/presence")
    assert resp.status_code == 200
    # Verify security headers on alias endpoint too
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"
