"""Tests for API key authentication on protected calendar-service endpoints.

The service uses bearer token auth via the ``require_api_key`` dependency.
Auth is ENABLED by default. When CALENDAR_AUTH_DISABLED=true, auth is disabled.
When auth is enabled but CALENDAR_API_KEY is not set, protected endpoints return
HTTP 500 (fail-secure).
"""

from __future__ import annotations

import httpx
import main
import pytest
from database import CalendarStore


@pytest.fixture
def client_with_auth(tmp_path, monkeypatch):
    """Client with auth enabled and CALENDAR_API_KEY set."""
    monkeypatch.setattr(main, "store", CalendarStore(str(tmp_path / "calendar.db")))
    monkeypatch.setattr(main, "CALENDAR_API_KEY", "test-secret-key")
    monkeypatch.setattr(main, "CALENDAR_AUTH_DISABLED", False)
    transport = httpx.ASGITransport(app=main.app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture
def client_auth_disabled(tmp_path, monkeypatch):
    """Client with auth explicitly disabled via CALENDAR_AUTH_DISABLED=true."""
    monkeypatch.setattr(main, "store", CalendarStore(str(tmp_path / "calendar.db")))
    monkeypatch.setattr(main, "CALENDAR_API_KEY", "")
    monkeypatch.setattr(main, "CALENDAR_AUTH_DISABLED", True)
    transport = httpx.ASGITransport(app=main.app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture
def client_auth_enabled_no_key(tmp_path, monkeypatch):
    """Client with auth enabled but no CALENDAR_API_KEY — should fail-secure."""
    monkeypatch.setattr(main, "store", CalendarStore(str(tmp_path / "calendar.db")))
    monkeypatch.setattr(main, "CALENDAR_API_KEY", "")
    monkeypatch.setattr(main, "CALENDAR_AUTH_DISABLED", False)
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
    """When CALENDAR_AUTH_DISABLED=true, protected endpoints are open."""

    async def test_get_config_without_token_succeeds(self, client_auth_disabled):
        async with client_auth_disabled as c:
            resp = await c.get("/api/calendar/config")
        assert resp.status_code == 200

    async def test_post_config_without_token_succeeds(self, client_auth_disabled):
        async with client_auth_disabled as c:
            resp = await c.post("/api/calendar/config", json={})
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
# Fail-secure — auth enabled but no key configured
# ═══════════════════════════════════════════════════════════════════════════════
class TestFailSecure:
    """When auth is enabled but CALENDAR_API_KEY not set, return HTTP 500."""

    async def test_get_config_returns_500_when_no_key_configured(
        self, client_auth_enabled_no_key
    ):
        async with client_auth_enabled_no_key as c:
            resp = await c.get("/api/calendar/config")
        assert resp.status_code == 500
        assert "not configured" in resp.json()["detail"]

    async def test_post_config_returns_500_when_no_key_configured(
        self, client_auth_enabled_no_key
    ):
        async with client_auth_enabled_no_key as c:
            resp = await c.post("/api/calendar/config", json={})
        assert resp.status_code == 500

    async def test_post_sync_returns_500_when_no_key_configured(
        self, client_auth_enabled_no_key
    ):
        async with client_auth_enabled_no_key as c:
            resp = await c.post("/api/calendar/sync")
        assert resp.status_code == 500

    async def test_public_endpoints_still_work_when_no_key_configured(
        self, client_auth_enabled_no_key
    ):
        """Health and read endpoints remain open even without key."""
        async with client_auth_enabled_no_key as c:
            health = await c.get("/health")
            upcoming = await c.get("/api/calendar/upcoming")
            today = await c.get("/api/calendar/today")
        assert health.status_code == 200
        assert upcoming.status_code == 200
        assert today.status_code == 200
