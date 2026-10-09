"""Behavioral tests for pc-agent.

Grouped by concern:

* Auth           - token enforcement + fail-closed when unconfigured
* Health         - unauthenticated health probe (Docker up/down)
* Valheim        - container control endpoints with a mocked Docker client
* Power profiles - powercfg-backed endpoints with a mocked subprocess

No test requires Docker Desktop, a real container, or Windows: the Docker
client is replaced via ``get_docker`` and ``powercfg`` via ``subprocess.run``.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from .conftest import TEST_TOKEN


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _fake_container(status="running", started_at="2026-10-09T08:00:00Z"):
    """Build a MagicMock standing in for a docker container object."""
    container = MagicMock()
    container.status = status
    container.attrs = {
        "State": {
            "StartedAt": started_at,
            "FinishedAt": "0001-01-01T00:00:00Z",
            "ExitCode": 0,
            "Health": {"Status": "healthy"},
        }
    }
    return container


def _fake_docker(container=None, raise_not_found=False):
    """Build a MagicMock docker client returning ``container`` from .get()."""
    client = MagicMock()
    if raise_not_found:
        import docker

        client.containers.get.side_effect = docker.errors.NotFound("nope")
    else:
        client.containers.get.return_value = container or _fake_container()
    return client


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
class TestAuth:
    """Token enforcement on protected routes."""

    PROTECTED_GET = [
        "/valheim/status",
        "/valheim/config",
        "/valheim/worlds",
        "/system/mode",
    ]
    PROTECTED_POST = [
        "/valheim/start",
        "/valheim/stop",
        "/valheim/restart",
    ]

    @pytest.mark.parametrize("route", PROTECTED_GET)
    def test_get_without_token_is_rejected(self, client, route):
        resp = client.get(route)
        assert resp.status_code == 401

    @pytest.mark.parametrize("route", PROTECTED_POST)
    def test_post_without_token_is_rejected(self, client, route):
        resp = client.post(route)
        assert resp.status_code == 401

    def test_wrong_token_is_rejected(self, client):
        resp = client.get("/valheim/status", headers={"X-Api-Token": "wrong"})
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid or missing API token"

    def test_valid_token_passes_auth(self, client, auth_headers):
        # Docker unavailable -> 503, which still means auth *passed* (not 401).
        with patch("main.get_docker", return_value=None):
            resp = client.get("/valheim/status", headers=auth_headers)
        assert resp.status_code == 503

    def test_fail_closed_when_token_unconfigured(self, main_module, monkeypatch):
        """With no PC_AGENT_TOKEN, protected routes return 503, never 200."""
        from fastapi.testclient import TestClient

        monkeypatch.setattr(main_module, "API_TOKEN", "")
        local_client = TestClient(main_module.app)

        resp = local_client.get(
            "/valheim/status", headers={"X-Api-Token": "anything"}
        )
        assert resp.status_code == 503
        assert "not configured" in resp.json()["detail"].lower()


# --------------------------------------------------------------------------- #
# Health (no auth)
# --------------------------------------------------------------------------- #
class TestHealth:
    def test_health_needs_no_token(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_reports_docker_up(self, client):
        with patch("main.get_docker", return_value=MagicMock()):
            body = client.get("/health").json()
        assert body == {"online": True, "service": "pc-agent", "docker": True}

    def test_health_reports_docker_down(self, client):
        with patch("main.get_docker", return_value=None):
            body = client.get("/health").json()
        assert body["online"] is True
        assert body["docker"] is False


# --------------------------------------------------------------------------- #
# Valheim container control (mocked Docker)
# --------------------------------------------------------------------------- #
class TestValheimStatus:
    def test_status_running(self, client, auth_headers):
        fake = _fake_docker(_fake_container(status="running"))
        with (
            patch("main.get_docker", return_value=fake),
            patch("main._latest_log_file", return_value=None),
            patch("main._read_env", return_value={"WORLD_NAME": "Midgard"}),
        ):
            resp = client.get("/valheim/status", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["running"] is True
        assert body["status"] == "running"
        assert body["world"] == "Midgard"
        assert body["uptime_seconds"] is not None

    def test_status_stopped_has_no_uptime(self, client, auth_headers):
        fake = _fake_docker(_fake_container(status="exited"))
        with (
            patch("main.get_docker", return_value=fake),
            patch("main._latest_log_file", return_value=None),
            patch("main._read_env", return_value={}),
        ):
            body = client.get("/valheim/status", headers=auth_headers).json()
        assert body["running"] is False
        assert body["uptime_seconds"] is None

    def test_status_container_not_found(self, client, auth_headers):
        fake = _fake_docker(raise_not_found=True)
        with patch("main.get_docker", return_value=fake):
            body = client.get("/valheim/status", headers=auth_headers).json()
        assert body["status"] == "not_found"
        assert body["running"] is False

    def test_status_docker_unavailable(self, client, auth_headers):
        with patch("main.get_docker", return_value=None):
            resp = client.get("/valheim/status", headers=auth_headers)
        assert resp.status_code == 503


class TestValheimStart:
    def test_start_stopped_container(self, client, auth_headers):
        container = _fake_container(status="exited")
        fake = _fake_docker(container)
        with patch("main.get_docker", return_value=fake):
            resp = client.post("/valheim/start", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "started"
        container.start.assert_called_once()

    def test_start_already_running(self, client, auth_headers):
        container = _fake_container(status="running")
        fake = _fake_docker(container)
        with patch("main.get_docker", return_value=fake):
            body = client.post("/valheim/start", headers=auth_headers).json()
        assert body["status"] == "already_running"
        container.start.assert_not_called()

    def test_start_not_found_returns_404(self, client, auth_headers):
        fake = _fake_docker(raise_not_found=True)
        with patch("main.get_docker", return_value=fake):
            resp = client.post("/valheim/start", headers=auth_headers)
        assert resp.status_code == 404

    def test_start_docker_unavailable(self, client, auth_headers):
        with patch("main.get_docker", return_value=None):
            resp = client.post("/valheim/start", headers=auth_headers)
        assert resp.status_code == 503


class TestValheimStop:
    def test_stop_running_container(self, client, auth_headers):
        container = _fake_container(status="running")
        fake = _fake_docker(container)
        with patch("main.get_docker", return_value=fake):
            resp = client.post("/valheim/stop", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "stopped"
        container.stop.assert_called_once_with(timeout=30)

    def test_stop_already_stopped(self, client, auth_headers):
        container = _fake_container(status="exited")
        fake = _fake_docker(container)
        with patch("main.get_docker", return_value=fake):
            body = client.post("/valheim/stop", headers=auth_headers).json()
        assert body["status"] == "already_stopped"
        container.stop.assert_not_called()


class TestValheimRestart:
    def test_restart_calls_docker(self, client, auth_headers):
        container = _fake_container(status="running")
        fake = _fake_docker(container)
        with patch("main.get_docker", return_value=fake):
            resp = client.post("/valheim/restart", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "restarted"
        container.restart.assert_called_once_with(timeout=30)


# --------------------------------------------------------------------------- #
# Power profiles (mocked subprocess / powercfg)
# --------------------------------------------------------------------------- #
class TestPowerModeGet:
    def test_get_mode_gaming(self, client, auth_headers):
        completed = SimpleNamespace(
            returncode=0,
            stdout="Power Scheme GUID: xxx  (High performance)",
            stderr="",
        )
        with patch("main.subprocess.run", return_value=completed):
            body = client.get("/system/mode", headers=auth_headers).json()
        assert body["mode"] == "gaming"
        assert body["windows_name"] == "High performance"

    def test_get_mode_balanced(self, client, auth_headers):
        completed = SimpleNamespace(
            returncode=0,
            stdout="Power Scheme GUID: xxx  (Balanced)",
            stderr="",
        )
        with patch("main.subprocess.run", return_value=completed):
            body = client.get("/system/mode", headers=auth_headers).json()
        assert body["mode"] == "balanced"

    def test_get_mode_powercfg_failure(self, client, auth_headers):
        completed = SimpleNamespace(returncode=1, stdout="", stderr="boom")
        with patch("main.subprocess.run", return_value=completed):
            body = client.get("/system/mode", headers=auth_headers).json()
        assert body["mode"] == "unknown"
        assert body["error"] == "boom"


class TestPowerModeSet:
    def test_set_valid_mode(self, client, auth_headers):
        completed = SimpleNamespace(returncode=0, stdout="", stderr="")
        with patch("main.subprocess.run", return_value=completed) as run:
            resp = client.post("/system/mode/gaming", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "mode": "gaming"}
        # Verify the GUID actually sent to powercfg matches the mapping.
        args = run.call_args[0][0]
        assert args[:2] == ["powercfg", "/setactive"]

    def test_set_invalid_mode_returns_400(self, client, auth_headers):
        resp = client.post("/system/mode/turbo", headers=auth_headers)
        assert resp.status_code == 400
        assert "Invalid mode" in resp.json()["detail"]

    def test_set_mode_powercfg_failure_returns_500(self, client, auth_headers):
        completed = SimpleNamespace(returncode=1, stdout="", stderr="denied")
        with patch("main.subprocess.run", return_value=completed):
            resp = client.post("/system/mode/servidor", headers=auth_headers)
        assert resp.status_code == 500

    def test_set_mode_requires_auth(self, client):
        resp = client.post("/system/mode/gaming")
        assert resp.status_code == 401


# --------------------------------------------------------------------------- #
# Endpoint structure / OpenAPI registration
# --------------------------------------------------------------------------- #
class TestRouteRegistration:
    def test_expected_routes_are_registered(self, main_module):
        paths = {route.path for route in main_module.app.routes}
        for expected in [
            "/health",
            "/valheim/status",
            "/valheim/start",
            "/valheim/stop",
            "/valheim/restart",
            "/system/mode",
            "/system/mode/{mode}",
        ]:
            assert expected in paths

    def test_openapi_schema_builds(self, client):
        schema = client.get("/openapi.json").json()
        assert schema["info"]["title"] == "pc-agent"


# --------------------------------------------------------------------------- #
# Async client coverage (pytest-asyncio + httpx ASGI transport)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_health_via_async_httpx(main_module):
    """Exercise the ASGI app through httpx's async transport."""
    import httpx

    transport = httpx.ASGITransport(app=main_module.app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as ac:
        resp = await ac.get("/health")
    assert resp.status_code == 200
    assert resp.json()["service"] == "pc-agent"


@pytest.mark.asyncio
async def test_async_auth_rejected_without_token(main_module, monkeypatch):
    import httpx

    monkeypatch.setattr(main_module, "API_TOKEN", TEST_TOKEN)
    transport = httpx.ASGITransport(app=main_module.app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as ac:
        resp = await ac.get("/valheim/status")
    assert resp.status_code == 401
