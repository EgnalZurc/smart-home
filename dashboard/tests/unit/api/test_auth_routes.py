"""Unit tests for auth_routes.py - authentication API endpoints."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def create_test_app():
    """Create a FastAPI app with auth routes for testing."""
    # Patch modules before importing auth_routes
    with (
        patch("auth_users.AUTH_DB_PATH", ":memory:"),
        patch("auth_users.HTPASSWD_PATH", "/nonexistent"),
        patch("auth_users.TRUST_SECRET", "test-secret"),
        patch("auth_devices.AUTH_DB_PATH", ":memory:"),
        patch("auth.AUTH_SECRET", "test-secret-key-32-chars"),
    ):
        from api import auth_routes

        app = FastAPI()
        app.include_router(auth_routes.router)
        return app, auth_routes


class TestServeLoginHtml:
    """Tests for _serve_login_html helper."""

    def test_returns_html_response(self):
        # Provide a simple HTML template that has the pattern we look for
        mock_html = '<div id="error-msg" class="hidden">__ERROR__</div>'
        with patch("pathlib.Path.read_text", return_value=mock_html):
            from api.auth_routes import _serve_login_html

            response = _serve_login_html()
            assert response.status_code == 200
            assert "text/html" in response.headers.get("content-type", "")

    def test_injects_error_message(self):
        mock_html = '<div id="error-msg" class="hidden">__ERROR__</div>'
        with patch("pathlib.Path.read_text", return_value=mock_html):
            from api.auth_routes import _serve_login_html

            response = _serve_login_html(error="Test error")
            body = response.body.decode()
            assert "Test error" in body
            # 'hidden' class should be removed
            assert 'id="error-msg"' in body


class TestDeviceCookieHelpers:
    """Tests for cookie helper functions."""

    def test_set_device_cookie(self):
        from api.auth_routes import _set_device_cookie

        response = MagicMock()
        _set_device_cookie(response, "series:token")

        response.set_cookie.assert_called_once()
        kwargs = response.set_cookie.call_args.kwargs
        assert kwargs["key"] == "smh_device"
        assert kwargs["value"] == "series:token"
        assert kwargs["httponly"] is True
        assert kwargs["secure"] is True

    def test_clear_device_cookie(self):
        from api.auth_routes import _clear_device_cookie

        response = MagicMock()
        _clear_device_cookie(response)

        response.delete_cookie.assert_called_once()
        kwargs = response.delete_cookie.call_args.kwargs
        assert kwargs["key"] == "smh_device"


class TestSendTrustEmail:
    """Tests for trust email sending."""

    @patch("api.auth_routes.smtplib.SMTP")
    @patch("api.auth_routes.auth_users")
    def test_sends_email_successfully(self, mock_users, mock_smtp):
        from api.auth_routes import _send_trust_email

        mock_users.make_action_url.side_effect = lambda base, token, action: (
            f"{base}/api/auth/trust/{action}?token={token}&sig=test"
        )

        mock_server = MagicMock()
        mock_smtp.return_value.__enter__.return_value = mock_server

        with (
            patch("api.auth_routes.SMTP_USER", "test@test.com"),
            patch("api.auth_routes.SMTP_PASSWORD", "password"),
        ):
            _send_trust_email("testuser", "Mozilla/5.0", "192.168.1.1", "test-token")

        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once()
        mock_server.sendmail.assert_called_once()

    @patch("api.auth_routes.smtplib.SMTP")
    @patch("api.auth_routes.auth_users")
    def test_logs_error_on_failure(self, mock_users, mock_smtp):
        from api.auth_routes import _send_trust_email

        mock_users.make_action_url.return_value = "http://test"
        mock_smtp.side_effect = Exception("SMTP error")

        with (
            patch("api.auth_routes.SMTP_USER", "test@test.com"),
            patch("api.auth_routes.SMTP_PASSWORD", "password"),
            patch("api.auth_routes.logger") as mock_logger,
        ):
            _send_trust_email("testuser", "UA", "IP", "token")

        mock_logger.error.assert_called()


class TestVerifyEndpoint:
    """Tests for the nginx auth_request endpoint."""

    def test_returns_200_for_authenticated_user(self):
        from api.auth_routes import router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        with patch(
            "api.auth_routes.auth_core.get_current_user", return_value="testuser"
        ):
            response = client.get("/api/auth/verify")
        assert response.status_code == 200
        assert response.headers.get("x-auth-user") == "testuser"

    def test_returns_401_for_unauthenticated(self):
        from api.auth_routes import router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        with patch("api.auth_routes.auth_core.get_current_user", return_value=None):
            response = client.get("/api/auth/verify")
        assert response.status_code == 401


class TestGetMeEndpoint:
    """Tests for /api/auth/me endpoint."""

    @patch("api.auth_routes.auth_core")
    @patch("api.auth_routes.user_profiles")
    @patch("api.auth_routes.auth_devices")
    def test_returns_user_info(self, mock_devices, mock_profiles, mock_auth):
        mock_auth.get_current_user.return_value = "testuser"
        mock_devices.get_device_cookie_from_request.return_value = None
        mock_profiles.get_user_profiles.return_value = ["SUPER"]
        mock_profiles.get_effective_level.return_value = 0
        mock_profiles.app_permissions.return_value = ["ac", "vacaciones"]
        mock_profiles.visible_external_services.return_value = []

        from api.auth_routes import router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        response = client.get("/api/auth/me")
        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "testuser"
        assert data["is_admin"] is True
        assert "apps" in data

    @patch("api.auth_routes.auth_core")
    def test_returns_401_when_not_authenticated(self, mock_auth):
        mock_auth.get_current_user.return_value = None

        from api.auth_routes import router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        response = client.get("/api/auth/me")
        assert response.status_code == 401


# NOTE: TestResultPage, TestTrustApproveEndpoint and TestTrustRejectEndpoint have
# been moved to test_trust_routes.py since those endpoints and the _result_page
# helper are now in api/trust_routes.py.
# NOTE: TestAdminUserEndpoints and TestAdminProfileEndpoints have been moved
# to test_auth_admin.py since those endpoints are now in api/auth/admin.py
