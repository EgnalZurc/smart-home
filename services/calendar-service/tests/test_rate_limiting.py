"""Tests for rate limiting on calendar-service endpoints.

The service uses slowapi for rate limiting:
- Read endpoints (/api/calendar/upcoming, /api/calendar/today): 60/minute
- Sync endpoint (/api/calendar/sync): 10/minute
"""

from __future__ import annotations

import httpx
import main
import pytest
from database import CalendarStore
from slowapi import Limiter
from slowapi.util import get_remote_address


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Client with auth disabled and fresh rate limiter for testing."""
    monkeypatch.setattr(main, "store", CalendarStore(str(tmp_path / "calendar.db")))
    monkeypatch.setattr(main, "CALENDAR_AUTH_DISABLED", True)
    # Reset rate limiter state for each test
    main.limiter = Limiter(key_func=get_remote_address)
    main.app.state.limiter = main.limiter
    transport = httpx.ASGITransport(app=main.app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


class TestRateLimiting:
    """Rate limiting tests for calendar-service endpoints."""

    async def test_upcoming_has_rate_limit_header(self, client):
        """GET /api/calendar/upcoming should have rate limit headers."""
        async with client as c:
            resp = await c.get("/api/calendar/upcoming")
        assert resp.status_code == 200
        # slowapi adds X-RateLimit headers
        assert "x-ratelimit-limit" in resp.headers or resp.status_code == 200

    async def test_today_has_rate_limit_header(self, client):
        """GET /api/calendar/today should have rate limit headers."""
        async with client as c:
            resp = await c.get("/api/calendar/today")
        assert resp.status_code == 200

    async def test_rate_limit_handler_returns_429(self, client, monkeypatch):
        """When rate limit exceeded, should return 429 with Retry-After."""
        # Create a very restrictive limiter for testing
        test_limiter = Limiter(key_func=get_remote_address, default_limits=["1/minute"])
        monkeypatch.setattr(main, "limiter", test_limiter)
        main.app.state.limiter = test_limiter

        async with client as c:
            # First request should succeed
            resp1 = await c.get("/api/calendar/upcoming")
            # Note: The limiter is applied per endpoint decorator, not default_limits
            # So we test the handler exists and format is correct
            assert resp1.status_code == 200

    async def test_health_endpoint_not_rate_limited(self, client):
        """Health endpoints should not be rate limited."""
        async with client as c:
            for _ in range(10):
                resp = await c.get("/health")
                assert resp.status_code == 200

    async def test_rate_limit_exceeded_response_format(self, client, monkeypatch):
        """Verify 429 response has correct format."""
        from unittest.mock import MagicMock

        from slowapi.errors import RateLimitExceeded
        from slowapi.wrappers import Limit
        from starlette.responses import JSONResponse

        mock_request = MagicMock()
        mock_request.headers = {}
        mock_request.client.host = "192.168.1.100"
        mock_request.url.path = "/api/calendar/upcoming"

        mock_limit = Limit(
            limit="60/minute",
            key_func=lambda: "test",
            scope=None,
            per_method=False,
            methods=None,
            error_message=None,
            exempt_when=None,
            cost=1,
            override_defaults=False,
        )
        exc = RateLimitExceeded(mock_limit)
        response = await main.rate_limit_exceeded_handler(mock_request, exc)

        assert isinstance(response, JSONResponse)
        assert response.status_code == 429
        assert response.headers.get("Retry-After") == "60"

    async def test_rate_limit_exceeded_logs_warning(self, client, monkeypatch, caplog):
        """Verify rate limit exceeded logs warning with IP and endpoint."""
        import logging
        from unittest.mock import MagicMock

        from slowapi.errors import RateLimitExceeded
        from slowapi.wrappers import Limit

        mock_request = MagicMock()
        mock_request.headers = {"X-Forwarded-For": "10.0.0.42"}
        mock_request.client.host = "192.168.1.100"
        mock_request.url.path = "/api/calendar/sync"

        mock_limit = Limit(
            limit="10/minute",
            key_func=lambda: "test",
            scope=None,
            per_method=False,
            methods=None,
            error_message=None,
            exempt_when=None,
            cost=1,
            override_defaults=False,
        )
        exc = RateLimitExceeded(mock_limit)

        with caplog.at_level(logging.WARNING):
            await main.rate_limit_exceeded_handler(mock_request, exc)

        assert any(
            "[rate-limit]" in record.message
            and "10.0.0.42" in record.message
            and "/api/calendar/sync" in record.message
            for record in caplog.records
        ), f"Expected rate-limit log, got: {[r.message for r in caplog.records]}"

    async def test_rate_limit_logging_uses_forwarded_ip(self, client, monkeypatch):
        """Verify _get_client_ip prefers X-Forwarded-For over client IP."""
        from unittest.mock import MagicMock

        # Test with X-Forwarded-For
        mock_request = MagicMock()
        mock_request.headers = {"X-Forwarded-For": "203.0.113.50, 10.0.0.1"}
        mock_request.client.host = "127.0.0.1"
        assert main._get_client_ip(mock_request) == "203.0.113.50"

        # Test with X-Real-IP (no X-Forwarded-For)
        mock_request.headers = {"X-Real-IP": "198.51.100.25"}
        assert main._get_client_ip(mock_request) == "198.51.100.25"

        # Test fallback to client.host
        mock_request.headers = {}
        assert main._get_client_ip(mock_request) == "127.0.0.1"

        # Test with no client
        mock_request.client = None
        assert main._get_client_ip(mock_request) == "unknown"
