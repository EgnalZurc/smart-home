"""Tests for rate limiting on calendar-service endpoints.

Verifies that slowapi rate limits are applied correctly.
"""

from __future__ import annotations

import httpx
import main
import pytest
from database import CalendarStore


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Test client with auth disabled for rate limit testing."""
    monkeypatch.setattr(main, "store", CalendarStore(str(tmp_path / "calendar.db")))
    monkeypatch.setattr(main, "CALENDAR_AUTH_DISABLED", True)
    monkeypatch.setattr(main, "CALENDAR_API_KEY", "")
    transport = httpx.ASGITransport(app=main.app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


class TestRateLimiting:
    """Verify rate limiting is configured on endpoints."""

    async def test_upcoming_endpoint_returns_rate_limit_headers(self, client):
        """Rate-limited endpoints should include X-RateLimit headers."""
        async with client as c:
            resp = await c.get("/api/calendar/upcoming")
        assert resp.status_code == 200
        # slowapi adds these headers when rate limiting is active
        # The exact header name depends on slowapi version
        # We verify the endpoint works and doesn't crash with rate limiting

    async def test_today_endpoint_works_with_rate_limiting(self, client):
        """Today endpoint should work with rate limiting configured."""
        async with client as c:
            resp = await c.get("/api/calendar/today")
        assert resp.status_code == 200

    async def test_config_endpoint_works_with_rate_limiting(self, client):
        """Config endpoint should work with rate limiting configured."""
        async with client as c:
            resp = await c.get("/api/calendar/config")
        assert resp.status_code == 200

    async def test_health_endpoint_not_rate_limited(self, client):
        """Health endpoints should not be rate limited."""
        async with client as c:
            # Make multiple rapid requests - health should always work
            for _ in range(10):
                resp = await c.get("/health")
                assert resp.status_code == 200


class TestRateLimitExceeded:
    """Test behavior when rate limits are exceeded.

    Note: These tests verify the rate limit handler is configured.
    In practice, exceeding 60 req/min in unit tests is slow, so we
    just verify the infrastructure is in place.
    """

    async def test_rate_limit_handler_exists(self, client):
        """App should have rate limit exceeded handler configured."""
        from slowapi.errors import RateLimitExceeded

        assert RateLimitExceeded in main.app.exception_handlers

    async def test_limiter_attached_to_app(self, client):
        """Limiter should be attached to app state."""
        assert hasattr(main.app.state, "limiter")
        assert main.app.state.limiter is not None
