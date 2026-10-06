"""Unit tests for api/proxy/vacaciones.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from httpx import Response

from api.proxy.vacaciones import (
    router,
    get_vacaciones,
    get_vacaciones_config,
    post_vacaciones_config,
    add_vacaciones_year,
    post_vacaciones_year,
    delete_vacaciones_year,
)


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
    async def test_get_vacaciones_success(self):
        """Returns all vacaciones data."""
        data = {"years": [{"year": 2024, "momentos": []}]}
        with patch("api.proxy.vacaciones.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = make_mock_response(data)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await get_vacaciones()
            assert result == data

    @pytest.mark.asyncio
    async def test_get_vacaciones_service_error(self):
        """Raises 503 when service unavailable."""
        with patch("api.proxy.vacaciones.httpx.AsyncClient") as mock_client:
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
        with patch("api.proxy.vacaciones.httpx.AsyncClient") as mock_client:
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
        new_config = {"nucleos": [{"name": "Family"}]}
        request = make_mock_request(json_data=new_config)

        with patch("api.proxy.vacaciones.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = make_mock_response(new_config)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await post_vacaciones_config(request)
            assert result == new_config

    @pytest.mark.asyncio
    async def test_add_year_success(self):
        """Adds new year successfully."""
        with patch("api.proxy.vacaciones.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = make_mock_response({"year": 2025})
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await add_vacaciones_year()
            assert result["year"] == 2025

    @pytest.mark.asyncio
    async def test_post_year_success(self):
        """Saves year planning successfully."""
        year_data = {"momentos": [{"name": "Christmas", "asignaciones": []}]}
        request = make_mock_request(json_data=year_data)

        with patch("api.proxy.vacaciones.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = make_mock_response(year_data)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await post_vacaciones_year(2024, request)
            assert result == year_data


class TestDeleteEndpoint:
    """Tests for DELETE endpoint."""

    @pytest.mark.asyncio
    async def test_delete_year_success(self):
        """Deletes year successfully."""
        with patch("api.proxy.vacaciones.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.delete.return_value = make_mock_response({"deleted": 2024})
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await delete_vacaciones_year(2024)
            assert result["deleted"] == 2024

    @pytest.mark.asyncio
    async def test_delete_year_not_found(self):
        """Raises 404 when year not found."""
        with patch("api.proxy.vacaciones.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.delete.return_value = make_mock_response(
                {"detail": "Year not found"}, 404
            )
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await delete_vacaciones_year(1999)
            assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_year_cannot_delete_only(self):
        """Raises 400 when trying to delete the only year."""
        with patch("api.proxy.vacaciones.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.delete.return_value = make_mock_response(
                {"detail": "Cannot delete only year"}, 400
            )
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await delete_vacaciones_year(2024)
            assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_delete_year_service_error(self):
        """Raises 503 on service error."""
        with patch("api.proxy.vacaciones.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.delete.side_effect = Exception("Connection refused")
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await delete_vacaciones_year(2024)
            assert exc.value.status_code == 503


class TestRouterConfiguration:
    """Tests for router configuration."""

    def test_router_has_correct_prefix(self):
        """Router has /api/vacaciones prefix."""
        assert router.prefix == "/api/vacaciones"

    def test_router_has_vacaciones_tag(self):
        """Router is tagged as Vacaciones."""
        assert "Vacaciones" in router.tags
