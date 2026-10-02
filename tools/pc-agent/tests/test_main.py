"""Tests for pc-agent.

Note: These tests mock Docker to run in CI (where Docker isn't available).
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture
def mock_docker():
    """Mock Docker client."""
    with patch.dict("sys.modules", {"docker": MagicMock()}):
        yield


@pytest.fixture
def mock_env(tmp_path):
    """Mock environment variables."""
    env_file = tmp_path / ".env"
    env_file.write_text("PC_AGENT_TOKEN=test-token\n")
    return {
        "PC_AGENT_TOKEN": "test-token",
        "VALHEIM_CONTAINER": "valheim-server",
        "VALHEIM_SERVER_DIR": str(tmp_path),
        "SCRIPTS_DIR": str(tmp_path / "scripts"),
    }


class TestHealthEndpoint:
    """Health endpoint tests."""

    def test_health_returns_online(self, mock_docker, mock_env):
        """Health endpoint should return online status."""
        with patch.dict("os.environ", mock_env):
            # Import after mocking
            with patch("docker.from_env") as mock_client:
                mock_client.return_value.ping.return_value = True
                
                from main import app
                from fastapi.testclient import TestClient
                
                client = TestClient(app)
                response = client.get("/health")
                
                assert response.status_code == 200
                data = response.json()
                assert data["online"] is True
                assert data["service"] == "pc-agent"


class TestAuthRequired:
    """Authentication tests."""

    def test_valheim_status_requires_token(self, mock_docker, mock_env):
        """Valheim endpoints should require auth token."""
        with patch.dict("os.environ", mock_env):
            with patch("docker.from_env") as mock_client:
                mock_client.return_value.ping.return_value = True
                
                from main import app
                from fastapi.testclient import TestClient
                
                client = TestClient(app)
                
                # Without token should fail
                response = client.get("/valheim/status")
                assert response.status_code == 401

    def test_valheim_status_with_token(self, mock_docker, mock_env):
        """Valheim endpoints should work with valid token."""
        with patch.dict("os.environ", mock_env):
            with patch("docker.from_env") as mock_client:
                # Setup mock container
                mock_container = MagicMock()
                mock_container.status = "running"
                mock_container.attrs = {"State": {"StartedAt": "2024-01-01T00:00:00Z"}}
                mock_client.return_value.containers.get.return_value = mock_container
                mock_client.return_value.ping.return_value = True
                
                from main import app
                from fastapi.testclient import TestClient
                
                client = TestClient(app)
                
                # With token should work
                response = client.get(
                    "/valheim/status",
                    headers={"X-Api-Token": "test-token"}
                )
                assert response.status_code == 200


class TestPowerMode:
    """Power profile tests."""

    def test_invalid_mode_rejected(self, mock_docker, mock_env):
        """Invalid power modes should be rejected."""
        with patch.dict("os.environ", mock_env):
            with patch("docker.from_env") as mock_client:
                mock_client.return_value.ping.return_value = True
                
                from main import app
                from fastapi.testclient import TestClient
                
                client = TestClient(app)
                
                response = client.post(
                    "/system/mode/invalid",
                    headers={"X-Api-Token": "test-token"}
                )
                assert response.status_code == 400
