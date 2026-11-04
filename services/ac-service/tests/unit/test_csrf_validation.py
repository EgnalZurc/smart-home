"""Unit tests for CSRF Origin/Referer validation.

Tests the fail-closed CSRF protection behavior:
- State-changing requests (POST/PUT/DELETE) require Origin OR Referer
- Both headers must be from allowed origins
- Health check paths are exempt
- GET/HEAD/OPTIONS always pass
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Mock the dependencies before importing main
with patch.dict(
    "os.environ",
    {
        "MELCLOUD_EMAIL": "test@test.com",
        "MELCLOUD_PASSWORD": "testpwd",
        "MELCLOUD_DEVICE_ID": "12345",
        "MELCLOUD_BUILDING_ID": "67890",
    },
):
    from main import app


@pytest.fixture
def client():
    """Create test client without lifespan."""
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def mock_components():
    """Mock all global components for control endpoint tests."""
    import main

    mock_controller = MagicMock()
    mock_state = MagicMock()
    mock_state.control_mode = "auto"
    mock_controller.state = mock_state
    mock_controller.current_state = mock_state

    mock_event_log = MagicMock()

    original_controller = main.ac_controller
    original_event_log = main.event_log

    main.ac_controller = mock_controller
    main.event_log = mock_event_log

    yield {"ac_controller": mock_controller, "event_log": mock_event_log}

    main.ac_controller = original_controller
    main.event_log = original_event_log


class TestCSRFValidation:
    """Tests for CSRF Origin/Referer validation."""

    # ── Missing Origin/Referer tests ──────────────────────────────────────────

    def test_post_without_origin_or_referer_rejected(self, client, mock_components):
        """POST without Origin or Referer should be rejected with 403."""
        response = client.post(
            "/api/ac/control",
            json={"mode": "auto"},
            headers={},  # No Origin or Referer
        )

        assert response.status_code == 403
        assert "Missing Origin/Referer header" in response.json()["detail"]

    def test_put_without_origin_or_referer_rejected(self, client, mock_components):
        """PUT without Origin or Referer should be rejected with 403."""
        response = client.request(
            "PUT",
            "/api/ac/config",
            json={"target_temperature": 23.0},
            headers={},
        )

        assert response.status_code == 403
        assert "Missing Origin/Referer header" in response.json()["detail"]

    def test_delete_without_origin_or_referer_rejected(self, client, mock_components):
        """DELETE without Origin or Referer should be rejected with 403."""
        response = client.request(
            "DELETE",
            "/api/ac/config",
            headers={},
        )

        assert response.status_code == 403
        assert "Missing Origin/Referer header" in response.json()["detail"]

    # ── Invalid Origin tests ──────────────────────────────────────────────────

    def test_post_with_invalid_origin_rejected(self, client, mock_components):
        """POST with invalid Origin should be rejected with 403."""
        response = client.post(
            "/api/ac/control",
            json={"mode": "auto"},
            headers={"Origin": "https://evil.com"},
        )

        assert response.status_code == 403
        assert "Invalid origin" in response.json()["detail"]

    def test_post_with_invalid_referer_rejected(self, client, mock_components):
        """POST with invalid Referer (no Origin) should be rejected with 403."""
        response = client.post(
            "/api/ac/control",
            json={"mode": "auto"},
            headers={"Referer": "https://evil.com/some/path"},
        )

        assert response.status_code == 403
        assert "Invalid referer origin" in response.json()["detail"]

    # ── Valid Origin tests ────────────────────────────────────────────────────

    def test_post_with_valid_origin_allowed(self, client, mock_components):
        """POST with valid Origin should be allowed."""
        response = client.post(
            "/api/ac/control",
            json={"mode": "auto"},
            headers={"Origin": "http://localhost"},
        )

        # Should pass CSRF and get to the endpoint (200 or other non-403)
        assert response.status_code != 403

    def test_post_with_tailscale_origin_allowed(self, client, mock_components):
        """POST with Tailscale Origin should be allowed."""
        response = client.post(
            "/api/ac/control",
            json={"mode": "auto"},
            headers={"Origin": "https://raspberrypi.tailaa37cd.ts.net"},
        )

        assert response.status_code != 403

    def test_post_with_valid_referer_allowed(self, client, mock_components):
        """POST with valid Referer (no Origin) should be allowed."""
        response = client.post(
            "/api/ac/control",
            json={"mode": "auto"},
            headers={"Referer": "http://localhost/some/path?query=value"},
        )

        assert response.status_code != 403

    def test_post_with_tailscale_referer_allowed(self, client, mock_components):
        """POST with Tailscale Referer (no Origin) should be allowed."""
        response = client.post(
            "/api/ac/control",
            json={"mode": "auto"},
            headers={
                "Referer": "https://raspberrypi.tailaa37cd.ts.net/smart-home/ac?tab=config"
            },
        )

        assert response.status_code != 403

    # ── Safe method tests ─────────────────────────────────────────────────────

    def test_get_without_origin_allowed(self, client, mock_components):
        """GET without Origin should always be allowed."""
        response = client.get("/api/ac/status", headers={})

        # Should not be 403 for CSRF reasons
        assert response.status_code != 403

    def test_options_without_origin_allowed(self, client, mock_components):
        """OPTIONS without Origin should always be allowed."""
        response = client.options("/api/ac/control", headers={})

        # OPTIONS is a safe method, should not be rejected
        assert response.status_code != 403

    # ── Health check exemption tests ──────────────────────────────────────────

    def test_health_check_exempt_from_csrf(self, client):
        """Health check endpoints should be exempt from CSRF checks."""
        # Test /health endpoint
        response = client.get("/health", headers={})
        assert response.status_code == 200

        # Test /api/health/ac endpoint
        response = client.get("/api/health/ac", headers={})
        assert response.status_code == 200

    # ── Security headers on rejection ─────────────────────────────────────────

    def test_csrf_rejection_includes_security_headers(self, client, mock_components):
        """CSRF rejection response should include security headers."""
        response = client.post(
            "/api/ac/control",
            json={"mode": "auto"},
            headers={},  # No Origin or Referer
        )

        assert response.status_code == 403
        assert response.headers.get("X-Content-Type-Options") == "nosniff"
        assert response.headers.get("X-Frame-Options") == "DENY"
        assert "Content-Security-Policy" in response.headers


class TestCSRFOriginExtraction:
    """Tests for Referer header origin extraction."""

    def test_referer_with_port_extracts_correctly(self, client, mock_components):
        """Referer with port should extract origin correctly."""
        response = client.post(
            "/api/ac/control",
            json={"mode": "auto"},
            headers={"Referer": "http://localhost:8002/api/ac/config"},
        )

        # localhost:8002 is in allowed origins
        assert response.status_code != 403

    def test_referer_without_path_extracts_correctly(self, client, mock_components):
        """Referer without path should extract origin correctly."""
        response = client.post(
            "/api/ac/control",
            json={"mode": "auto"},
            headers={"Referer": "http://localhost"},
        )

        assert response.status_code != 403

    def test_malformed_referer_rejected(self, client, mock_components):
        """Malformed Referer should be rejected."""
        response = client.post(
            "/api/ac/control",
            json={"mode": "auto"},
            headers={"Referer": "not-a-valid-url"},
        )

        assert response.status_code == 403


class TestCSRFWithRealEndpoints:
    """Integration tests for CSRF with actual endpoints."""

    def test_config_post_requires_origin(self, client, mock_components):
        """POST /api/ac/config requires Origin or Referer."""
        # Without Origin/Referer
        response = client.post("/api/ac/config", json={"target_temperature": 23.0})
        assert response.status_code == 403

        # With valid Origin
        response = client.post(
            "/api/ac/config",
            json={"target_temperature": 23.0},
            headers={"Origin": "http://localhost"},
        )
        assert response.status_code != 403

    def test_manual_post_requires_origin(self, client, mock_components):
        """POST /api/ac/manual requires Origin or Referer."""
        mock_components["ac_controller"].melcloud = MagicMock()
        mock_components["ac_controller"].melcloud.set_temperature.return_value = True

        # Without Origin/Referer
        response = client.post(
            "/api/ac/manual",
            json={"mode": "cool", "fan_speed": 0, "temperature": 23.0},
        )
        assert response.status_code == 403

        # With valid Origin
        response = client.post(
            "/api/ac/manual",
            json={"mode": "cool", "fan_speed": 0, "temperature": 23.0},
            headers={"Origin": "http://localhost"},
        )
        assert response.status_code != 403
