"""Tests for auth endpoint rate limiting with slowapi.

Verifies that the /api/auth/token endpoint is protected by rate limiting
to prevent brute-force attacks.

Note on rate limiter testing:
The slowapi rate limiter uses get_remote_address which extracts the client IP
from X-Forwarded-For or request.client.host. In TestClient, this always returns
"testclient" regardless of headers. Therefore, we can only test:
1. That the limiter is configured correctly
2. That the decorator is applied
3. That rate limiting triggers after threshold exceeded

For per-IP isolation testing, integration tests with real HTTP clients are needed.
"""

import os

import pytest


# Set env var before any imports that might need it
os.environ.setdefault("AUTH_SECRET", "test-secret-key-32-chars-minimum-length-here")


class TestAuthTokenRateLimitConfiguration:
    """Test that rate limiting is properly configured."""

    def test_rate_limit_decorator_exists(self):
        """Verify the rate limit decorator is applied to post_token."""
        from api.auth_routes import post_token

        # slowapi adds __wrapped__ attribute when decorating
        assert hasattr(
            post_token, "__wrapped__"
        ), "post_token should have rate limit decorator"

    def test_limiter_is_configured(self):
        """Verify the limiter is properly configured in auth_routes."""
        from api.auth_routes import limiter

        assert limiter is not None
        assert limiter._key_func is not None  # Should have key function set

    def test_limiter_attached_to_app(self, monkeypatch):
        """Verify the limiter is attached to app state."""
        import main

        assert hasattr(main.app.state, "limiter")
        assert main.app.state.limiter is not None


class TestAuthTokenRateLimitBehavior:
    """Test rate limiting behavior on POST /api/auth/token endpoint.

    These tests verify that the rate limiter is functional. Since TestClient
    uses "testclient" as the IP for all requests, we need to ensure the limiter
    storage is cleared before testing to avoid state pollution from other tests.
    """

    @pytest.fixture
    def clean_limiter_client(self, monkeypatch):
        """Create a test client with a clean rate limiter state.

        The key insight is that slowapi decorators bind to the limiter at
        decoration time (module import), so we need to clear the SAME limiter's
        storage rather than replacing it.
        """
        from unittest.mock import patch

        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from limits.storage import MemoryStorage
        from slowapi import _rate_limit_exceeded_handler
        from slowapi.errors import RateLimitExceeded

        from api import auth_routes

        # Get the ACTUAL limiter that the decorator is bound to
        limiter = auth_routes.limiter

        # Reset the limiter's storage to get a clean state
        # Method 1: If limiter has reset() method
        if hasattr(limiter, "reset"):
            limiter.reset()
        # Method 2: Replace storage with fresh MemoryStorage
        elif hasattr(limiter, "_storage"):
            limiter._storage = MemoryStorage()
        # Method 3: If limiter has _limiter attribute with storage
        elif hasattr(limiter, "_limiter") and hasattr(limiter._limiter, "storage"):
            limiter._limiter.storage = MemoryStorage()

        # Create a test app with the router
        app = FastAPI()
        app.state.limiter = limiter
        app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
        app.include_router(auth_routes.router)

        # Mock authenticate_user to return False (invalid credentials)
        with patch("auth_users.authenticate_user", return_value=False):
            yield TestClient(app)

    def test_rate_limit_triggered_after_threshold(self, clean_limiter_client):
        """Verify that exceeding rate limit returns HTTP 429.

        The endpoint is limited to 5 requests per minute.
        """
        client = clean_limiter_client

        # Make exactly 5 requests (the limit)
        for i in range(5):
            response = client.post(
                "/api/auth/token",
                data={
                    "username": f"testuser_{i}",
                    "password": "wrongpassword",
                },
            )
            # Should not be rate limited yet (200 for success page, 303 for redirect)
            assert response.status_code in (
                200,
                303,
            ), f"Request {i+1} should not be rate limited, got {response.status_code}"

        # 6th request should be rate limited
        response = client.post(
            "/api/auth/token",
            data={
                "username": "testuser_overflow",
                "password": "wrongpassword",
            },
        )
        assert response.status_code == 429, "6th request should be rate limited"
