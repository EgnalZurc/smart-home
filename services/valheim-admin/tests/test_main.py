"""Unit tests for valheim-admin service."""

import pytest
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

# Mock environment before importing main
import os
os.environ.setdefault("VALHEIM_ENV_FILE", "/tmp/test.env")
os.environ.setdefault("VALHEIM_WORLDS_DIR", "/tmp/test_worlds")
os.environ.setdefault("VALHEIM_LOGS_DIR", "/tmp/test_logs")

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


class TestEnvHelpers:
    """Tests for .env file read/write helpers."""

    def test_read_env_empty_file(self, tmp_path):
        """read_env returns empty dict for non-existent file."""
        from src.main import read_env, ENV_FILE
        with patch.object(Path, 'exists', return_value=False):
            # Need to patch the module's ENV_FILE
            import src.main as main_module
            original = main_module.ENV_FILE
            main_module.ENV_FILE = tmp_path / "nonexistent.env"
            result = main_module.read_env()
            main_module.ENV_FILE = original
        assert result == {}

    def test_read_env_parses_values(self, tmp_path):
        """read_env correctly parses key=value pairs."""
        env_file = tmp_path / ".env"
        env_file.write_text("""
# Comment line
SERVER_NAME=MyServer
WORLD_NAME=TestWorld
SERVER_PASS=secret123
# Another comment
EMPTY_VAL=
""")
        import src.main as main_module
        original = main_module.ENV_FILE
        main_module.ENV_FILE = env_file
        result = main_module.read_env()
        main_module.ENV_FILE = original

        assert result["SERVER_NAME"] == "MyServer"
        assert result["WORLD_NAME"] == "TestWorld"
        assert result["SERVER_PASS"] == "secret123"
        assert result["EMPTY_VAL"] == ""

    def test_write_env_preserves_comments(self, tmp_path):
        """write_env preserves comment lines."""
        env_file = tmp_path / ".env"
        env_file.write_text("""# Header comment
SERVER_NAME=OldName
# Middle comment
WORLD_NAME=OldWorld
""")
        import src.main as main_module
        original = main_module.ENV_FILE
        main_module.ENV_FILE = env_file
        main_module.write_env({"SERVER_NAME": "NewName", "WORLD_NAME": "NewWorld"})
        main_module.ENV_FILE = original

        content = env_file.read_text()
        assert "# Header comment" in content
        assert "# Middle comment" in content
        assert "SERVER_NAME=NewName" in content
        assert "WORLD_NAME=NewWorld" in content


class TestLogParsing:
    """Tests for log parsing functions."""

    def test_parse_join_code_found(self):
        """parse_join_code extracts 6-digit code."""
        from src.main import parse_join_code
        log = "Server started with join code 123456 successfully"
        assert parse_join_code(log) == "123456"

    def test_parse_join_code_alternate_format(self):
        """parse_join_code handles alternate format."""
        from src.main import parse_join_code
        log = "Join code: 654321"
        assert parse_join_code(log) == "654321"

    def test_parse_join_code_not_found(self):
        """parse_join_code returns None when no code."""
        from src.main import parse_join_code
        log = "Server started without crossplay"
        assert parse_join_code(log) is None

    def test_parse_players_counts_correctly(self):
        """parse_players counts connects minus disconnects."""
        from src.main import parse_players
        log = """
Got handshake from client 1
Got handshake from client 2
Got handshake from client 3
Closing socket for ZDOID user1
"""
        # 3 connects - 1 disconnect = 2
        assert parse_players(log) == 2

    def test_parse_players_no_negative(self):
        """parse_players never returns negative."""
        from src.main import parse_players
        log = """
Closing socket for ZDOID user1
Closing socket for ZDOID user2
"""
        assert parse_players(log) == 0


class TestWorldHelpers:
    """Tests for world management helpers."""

    def test_sanitize_name_removes_special_chars(self):
        """_sanitize_name removes special characters."""
        from src.main import _sanitize_name
        assert _sanitize_name("My World!@#$") == "MyWorld"
        assert _sanitize_name("  test_world-1  ") == "test_world-1"
        assert _sanitize_name("válhéim") == "vlhim"

    def test_world_format_v1(self, tmp_path):
        """_world_format detects v1 format."""
        from src.main import _world_format
        world = tmp_path / "TestWorld"
        world.mkdir()
        (world / "_main.1.db2").write_bytes(b"data")
        (world / "_main.1.fwl2").write_bytes(b"data")
        assert _world_format(world) == "v1"

    def test_world_format_legacy(self, tmp_path):
        """_world_format detects legacy format."""
        from src.main import _world_format
        world = tmp_path / "OldWorld"
        world.mkdir()
        (world / "OldWorld.db").write_bytes(b"data")
        (world / "OldWorld.fwl").write_bytes(b"data")
        assert _world_format(world) == "legacy"

    def test_world_format_empty(self, tmp_path):
        """_world_format returns empty for empty dir."""
        from src.main import _world_format
        world = tmp_path / "EmptyWorld"
        world.mkdir()
        assert _world_format(world) == "empty"


class TestBinaryValidation:
    """Tests for Valheim binary file validation."""

    def test_validate_ok_valid(self):
        """_validate_ok accepts valid .ok file."""
        from src.main import _validate_ok, VALHEIM_V1_VERSION
        data = VALHEIM_V1_VERSION.to_bytes(4, "little")
        assert _validate_ok(data) is None

    def test_validate_ok_wrong_size(self):
        """_validate_ok rejects wrong size."""
        from src.main import _validate_ok
        assert _validate_ok(b"\x29\x00") is not None  # Too small

    def test_validate_ok_wrong_version(self):
        """_validate_ok rejects wrong version."""
        from src.main import _validate_ok
        data = (99).to_bytes(4, "little")
        assert _validate_ok(data) is not None

    def test_validate_db2_valid(self):
        """_validate_db2 accepts valid header."""
        from src.main import _validate_db2, VALHEIM_V1_VERSION
        # First 4 bytes = version, rest is data
        data = VALHEIM_V1_VERSION.to_bytes(4, "little") + b"\x00" * 100
        assert _validate_db2(data) is None

    def test_validate_db2_too_small(self):
        """_validate_db2 rejects small files."""
        from src.main import _validate_db2
        assert _validate_db2(b"\x29\x00") is not None

    def test_validate_chunk_valid(self):
        """_validate_chunk accepts valid header."""
        from src.main import _validate_chunk
        # First two bytes should be 0x29 0x00
        data = b"\x29\x00\x00\x00" + b"\x00" * 100
        assert _validate_chunk(data) is None

    def test_validate_chunk_invalid_header(self):
        """_validate_chunk rejects invalid header."""
        from src.main import _validate_chunk
        data = b"\xFF\xFF\x00\x00" + b"\x00" * 100
        assert _validate_chunk(data) is not None


class TestDockerfileStructure:
    """Tests for Dockerfile correctness."""

    @pytest.fixture
    def dockerfile_content(self):
        dockerfile = Path(__file__).parent.parent / "Dockerfile"
        return dockerfile.read_text()

    def test_base_image_is_python(self, dockerfile_content):
        """Dockerfile uses Python base image."""
        assert "FROM python:3.12" in dockerfile_content

    def test_exposes_port_8080(self, dockerfile_content):
        """Dockerfile exposes port 8080."""
        assert "EXPOSE 8080" in dockerfile_content

    def test_installs_docker_cli(self, dockerfile_content):
        """Dockerfile installs docker CLI for container control."""
        assert "docker-ce-cli" in dockerfile_content
        assert "docker-compose-plugin" in dockerfile_content

    def test_runs_uvicorn(self, dockerfile_content):
        """Dockerfile runs uvicorn on startup."""
        assert "uvicorn" in dockerfile_content
        assert "main:app" in dockerfile_content

    def test_copies_requirements(self, dockerfile_content):
        """Dockerfile copies and installs requirements."""
        assert "COPY requirements.txt" in dockerfile_content
        assert "pip install" in dockerfile_content


class TestAPIEndpoints:
    """Tests for API endpoints using TestClient."""

    @pytest.fixture
    def client(self, tmp_path):
        """Create test client with mocked paths."""
        import src.main as main_module
        
        # Setup temp directories
        env_file = tmp_path / ".env"
        env_file.write_text("WORLD_NAME=TestWorld\nSERVER_NAME=TestServer\n")
        worlds_dir = tmp_path / "worlds"
        worlds_dir.mkdir()
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()
        
        # Patch paths
        main_module.ENV_FILE = env_file
        main_module.WORLDS_DIR = worlds_dir
        main_module.LOGS_DIR = logs_dir
        
        return TestClient(main_module.app)

    def test_get_config(self, client, tmp_path):
        """GET /api/config returns current config."""
        response = client.get("/api/config")
        assert response.status_code == 200
        data = response.json()
        assert data["world_name"] == "TestWorld"
        assert data["server_name"] == "TestServer"

    def test_list_worlds_empty(self, client):
        """GET /api/worlds returns empty list."""
        response = client.get("/api/worlds")
        assert response.status_code == 200
        data = response.json()
        assert data["worlds"] == []

    def test_list_worlds_with_worlds(self, client, tmp_path):
        """GET /api/worlds lists existing worlds."""
        import src.main as main_module
        worlds_dir = main_module.WORLDS_DIR
        
        # Create a test world
        world = worlds_dir / "MyWorld"
        world.mkdir()
        (world / "test.db2").write_bytes(b"data")
        
        response = client.get("/api/worlds")
        assert response.status_code == 200
        data = response.json()
        assert len(data["worlds"]) == 1
        assert data["worlds"][0]["name"] == "MyWorld"
        assert data["worlds"][0]["format"] == "v1"

    def test_get_logs_no_logs(self, client):
        """GET /api/logs handles missing logs gracefully."""
        response = client.get("/api/logs")
        assert response.status_code == 200
        data = response.json()
        assert data["lines"] == []


class TestConfigValidation:
    """Tests for config update validation."""

    @pytest.fixture
    def client(self, tmp_path):
        """Create test client."""
        import src.main as main_module
        env_file = tmp_path / ".env"
        env_file.write_text("WORLD_NAME=Test\nSERVER_NAME=Test\nSERVER_PASS=12345\n")
        main_module.ENV_FILE = env_file
        main_module.WORLDS_DIR = tmp_path / "worlds"
        main_module.WORLDS_DIR.mkdir()
        return TestClient(main_module.app)

    @patch('src.main.recreate_game_container', new_callable=AsyncMock)
    def test_config_rejects_short_password(self, mock_recreate, client):
        """POST /api/config rejects password < 5 chars."""
        response = client.post("/api/config", json={
            "server_name": "Test",
            "world_name": "World",
            "server_pass": "1234",  # Too short
            "server_public": False,
            "crossplay": False,
            "save_interval": 1800,
            "backups": 4
        })
        assert response.status_code == 400
        assert "5 characters" in response.json()["detail"]

    @patch('src.main.recreate_game_container', new_callable=AsyncMock)
    def test_config_rejects_empty_world(self, mock_recreate, client):
        """POST /api/config rejects empty world name."""
        response = client.post("/api/config", json={
            "server_name": "Test",
            "world_name": "",  # Empty
            "server_pass": "12345",
            "server_public": False,
            "crossplay": False,
            "save_interval": 1800,
            "backups": 4
        })
        assert response.status_code == 400
        assert "empty" in response.json()["detail"].lower()


class TestWorldCreation:
    """Tests for world creation endpoint."""

    @pytest.fixture
    def client(self, tmp_path):
        """Create test client."""
        import src.main as main_module
        main_module.WORLDS_DIR = tmp_path / "worlds"
        main_module.WORLDS_DIR.mkdir()
        return TestClient(main_module.app)

    def test_create_world_success(self, client, tmp_path):
        """POST /api/worlds/new creates new world folder."""
        import src.main as main_module
        response = client.post("/api/worlds/new", data={"world_name": "NewWorld"})
        assert response.status_code == 200
        assert (main_module.WORLDS_DIR / "NewWorld").exists()

    def test_create_world_rejects_empty_name(self, client):
        """POST /api/worlds/new rejects empty name."""
        response = client.post("/api/worlds/new", data={"world_name": ""})
        assert response.status_code == 400

    def test_create_world_rejects_invalid_chars(self, client):
        """POST /api/worlds/new sanitizes name."""
        response = client.post("/api/worlds/new", data={"world_name": "!!!"})
        assert response.status_code == 400

    def test_create_world_rejects_duplicate(self, client, tmp_path):
        """POST /api/worlds/new rejects existing world."""
        import src.main as main_module
        (main_module.WORLDS_DIR / "ExistingWorld").mkdir()
        response = client.post("/api/worlds/new", data={"world_name": "ExistingWorld"})
        assert response.status_code == 400
        assert "already exists" in response.json()["detail"]
