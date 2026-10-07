"""Unit tests for valheim-admin proxy service.

valheim-admin acts as a proxy to pc-agent on the Windows PC.
These tests verify the proxy endpoints work correctly.
"""

from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

import pytest
import httpx
from fastapi import HTTPException
from fastapi.testclient import TestClient


# ── Health Endpoints ──────────────────────────────────────────────────────────


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


class TestHealthReadyEndpoint:
    """Tests for the /health/ready endpoint."""

    def test_ready_when_pc_agent_reachable(self):
        """Ready endpoint should return 200 when pc-agent is reachable."""
        from src.main import app

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            client = TestClient(app)
            response = client.get("/health/ready")

            assert response.status_code == 200
            data = response.json()
            assert data["ready"] is True
            assert data["backend_status"] == "reachable"

    def test_not_ready_when_pc_agent_unreachable(self):
        """Ready endpoint should return 503 when pc-agent is unreachable."""
        from src.main import app

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get.side_effect = httpx.ConnectError("Connection refused")
            mock_client_class.return_value.__aenter__.return_value = mock_client

            client = TestClient(app)
            response = client.get("/health/ready")

            assert response.status_code == 503
            data = response.json()["detail"]
            assert data["ready"] is False
            assert data["backend_status"] == "unreachable"

    def test_not_ready_when_pc_agent_timeout(self):
        """Ready endpoint should return 503 on timeout."""
        from src.main import app

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get.side_effect = httpx.TimeoutException("Timed out")
            mock_client_class.return_value.__aenter__.return_value = mock_client

            client = TestClient(app)
            response = client.get("/health/ready")

            assert response.status_code == 503


# ── SPA Endpoint ──────────────────────────────────────────────────────────────


class TestServeIndex:
    """Tests for the / endpoint (SPA)."""

    def test_serve_index_returns_html(self):
        """Index endpoint should return HTML content."""
        from src.main import app

        client = TestClient(app)
        response = client.get("/")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_serve_index_has_cache_headers(self):
        """Index should have no-cache headers."""
        from src.main import app

        client = TestClient(app)
        response = client.get("/")

        assert "no-cache" in response.headers.get("cache-control", "")

    def test_serve_index_missing_file(self, tmp_path):
        """Index should return fallback when file missing."""
        from src.main import app

        # Patch the path to a non-existent location
        with patch("src.main.Path") as mock_path:
            mock_instance = MagicMock()
            mock_instance.parent = tmp_path
            mock_instance.__truediv__ = lambda self, x: tmp_path / x
            mock_path.return_value = mock_instance

            # The actual path check in serve_index
            with patch.object(Path, "exists", return_value=False):
                client = TestClient(app)
                response = client.get("/")

                # Should still return 200 with fallback HTML
                assert response.status_code == 200


# ── Server Control Endpoints ──────────────────────────────────────────────────


class TestServerStatusEndpoint:
    """Tests for /api/status endpoint."""

    def test_status_returns_data_when_pc_reachable(self):
        """Status should return server data when PC is reachable."""
        from src.main import app, pc_agent

        with patch.object(
            pc_agent,
            "get",
            new_callable=AsyncMock,
            return_value={"running": True, "players": 2},
        ):
            client = TestClient(app)
            response = client.get("/api/status")

            assert response.status_code == 200
            data = response.json()
            assert data["running"] is True
            assert data["players"] == 2

    def test_status_returns_degraded_when_pc_unreachable(self):
        """Status should return degraded info when PC is unreachable."""
        from src.main import app, pc_agent

        with patch.object(
            pc_agent,
            "get",
            new_callable=AsyncMock,
            side_effect=HTTPException(503, "Service unreachable"),
        ):
            client = TestClient(app)
            response = client.get("/api/status")

            assert response.status_code == 200
            data = response.json()
            assert data["running"] is False
            assert data["pc_agent"] == "offline"


class TestServerStartEndpoint:
    """Tests for /api/server/start endpoint."""

    def test_start_server_success(self):
        """Start should proxy to pc-agent."""
        from src.main import app, pc_agent

        with patch.object(
            pc_agent,
            "post",
            new_callable=AsyncMock,
            return_value={"status": "starting"},
        ):
            client = TestClient(app)
            response = client.post("/api/server/start")

            assert response.status_code == 200
            assert response.json()["status"] == "starting"

    def test_start_server_pc_unreachable(self):
        """Start should return 503 when PC unreachable."""
        from src.main import app, pc_agent

        with patch.object(
            pc_agent,
            "post",
            new_callable=AsyncMock,
            side_effect=HTTPException(503, "Service unreachable"),
        ):
            client = TestClient(app)
            response = client.post("/api/server/start")

            assert response.status_code == 503


class TestServerStopEndpoint:
    """Tests for /api/server/stop endpoint."""

    def test_stop_server_success(self):
        """Stop should proxy to pc-agent."""
        from src.main import app, pc_agent

        with patch.object(
            pc_agent,
            "post",
            new_callable=AsyncMock,
            return_value={"status": "stopped"},
        ):
            client = TestClient(app)
            response = client.post("/api/server/stop")

            assert response.status_code == 200
            assert response.json()["status"] == "stopped"


class TestServerRestartEndpoint:
    """Tests for /api/server/restart endpoint."""

    def test_restart_server_success(self):
        """Restart should proxy to pc-agent."""
        from src.main import app, pc_agent

        with patch.object(
            pc_agent,
            "post",
            new_callable=AsyncMock,
            return_value={"status": "restarting"},
        ):
            client = TestClient(app)
            response = client.post("/api/server/restart")

            assert response.status_code == 200
            assert response.json()["status"] == "restarting"


# ── Config Endpoints ──────────────────────────────────────────────────────────


class TestConfigGetEndpoint:
    """Tests for GET /api/config endpoint."""

    def test_get_config_success(self):
        """Get config should return configuration."""
        from src.main import app, pc_agent

        config_data = {
            "server_name": "Test Server",
            "world_name": "TestWorld",
            "server_pass": "secret",
        }
        with patch.object(
            pc_agent, "get", new_callable=AsyncMock, return_value=config_data
        ):
            client = TestClient(app)
            response = client.get("/api/config")

            assert response.status_code == 200
            assert response.json()["server_name"] == "Test Server"


class TestConfigPostEndpoint:
    """Tests for POST /api/config endpoint."""

    def test_update_config_success(self):
        """Update config should send form data to pc-agent."""
        from src.main import app, pc_agent

        with patch.object(
            pc_agent,
            "post",
            new_callable=AsyncMock,
            return_value={"status": "updated"},
        ) as mock_post:
            client = TestClient(app)
            response = client.post(
                "/api/config",
                data={
                    "server_name": "New Server",
                    "world_name": "NewWorld",
                    "server_pass": "newpass",
                    "server_public": "false",
                    "crossplay": "true",
                    "save_interval": "900",
                    "backups": "3",
                },
            )

            assert response.status_code == 200
            # Verify the data was passed correctly
            call_args = mock_post.call_args
            assert call_args[0][0] == "/valheim/config"
            assert call_args[0][1]["server_name"] == "New Server"


# ── Logs Endpoint ─────────────────────────────────────────────────────────────


class TestLogsEndpoint:
    """Tests for /api/logs endpoint."""

    def test_get_logs_default_lines(self):
        """Get logs should use default line count."""
        from src.main import app, pc_agent

        with patch.object(
            pc_agent,
            "get",
            new_callable=AsyncMock,
            return_value={"logs": ["line1", "line2"]},
        ) as mock_get:
            client = TestClient(app)
            response = client.get("/api/logs")

            assert response.status_code == 200
            # Check default lines param
            call_kwargs = mock_get.call_args.kwargs
            assert call_kwargs["params"]["lines"] == "80"

    def test_get_logs_custom_lines(self):
        """Get logs should accept custom line count."""
        from src.main import app, pc_agent

        with patch.object(
            pc_agent,
            "get",
            new_callable=AsyncMock,
            return_value={"logs": ["line1"]},
        ) as mock_get:
            client = TestClient(app)
            response = client.get("/api/logs?lines=50")

            assert response.status_code == 200
            call_kwargs = mock_get.call_args.kwargs
            assert call_kwargs["params"]["lines"] == "50"


# ── Worlds Endpoints ──────────────────────────────────────────────────────────


class TestWorldsListEndpoint:
    """Tests for GET /api/worlds endpoint."""

    def test_list_worlds_success(self):
        """List worlds should return world data."""
        from src.main import app, pc_agent

        worlds_data = {"worlds": [{"name": "World1"}, {"name": "World2"}]}
        with patch.object(
            pc_agent, "get", new_callable=AsyncMock, return_value=worlds_data
        ):
            client = TestClient(app)
            response = client.get("/api/worlds")

            assert response.status_code == 200
            assert len(response.json()["worlds"]) == 2


class TestWorldsCreateEndpoint:
    """Tests for POST /api/worlds/new endpoint."""

    def test_create_world_success(self):
        """Create world should send world name to pc-agent."""
        from src.main import app, pc_agent

        with patch.object(
            pc_agent,
            "post",
            new_callable=AsyncMock,
            return_value={"created": True, "name": "NewWorld"},
        ) as mock_post:
            client = TestClient(app)
            response = client.post("/api/worlds/new", data={"world_name": "NewWorld"})

            assert response.status_code == 200
            call_args = mock_post.call_args
            assert call_args[0][1]["world_name"] == "NewWorld"


class TestWorldsActivateEndpoint:
    """Tests for POST /api/worlds/activate endpoint."""

    def test_activate_world_success(self):
        """Activate world should send world name to pc-agent."""
        from src.main import app, pc_agent

        with patch.object(
            pc_agent,
            "post",
            new_callable=AsyncMock,
            return_value={"activated": True},
        ):
            client = TestClient(app)
            response = client.post(
                "/api/worlds/activate", data={"world_name": "TestWorld"}
            )

            assert response.status_code == 200


class TestWorldsDeleteEndpoint:
    """Tests for DELETE /api/worlds/{name} endpoint."""

    def test_delete_world_success(self):
        """Delete world should call pc-agent delete."""
        from src.main import app, pc_agent

        with patch.object(
            pc_agent,
            "delete",
            new_callable=AsyncMock,
            return_value={"deleted": True},
        ) as mock_delete:
            client = TestClient(app)
            response = client.delete("/api/worlds/OldWorld")

            assert response.status_code == 200
            mock_delete.assert_called_once_with("/valheim/worlds/OldWorld")


# ── PC Control Endpoints ──────────────────────────────────────────────────────


class TestPCStatusEndpoint:
    """Tests for /api/pc/status endpoint."""

    def test_pc_status_online(self):
        """PC status should return health data when reachable."""
        from src.main import app, pc_agent

        with patch.object(
            pc_agent,
            "get",
            new_callable=AsyncMock,
            return_value={"online": True, "docker": True},
        ):
            client = TestClient(app)
            response = client.get("/api/pc/status")

            assert response.status_code == 200
            data = response.json()
            assert data["online"] is True

    def test_pc_status_offline(self):
        """PC status should indicate offline when unreachable."""
        from src.main import app, pc_agent

        with patch.object(
            pc_agent,
            "get",
            new_callable=AsyncMock,
            side_effect=HTTPException(503, "Service unreachable"),
        ):
            client = TestClient(app)
            response = client.get("/api/pc/status")

            assert response.status_code == 200
            data = response.json()
            assert data["online"] is False


class TestPCModeGetEndpoint:
    """Tests for GET /api/pc/mode endpoint."""

    def test_get_pc_mode_success(self):
        """Get PC mode should return current profile."""
        from src.main import app, pc_agent

        with patch.object(
            pc_agent,
            "get",
            new_callable=AsyncMock,
            return_value={"mode": "gaming"},
        ):
            client = TestClient(app)
            response = client.get("/api/pc/mode")

            assert response.status_code == 200
            assert response.json()["mode"] == "gaming"


class TestPCModeSetEndpoint:
    """Tests for POST /api/pc/mode/{mode} endpoint."""

    def test_set_valid_mode_gaming(self):
        """Setting gaming mode should succeed."""
        from src.main import app, pc_agent

        with patch.object(
            pc_agent,
            "post",
            new_callable=AsyncMock,
            return_value={"mode": "gaming", "applied": True},
        ):
            client = TestClient(app)
            response = client.post("/api/pc/mode/gaming")

            assert response.status_code == 200

    def test_set_valid_mode_servidor(self):
        """Setting servidor mode should succeed."""
        from src.main import app, pc_agent

        with patch.object(
            pc_agent,
            "post",
            new_callable=AsyncMock,
            return_value={"mode": "servidor", "applied": True},
        ):
            client = TestClient(app)
            response = client.post("/api/pc/mode/servidor")

            assert response.status_code == 200

    def test_set_valid_mode_balanced(self):
        """Setting balanced mode should succeed."""
        from src.main import app, pc_agent

        with patch.object(
            pc_agent,
            "post",
            new_callable=AsyncMock,
            return_value={"mode": "balanced", "applied": True},
        ):
            client = TestClient(app)
            response = client.post("/api/pc/mode/balanced")

            assert response.status_code == 200

    def test_invalid_mode_rejected(self):
        """Invalid power modes should be rejected."""
        from src.main import app

        client = TestClient(app)
        response = client.post("/api/pc/mode/invalid")

        assert response.status_code == 400


# ── Dockerfile Structure ──────────────────────────────────────────────────────


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
