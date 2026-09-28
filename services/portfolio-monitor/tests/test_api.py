"""
Test API endpoints.

Basic smoke tests for API endpoints to ensure they respond correctly.
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create a test client for the API."""
    from main import app
    return TestClient(app)


class TestHealthEndpoint:
    """Tests for health check endpoint."""

    def test_health_returns_200(self, client):
        """Health endpoint should return 200."""
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_returns_status(self, client):
        """Health endpoint should return online field."""
        response = client.get("/health")
        data = response.json()
        assert "online" in data
        assert data["online"] is True


class TestAPIEndpoints:
    """Tests for main API endpoints."""

    def test_summary_endpoint_exists(self, client):
        """Summary endpoint should exist and return JSON."""
        response = client.get("/api/portfolio/summary")
        # May return 200 or 500 depending on config, but should not 404
        assert response.status_code != 404

    def test_etf_endpoint_exists(self, client):
        """ETF endpoint should exist."""
        response = client.get("/api/portfolio/etf")
        assert response.status_code != 404

    def test_crypto_endpoint_exists(self, client):
        """Crypto endpoint should exist."""
        response = client.get("/api/portfolio/crypto")
        assert response.status_code != 404

    def test_schedule_endpoint_exists(self, client):
        """Schedule endpoint should exist."""
        response = client.get("/api/portfolio/schedule")
        assert response.status_code == 200

    def test_schedule_returns_times(self, client):
        """Schedule endpoint should return monitor times."""
        response = client.get("/api/portfolio/schedule")
        data = response.json()
        
        # Schedule times are nested under 'schedule' key
        assert "schedule" in data
        assert "etf_time" in data["schedule"]
        assert "crypto_time" in data["schedule"]


class TestStaticFiles:
    """Tests for static file serving."""

    def test_dashboard_html_served(self, client):
        """Dashboard HTML should be served at /smart-home/portfolio."""
        response = client.get("/smart-home/portfolio")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")
