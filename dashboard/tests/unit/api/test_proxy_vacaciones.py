"""Unit tests for api/proxy/vacaciones.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from httpx import Response

from api.proxy.vacaciones import (
    add_vacaciones_year,
    delete_vacaciones_year,
    get_vacaciones,
    get_vacaciones_config,
    post_vacaciones_config,
    post_vacaciones_year,
    router,
)


def make_mock_response(data, status_code=200):
    """Create a mock HTTP response."""
    resp = MagicMock(spec=Response)
    resp.status_code = status_code
    resp.json.return_value = data
    resp.text = str(data)
    return resp


def make_mock_request(json_data=None):
    """Create a mock FastAPI request."""
    mock_req = MagicMock()
    if json_data is not None:
        mock_req.json = AsyncMock(return_value=json_data)
    return mock_req


# All tests mock httpx at the base module level since ServiceProxy uses httpx
HTTPX_PATCH = "libs.service_proxy.proxy.httpx.AsyncClient"


class TestGetEndpoints:
    """Tests for GET endpoints."""

    @pytest.mark.asyncio
    async def test_get_vacaciones_success(self):
        """Returns all vacaciones data."""
        data = {"years": [{"year": 2024, "momentos": []}]}
        with patch(HTTPX_PATCH) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = make_mock_response(data)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await get_vacaciones()
            assert result == data

    @pytest.mark.asyncio
    async def test_get_vacaciones_service_error(self):
        """Raises 503 when service unavailable."""
        with patch(HTTPX_PATCH) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.side_effect = Exception("Connection refused")
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await get_vacaciones()
            assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_get_config_success(self):
        """Returns config data."""
        config = {"nucleos": [], "personas": []}
        with patch(HTTPX_PATCH) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = make_mock_response(config)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await get_vacaciones_config()
            assert result == config


class TestPostEndpoints:
    """Tests for POST endpoints."""

    @pytest.mark.asyncio
    async def test_post_config_success(self):
        """Saves config successfully."""
        req = make_mock_request({"nucleos": ["A"], "personas": ["B"]})
        resp_data = {"status": "saved"}

        with patch(HTTPX_PATCH) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = make_mock_response(resp_data)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await post_vacaciones_config(req)
            assert result == resp_data

    @pytest.mark.asyncio
    async def test_add_year_success(self):
        """Adds new year successfully."""
        request = make_mock_request()
        resp_data = {"year": 2025, "momentos": []}

        with patch(HTTPX_PATCH) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = make_mock_response(resp_data)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await add_vacaciones_year(request)
            assert result == resp_data

    @pytest.mark.asyncio
    async def test_post_year_success(self):
        """Saves year data successfully."""
        req = make_mock_request({"momentos": [{"id": 1}]})
        resp_data = {"status": "saved"}

        with patch(HTTPX_PATCH) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = make_mock_response(resp_data)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await post_vacaciones_year(2024, req)
            assert result == resp_data


class TestDeleteEndpoint:
    """Tests for DELETE endpoint."""

    @pytest.mark.asyncio
    async def test_delete_year_success(self):
        """Deletes year successfully."""
        request = make_mock_request()
        resp_data = {"status": "deleted"}

        with patch(HTTPX_PATCH) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.delete.return_value = make_mock_response(resp_data)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await delete_vacaciones_year(2024, request)
            assert result == resp_data

    @pytest.mark.asyncio
    async def test_delete_year_not_found(self):
        """Returns error when year not found."""
        request = make_mock_request()
        with patch(HTTPX_PATCH) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.delete.return_value = make_mock_response(
                {"detail": "Year not found"}, status_code=404
            )
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await delete_vacaciones_year(1999, request)
            assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_year_cannot_delete_only(self):
        """Returns error when trying to delete last year."""
        request = make_mock_request()
        with patch(HTTPX_PATCH) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.delete.return_value = make_mock_response(
                {"detail": "Cannot delete"}, status_code=400
            )
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await delete_vacaciones_year(2024, request)
            assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_delete_year_service_error(self):
        """Raises 503 when service unavailable."""
        request = make_mock_request()
        with patch(HTTPX_PATCH) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.delete.side_effect = Exception("Connection refused")
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await delete_vacaciones_year(2024, request)
            assert exc.value.status_code == 503
