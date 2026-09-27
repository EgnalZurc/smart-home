"""Unit tests for api/routes.py — backend dashboard routes.

Covers:
  - Health check endpoints (all public, no auth)
  - Container control endpoints (SUPER only)
  - CONTROLLABLE_CONTAINERS mapping completeness
  - _require_super authorization guard

NOTE: AC-specific endpoints (/api/status, /api/sensors, etc.) are NOT tested here.
They live in ac-service and are tested in ~/projects/smart-home/ac-service/tests/.
"""
import sys
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

# ── Mock passlib before any auth import ───────────────────────────────────────
# passlib is installed in the Docker container but not in the Pi test environment.
_mock_passlib = MagicMock()
_mock_passlib.hash.apr_md5_crypt.verify.return_value = True
sys.modules.setdefault('passlib', _mock_passlib)
sys.modules.setdefault('passlib.hash', _mock_passlib.hash)

from fastapi.testclient import TestClient
from fastapi import FastAPI


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_client():
    """TestClient for routes.py without auth."""
    from api import routes
    app = FastAPI()
    app.include_router(routes.router)
    return TestClient(app, raise_server_exceptions=True)


def _make_client_authed(profile_key: str, username: str):
    """TestClient with a fake user injected via _require_super patch."""
    from api import routes
    import user_profiles

    app = FastAPI()

    from starlette.middleware.base import BaseHTTPMiddleware

    class FakeAuth(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            # Store fake identity on request.state so _require_super can read it
            request.state._fake_user = username
            request.state._fake_profile = profile_key
            return await call_next(request)

    app.add_middleware(FakeAuth)
    app.include_router(routes.router)

    client = TestClient(app, raise_server_exceptions=True)
    return client, username, profile_key


def _super_client():
    """Client authenticated as SUPER."""
    c, user, profile = _make_client_authed('SUPER', 'egnal')
    return c, user, profile


def _familia_client():
    """Client authenticated as FAMILIA_PRINCIPAL."""
    c, user, profile = _make_client_authed('FAMILIA_PRINCIPAL', 'virchi')
    return c, user, profile


def _patch_require_super(username: str, profile_key: str):
    """Context manager: patch _require_super to return username or raise 403."""
    import user_profiles
    from fastapi import HTTPException

    profiles = user_profiles.PROFILES
    profile_def = profiles.get(profile_key, {})
    is_super = profile_def.get('show_config_apps', False)

    def fake_require_super(request):
        if not is_super:
            raise HTTPException(status_code=403, detail='SUPER profile required')
        return username

    return patch('api.routes._require_super', side_effect=fake_require_super)



class TestHealthBackend:
    """/api/health/backend — always returns online:true, no auth required."""

    def test_returns_200(self):
        assert _make_client().get("/api/health/backend").status_code == 200

    def test_returns_online_true(self):
        assert _make_client().get("/api/health/backend").json() == {"online": True}


class TestHealthZigbee:
    """/api/health/zigbee — proxies to ac-service."""

    def test_returns_200_when_ac_service_responds(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"online": True, "mqtt_connected": True, "active_sensors": 5}
        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_resp)
            r = _make_client().get("/api/health/zigbee")
        assert r.status_code == 200
        assert r.json()["online"] is True
        assert r.json()["mqtt_connected"] is True

    def test_returns_offline_when_ac_service_unreachable(self):
        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__.return_value.get = AsyncMock(
                side_effect=Exception("connection refused")
            )
            r = _make_client().get("/api/health/zigbee")
        assert r.json()["online"] is False
        assert r.json()["mqtt_connected"] is False


class TestHealthAC:
    """/api/health/ac — proxies to ac-service /health."""

    def test_returns_online_true_when_ac_healthy(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"online": True, "service": "ac"}
        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_resp)
            r = _make_client().get("/api/health/ac")
        assert r.status_code == 200
        assert r.json()["online"] is True

    def test_returns_offline_when_ac_service_down(self):
        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__.return_value.get = AsyncMock(
                side_effect=Exception("timeout")
            )
            r = _make_client().get("/api/health/ac")
        assert r.json()["online"] is False


class TestHealthVacaciones:
    """/api/health/vacaciones."""

    def test_returns_online_true(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"online": True, "service": "vacaciones"}
        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_resp)
            r = _make_client().get("/api/health/vacaciones")
        assert r.json()["online"] is True

    def test_returns_offline_on_error(self):
        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__.return_value.get = AsyncMock(
                side_effect=Exception("down")
            )
            r = _make_client().get("/api/health/vacaciones")
        assert r.json()["online"] is False


class TestHealthImmich:
    """/api/health/immich."""

    def test_returns_online_true_when_pong(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"res": "pong"}
        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_resp)
            r = _make_client().get("/api/health/immich")
        assert r.json()["online"] is True

    def test_returns_offline_when_not_pong(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"res": "error"}
        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_resp)
            r = _make_client().get("/api/health/immich")
        assert r.json()["online"] is False


# ── Container mapping ─────────────────────────────────────────────────────────

class TestControllableContainersMapping:

    def test_all_expected_keys_present(self):
        from api.routes import CONTROLLABLE_CONTAINERS
        assert set(CONTROLLABLE_CONTAINERS.keys()) == {"ac", "vacaciones", "casita", "photos", "passwords", "valheim"}

    def test_ac_maps_to_ac_service_container(self):
        from api.routes import CONTROLLABLE_CONTAINERS
        assert CONTROLLABLE_CONTAINERS["ac"] == ["ac-service"]

    def test_vacaciones_maps_to_vacaciones_service(self):
        from api.routes import CONTROLLABLE_CONTAINERS
        assert CONTROLLABLE_CONTAINERS["vacaciones"] == ["vacaciones-service"]

    def test_casita_maps_to_casita_suenos(self):
        from api.routes import CONTROLLABLE_CONTAINERS
        assert CONTROLLABLE_CONTAINERS["casita"] == ["casita-suenos"]

    def test_photos_maps_to_three_immich_containers(self):
        from api.routes import CONTROLLABLE_CONTAINERS
        containers = CONTROLLABLE_CONTAINERS["photos"]
        assert "immich_server" in containers
        assert "immich_postgres" in containers
        assert "immich_redis" in containers
        assert len(containers) == 3

    def test_passwords_maps_to_vaultwarden(self):
        from api.routes import CONTROLLABLE_CONTAINERS
        assert CONTROLLABLE_CONTAINERS["passwords"] == ["vaultwarden"]

    def test_valheim_maps_to_valheim_server(self):
        from api.routes import CONTROLLABLE_CONTAINERS
        assert CONTROLLABLE_CONTAINERS["valheim"] == ["valheim-server"]

    def test_no_container_name_in_multiple_keys(self):
        from api.routes import CONTROLLABLE_CONTAINERS
        all_containers = [c for cs in CONTROLLABLE_CONTAINERS.values() for c in cs]
        assert len(all_containers) == len(set(all_containers))


# ── _require_super guard ──────────────────────────────────────────────────────



def _patch_super_inline():
    """Patch inline auth in GET /api/containers to simulate SUPER user."""
    import auth as auth_core
    import user_profiles
    from contextlib import contextmanager
    from unittest.mock import patch as _patch

    class CombinedPatch:
        def __init__(self):
            self._patches = [
                _patch.object(auth_core, 'get_current_user', return_value='egnal'),
                _patch.object(user_profiles, 'get_profile_key', return_value='SUPER'),
            ]
        def __enter__(self):
            for p in self._patches:
                p.start()
            return self
        def __exit__(self, *args):
            for p in self._patches:
                p.stop()

    return CombinedPatch()

class TestRequireSuperGuard:

    def test_familia_principal_returns_403(self):
        """FAMILIA_PRINCIPAL (no show_gaming_apps) cannot access /api/containers."""
        import auth as auth_core
        import user_profiles
        c = _make_client()
        with patch.object(auth_core, 'get_current_user', return_value='virchi'),              patch.object(user_profiles, 'get_profile_key', return_value='FAMILIA_PRINCIPAL'):
            r = c.get("/api/containers")
        assert r.status_code == 403

    def test_super_can_call_get_containers(self):
        """SUPER can access /api/containers and sees all services."""
        import auth as auth_core
        import user_profiles
        c = _make_client()
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {"Names": ["/ac-service"], "State": "running"},
            {"Names": ["/vacaciones-service"], "State": "running"},
            {"Names": ["/casita-suenos"], "State": "running"},
            {"Names": ["/immich_server"], "State": "running"},
            {"Names": ["/immich_postgres"], "State": "running"},
            {"Names": ["/immich_redis"], "State": "running"},
            {"Names": ["/vaultwarden"], "State": "running"},
            {"Names": ["/valheim-server"], "State": "running"},
        ]
        with patch.object(auth_core, 'get_current_user', return_value='egnal'),              patch.object(user_profiles, 'get_profile_key', return_value='SUPER'):
            with patch("httpx.AsyncClient") as mock_cls:
                mock_cls.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_resp)
                r = c.get("/api/containers")
        assert r.status_code == 200


# ── GET /api/containers ───────────────────────────────────────────────────────

class TestGetContainers:

    def _docker_resp(self, states: dict):
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {"Names": [f"/{name}"], "State": state}
            for name, state in states.items()
        ]
        return mock_resp

    def _all_running(self):
        return self._docker_resp({
            "ac-service": "running", "vacaciones-service": "running",
            "casita-suenos": "running", "immich_server": "running",
            "immich_postgres": "running", "immich_redis": "running",
            "vaultwarden": "running",
        })

    def test_all_services_running(self):
        c = _make_client()
        with _patch_super_inline():
            with patch("httpx.AsyncClient") as mock_cls:
                mock_cls.return_value.__aenter__.return_value.get = AsyncMock(return_value=self._all_running())
                r = c.get("/api/containers")
        assert r.status_code == 200
        data = r.json()
        for key in ("ac", "vacaciones", "casita", "photos", "passwords"):
            assert data[key]["running"] is True

    def test_ac_stopped_photos_running(self):
        c = _make_client()
        mock_resp = self._docker_resp({
            "ac-service": "exited", "vacaciones-service": "running",
            "casita-suenos": "running", "immich_server": "running",
            "immich_postgres": "running", "immich_redis": "running",
            "vaultwarden": "running",
        })
        with _patch_super_inline():
            with patch("httpx.AsyncClient") as mock_cls:
                mock_cls.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_resp)
                r = c.get("/api/containers")
        data = r.json()
        assert data["ac"]["running"] is False
        assert data["photos"]["running"] is True

    def test_photos_partial_stop_means_not_running(self):
        c = _make_client()
        mock_resp = self._docker_resp({
            "ac-service": "running", "vacaciones-service": "running",
            "casita-suenos": "running", "immich_server": "running",
            "immich_postgres": "exited",   # ← postgres stopped
            "immich_redis": "running", "vaultwarden": "running",
        })
        with _patch_super_inline():
            with patch("httpx.AsyncClient") as mock_cls:
                mock_cls.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_resp)
                r = c.get("/api/containers")
        assert r.json()["photos"]["running"] is False

    def test_response_includes_states_detail(self):
        c = _make_client()
        mock_resp = self._docker_resp({
            "ac-service": "running", "vacaciones-service": "exited",
            "casita-suenos": "running", "immich_server": "running",
            "immich_postgres": "running", "immich_redis": "running",
            "vaultwarden": "running",
        })
        with _patch_super_inline():
            with patch("httpx.AsyncClient") as mock_cls:
                mock_cls.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_resp)
                r = c.get("/api/containers")
        data = r.json()
        assert data["ac"]["states"]["ac-service"] == "running"
        assert data["vacaciones"]["states"]["vacaciones-service"] == "exited"

    def test_docker_proxy_unreachable_returns_503(self):
        c = _make_client()
        with _patch_super_inline():
            with patch("httpx.AsyncClient") as mock_cls:
                mock_cls.return_value.__aenter__.return_value.get = AsyncMock(
                    side_effect=Exception("connection refused")
                )
                r = c.get("/api/containers")
        assert r.status_code == 503


# ── POST /api/containers/{key}/stop ──────────────────────────────────────────

class TestStopService:

    def test_stop_known_service_returns_200(self):
        c = _make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 204
        with _patch_require_super('egnal', 'SUPER'):
            with patch("httpx.AsyncClient") as mock_cls:
                mock_cls.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_resp)
                r = c.post("/api/containers/ac/stop")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_stop_unknown_service_returns_404(self):
        c = _make_client()
        with _patch_require_super('egnal', 'SUPER'):
            r = c.post("/api/containers/nonexistent/stop")
        assert r.status_code == 404

    def test_stop_already_stopped_container_is_ok(self):
        c = _make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 304
        with _patch_require_super('egnal', 'SUPER'):
            with patch("httpx.AsyncClient") as mock_cls:
                mock_cls.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_resp)
                r = c.post("/api/containers/ac/stop")
        assert r.json()["status"] == "ok"

    def test_stop_non_super_returns_403(self):
        c = _make_client()
        with _patch_require_super('virchi', 'FAMILIA_PRINCIPAL'):
            r = c.post("/api/containers/ac/stop")
        assert r.status_code == 403

    def test_stop_photos_stops_all_three_containers(self):
        c = _make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 204
        call_urls = []

        async def fake_post(url, **kwargs):
            call_urls.append(url)
            return mock_resp

        with _patch_require_super('egnal', 'SUPER'):
            with patch("httpx.AsyncClient") as mock_cls:
                mock_cls.return_value.__aenter__.return_value.post = fake_post
                r = c.post("/api/containers/photos/stop")

        assert r.status_code == 200
        assert any("immich_server" in u for u in call_urls)
        assert any("immich_postgres" in u for u in call_urls)
        assert any("immich_redis" in u for u in call_urls)
        assert len(call_urls) == 3


# ── POST /api/containers/{key}/start ─────────────────────────────────────────

class TestStartService:

    def test_start_known_service_returns_200(self):
        c = _make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 204
        with _patch_require_super('egnal', 'SUPER'):
            with patch("httpx.AsyncClient") as mock_cls:
                mock_cls.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_resp)
                r = c.post("/api/containers/ac/start")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_start_unknown_service_returns_404(self):
        c = _make_client()
        with _patch_require_super('egnal', 'SUPER'):
            r = c.post("/api/containers/unknown/start")
        assert r.status_code == 404

    def test_start_already_running_is_ok(self):
        c = _make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 304
        with _patch_require_super('egnal', 'SUPER'):
            with patch("httpx.AsyncClient") as mock_cls:
                mock_cls.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_resp)
                r = c.post("/api/containers/vacaciones/start")
        assert r.json()["status"] == "ok"

    def test_start_non_super_returns_403(self):
        c = _make_client()
        with _patch_require_super('virchi', 'FAMILIA_PRINCIPAL'):
            r = c.post("/api/containers/ac/start")
        assert r.status_code == 403
