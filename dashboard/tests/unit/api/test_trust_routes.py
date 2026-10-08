"""Unit tests for trust_routes.py - trusted-device email-link endpoints."""

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def app():
    """Create FastAPI app with the trust router."""
    from api.trust_routes import router

    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def client(app):
    """Create test client."""
    return TestClient(app)


class TestTrustApproveEndpoint:
    """Tests for trust request approval."""

    @patch("api.trust_routes.auth_users")
    def test_approve_with_invalid_signature(self, mock_users, client):
        mock_users.verify_action_sig.return_value = False

        response = client.get("/api/auth/trust/approve?token=test&sig=invalid")
        assert response.status_code == 403

    @patch("api.trust_routes.auth_users")
    def test_approve_already_processed(self, mock_users, client):
        mock_users.verify_action_sig.return_value = True
        mock_users.resolve_trust_request.return_value = None

        response = client.get("/api/auth/trust/approve?token=test&sig=valid")
        assert response.status_code == 200
        assert "Ya procesado" in response.text

    @patch("api.trust_routes.auth_users")
    def test_approve_success(self, mock_users, client):
        mock_users.verify_action_sig.return_value = True
        mock_users.resolve_trust_request.return_value = {"username": "testuser"}

        response = client.get("/api/auth/trust/approve?token=test&sig=valid")
        assert response.status_code == 200
        assert "aprobada" in response.text.lower()


class TestTrustRejectEndpoint:
    """Tests for trust request rejection."""

    @patch("api.trust_routes.auth_users")
    def test_reject_success(self, mock_users, client):
        mock_users.verify_action_sig.return_value = True
        mock_users.resolve_trust_request.return_value = {"username": "testuser"}

        response = client.get("/api/auth/trust/reject?token=test&sig=valid")
        assert response.status_code == 200
        assert "rechazada" in response.text.lower()

    @patch("api.trust_routes.auth_users")
    def test_reject_invalid_signature(self, mock_users, client):
        mock_users.verify_action_sig.return_value = False

        response = client.get("/api/auth/trust/reject?token=test&sig=invalid")
        assert response.status_code == 403

    @patch("api.trust_routes.auth_users")
    def test_reject_already_processed(self, mock_users, client):
        mock_users.verify_action_sig.return_value = True
        mock_users.resolve_trust_request.return_value = None

        response = client.get("/api/auth/trust/reject?token=test&sig=valid")
        assert response.status_code == 200
        assert "procesado" in response.text.lower()


class TestResultPage:
    """Tests for the _result_page helper."""

    def test_result_page_success(self):
        from api.trust_routes import _result_page

        html = _result_page("Test Title", "Test message", success=True)
        assert "Test Title" in html
        assert "Test message" in html
        assert "✅" in html

    def test_result_page_failure(self):
        from api.trust_routes import _result_page

        html = _result_page("Error", "Something failed", success=False)
        assert "Error" in html
        assert "❌" in html
