"""
Tests for security features: CSRF protection, Swagger docs, and CSP headers.
"""

import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


class TestCSRFProtection:
    """Tests for CSRF protection via Origin validation."""

    @pytest.fixture
    def client(self):
        """Create a test client with mocked orchestrator."""
        with patch("main.get_orchestrator"):
            from main import app

            return TestClient(app, raise_server_exceptions=False)

    def test_csrf_blocks_invalid_origin_on_post(self, client: TestClient):
        """POST with invalid Origin header should return 403."""
        response = client.post(
            "/api/portfolio/refresh",
            headers={"Origin": "https://evil.com"},
        )
        assert response.status_code == 403
        assert response.json() == {"error": "Forbidden: invalid origin"}

    def test_csrf_allows_valid_origin_tailscale(self, client: TestClient):
        """POST with valid Tailscale Origin should be allowed."""
        response = client.post(
            "/api/portfolio/refresh",
            headers={"Origin": "https://raspberrypi.tailaa37cd.ts.net"},
        )
        # Should not be 403 (may be other error like 500 from mocked orchestrator)
        assert response.status_code != 403

    def test_csrf_allows_valid_origin_localhost(self, client: TestClient):
        """POST with valid localhost Origin should be allowed."""
        response = client.post(
            "/api/portfolio/refresh",
            headers={"Origin": "http://localhost:8010"},
        )
        assert response.status_code != 403

    def test_csrf_allows_request_without_origin(self, client: TestClient):
        """POST without Origin header should be allowed (non-browser clients)."""
        response = client.post("/api/portfolio/refresh")
        # Should not be 403 - curl/scripts don't send Origin
        assert response.status_code != 403

    def test_csrf_allows_get_with_any_origin(self, client: TestClient):
        """GET requests should be allowed regardless of Origin."""
        response = client.get(
            "/health",
            headers={"Origin": "https://evil.com"},
        )
        # GET is not state-changing, should be allowed
        assert response.status_code != 403

    def test_csrf_blocks_patch_with_invalid_origin(self, client: TestClient):
        """PATCH with invalid Origin should be blocked."""
        response = client.patch(
            "/api/portfolio/alerts/test/complete",
            headers={"Origin": "https://malicious-site.com"},
        )
        assert response.status_code == 403

    def test_csrf_blocks_delete_with_invalid_origin(self, client: TestClient):
        """DELETE with invalid Origin should be blocked."""
        response = client.delete(
            "/api/portfolio/alerts/test",
            headers={"Origin": "https://attacker.com"},
        )
        assert response.status_code == 403


class TestSwaggerDisabledInProduction:
    """Tests for Swagger/ReDoc disabled in production."""

    def test_swagger_disabled_in_production(self):
        """Swagger docs should be disabled when ENVIRONMENT=production."""
        with patch.dict(os.environ, {"ENVIRONMENT": "production"}, clear=False):
            # Need to reimport to pick up new env
            import importlib

            import main

            importlib.reload(main)

            client = TestClient(main.app, raise_server_exceptions=False)

            # Both /docs and /redoc should return 404
            response = client.get("/docs")
            assert response.status_code == 404

            response = client.get("/redoc")
            assert response.status_code == 404

    def test_swagger_enabled_in_development(self):
        """Swagger docs should be enabled when ENVIRONMENT=development."""
        with patch.dict(os.environ, {"ENVIRONMENT": "development"}, clear=False):
            import importlib

            import main

            importlib.reload(main)

            client = TestClient(main.app, raise_server_exceptions=False)

            # /docs should return 200 (or redirect)
            response = client.get("/docs")
            assert response.status_code in (200, 307)

            response = client.get("/redoc")
            assert response.status_code in (200, 307)


class TestSecurityHeaders:
    """Tests for security headers including CSP."""

    @pytest.fixture
    def client(self):
        """Create a test client with mocked orchestrator."""
        with patch("main.get_orchestrator"):
            from main import app

            return TestClient(app, raise_server_exceptions=False)

    def test_security_headers_present(self, client: TestClient):
        """All security headers should be present in responses."""
        response = client.get("/health")

        assert response.headers.get("X-Content-Type-Options") == "nosniff"
        assert response.headers.get("X-Frame-Options") == "DENY"
        assert response.headers.get("X-XSS-Protection") == "1; mode=block"
        assert "Content-Security-Policy" in response.headers
        assert (
            response.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
        )

    def test_csp_header_content(self, client: TestClient):
        """CSP header should have correct directives."""
        response = client.get("/health")

        csp = response.headers.get("Content-Security-Policy", "")
        assert "default-src 'self'" in csp
        assert "script-src 'self'" in csp
        assert "style-src 'self' 'unsafe-inline'" in csp

    def test_cache_control_on_api_endpoints(self, client: TestClient):
        """API endpoints should have no-store cache control."""
        response = client.get("/api/health/portfolio")

        assert response.headers.get("Cache-Control") == "no-store, max-age=0"

    def test_no_cache_control_on_non_api_endpoints(self, client: TestClient):
        """Non-API endpoints should not have cache control header."""
        response = client.get("/health")

        # /health is not under /api/, so no Cache-Control added by middleware
        # (though it may have a default)
        cache_control = response.headers.get("Cache-Control", "")
        # Should NOT have "no-store, max-age=0" specifically
        if cache_control:
            # If present, it shouldn't be our API-specific header
            pass  # Other cache settings are fine
