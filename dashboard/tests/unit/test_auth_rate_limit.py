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

import sys

import pytest


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
        # Set required env vars before importing main
        monkeypatch.setenv("AUTH_SECRET", "test-secret-key-32-chars-minimum-length-here")

        # Clear cached modules to ensure fresh import with env var
        modules_to_clear = [
            mod
            for mod in list(sys.modules.keys())
            if mod.startswith(("main", "api."))
        ]
        for mod in modules_to_clear:
            if mod in sys.modules:
                del sys.modules[mod]

        import main

        assert hasattr(main.app.state, "limiter")
        assert main.app.state.limiter is not None


class TestAuthTokenRateLimitBehavior:
    """Test rate limiting behavior on POST /api/auth/token endpoint.

    These tests verify that the rate limiter is functional. Since TestClient
    uses "testclient" as the IP for all requests, and the rate limiter may
    have state from other tests, we use unique request patterns.
    """

    @pytest.fixture
    def fresh_app_client(self, monkeypatch):
        """Create a completely fresh FastAPI app with rate limiter for testing.

        This fixture creates an isolated app instance to avoid state pollution
        from other tests.
        """
        from unittest.mock import patch

        # Set required env vars
        monkeypatch.setenv("AUTH_SECRET", "test-secret-key-32-chars-minimum-length-here")

        # Clear ALL modules that might cache state
        modules_to_clear = [
            mod
            for mod in list(sys.modules.keys())
            if mod.startswith(("api.", "main", "auth", "slowapi"))
        ]
        for mod in modules_to_clear:
            if mod in sys.modules:
                del sys.modules[mod]

        # Patch auth_users BEFORE importing
        with patch("auth_users.authenticate_user", return_value=False):
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
            from slowapi import Limiter, _rate_limit_exceeded_handler
            from slowapi.errors import RateLimitExceeded
            from slowapi.util import get_remote_address

            # Create a fresh limiter and app
            fresh_limiter = Limiter(key_func=get_remote_address)

            # Need to re-import and patch auth_routes limiter
            from api import auth_routes

            # Replace the module's limiter with our fresh one
            original_limiter = auth_routes.limiter
            auth_routes.limiter = fresh_limiter

            # Create fresh app with the router
            app = FastAPI()
            app.state.limiter = fresh_limiter
            app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
            app.include_router(auth_routes.router)

            yield TestClient(app)

            # Restore original limiter
            auth_routes.limiter = original_limiter

    def test_rate_limit_triggered_after_threshold(self, fresh_app_client):
        """Verify that exceeding rate limit returns HTTP 429.

        The endpoint is limited to 5 requests per minute.
        """
        client = fresh_app_client

        # Make exactly 5 requests (the limit)
        for i in range(5):
            response = client.post(
                "/api/auth/token",
                data={
                    "username": f"testuser_{i}",
                    "password": "wrongpassword",
                },
            )
            # Should not be rate limited yet
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
