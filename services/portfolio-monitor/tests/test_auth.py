"""
Tests for bearer token authentication on POST endpoints.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def reset_rate_limiters():
    """Reset rate limiters before each test."""
    from api.routes import _config_limiter, _refresh_limiter

    _refresh_limiter._data.clear()
    _config_limiter._data.clear()
    yield
    _refresh_limiter._data.clear()
    _config_limiter._data.clear()


@pytest.fixture
def mock_orchestrator():
    """Mock orchestrator for control endpoints."""
    mock_orch = MagicMock()
    mock_orch.run_all_monitors = MagicMock(return_value=None)
    mock_orch.run_monitor = MagicMock(return_value=None)
    mock_orch.reload_config = MagicMock(return_value=None)
    mock_orch._load_upcoming_alerts = MagicMock(return_value=None)
    with patch("api.routes.get_orchestrator", return_value=mock_orch):
        yield mock_orch


class TestAuthDisabled:
    """Tests when AUTH_TOKEN is not configured (backwards compat)."""

    @pytest.fixture
    def client_no_auth(self):
        """Test client with auth disabled (no AUTH_TOKEN)."""
        with patch("api.routes.auth._get_auth_token", return_value=""):
            from main import app

            with TestClient(app) as client:
                yield client

    def test_refresh_all_no_auth_required(self, client_no_auth, mock_orchestrator):
        """POST /refresh works without auth when AUTH_TOKEN not set."""
        response = client_no_auth.post("/api/portfolio/refresh")
        assert response.status_code == 200
        assert response.json()["status"] == "refresh_started"

    def test_refresh_monitor_no_auth_required(self, client_no_auth, mock_orchestrator):
        """POST /refresh/{monitor} works without auth when AUTH_TOKEN not set."""
        response = client_no_auth.post("/api/portfolio/refresh/etf")
        assert response.status_code == 200
        assert response.json()["status"] == "refresh_started"

    def test_reload_config_no_auth_required(self, client_no_auth, mock_orchestrator):
        """POST /reload-config works without auth when AUTH_TOKEN not set."""
        response = client_no_auth.post("/api/portfolio/reload-config")
        assert response.status_code == 200
        assert response.json()["status"] == "config_reloaded"


class TestAuthEnabled:
    """Tests when AUTH_TOKEN is configured."""

    @pytest.fixture
    def client_with_auth(self):
        """Test client with auth enabled (AUTH_TOKEN set)."""
        with patch("api.routes.auth._get_auth_token", return_value="test-secret-token"):
            from main import app

            with TestClient(app) as client:
                yield client

    def test_missing_auth_header_returns_401(self, client_with_auth, mock_orchestrator):
        """POST without Authorization header returns 401."""
        response = client_with_auth.post("/api/portfolio/refresh")
        assert response.status_code == 401
        assert "Authorization header required" in response.json()["detail"]
        assert response.headers.get("WWW-Authenticate") == "Bearer"

    def test_invalid_auth_format_returns_401(self, client_with_auth, mock_orchestrator):
        """POST with malformed Authorization header returns 401."""
        response = client_with_auth.post(
            "/api/portfolio/refresh",
            headers={"Authorization": "Basic dXNlcjpwYXNz"},
        )
        assert response.status_code == 401
        assert "Invalid authorization header format" in response.json()["detail"]

    def test_invalid_token_returns_403(self, client_with_auth, mock_orchestrator):
        """POST with wrong token returns 403."""
        response = client_with_auth.post(
            "/api/portfolio/refresh",
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert response.status_code == 403
        assert "Invalid token" in response.json()["detail"]

    def test_valid_token_allows_request(self, client_with_auth, mock_orchestrator):
        """POST with valid token succeeds."""
        response = client_with_auth.post(
            "/api/portfolio/refresh",
            headers={"Authorization": "Bearer test-secret-token"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "refresh_started"

    def test_bearer_case_insensitive(self, client_with_auth, mock_orchestrator):
        """Bearer prefix is case-insensitive."""
        response = client_with_auth.post(
            "/api/portfolio/refresh",
            headers={"Authorization": "BEARER test-secret-token"},
        )
        assert response.status_code == 200

    def test_refresh_monitor_requires_auth(self, client_with_auth, mock_orchestrator):
        """POST /refresh/{monitor} requires auth when enabled."""
        # Without auth
        response = client_with_auth.post("/api/portfolio/refresh/etf")
        assert response.status_code == 401

        # With auth
        response = client_with_auth.post(
            "/api/portfolio/refresh/etf",
            headers={"Authorization": "Bearer test-secret-token"},
        )
        assert response.status_code == 200

    def test_reload_config_requires_auth(self, client_with_auth, mock_orchestrator):
        """POST /reload-config requires auth when enabled."""
        # Without auth
        response = client_with_auth.post("/api/portfolio/reload-config")
        assert response.status_code == 401

        # With auth
        response = client_with_auth.post(
            "/api/portfolio/reload-config",
            headers={"Authorization": "Bearer test-secret-token"},
        )
        assert response.status_code == 200


class TestAlertCompleteAuth:
    """Tests for alert completion endpoint authentication."""

    @pytest.fixture
    def mock_alerts(self, mock_orchestrator):
        """Mock alert functions."""
        mock_alert = MagicMock()
        mock_alert.alert_id = "test-alert"

        with patch("alerts.get_all_alerts", return_value=[mock_alert]):
            with patch("alerts.mark_alert_completed", return_value=True):
                yield

    @pytest.fixture
    def client_no_auth(self, mock_alerts):
        """Test client with auth disabled (no AUTH_TOKEN)."""
        with patch("api.routes.auth._get_auth_token", return_value=""):
            from main import app

            with TestClient(app) as client:
                yield client

    @pytest.fixture
    def client_with_auth(self, mock_alerts):
        """Test client with auth enabled (AUTH_TOKEN set)."""
        with patch("api.routes.auth._get_auth_token", return_value="test-secret-token"):
            from main import app

            with TestClient(app) as client:
                yield client

    def test_complete_alert_no_auth_when_disabled(self, client_no_auth):
        """POST /alerts/{id}/complete works without auth when disabled."""
        response = client_no_auth.post("/api/portfolio/alerts/test-alert/complete")
        assert response.status_code == 200
        assert response.json()["status"] == "completed"

    def test_complete_alert_requires_auth_when_enabled(self, client_with_auth):
        """POST /alerts/{id}/complete requires auth when enabled."""
        # Without auth
        response = client_with_auth.post("/api/portfolio/alerts/test-alert/complete")
        assert response.status_code == 401

        # With auth
        response = client_with_auth.post(
            "/api/portfolio/alerts/test-alert/complete",
            headers={"Authorization": "Bearer test-secret-token"},
        )
        assert response.status_code == 200


class TestNotificationAuth:
    """Tests for notification test endpoint authentication."""

    @pytest.fixture
    def mock_notifier(self):
        """Mock email notifier."""
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.message = "Test sent"

        mock_notifier_instance = MagicMock()
        mock_notifier_instance.enabled = True
        mock_notifier_instance.send_test.return_value = mock_result

        with patch("email_notifier.EmailNotifier", return_value=mock_notifier_instance):
            yield

    @pytest.fixture
    def client_no_auth(self, mock_notifier):
        """Test client with auth disabled (no AUTH_TOKEN)."""
        with patch("api.routes.auth._get_auth_token", return_value=""):
            from main import app

            with TestClient(app) as client:
                yield client

    @pytest.fixture
    def client_with_auth(self, mock_notifier):
        """Test client with auth enabled (AUTH_TOKEN set)."""
        with patch("api.routes.auth._get_auth_token", return_value="test-secret-token"):
            from main import app

            with TestClient(app) as client:
                yield client

    def test_notification_test_no_auth_when_disabled(self, client_no_auth):
        """POST /notifications/test works without auth when disabled."""
        response = client_no_auth.post("/api/portfolio/notifications/test")
        assert response.status_code == 200
        assert response.json()["status"] == "sent"

    def test_notification_test_requires_auth_when_enabled(self, client_with_auth):
        """POST /notifications/test requires auth when enabled."""
        # Without auth
        response = client_with_auth.post("/api/portfolio/notifications/test")
        assert response.status_code == 401

        # With auth
        response = client_with_auth.post(
            "/api/portfolio/notifications/test",
            headers={"Authorization": "Bearer test-secret-token"},
        )
        assert response.status_code == 200


class TestGetEndpointsNoAuth:
    """Verify GET endpoints remain unprotected."""

    @pytest.fixture
    def client(self, mock_orchestrator):
        """Test client with auth enabled but for GET requests."""
        with patch("api.routes.auth._get_auth_token", return_value="test-secret-token"):
            from main import app

            with TestClient(app) as client:
                yield client

    def test_health_no_auth(self, client):
        """GET /health works without auth even when enabled."""
        response = client.get("/health")
        assert response.status_code == 200

    def test_schedule_no_auth(self, client, mock_orchestrator):
        """GET /schedule works without auth even when enabled."""
        mock_orchestrator.get_schedule.return_value = {}
        mock_orchestrator.get_next_run_times.return_value = {}
        response = client.get("/api/portfolio/schedule")
        assert response.status_code == 200
