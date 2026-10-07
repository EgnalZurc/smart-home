"""Unit tests for auth_routes.py - additional tests to reach 80% coverage."""

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def app():
    """Create FastAPI app with auth router."""
    from api.auth_routes import router

    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def client(app):
    """Create test client."""
    return TestClient(app)


class TestLoginPage:
    def test_login_redirects_if_authenticated(self, client):
        with patch("api.auth_routes.auth_core.get_current_user", return_value="admin"):
            response = client.get("/api/auth/login", follow_redirects=False)

            assert response.status_code == 302
            assert response.headers["location"] == "/smart-home"

    def test_login_serves_page_if_not_authenticated(self, client):
        # Create a temp login.html
        from pathlib import Path

        with patch("api.auth_routes.auth_core.get_current_user", return_value=None):
            # Mock the login.html file read
            mock_content = '<div id="error-msg" hidden>__ERROR__</div>'
            with patch.object(Path, "read_text", return_value=mock_content):
                response = client.get("/api/auth/login")

                assert response.status_code == 200


class TestTokenEndpoint:
    def test_token_invalid_credentials(self, client):
        with (
            patch("api.auth_routes.auth_users.authenticate_user", return_value=False),
            patch.object(
                __import__("pathlib").Path,
                "read_text",
                return_value='<div id="error-msg" hidden>__ERROR__</div>',
            ),
        ):
            response = client.post(
                "/api/auth/token",
                data={"username": "baduser", "password": "badpass"},
            )

            assert response.status_code == 200
            # Should return login page with error

    def test_token_success_redirects(self, client):
        with (
            patch("api.auth_routes.auth_users.authenticate_user", return_value=True),
            patch("api.auth_routes.auth_core.create_token", return_value="test-jwt"),
            patch("api.auth_routes.auth_core.set_session_cookie"),
        ):
            response = client.post(
                "/api/auth/token",
                data={"username": "testuser", "password": "testpass"},
                follow_redirects=False,
            )

            assert response.status_code == 303
            assert response.headers["location"] == "/smart-home"

    def test_token_sanitizes_next_url(self, client):
        with (
            patch("api.auth_routes.auth_users.authenticate_user", return_value=True),
            patch("api.auth_routes.auth_core.create_token", return_value="test-jwt"),
            patch("api.auth_routes.auth_core.set_session_cookie"),
        ):
            # Try to inject external URL
            response = client.post(
                "/api/auth/token",
                data={
                    "username": "testuser",
                    "password": "testpass",
                    "next_url": "//evil.com",
                },
                follow_redirects=False,
            )

            assert response.status_code == 303
            assert response.headers["location"] == "/smart-home"

    def test_token_trusted_with_approved_request(self, client):
        approved_row = {"token": "test-token", "username": "testuser"}

        with (
            patch("api.auth_routes.auth_users.authenticate_user", return_value=True),
            patch(
                "api.auth_routes.auth_users.get_approved_trust_request",
                return_value=approved_row,
            ),
            patch(
                "api.auth_routes.auth_devices.create_device_token",
                return_value="device-cookie",
            ),
            patch("api.auth_routes.auth_users.delete_trust_request"),
            patch("api.auth_routes.auth_core.create_token", return_value="test-jwt"),
            patch("api.auth_routes.auth_core.set_session_cookie"),
        ):
            response = client.post(
                "/api/auth/token",
                data={
                    "username": "testuser",
                    "password": "testpass",
                    "trusted": "true",
                },
                follow_redirects=False,
            )

            assert response.status_code == 303

    def test_token_trusted_creates_pending_request(self, client):
        with (
            patch("api.auth_routes.auth_users.authenticate_user", return_value=True),
            patch(
                "api.auth_routes.auth_users.get_approved_trust_request",
                return_value=None,
            ),
            patch(
                "api.auth_routes.auth_users.has_active_trust_request",
                return_value=False,
            ),
            patch(
                "api.auth_routes.auth_users.create_trust_request",
                return_value="new-token-123",
            ),
            patch("api.auth_routes._send_trust_email") as mock_email,
            patch("api.auth_routes.auth_core.create_token", return_value="test-jwt"),
            patch("api.auth_routes.auth_core.set_session_cookie"),
        ):
            response = client.post(
                "/api/auth/token",
                data={
                    "username": "testuser",
                    "password": "testpass",
                    "trusted": "true",
                },
                follow_redirects=False,
            )

            assert response.status_code == 303
            mock_email.assert_called_once()


class TestLogoutEndpoint:
    def test_logout_clears_cookies(self, client):
        with (
            patch(
                "api.auth_routes.auth_devices.get_device_cookie_from_request",
                return_value=None,
            ),
            patch("api.auth_routes.auth_core.clear_session_cookie"),
        ):
            response = client.post("/api/auth/logout", follow_redirects=False)

            assert response.status_code == 303
            assert response.headers["location"] == "/api/auth/login"

    def test_logout_revokes_device_token(self, client):
        with (
            patch(
                "api.auth_routes.auth_devices.get_device_cookie_from_request",
                return_value="test-device-cookie",
            ),
            patch(
                "api.auth_routes.auth_devices._decode_cookie",
                return_value=("series123", "token456"),
            ),
            patch("api.auth_routes.auth_devices.revoke_device", return_value=True),
            patch("api.auth_routes.auth_core.clear_session_cookie"),
        ):
            response = client.post("/api/auth/logout", follow_redirects=False)

            assert response.status_code == 303


class TestMeEndpoint:
    def test_me_authenticated(self, client):
        with (
            patch(
                "api.auth_routes.auth_core.get_current_user", return_value="testuser"
            ),
            patch(
                "api.auth_routes.auth_devices.get_device_cookie_from_request",
                return_value=None,
            ),
            patch(
                "api.auth_routes.user_profiles.get_user_profiles",
                return_value=["profile1"],
            ),
            patch("api.auth_routes.user_profiles.get_effective_level", return_value=1),
            patch(
                "api.auth_routes.user_profiles.app_permissions",
                return_value=[{"key": "ac", "can_edit": True}],
            ),
            patch(
                "api.auth_routes.user_profiles.visible_external_services",
                return_value=[],
            ),
        ):
            response = client.get("/api/auth/me")

            assert response.status_code == 200
            data = response.json()
            assert data["username"] == "testuser"
            assert data["is_admin"] is False

    def test_me_not_authenticated(self, client):
        with patch("api.auth_routes.auth_core.get_current_user", return_value=None):
            response = client.get("/api/auth/me")

            assert response.status_code == 401


class TestTrustApproval:
    def test_approve_valid_signature(self, client):
        row = {"username": "testuser", "token": "test-token"}

        with (
            patch("api.auth_routes.auth_users.verify_action_sig", return_value=True),
            patch("api.auth_routes.auth_users.resolve_trust_request", return_value=row),
        ):
            response = client.get(
                "/api/auth/trust/approve",
                params={"token": "test-token", "sig": "valid"},
            )

            assert response.status_code == 200
            assert "aprobada" in response.text.lower()

    def test_approve_invalid_signature(self, client):
        with patch("api.auth_routes.auth_users.verify_action_sig", return_value=False):
            response = client.get(
                "/api/auth/trust/approve",
                params={"token": "test-token", "sig": "invalid"},
            )

            assert response.status_code == 403

    def test_approve_already_processed(self, client):
        with (
            patch("api.auth_routes.auth_users.verify_action_sig", return_value=True),
            patch(
                "api.auth_routes.auth_users.resolve_trust_request", return_value=None
            ),
        ):
            response = client.get(
                "/api/auth/trust/approve",
                params={"token": "test-token", "sig": "valid"},
            )

            assert response.status_code == 200
            assert "procesado" in response.text.lower()


class TestTrustReject:
    def test_reject_valid_signature(self, client):
        row = {"username": "testuser", "token": "test-token"}

        with (
            patch("api.auth_routes.auth_users.verify_action_sig", return_value=True),
            patch("api.auth_routes.auth_users.resolve_trust_request", return_value=row),
        ):
            response = client.get(
                "/api/auth/trust/reject", params={"token": "test-token", "sig": "valid"}
            )

            assert response.status_code == 200
            assert "rechazada" in response.text.lower()

    def test_reject_invalid_signature(self, client):
        with patch("api.auth_routes.auth_users.verify_action_sig", return_value=False):
            response = client.get(
                "/api/auth/trust/reject",
                params={"token": "test-token", "sig": "invalid"},
            )

            assert response.status_code == 403


class TestVerifyEndpoint:
    def test_verify_authenticated(self, client):
        with patch("auth.get_current_user", return_value="testuser"):
            response = client.get("/api/auth/verify")

            assert response.status_code == 200
            assert response.headers.get("X-Auth-User") == "testuser"

    def test_verify_not_authenticated(self, client):
        with patch("auth.get_current_user", return_value=None):
            response = client.get("/api/auth/verify")

            assert response.status_code == 401


# NOTE: TestAdminUserEndpoints and TestAdminProfileEndpoints have been moved
# to test_auth_admin.py since those endpoints are now in api/auth/admin.py


class TestResultPage:
    def test_result_page_success(self):
        from api.auth_routes import _result_page

        html = _result_page("Test Title", "Test message", success=True)

        assert "Test Title" in html
        assert "Test message" in html
        assert "✅" in html

    def test_result_page_failure(self):
        from api.auth_routes import _result_page

        html = _result_page("Error", "Something failed", success=False)

        assert "Error" in html
        assert "❌" in html


class TestHelpers:
    def test_serve_login_html_with_error(self):
        from pathlib import Path

        from api.auth_routes import _serve_login_html

        mock_content = '<div id="error-msg" class="hidden other">__ERROR__</div>'

        with patch.object(Path, "read_text", return_value=mock_content):
            response = _serve_login_html(error="Test error")

            assert response.status_code == 200
            assert "Test error" in response.body.decode()
