"""Tests for API key authentication on protected calendar-service endpoints.

The service uses bearer token auth via the ``require_api_key`` dependency.
When CALENDAR_API_KEY is set, protected endpoints require
``Authorization: Bearer <key>``. When unset (empty), auth is disabled.
"""

from __future__ import annotations

import httpx
import main
import pytest
from database import CalendarStore


@pytest.fixture
def client_with_auth(tmp_path, monkeypatch):
    """Client with CALENDAR_API_KEY set — auth is enforced."""
    monkeypatch.setattr(main, "store", CalendarStore(str(tmp_path / "calendar.db")))
    monkeypatch.setattr(main, "CALENDAR_API_KEY", "test-secret-key")
    transport = httpx.ASGITransport(app=main.app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture
def client_no_auth(tmp_path, monkeypatch):
    """Client with CALENDAR_API_KEY empty — auth is disabled (dev mode)."""
    monkeypatch.setattr(main, "store", CalendarStore(str(tmp_path / "calendar.db")))
    monkeypatch.setattr(main, "CALENDAR_API_KEY", "")
    transport = httpx.ASGITransport(app=main.app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


# ═══════════════════════════════════════════════════════════════════════════════
# Auth enabled — missing/invalid token → 401/403
# ═══════════════════════════════════════════════════════════════════════════════
class TestAuthEnabled:
    """When CALENDAR_API_KEY is set, protected endpoints require valid bearer."""

    async def test_get_config_without_token_returns_401(self, client_with_auth):
        async with client_with_auth as c:
            resp = await c.get("/api/calendar/config")
        assert resp.status_code == 401
        assert "Missing" in resp.json()["detail"]

    async def test_post_config_without_token_returns_401(self, client_with_auth):
        async with client_with_auth as c:
            resp = await c.post("/api/calendar/config", json={})
        assert resp.status_code == 401

    async def test_post_sync_without_token_returns_401(self, client_with_auth):
        async with client_with_auth as c:
            resp = await c.post("/api/calendar/sync")
        assert resp.status_code == 401

    async def test_get_config_with_invalid_token_returns_403(self, client_with_auth):
        async with client_with_auth as c:
            resp = await c.get(
                "/api/calendar/config",
                headers={"Authorization": "Bearer wrong-key"},
            )
        assert resp.status_code == 403
        assert "Invalid" in resp.json()["detail"]

    async def test_post_config_with_invalid_token_returns_403(self, client_with_auth):
        async with client_with_auth as c:
            resp = await c.post(
                "/api/calendar/config",
                json={},
                headers={"Authorization": "Bearer wrong-key"},
            )
        assert resp.status_code == 403

    async def test_get_config_with_valid_token_succeeds(self, client_with_auth):
        async with client_with_auth as c:
            resp = await c.get(
                "/api/calendar/config",
                headers={"Authorization": "Bearer test-secret-key"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert "calendars" in body
        assert "rules" in body

    async def test_post_config_with_valid_token_succeeds(self, client_with_auth):
        async with client_with_auth as c:
            resp = await c.post(
                "/api/calendar/config",
                json={"calendars": []},
                headers={"Authorization": "Bearer test-secret-key"},
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    async def test_public_endpoints_do_not_require_auth(self, client_with_auth):
        """Health and read endpoints remain open even with auth enabled."""
        async with client_with_auth as c:
            health = await c.get("/health")
            upcoming = await c.get("/api/calendar/upcoming")
            today = await c.get("/api/calendar/today")
        assert health.status_code == 200
        assert upcoming.status_code == 200
        assert today.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
# Auth disabled — all requests allowed (dev mode)
# ═══════════════════════════════════════════════════════════════════════════════
class TestAuthDisabled:
    """When CALENDAR_API_KEY is empty, protected endpoints are open."""

    async def test_get_config_without_token_succeeds(self, client_no_auth):
        async with client_no_auth as c:
            resp = await c.get("/api/calendar/config")
        assert resp.status_code == 200

    async def test_post_config_without_token_succeeds(self, client_no_auth):
        async with client_no_auth as c:
            resp = await c.post("/api/calendar/config", json={})
        assert resp.status_code == 200
