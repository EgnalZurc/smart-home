"""Unit tests for api/proxy/casita.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from httpx import Response

from api.proxy.casita import (
    router,
    get_casita_status,
    get_casita_radar,
    get_casita_dismissed,
    get_casita_schedule,
    save_casita_schedule,
    dismiss_casita_property,
    undismiss_casita_property,
    mark_casita_viewed,
    save_casita_comment,
    get_casita_summary,
    run_casita_scraping,
    run_casita_summary,
)


def make_mock_response(data, status_code=200):
    """Create a mock HTTP response."""
    resp = MagicMock(spec=Response)
    resp.status_code = status_code
    resp.json.return_value = data
    return resp


def make_mock_request(json_data=None, query_string=""):
    """Create a mock FastAPI request."""
    mock_req = MagicMock()
    mock_req.url = MagicMock()
    mock_req.url.query = query_string
    if json_data is not None:
        mock_req.json = AsyncMock(return_value=json_data)
    return mock_req


class TestGetEndpoints:
    """Tests for GET endpoints."""

    @pytest.mark.asyncio
    async def test_get_status_success(self):
        """Returns casita status."""
        status = {"online": True, "total_properties": 50}
        with patch("api.proxy.casita.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = make_mock_response(status)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await get_casita_status()
            assert result == status

    @pytest.mark.asyncio
    async def test_get_status_service_error_returns_fallback(self):
        """Returns fallback on service error."""
        with patch("api.proxy.casita.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.side_effect = Exception("Connection refused")
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await get_casita_status()
            assert result["online"] == False
            assert "error" in result

    @pytest.mark.asyncio
    async def test_get_radar_success(self):
        """Returns radar properties."""
        radar = {"items": [{"id": "1"}], "total": 1}
        request = make_mock_request(query_string="")
        
        with patch("api.proxy.casita.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = make_mock_response(radar)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await get_casita_radar(request)
            assert result == radar

    @pytest.mark.asyncio
    async def test_get_radar_with_query_params(self):
        """Passes query params correctly."""
        request = make_mock_request(query_string="limit=10&offset=20")
        
        with patch("api.proxy.casita.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = make_mock_response({"items": []})
            mock_client.return_value.__aenter__.return_value = mock_instance

            await get_casita_radar(request)
            
            call_url = mock_instance.get.call_args[0][0]
            assert "limit=10&offset=20" in call_url

    @pytest.mark.asyncio
    async def test_get_radar_error_returns_fallback(self):
        """Returns empty fallback on error."""
        request = make_mock_request()
        
        with patch("api.proxy.casita.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.side_effect = Exception("Timeout")
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await get_casita_radar(request)
            assert result["items"] == []
            assert "error" in result

    @pytest.mark.asyncio
    async def test_get_dismissed_success(self):
        """Returns dismissed properties."""
        dismissed = {"properties": [{"id": "1", "reason": "too far"}]}
        with patch("api.proxy.casita.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = make_mock_response(dismissed)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await get_casita_dismissed()
            assert result == dismissed

    @pytest.mark.asyncio
    async def test_get_schedule_success(self):
        """Returns schedule config."""
        schedule = {"hours": [8, 14, 20]}
        with patch("api.proxy.casita.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = make_mock_response(schedule)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await get_casita_schedule()
            assert result == schedule

    @pytest.mark.asyncio
    async def test_get_summary_success(self):
        """Returns AI summary."""
        summary = {"content": "3 new properties...", "sent_at": "2024-01-01"}
        with patch("api.proxy.casita.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = make_mock_response(summary)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await get_casita_summary()
            assert result == summary


class TestPostEndpoints:
    """Tests for POST endpoints."""

    @pytest.mark.asyncio
    async def test_save_schedule_success(self):
        """Saves schedule successfully."""
        new_schedule = {"hours": [9, 15]}
        request = make_mock_request(json_data=new_schedule)

        with patch("api.proxy.casita.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = make_mock_response(new_schedule)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await save_casita_schedule(request)
            assert result == new_schedule

    @pytest.mark.asyncio
    async def test_save_schedule_error(self):
        """Raises 503 on service error."""
        request = make_mock_request(json_data={})

        with patch("api.proxy.casita.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.side_effect = Exception("Error")
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await save_casita_schedule(request)
            assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_dismiss_property_success(self):
        """Dismisses property successfully."""
        request = make_mock_request(json_data={"property_id": "1"})

        with patch("api.proxy.casita.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = make_mock_response({"status": "dismissed"})
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await dismiss_casita_property(request)
            assert result["status"] == "dismissed"

    @pytest.mark.asyncio
    async def test_undismiss_property_success(self):
        """Undismisses property successfully."""
        request = make_mock_request(json_data={"property_id": "1"})

        with patch("api.proxy.casita.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = make_mock_response({"status": "restored"})
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await undismiss_casita_property(request)
            assert result["status"] == "restored"

    @pytest.mark.asyncio
    async def test_mark_viewed_success(self):
        """Marks property as viewed."""
        request = make_mock_request(json_data={"property_id": "1"})

        with patch("api.proxy.casita.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = make_mock_response({"viewed": True})
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await mark_casita_viewed(request)
            assert result["viewed"] == True

    @pytest.mark.asyncio
    async def test_save_comment_success(self):
        """Saves comment successfully."""
        request = make_mock_request(json_data={"property_id": "1", "comment": "Nice!"})

        with patch("api.proxy.casita.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = make_mock_response({"saved": True})
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await save_casita_comment(request)
            assert result["saved"] == True

    @pytest.mark.asyncio
    async def test_run_scraping_success(self):
        """Triggers scraping successfully."""
        with patch("api.proxy.casita.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = make_mock_response({"started": True})
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await run_casita_scraping()
            assert result["started"] == True

    @pytest.mark.asyncio
    async def test_run_summary_success(self):
        """Triggers summary generation successfully."""
        with patch("api.proxy.casita.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = make_mock_response({"generated": True})
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await run_casita_summary()
            assert result["generated"] == True


class TestRouterConfiguration:
    """Tests for router configuration."""

    def test_router_has_correct_prefix(self):
        """Router has /api/casita prefix."""
        assert router.prefix == "/api/casita"

    def test_router_has_casita_tag(self):
        """Router is tagged as Casita."""
        assert "Casita" in router.tags
