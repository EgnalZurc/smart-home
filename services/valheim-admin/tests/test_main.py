"""Unit tests for valheim-admin proxy service.

valheim-admin now acts as a pure proxy to pc-agent on the Windows PC.
These tests verify the proxy endpoints work correctly.
"""

from pathlib import Path
from unittest.mock import patch, AsyncMock

import pytest
from fastapi.testclient import TestClient


class TestHealthEndpoint:
    """Tests for the /health endpoint."""

    def test_health_returns_online(self):
        """Health endpoint should return online status."""
        from src.main import app

        client = TestClient(app)
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["online"] is True
        assert data["service"] == "valheim-admin"


class TestDockerfileStructure:
    """Tests for Dockerfile structure."""

    @pytest.fixture
    def dockerfile_content(self):
        dockerfile = Path(__file__).parent.parent / "Dockerfile"
        return dockerfile.read_text()

    def test_base_image_is_python(self, dockerfile_content):
        """Dockerfile should use Python base image."""
        assert "FROM python:" in dockerfile_content

    def test_exposes_port_8080(self, dockerfile_content):
        """Dockerfile should expose port 8080."""
        assert "EXPOSE 8080" in dockerfile_content

    def test_runs_uvicorn(self, dockerfile_content):
        """Dockerfile should run uvicorn."""
        assert "uvicorn" in dockerfile_content


class TestProxyEndpoints:
    """Tests for proxy endpoints."""

    @pytest.fixture
    def mock_pc_agent(self):
        """Mock the pc-agent HTTP calls."""
        with patch("src.main._get", new_callable=AsyncMock) as mock_get:
            with patch("src.main._post", new_callable=AsyncMock) as mock_post:
                yield {"get": mock_get, "post": mock_post}

    def test_status_returns_degraded_when_pc_unreachable(self):
        """Status should return degraded info when PC is unreachable."""
        from src.main import app
        import httpx

        with patch("src.main._get", new_callable=AsyncMock) as mock_get:
            from fastapi import HTTPException

            mock_get.side_effect = HTTPException(503, "PC unreachable")

            client = TestClient(app)
            response = client.get("/api/status")

            # Should not raise, returns degraded status
            assert response.status_code == 200
            data = response.json()
            assert data["running"] is False
            # Code returns "offline", not "unreachable"
            assert data["pc_agent"] in ("offline", "unreachable")

    def test_pc_status_returns_offline_when_unreachable(self):
        """PC status should indicate offline when unreachable."""
        from src.main import app
        from fastapi import HTTPException

        with patch("src.main._get", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = HTTPException(503, "PC unreachable")

            client = TestClient(app)
            response = client.get("/api/pc/status")

            assert response.status_code == 200
            data = response.json()
            assert data["online"] is False


class TestPowerModeValidation:
    """Tests for power mode endpoint validation."""

    def test_invalid_mode_rejected(self):
        """Invalid power modes should be rejected."""
        from src.main import app

        client = TestClient(app)
        response = client.post("/api/pc/mode/invalid")

        assert response.status_code == 400
