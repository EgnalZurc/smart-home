"""Unit tests for api/proxy/ac.py.

After the migration to the shared ``libs/service_proxy`` library, the AC proxy
routes delegate all HTTP work to ``ServiceProxy``. The shared proxy performs the
actual ``httpx`` calls inside ``libs.service_proxy.proxy``, so these tests patch
``httpx.AsyncClient`` there (``PROXY_HTTPX``) rather than in ``api.proxy.ac``.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from httpx import Response

from api.proxy.ac import (
    router,
    get_ac_status,
    get_ac_sensors,
    get_ac_sensors_history,
    get_ac_history,
    get_ac_config,
    update_ac_config,
    set_ac_control_mode,
    set_ac_manual_params,
    update_ac_manual_param,
    get_ac_real,
    get_ac_outdoor,
    get_ac_errors,
    get_ac_energy_current,
    get_ac_energy_hourly,
    get_ac_energy_monthly,
    get_ac_subscriptions_stats,
)

# Patch target: the shared library's httpx client.
PROXY_HTTPX = "libs.service_proxy.proxy.httpx.AsyncClient"


def make_mock_response(data, status_code=200):
    """Create a mock HTTP response."""
    resp = MagicMock(spec=Response)
    resp.status_code = status_code
    resp.json.return_value = data
    return resp


def make_mock_request(json_data=None):
    """Create a mock FastAPI request."""
    mock_req = MagicMock()
    if json_data is not None:
        mock_req.json = AsyncMock(return_value=json_data)
    return mock_req


class TestGetEndpoints:
    """Tests for GET endpoints."""

    @pytest.mark.asyncio
    async def test_get_status_success(self):
        """Returns AC status."""
        status = {"mode": "auto", "temp": 23.5}
        with patch(PROXY_HTTPX) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = make_mock_response(status)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await get_ac_status()
            assert result == status

    @pytest.mark.asyncio
    async def test_get_status_service_error(self):
        """Raises 503 when service unavailable."""
        with patch(PROXY_HTTPX) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.side_effect = Exception("Connection refused")
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await get_ac_status()
            assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_get_sensors_success(self):
        """Returns sensor readings."""
        sensors = {"bedroom": 24.0, "living": 25.5}
        with patch(PROXY_HTTPX) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = make_mock_response(sensors)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await get_ac_sensors()
            assert result == sensors

    @pytest.mark.asyncio
    async def test_get_sensors_history_with_params(self):
        """Passes history params correctly."""
        history = [{"ts": 1000, "temp": 24.0}]
        with patch(PROXY_HTTPX) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = make_mock_response(history)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await get_ac_sensors_history(start=1000, end=2000, last=10)
            assert result == history

    @pytest.mark.asyncio
    async def test_get_history_with_limit(self):
        """Passes limit param correctly."""
        history = [{"action": "on", "ts": 1000}]
        with patch(PROXY_HTTPX) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = make_mock_response(history)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await get_ac_history(limit=50)
            assert result == history

    @pytest.mark.asyncio
    async def test_get_config_success(self):
        """Returns config."""
        config = {"target_temp": 23.0, "hysteresis": 0.5}
        with patch(PROXY_HTTPX) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = make_mock_response(config)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await get_ac_config()
            assert result == config

    @pytest.mark.asyncio
    async def test_get_real_success(self):
        """Returns real AC state."""
        state = {"power": True, "setpoint": 22}
        with patch(PROXY_HTTPX) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = make_mock_response(state)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await get_ac_real()
            assert result == state

    @pytest.mark.asyncio
    async def test_get_outdoor_success(self):
        """Returns outdoor data."""
        outdoor = {"temp": 35.0, "aqi": 50}
        with patch(PROXY_HTTPX) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = make_mock_response(outdoor)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await get_ac_outdoor()
            assert result == outdoor

    @pytest.mark.asyncio
    async def test_get_errors_success(self):
        """Returns errors list."""
        errors = [{"id": "e1", "msg": "Sensor offline"}]
        with patch(PROXY_HTTPX) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = make_mock_response(errors)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await get_ac_errors()
            assert result == errors

    @pytest.mark.asyncio
    async def test_get_energy_current_success(self):
        """Returns current energy data."""
        energy = {"kwh": 1.5, "cost": 0.30}
        with patch(PROXY_HTTPX) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = make_mock_response(energy)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await get_ac_energy_current()
            assert result == energy

    @pytest.mark.asyncio
    async def test_get_energy_hourly_success(self):
        """Returns hourly energy data."""
        hourly = [{"hour": 0, "kwh": 0.5}]
        with patch(PROXY_HTTPX) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = make_mock_response(hourly)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await get_ac_energy_hourly()
            assert result == hourly

    @pytest.mark.asyncio
    async def test_get_energy_monthly_success(self):
        """Returns monthly energy data."""
        monthly = [{"month": "2024-01", "kwh": 50}]
        with patch(PROXY_HTTPX) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = make_mock_response(monthly)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await get_ac_energy_monthly()
            assert result == monthly

    @pytest.mark.asyncio
    async def test_get_subscriptions_stats_success(self):
        """Returns subscription stats."""
        stats = {"active": 5, "stale": 1}
        with patch(PROXY_HTTPX) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = make_mock_response(stats)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await get_ac_subscriptions_stats()
            assert result == stats


class TestPostEndpoints:
    """Tests for POST endpoints."""

    @pytest.mark.asyncio
    async def test_update_config_success(self):
        """Updates config successfully."""
        new_config = {"target_temp": 24.0}
        request = make_mock_request(json_data=new_config)

        with patch(PROXY_HTTPX) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = make_mock_response(new_config)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await update_ac_config(request)
            assert result == new_config

    @pytest.mark.asyncio
    async def test_update_config_validation_error(self):
        """Raises HTTPException on validation error."""
        request = make_mock_request(json_data={"invalid": "data"})

        with patch(PROXY_HTTPX) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = make_mock_response(
                {"detail": "Invalid field"}, 400
            )
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await update_ac_config(request)
            assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_set_control_mode_success(self):
        """Sets control mode successfully."""
        request = make_mock_request(json_data={"mode": "manual"})

        with patch(PROXY_HTTPX) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = make_mock_response({"mode": "manual"})
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await set_ac_control_mode(request)
            assert result["mode"] == "manual"

    @pytest.mark.asyncio
    async def test_set_manual_params_success(self):
        """Sets manual params successfully."""
        params = {"temp": 22, "fan": "high"}
        request = make_mock_request(json_data=params)

        with patch(PROXY_HTTPX) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = make_mock_response(params)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await set_ac_manual_params(request)
            assert result == params

    @pytest.mark.asyncio
    async def test_update_manual_param_success(self):
        """Updates single param successfully."""
        with patch(PROXY_HTTPX) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = make_mock_response({"temp": 22})
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await update_ac_manual_param("temp", "22")
            assert result["temp"] == 22

    @pytest.mark.asyncio
    async def test_update_manual_param_forwards_query(self):
        """Single-param update forwards param/value as a query string."""
        with patch(PROXY_HTTPX) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = make_mock_response({"ok": True})
            mock_client.return_value.__aenter__.return_value = mock_instance

            await update_ac_manual_param("temp", "22")

            called_url = mock_instance.post.call_args.args[0]
            assert called_url.endswith("/api/ac/manual/param?param=temp&value=22")


class TestRouterConfiguration:
    """Tests for router configuration."""

    def test_router_has_correct_prefix(self):
        """Router has /api/ac prefix."""
        assert router.prefix == "/api/ac"

    def test_router_has_ac_tag(self):
        """Router is tagged as AC."""
        assert "AC" in router.tags


class TestErrorHandlingPaths:
    """Tests for error handling paths to improve coverage."""

    @pytest.mark.asyncio
    async def test_get_sensors_network_error(self):
        """Raises 503 on network error getting sensors."""
        with patch(PROXY_HTTPX) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.side_effect = Exception("Connection refused")
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await get_ac_sensors()
            assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_get_sensors_history_network_error(self):
        """Raises 503 on network error getting history."""
        with patch(PROXY_HTTPX) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.side_effect = Exception("Connection refused")
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await get_ac_sensors_history()
            assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_get_history_network_error(self):
        """Raises 503 on network error getting action history."""
        with patch(PROXY_HTTPX) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.side_effect = Exception("Connection refused")
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await get_ac_history()
            assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_get_config_network_error(self):
        """Raises 503 on network error getting config."""
        with patch(PROXY_HTTPX) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.side_effect = Exception("Connection refused")
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await get_ac_config()
            assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_get_real_network_error(self):
        """Raises 503 on network error getting real state."""
        with patch(PROXY_HTTPX) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.side_effect = Exception("Connection refused")
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await get_ac_real()
            assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_get_outdoor_network_error(self):
        """Raises 503 on network error getting outdoor data."""
        with patch(PROXY_HTTPX) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.side_effect = Exception("Connection refused")
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await get_ac_outdoor()
            assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_get_errors_network_error(self):
        """Raises 503 on network error getting errors."""
        with patch(PROXY_HTTPX) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.side_effect = Exception("Connection refused")
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await get_ac_errors()
            assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_get_energy_current_network_error(self):
        """Raises 503 on network error getting current energy."""
        with patch(PROXY_HTTPX) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.side_effect = Exception("Connection refused")
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await get_ac_energy_current()
            assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_get_energy_hourly_network_error(self):
        """Raises 503 on network error getting hourly energy."""
        with patch(PROXY_HTTPX) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.side_effect = Exception("Connection refused")
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await get_ac_energy_hourly()
            assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_get_energy_monthly_network_error(self):
        """Raises 503 on network error getting monthly energy."""
        with patch(PROXY_HTTPX) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.side_effect = Exception("Connection refused")
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await get_ac_energy_monthly()
            assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_get_subscriptions_stats_network_error(self):
        """Raises 503 on network error getting subscription stats."""
        with patch(PROXY_HTTPX) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.side_effect = Exception("Connection refused")
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await get_ac_subscriptions_stats()
            assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_update_config_network_error(self):
        """Raises 503 on network error updating config."""
        request = make_mock_request(json_data={"target_temp": 24})

        with patch(PROXY_HTTPX) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.side_effect = Exception("Connection refused")
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await update_ac_config(request)
            assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_set_control_mode_network_error(self):
        """Raises 503 on network error setting control mode."""
        request = make_mock_request(json_data={"mode": "auto"})

        with patch(PROXY_HTTPX) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.side_effect = Exception("Connection refused")
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await set_ac_control_mode(request)
            assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_set_control_mode_validation_error(self):
        """Raises HTTPException on validation error setting control mode."""
        request = make_mock_request(json_data={"mode": "invalid"})

        with patch(PROXY_HTTPX) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = make_mock_response(
                {"detail": "Invalid mode"}, 400
            )
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await set_ac_control_mode(request)
            assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_set_manual_params_network_error(self):
        """Raises 503 on network error setting manual params."""
        request = make_mock_request(json_data={"temp": 22})

        with patch(PROXY_HTTPX) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.side_effect = Exception("Connection refused")
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await set_ac_manual_params(request)
            assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_set_manual_params_validation_error(self):
        """Raises HTTPException on validation error setting manual params."""
        request = make_mock_request(json_data={"temp": "invalid"})

        with patch(PROXY_HTTPX) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = make_mock_response(
                {"detail": "Invalid temperature"}, 400
            )
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await set_ac_manual_params(request)
            assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_update_manual_param_network_error(self):
        """Raises 503 on network error updating single param."""
        with patch(PROXY_HTTPX) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.side_effect = Exception("Connection refused")
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await update_ac_manual_param("temp", "22")
            assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_update_manual_param_validation_error(self):
        """Raises HTTPException on validation error updating param."""
        with patch(PROXY_HTTPX) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = make_mock_response(
                {"detail": "Invalid param"}, 400
            )
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await update_ac_manual_param("invalid", "value")
            assert exc.value.status_code == 400


class TestHistoryParameters:
    """Tests for history endpoint parameter handling."""

    @pytest.mark.asyncio
    async def test_history_with_no_params(self):
        """History works with no optional params (sends params=None)."""
        with patch(PROXY_HTTPX) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = make_mock_response([])
            mock_client.return_value.__aenter__.return_value = mock_instance

            await get_ac_sensors_history()

            call_args = mock_instance.get.call_args
            assert call_args.kwargs["params"] is None

    @pytest.mark.asyncio
    async def test_history_with_start_only(self):
        """History with start param only."""
        with patch(PROXY_HTTPX) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = make_mock_response([])
            mock_client.return_value.__aenter__.return_value = mock_instance

            await get_ac_sensors_history(start=1000.0)

            call_args = mock_instance.get.call_args
            assert call_args.kwargs["params"] == {"start": 1000.0}

    @pytest.mark.asyncio
    async def test_history_with_end_only(self):
        """History with end param only."""
        with patch(PROXY_HTTPX) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = make_mock_response([])
            mock_client.return_value.__aenter__.return_value = mock_instance

            await get_ac_sensors_history(end=2000.0)

            call_args = mock_instance.get.call_args
            assert call_args.kwargs["params"] == {"end": 2000.0}

    @pytest.mark.asyncio
    async def test_history_with_last_only(self):
        """History with last param only."""
        with patch(PROXY_HTTPX) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = make_mock_response([])
            mock_client.return_value.__aenter__.return_value = mock_instance

            await get_ac_sensors_history(last=50)

            call_args = mock_instance.get.call_args
            assert call_args.kwargs["params"] == {"last": 50}
