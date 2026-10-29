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
    """Create a test client with a temporary database."""
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
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"


# ═══════════════════════════════════════════════════════════════════════════════
# Rate Limiting Tests
# ═══════════════════════════════════════════════════════════════════════════════


async def test_rate_limiter_returns_429_when_exceeded(tmp_path, monkeypatch):
    """Test that rate limiter returns 429 when request limit is exceeded."""
    from smart_home_common.rate_limiter import InMemoryRateLimiter

    strict_limiter = InMemoryRateLimiter(
        max_requests=1,
        window_seconds=60,
        max_entries=100,
    )
    monkeypatch.setattr(main, "rate_limiter", strict_limiter)
    monkeypatch.setattr(main, "store", PresenceStore(str(tmp_path / "presence.db")))

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        resp1 = await c.get("/health")
        assert resp1.status_code == 200

        resp2 = await c.get("/health")
        assert resp2.status_code == 429
        assert "Rate limit exceeded" in resp2.json()["detail"]


async def test_rate_limiter_applies_to_health_alias(tmp_path, monkeypatch):
    """Test that rate limiter also applies to the /api/health/presence endpoint."""
    from smart_home_common.rate_limiter import InMemoryRateLimiter

    strict_limiter = InMemoryRateLimiter(
        max_requests=1,
        window_seconds=60,
        max_entries=100,
    )
    monkeypatch.setattr(main, "rate_limiter", strict_limiter)
    monkeypatch.setattr(main, "store", PresenceStore(str(tmp_path / "presence.db")))

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        resp1 = await c.get("/api/health/presence")
        assert resp1.status_code == 200

        resp2 = await c.get("/api/health/presence")
        assert resp2.status_code == 429
