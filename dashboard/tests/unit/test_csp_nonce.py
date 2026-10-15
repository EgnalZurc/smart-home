"""Tests for CSP nonce generation middleware."""

import re

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from middleware.csp_nonce import (
    CSPNonceMiddleware,
    generate_nonce,
    get_csp_nonce,
)
from starlette.responses import JSONResponse


class TestGenerateNonce:
    """Tests for the generate_nonce function."""

    def test_returns_string(self):
        """Nonce should be a string."""
        nonce = generate_nonce()
        assert isinstance(nonce, str)

    def test_length(self):
        """Nonce from token_urlsafe(16) should be 22 chars."""
        nonce = generate_nonce()
        assert len(nonce) == 22

    def test_url_safe_characters(self):
        """Nonce should only contain URL-safe base64 chars."""
        nonce = generate_nonce()
        # URL-safe base64: alphanumeric, hyphen, underscore
        assert re.match(r"^[A-Za-z0-9_-]+$", nonce)

    def test_uniqueness(self):
        """Each call should generate a unique nonce."""
        nonces = {generate_nonce() for _ in range(100)}
        assert len(nonces) == 100  # All unique


class TestGetCspNonce:
    """Tests for the get_csp_nonce utility function."""

    def test_returns_nonce_from_request_state(self):
        """Should return nonce stored in request.state."""

        class MockState:
            csp_nonce = "test-nonce-123"

        class MockRequest:
            state = MockState()

        assert get_csp_nonce(MockRequest()) == "test-nonce-123"

    def test_returns_empty_string_when_not_set(self):
        """Should return empty string if middleware not installed."""

        class MockState:
            pass  # No csp_nonce attribute

        class MockRequest:
            state = MockState()

        assert get_csp_nonce(MockRequest()) == ""


class TestCSPNonceMiddleware:
    """Tests for the CSPNonceMiddleware class."""

    @pytest.fixture
    def app_with_middleware(self):
        """Create a test app with CSP middleware."""
        app = FastAPI()
        app.add_middleware(CSPNonceMiddleware)

        @app.get("/test")
        async def test_route(request: Request):
            return JSONResponse({"nonce": request.state.csp_nonce})

        return app

    @pytest.fixture
    def client(self, app_with_middleware):
        """Create test client."""
        return TestClient(app_with_middleware)

    def test_adds_csp_header(self, client):
        """Response should include Content-Security-Policy header."""
        response = client.get("/test")
        assert "Content-Security-Policy" in response.headers

    def test_nonce_in_csp_header(self, client):
        """CSP header should contain the nonce."""
        response = client.get("/test")
        csp = response.headers["Content-Security-Policy"]
        body = response.json()
        nonce = body["nonce"]

        # Nonce should appear in script-src directive
        assert f"'nonce-{nonce}'" in csp

    def test_nonce_stored_in_request_state(self, client):
        """Nonce should be accessible in route handler via request.state."""
        response = client.get("/test")
        body = response.json()

        assert "nonce" in body
        assert len(body["nonce"]) == 22

    def test_unique_nonce_per_request(self, client):
        """Each request should get a unique nonce."""
        nonces = set()
        for _ in range(10):
            response = client.get("/test")
            nonces.add(response.json()["nonce"])

        assert len(nonces) == 10

    def test_default_directives_present(self, client):
        """Default CSP directives should all be present."""
        response = client.get("/test")
        csp = response.headers["Content-Security-Policy"]

        assert "default-src 'self'" in csp
        assert "script-src" in csp
        assert "style-src" in csp
        assert "img-src" in csp
        assert "frame-ancestors 'self'" in csp

    def test_custom_directives(self):
        """Should accept custom CSP directives."""
        app = FastAPI()
        custom_directives = {
            "default-src": "'none'",
            "script-src": "'nonce-{nonce}' https://cdn.example.com",
        }
        app.add_middleware(CSPNonceMiddleware, csp_directives=custom_directives)

        @app.get("/test")
        async def test_route():
            return {"ok": True}

        client = TestClient(app)
        response = client.get("/test")
        csp = response.headers["Content-Security-Policy"]

        assert "default-src 'none'" in csp
        assert "https://cdn.example.com" in csp
        # Should NOT contain default directives not in custom
        assert "frame-ancestors" not in csp


class TestCSPHeaderFormat:
    """Tests for CSP header format compliance."""

    @pytest.fixture
    def client(self):
        """Create test client with default middleware."""
        app = FastAPI()
        app.add_middleware(CSPNonceMiddleware)

        @app.get("/test")
        async def test_route():
            return {"ok": True}

        return TestClient(app)

    def test_directives_separated_by_semicolon(self, client):
        """Directives should be separated by semicolon and space."""
        response = client.get("/test")
        csp = response.headers["Content-Security-Policy"]

        # Should have multiple directives separated by "; "
        parts = csp.split("; ")
        assert len(parts) > 1

    def test_valid_nonce_format(self, client):
        """Nonce in CSP should follow 'nonce-<value>' format."""
        response = client.get("/test")
        csp = response.headers["Content-Security-Policy"]

        # Find nonce pattern
        nonce_match = re.search(r"'nonce-([A-Za-z0-9_-]+)'", csp)
        assert nonce_match is not None
        assert len(nonce_match.group(1)) == 22
