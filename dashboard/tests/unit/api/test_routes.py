"""Unit tests for routes - health checks and proxy endpoints.

Tests for the refactored route structure with separate modules.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def app():
    """Create FastAPI app with routes."""
    from api.routes import router

    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def client(app):
    """Create test client."""
    return TestClient(app)


# ══════════════════════════════════════════════════════════════════════════════
# Health Check Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestHealthEndpoints:
    def test_health_returns_ok(self, client):
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_backend_health(self, client):
        response = client.get("/api/health/backend")
        assert response.status_code == 200
        assert response.json()["online"] is True

    def test_zigbee_health_success(self, client):
        with patch("api.health.httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "online": True,
                "mqtt_connected": True,
                "active_sensors": 5,
            }
            mock_response.status_code = 200
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            response = client.get("/api/health/zigbee")

            assert response.status_code == 200

    def test_zigbee_health_failure(self, client):
        with patch("api.health.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                side_effect=Exception("Connection failed")
            )

            response = client.get("/api/health/zigbee")

            assert response.status_code == 200
            data = response.json()
            assert data["online"] is False

    def test_ac_health_success(self, client):
        with patch("api.health.httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {"online": True}
            mock_response.status_code = 200
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            response = client.get("/api/health/ac")

            assert response.status_code == 200
            assert response.json()["online"] is True

    def test_ac_health_failure(self, client):
        with patch("api.health.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                side_effect=Exception("Connection failed")
            )

            response = client.get("/api/health/ac")

            assert response.status_code == 200
            assert response.json()["online"] is False

    def test_vacaciones_health_success(self, client):
        with patch("api.health.httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {"online": True}
            mock_response.status_code = 200
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            response = client.get("/api/health/vacaciones")
            assert response.status_code == 200

    def test_immich_health_success(self, client):
        with patch("api.health.httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"res": "pong"}
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            response = client.get("/api/health/immich")

            assert response.status_code == 200
            assert response.json()["online"] is True

    def test_casita_health_failure(self, client):
        with patch("api.health.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                side_effect=Exception("Timeout")
            )

            response = client.get("/api/health/casita")

            assert response.status_code == 200
            assert response.json()["online"] is False

    def test_baby_gifts_health(self, client):
        with patch("api.health.httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {"online": True}
            mock_response.status_code = 200
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            response = client.get("/api/health/baby-gifts")
            assert response.status_code == 200

    def test_portfolio_health(self, client):
        with patch("api.health.httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {"online": True}
            mock_response.status_code = 200
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            response = client.get("/api/health/portfolio")
            assert response.status_code == 200

    def test_passwords_health_success(self, client):
        with patch("api.health.httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            response = client.get("/api/health/passwords")

            assert response.status_code == 200
            assert response.json()["online"] is True

    def test_ai_health_success(self, client):
        with patch("api.health.httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {"status": True}
            mock_response.status_code = 200
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            response = client.get("/api/health/ai")

            assert response.status_code == 200
            assert response.json()["online"] is True

    def test_valheim_health(self, client):
        with patch("api.health.httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {"online": True}
            mock_response.status_code = 200
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            response = client.get("/api/health/valheim")
            assert response.status_code == 200

    def test_valheim_server_health_online(self, client):
        with patch("api.health.httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "running": True,
                "join_code": "ABC123",
                "players": 2,
            }
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            response = client.get("/api/health/valheim-server")

            assert response.status_code == 200
            data = response.json()
            assert data["online"] is True
            assert data["join_code"] == "ABC123"

    def test_valheim_server_health_running_no_code(self, client):
        with patch("api.health.httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "running": True,
                "join_code": None,
            }
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            response = client.get("/api/health/valheim-server")

            data = response.json()
            assert data["online"] is False
            assert data["running"] is True


# ══════════════════════════════════════════════════════════════════════════════
# Casita Proxy Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestCasitaProxies:
    def test_casita_status_success(self, client):
        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "online": True,
                "total_properties": 10,
            }
            mock_response.status_code = 200
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            response = client.get("/api/casita/status")

            assert response.status_code == 200
            assert response.json()["online"] is True

    def test_casita_status_failure(self, client):
        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                side_effect=Exception("Timeout")
            )

            response = client.get("/api/casita/status")

            assert response.status_code == 200
            data = response.json()
            assert data["online"] is False
            assert "error" in data

    def test_casita_radar(self, client):
        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {"items": [], "total": 0}
            mock_response.status_code = 200
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            response = client.get("/api/casita/radar")
            assert response.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# Container Control Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestContainerEndpoints:
    def test_get_containers_not_super(self, client):
        with patch("auth.get_current_user", return_value="user"):
            with patch("user_profiles.is_super", return_value=False):
                response = client.get("/api/system/containers")
                assert response.status_code == 403

    def test_get_containers_success(self, client):
        with patch("auth.get_current_user", return_value="admin"):
            with patch("user_profiles.is_super", return_value=True):
                with patch("system.containers.httpx.AsyncClient") as mock_client:
                    mock_response = MagicMock()
                    mock_response.json.return_value = [
                        {"Names": ["/ac-service"], "State": "running"},
                        {"Names": ["/dashboard"], "State": "running"},
                    ]
                    mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                        return_value=mock_response
                    )

                    response = client.get("/api/system/containers")

                    assert response.status_code == 200
                    data = response.json()
                    assert "ac" in data

    def test_stop_service_not_found(self, client):
        with patch("auth.get_current_user", return_value="admin"):
            with patch("user_profiles.is_super", return_value=True):
                response = client.post("/api/system/containers/unknown/stop")
                assert response.status_code == 404

    def test_stop_service_success(self, client):
        with patch("auth.get_current_user", return_value="admin"):
            with patch("user_profiles.is_super", return_value=True):
                with patch("system.containers.httpx.AsyncClient") as mock_client:
                    mock_response = MagicMock()
                    mock_response.status_code = 204
                    mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                        return_value=mock_response
                    )

                    response = client.post("/api/system/containers/ac/stop")

                    assert response.status_code == 200
                    assert response.json()["status"] == "ok"

    def test_start_service_success(self, client):
        with patch("auth.get_current_user", return_value="admin"):
            with patch("user_profiles.is_super", return_value=True):
                with patch("system.containers.httpx.AsyncClient") as mock_client:
                    mock_response = MagicMock()
                    mock_response.status_code = 204
                    mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                        return_value=mock_response
                    )

                    response = client.post("/api/system/containers/ac/start")

                    assert response.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# AC Proxy Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestACProxies:
    def test_ac_status(self, client):
        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {"state": "off", "setpoint": 24.0}
            mock_response.status_code = 200
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            response = client.get("/api/ac/status")
            assert response.status_code == 200

    def test_ac_sensors(self, client):
        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {"sensors": []}
            mock_response.status_code = 200
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            response = client.get("/api/ac/sensors")
            assert response.status_code == 200

    def test_ac_config_get(self, client):
        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {"target_temperature": 25.0}
            mock_response.status_code = 200
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            response = client.get("/api/ac/config")
            assert response.status_code == 200

    def test_ac_config_post(self, client):
        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"status": "ok"}
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            response = client.post(
                "/api/ac/config", json={"target_temperature": 24.0}
            )
            assert response.status_code == 200

    def test_ac_control(self, client):
        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"mode": "auto"}
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            response = client.post("/api/ac/control", json={"mode": "auto"})
            assert response.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# Vacaciones Proxy Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestVacacionesProxies:
    def test_vacaciones_get(self, client):
        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {"years": [2024, 2025]}
            mock_response.status_code = 200
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            response = client.get("/api/vacaciones")
            assert response.status_code == 200

    def test_vacaciones_config(self, client):
        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {"nucleos": []}
            mock_response.status_code = 200
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            response = client.get("/api/vacaciones/config")
            assert response.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# Portfolio Proxy Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestPortfolioProxies:
    def test_portfolio_summary(self, client):
        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {"total_value": 10000}
            mock_response.status_code = 200
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            response = client.get("/api/portfolio/summary")
            assert response.status_code == 200

    def test_portfolio_etf(self, client):
        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {"etfs": []}
            mock_response.status_code = 200
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            response = client.get("/api/portfolio/etf")
            assert response.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# PC Control Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestPCControl:
    def test_pc_status_offline(self, client):
        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                side_effect=Exception("Timeout")
            )

            response = client.get("/api/pc/status")

            assert response.status_code == 200
            assert response.json()["online"] is False

    def test_pc_mode_get(self, client):
        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {"mode": "balanced"}
            mock_response.status_code = 200
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            response = client.get("/api/pc/mode")
            assert response.status_code == 200

    def test_pc_mode_set_invalid(self, client):
        response = client.post("/api/pc/mode/invalid")
        assert response.status_code == 400

    def test_pc_mode_set_valid(self, client):
        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {"mode": "gaming"}
            mock_response.status_code = 200
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            response = client.post("/api/pc/mode/gaming")
            assert response.status_code == 200

