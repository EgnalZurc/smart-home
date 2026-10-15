"""Unit tests for valheim-admin proxy service.

valheim-admin acts as a proxy to pc-agent on the Windows PC.
These tests verify the proxy endpoints work correctly.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
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
        from src.main import app, pc_agent

        with patch.object(
            pc_agent,
            "get",
            new_callable=AsyncMock,
            return_value={"online": True, "docker": True},
        ):
            client = TestClient(app)
            response = client.get("/health/ready")

            assert response.status_code == 200
            data = response.json()
            assert data["ready"] is True
            assert data["backend_status"] == "reachable"

    def test_not_ready_when_pc_agent_unreachable(self):
        """Ready endpoint should return 503 when pc-agent is unreachable."""
        from src.main import app, pc_agent

        with patch.object(
            pc_agent,
            "get",
            new_callable=AsyncMock,
            side_effect=httpx.ConnectError("Connection refused"),
        ):
            client = TestClient(app)
            response = client.get("/health/ready")

            assert response.status_code == 503
            data = response.json()["detail"]
            assert data["ready"] is False
            assert data["backend_status"] == "unreachable"

    def test_not_ready_when_pc_agent_timeout(self):
        """Ready endpoint should return 503 on timeout."""
        from src.main import app, pc_agent

        with patch.object(
            pc_agent,
            "get",
            new_callable=AsyncMock,
            side_effect=httpx.TimeoutException("Timed out"),
        ):
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


# ── world_name Validation ─────────────────────────────────────────────────────


class TestWorldNameValidation:
    """Tests for the validate_world_name helper and the endpoints using it."""

    def test_validate_accepts_valid_names(self):
        """Alphanumeric names with underscore/hyphen should pass unchanged."""
        from src.main import validate_world_name

        for name in ("MyWorld", "world_1", "a-b-c", "A1_2-3", "x" * 64):
            assert validate_world_name(name) == name

    def test_validate_rejects_empty(self):
        """Empty names should raise 400."""
        from src.main import validate_world_name

        with pytest.raises(HTTPException) as exc:
            validate_world_name("")
        assert exc.value.status_code == 400

    def test_validate_rejects_too_long(self):
        """Names longer than 64 chars should raise 400."""
        from src.main import validate_world_name

        with pytest.raises(HTTPException) as exc:
            validate_world_name("x" * 65)
        assert exc.value.status_code == 400

    @pytest.mark.parametrize(
        "bad_name",
        [
            "../etc/passwd",
            "world/sub",
            "world name",
            "world;rm -rf /",
            "world$(whoami)",
            "world`id`",
            "world|cat",
            "world&echo",
            "world.bak",
            "wörld",
            "world\x00",
        ],
    )
    def test_validate_rejects_injection_chars(self, bad_name):
        """Path traversal and shell metacharacters should raise 400."""
        from src.main import validate_world_name

        with pytest.raises(HTTPException) as exc:
            validate_world_name(bad_name)
        assert exc.value.status_code == 400

    def test_update_config_rejects_bad_world_name(self):
        """POST /api/config with an invalid world_name should return 400."""
        from src.main import app, pc_agent

        with patch.object(pc_agent, "post", new_callable=AsyncMock) as mock_post:
            client = TestClient(app)
            response = client.post(
                "/api/config",
                data={
                    "server_name": "New Server",
                    "world_name": "../evil",
                    "server_pass": "newpass",
                    "server_public": "false",
                    "crossplay": "true",
                    "save_interval": "900",
                    "backups": "3",
                },
            )

            assert response.status_code == 400
            mock_post.assert_not_called()

    def test_create_world_rejects_bad_world_name(self):
        """POST /api/worlds/new with an invalid world_name should return 400."""
        from src.main import app, pc_agent

        with patch.object(pc_agent, "post", new_callable=AsyncMock) as mock_post:
            client = TestClient(app)
            response = client.post(
                "/api/worlds/new", data={"world_name": "world;rm -rf /"}
            )

            assert response.status_code == 400
            mock_post.assert_not_called()

    def test_activate_world_rejects_bad_world_name(self):
        """POST /api/worlds/activate with an invalid world_name returns 400."""
        from src.main import app, pc_agent

        with patch.object(pc_agent, "post", new_callable=AsyncMock) as mock_post:
            client = TestClient(app)
            response = client.post(
                "/api/worlds/activate", data={"world_name": "bad name"}
            )

            assert response.status_code == 400
            mock_post.assert_not_called()

    def test_delete_world_rejects_bad_world_name(self):
        """DELETE /api/worlds/{name} with an invalid world_name returns 400."""
        from src.main import app, pc_agent

        with patch.object(pc_agent, "delete", new_callable=AsyncMock) as mock_delete:
            client = TestClient(app)
            # A single path segment that reaches the handler but fails validation
            # (contains a shell metacharacter). Encoded slashes would 404 at the
            # router before reaching the handler, so we test the handler guard here.
            response = client.delete("/api/worlds/world$(whoami)")

            assert response.status_code == 400
            mock_delete.assert_not_called()


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


class TestServerNameValidation:
    """Tests for server_name validation in update_config."""

    def test_valid_server_name_passes(self):
        """A valid server_name (letters, digits, spaces) passes validation."""
        from src.main import validate_server_name

        assert validate_server_name("My Valheim Server 1") == "My Valheim Server 1"
        assert validate_server_name("TestServer") == "TestServer"
        assert validate_server_name("A") == "A"

    def test_server_name_rejects_empty(self):
        """Empty server_name raises HTTPException 400."""
        from src.main import validate_server_name

        with pytest.raises(HTTPException) as exc_info:
            validate_server_name("")
        assert exc_info.value.status_code == 400

    def test_server_name_rejects_special_chars(self):
        """server_name with special characters raises HTTPException 400."""
        from src.main import validate_server_name

        invalid_names = ["Server<script>", "Test;echo", "Name|cat", "Server\nNew"]
        for name in invalid_names:
            with pytest.raises(HTTPException) as exc_info:
                validate_server_name(name)
            assert exc_info.value.status_code == 400

    def test_server_name_rejects_too_long(self):
        """server_name over 64 chars raises HTTPException 400."""
        from src.main import validate_server_name

        long_name = "A" * 65
        with pytest.raises(HTTPException) as exc_info:
            validate_server_name(long_name)
        assert exc_info.value.status_code == 400


class TestServerPassValidation:
    """Tests for server_pass validation in update_config."""

    def test_valid_server_pass_passes(self):
        """Valid passwords pass validation."""
        from src.main import validate_server_pass

        assert validate_server_pass("mypassword123") == "mypassword123"
        assert validate_server_pass("P@ssw0rd!#$%") == "P@ssw0rd!#$%"
        assert validate_server_pass("") == ""  # Empty password allowed

    def test_server_pass_rejects_too_long(self):
        """Password over 128 chars raises HTTPException 400."""
        from src.main import validate_server_pass

        long_pass = "A" * 129
        with pytest.raises(HTTPException) as exc_info:
            validate_server_pass(long_pass)
        assert exc_info.value.status_code == 400

    def test_server_pass_rejects_newlines(self):
        """Password with newlines raises HTTPException 400."""
        from src.main import validate_server_pass

        with pytest.raises(HTTPException) as exc_info:
            validate_server_pass("pass\nword")
        assert exc_info.value.status_code == 400

    def test_server_pass_rejects_null_bytes(self):
        """Password with null bytes raises HTTPException 400."""
        from src.main import validate_server_pass

        with pytest.raises(HTTPException) as exc_info:
            validate_server_pass("pass\0word")
        assert exc_info.value.status_code == 400


class TestConfigBoundsValidation:
    """Tests for save_interval and backups clamping."""

    def test_clamp_save_interval_within_bounds(self):
        """Values within bounds are unchanged."""
        from src.main import clamp_save_interval

        assert clamp_save_interval(1800) == 1800
        assert clamp_save_interval(300) == 300
        assert clamp_save_interval(86400) == 86400

    def test_clamp_save_interval_below_min(self):
        """Values below minimum are clamped to minimum (300s = 5min)."""
        from src.main import clamp_save_interval

        assert clamp_save_interval(0) == 300
        assert clamp_save_interval(100) == 300
        assert clamp_save_interval(-1) == 300

    def test_clamp_save_interval_above_max(self):
        """Values above maximum are clamped to maximum (86400s = 24h)."""
        from src.main import clamp_save_interval

        assert clamp_save_interval(100000) == 86400
        assert clamp_save_interval(999999) == 86400

    def test_clamp_backups_within_bounds(self):
        """Values within bounds are unchanged."""
        from src.main import clamp_backups

        assert clamp_backups(4) == 4
        assert clamp_backups(1) == 1
        assert clamp_backups(100) == 100

    def test_clamp_backups_below_min(self):
        """Values below minimum are clamped to minimum (1)."""
        from src.main import clamp_backups

        assert clamp_backups(0) == 1
        assert clamp_backups(-5) == 1

    def test_clamp_backups_above_max(self):
        """Values above maximum are clamped to maximum (100)."""
        from src.main import clamp_backups

        assert clamp_backups(150) == 100
        assert clamp_backups(999) == 100


class TestSanitizeShellArg:
    """Tests for shell argument sanitization utility."""

    def test_sanitize_simple_string(self):
        """Simple alphanumeric strings remain unchanged (no quotes needed)."""
        from src.main import _sanitize_shell_arg

        # shlex.quote only adds quotes when necessary
        result = _sanitize_shell_arg("hello")
        assert result == "hello"

    def test_sanitize_empty_string(self):
        """Empty strings are quoted."""
        from src.main import _sanitize_shell_arg

        result = _sanitize_shell_arg("")
        assert result == "''"

    def test_sanitize_string_with_spaces(self):
        """Strings with spaces are properly quoted."""
        from src.main import _sanitize_shell_arg

        result = _sanitize_shell_arg("hello world")
        assert result == "'hello world'"

    def test_sanitize_string_with_special_chars(self):
        """Special shell characters are escaped."""
        from src.main import _sanitize_shell_arg

        # semicolon - command separator
        result = _sanitize_shell_arg("test;rm -rf /")
        assert ";" in result
        assert result.startswith("'")

        # dollar sign - variable expansion
        result = _sanitize_shell_arg("$HOME")
        assert result.startswith("'")
        assert "$HOME" in result

        # backticks - command substitution
        result = _sanitize_shell_arg("`whoami`")
        assert result.startswith("'")
        assert "`whoami`" in result

    def test_sanitize_string_with_quotes(self):
        """Strings containing single quotes are properly escaped."""
        from src.main import _sanitize_shell_arg

        result = _sanitize_shell_arg("it's a test")
        # shlex.quote escapes embedded single quotes: 'it'"'"'s a test'
        assert "it" in result and "s a test" in result

    def test_sanitize_injection_attempts(self):
        """Common injection patterns are neutralized."""
        from src.main import _sanitize_shell_arg

        # Only test patterns that contain shell metacharacters
        # (shlex.quote won't quote plain alphanumeric/dots/slashes)
        injection_patterns = [
            ("$(whoami)", True),  # command substitution - needs quoting
            ("`id`", True),  # backtick substitution - needs quoting
            ("| cat /etc/passwd", True),  # pipe - needs quoting
            ("&& rm -rf /", True),  # logical AND - needs quoting
            ("; echo pwned", True),  # semicolon - needs quoting
            ("' || true #", True),  # quote and logical OR - needs quoting
        ]
        for pattern, should_be_quoted in injection_patterns:
            result = _sanitize_shell_arg(pattern)
            if should_be_quoted:
                # Result should be quoted to prevent shell interpretation
                assert result.startswith("'") or '"' in result, (
                    f"Pattern {pattern!r} should be quoted, got {result!r}"
                )
