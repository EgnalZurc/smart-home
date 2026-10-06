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


class TestResultPage:
    """Tests for _result_page helper."""

    def test_success_page_has_checkmark(self):
        from api.auth_routes import _result_page

        html = _result_page("Success", "It worked!", success=True)
        assert "✅" in html
        assert "Success" in html
        assert "It worked!" in html

    def test_failure_page_has_x_mark(self):
        from api.auth_routes import _result_page

        html = _result_page("Failed", "Something went wrong", success=False)
        assert "❌" in html
        assert "Failed" in html


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


class TestRequireSuper:
    """Tests for _require_super access control."""

    @patch("api.auth_routes.auth_core")
    @patch("api.auth_routes.user_profiles")
    def test_returns_username_when_super(self, mock_profiles, mock_auth):
        from api.auth_routes import _require_super

        mock_auth.get_current_user.return_value = "admin"
        mock_profiles.is_super.return_value = True
        request = MagicMock()

        result = _require_super(request)
        assert result == "admin"

    @patch("api.auth_routes.auth_core")
    def test_raises_401_when_not_authenticated(self, mock_auth):
        from api.auth_routes import _require_super
        from fastapi import HTTPException

        mock_auth.get_current_user.return_value = None
        request = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            _require_super(request)
        assert exc_info.value.status_code == 401

    @patch("api.auth_routes.auth_core")
    @patch("api.auth_routes.user_profiles")
    def test_raises_403_when_not_super(self, mock_profiles, mock_auth):
        from api.auth_routes import _require_super
        from fastapi import HTTPException

        mock_auth.get_current_user.return_value = "normaluser"
        mock_profiles.is_super.return_value = False
        request = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            _require_super(request)
        assert exc_info.value.status_code == 403


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


class TestTrustApproveEndpoint:
    """Tests for trust request approval."""

    @patch("api.auth_routes.auth_users")
    def test_approve_with_invalid_signature(self, mock_users):
        mock_users.verify_action_sig.return_value = False

        from api.auth_routes import router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        response = client.get("/api/auth/trust/approve?token=test&sig=invalid")
        assert response.status_code == 403

    @patch("api.auth_routes.auth_users")
    def test_approve_already_processed(self, mock_users):
        mock_users.verify_action_sig.return_value = True
        mock_users.resolve_trust_request.return_value = None

        from api.auth_routes import router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        response = client.get("/api/auth/trust/approve?token=test&sig=valid")
        assert response.status_code == 200
        assert "Ya procesado" in response.text

    @patch("api.auth_routes.auth_users")
    def test_approve_success(self, mock_users):
        mock_users.verify_action_sig.return_value = True
        mock_users.resolve_trust_request.return_value = {"username": "testuser"}

        from api.auth_routes import router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        response = client.get("/api/auth/trust/approve?token=test&sig=valid")
        assert response.status_code == 200
        assert "aprobada" in response.text


class TestTrustRejectEndpoint:
    """Tests for trust request rejection."""

    @patch("api.auth_routes.auth_users")
    def test_reject_success(self, mock_users):
        mock_users.verify_action_sig.return_value = True
        mock_users.resolve_trust_request.return_value = {"username": "testuser"}

        from api.auth_routes import router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        response = client.get("/api/auth/trust/reject?token=test&sig=valid")
        assert response.status_code == 200
        assert "rechazada" in response.text


class TestAdminUserEndpoints:
    """Tests for admin user management endpoints."""

    @patch("api.auth_routes.auth_core")
    @patch("api.auth_routes.user_profiles")
    @patch("api.auth_routes.auth_users")
    def test_list_users(self, mock_users, mock_profiles, mock_auth):
        mock_auth.get_current_user.return_value = "admin"
        mock_profiles.is_super.return_value = True
        mock_users.get_all_users.return_value = [
            {"id": "1", "username": "user1", "display_name": "User 1", "icon": None}
        ]
        mock_profiles.get_user_profiles_detailed.return_value = []
        mock_profiles.get_effective_level.return_value = 1

        from api.auth_routes import router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        response = client.get("/api/auth/admin/users")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["username"] == "user1"

    @patch("api.auth_routes.auth_core")
    @patch("api.auth_routes.user_profiles")
    @patch("api.auth_routes.auth_users")
    def test_create_user(self, mock_users, mock_profiles, mock_auth):
        mock_auth.get_current_user.return_value = "admin"
        mock_profiles.is_super.return_value = True
        mock_users.create_user.return_value = "new-uuid"
        mock_users.get_user_by_id.return_value = {
            "id": "new-uuid",
            "username": "newuser",
            "display_name": "New User",
            "icon": None,
        }

        from api.auth_routes import router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        response = client.post(
            "/api/auth/admin/users",
            json={"username": "newuser", "password": "password123"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "newuser"

    @patch("api.auth_routes.auth_core")
    @patch("api.auth_routes.user_profiles")
    def test_create_user_missing_username(self, mock_profiles, mock_auth):
        mock_auth.get_current_user.return_value = "admin"
        mock_profiles.is_super.return_value = True

        from api.auth_routes import router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        response = client.post(
            "/api/auth/admin/users", json={"password": "password123"}
        )
        assert response.status_code == 400

    @patch("api.auth_routes.auth_core")
    @patch("api.auth_routes.user_profiles")
    @patch("api.auth_routes.auth_users")
    def test_delete_user(self, mock_users, mock_profiles, mock_auth):
        mock_auth.get_current_user.return_value = "admin"
        mock_profiles.is_super.return_value = True
        mock_users.get_user_by_id.return_value = {
            "id": "user-id",
            "username": "todelete",
            "display_name": "To Delete",
            "icon": None,
        }
        mock_users.delete_user.return_value = None

        from api.auth_routes import router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        response = client.delete("/api/auth/admin/users/user-id")
        assert response.status_code == 200
        assert response.json()["deleted"] is True

    @patch("api.auth_routes.auth_core")
    @patch("api.auth_routes.user_profiles")
    @patch("api.auth_routes.auth_users")
    def test_cannot_delete_self(self, mock_users, mock_profiles, mock_auth):
        mock_auth.get_current_user.return_value = "admin"
        mock_profiles.is_super.return_value = True
        mock_users.get_user_by_id.return_value = {
            "id": "admin-id",
            "username": "admin",
            "display_name": "Admin",
            "icon": None,
        }

        from api.auth_routes import router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        response = client.delete("/api/auth/admin/users/admin-id")
        assert response.status_code == 400


class TestAdminProfileEndpoints:
    """Tests for admin profile management endpoints."""

    @patch("api.auth_routes.auth_core")
    @patch("api.auth_routes.user_profiles")
    def test_list_profiles(self, mock_profiles, mock_auth):
        mock_auth.get_current_user.return_value = "admin"
        mock_profiles.is_super.return_value = True
        mock_profiles.get_all_profiles.return_value = {
            "SUPER": {
                "name": "SUPER",
                "level": 0,
                "description": "Admin",
                "protected": True,
            }
        }

        from api.auth_routes import router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        response = client.get("/api/auth/admin/profiles")
        assert response.status_code == 200
        data = response.json()
        assert "SUPER" in data

    @patch("api.auth_routes.auth_core")
    @patch("api.auth_routes.user_profiles")
    def test_create_profile(self, mock_profiles, mock_auth):
        mock_auth.get_current_user.return_value = "admin"
        mock_profiles.is_super.return_value = True
        mock_profiles.create_profile.return_value = "new-profile-id"

        from api.auth_routes import router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        response = client.post(
            "/api/auth/admin/profiles",
            json={"name": "CUSTOM", "level": 2, "description": "Custom profile"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "CUSTOM"
        assert data["level"] == 2

    @patch("api.auth_routes.auth_core")
    @patch("api.auth_routes.user_profiles")
    def test_create_profile_invalid_level(self, mock_profiles, mock_auth):
        mock_auth.get_current_user.return_value = "admin"
        mock_profiles.is_super.return_value = True

        from api.auth_routes import router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        response = client.post(
            "/api/auth/admin/profiles",
            json={"name": "BAD", "level": 5, "description": "Invalid"},
        )
        assert response.status_code == 400

    @patch("api.auth_routes.auth_core")
    @patch("api.auth_routes.user_profiles")
    def test_delete_profile(self, mock_profiles, mock_auth):
        mock_auth.get_current_user.return_value = "admin"
        mock_profiles.is_super.return_value = True
        mock_profiles.delete_profile.return_value = None

        from api.auth_routes import router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        response = client.delete("/api/auth/admin/profiles/custom-id")
        assert response.status_code == 200
        assert response.json()["deleted"] == "custom-id"
