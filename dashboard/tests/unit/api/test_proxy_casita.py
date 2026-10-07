"""Unit tests for api/proxy/casita.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from httpx import Response

from api.proxy.casita import (
    dismiss_casita_property,
    get_casita_dismissed,
    get_casita_radar,
    get_casita_schedule,
    get_casita_status,
    get_casita_summary,
    mark_casita_viewed,
    router,
    run_casita_scraping,
    run_casita_summary,
    save_casita_comment,
    save_casita_schedule,
    undismiss_casita_property,
)


def make_mock_response(data, status_code=200):
    """Create a mock HTTP response."""
    resp = MagicMock(spec=Response)
    resp.status_code = status_code
    resp.json.return_value = data
    resp.text = str(data)
    return resp


def make_mock_request(json_data=None, query_params=None):
    """Create a mock FastAPI request."""
    mock_req = MagicMock()
    mock_req.query_params = query_params or {}
    if json_data is not None:
        mock_req.json = AsyncMock(return_value=json_data)
    return mock_req


# All tests mock httpx at the base module level since ServiceProxy uses httpx
HTTPX_PATCH = "api.proxy.base.httpx.AsyncClient"


class TestGetEndpoints:
    """Tests for GET endpoints."""

    @pytest.mark.asyncio
    async def test_get_status_success(self):
        """Returns casita status."""
        status = {"online": True, "total_properties": 50}
        with patch(HTTPX_PATCH) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = make_mock_response(status)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await get_casita_status()
            assert result == status

    @pytest.mark.asyncio
    async def test_get_status_service_error_returns_fallback(self):
        """Returns fallback on service error."""
        with patch(HTTPX_PATCH) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.side_effect = Exception("Connection refused")
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await get_casita_status()
            assert result["online"] is False
            assert "error" in result

    @pytest.mark.asyncio
    async def test_get_radar_success(self):
        """Returns radar properties."""
        radar = {"items": [{"id": "1"}], "total": 1}
        request = make_mock_request()

        with patch(HTTPX_PATCH) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = make_mock_response(radar)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await get_casita_radar(request)
            assert result == radar

    @pytest.mark.asyncio
    async def test_get_radar_with_query_params(self):
        """Passes query params correctly."""
        request = make_mock_request(query_params={"limit": "10", "offset": "20"})

        with patch(HTTPX_PATCH) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = make_mock_response({"items": []})
            mock_client.return_value.__aenter__.return_value = mock_instance

            await get_casita_radar(request)

            # The call should include params
            mock_instance.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_radar_error_returns_fallback(self):
        """Returns fallback on radar error."""
        request = make_mock_request()

        with patch(HTTPX_PATCH) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.side_effect = Exception("Connection refused")
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await get_casita_radar(request)
            assert result["items"] == []
            assert "error" in result

    @pytest.mark.asyncio
    async def test_get_dismissed_success(self):
        """Returns dismissed properties."""
        dismissed = {"properties": [{"id": "1"}]}
        with patch(HTTPX_PATCH) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = make_mock_response(dismissed)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await get_casita_dismissed()
            assert result == dismissed

    @pytest.mark.asyncio
    async def test_get_schedule_success(self):
        """Returns schedule config."""
        schedule = {"cron": "0 8 * * *"}
        with patch(HTTPX_PATCH) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = make_mock_response(schedule)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await get_casita_schedule()
            assert result == schedule

    @pytest.mark.asyncio
    async def test_get_summary_success(self):
        """Returns AI summary."""
        summary = {"content": "Test summary", "sent_at": "2024-01-01"}
        with patch(HTTPX_PATCH) as mock_client:
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
        request = make_mock_request({"cron": "0 9 * * *"})
        resp_data = {"status": "saved"}

        with patch(HTTPX_PATCH) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = make_mock_response(resp_data)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await save_casita_schedule(request)
            assert result == resp_data

    @pytest.mark.asyncio
    async def test_save_schedule_error(self):
        """Raises on schedule save error."""
        request = make_mock_request({"cron": "invalid"})

        with patch(HTTPX_PATCH) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.side_effect = Exception("Connection refused")
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await save_casita_schedule(request)
            assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_dismiss_property_success(self):
        """Dismisses property successfully."""
        request = make_mock_request({"property_id": "123"})
        resp_data = {"status": "dismissed"}

        with patch(HTTPX_PATCH) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = make_mock_response(resp_data)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await dismiss_casita_property(request)
            assert result == resp_data

    @pytest.mark.asyncio
    async def test_undismiss_property_success(self):
        """Undismisses property successfully."""
        request = make_mock_request({"property_id": "123"})
        resp_data = {"status": "undismissed"}

        with patch(HTTPX_PATCH) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = make_mock_response(resp_data)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await undismiss_casita_property(request)
            assert result == resp_data

    @pytest.mark.asyncio
    async def test_mark_viewed_success(self):
        """Marks property as viewed."""
        request = make_mock_request({"property_id": "123"})
        resp_data = {"status": "viewed"}

        with patch(HTTPX_PATCH) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = make_mock_response(resp_data)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await mark_casita_viewed(request)
            assert result == resp_data

    @pytest.mark.asyncio
    async def test_save_comment_success(self):
        """Saves comment successfully."""
        request = make_mock_request({"property_id": "123", "comment": "Nice!"})
        resp_data = {"status": "saved"}

        with patch(HTTPX_PATCH) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = make_mock_response(resp_data)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await save_casita_comment(request)
            assert result == resp_data

    @pytest.mark.asyncio
    async def test_run_scraping_success(self):
        """Triggers scraping successfully."""
        resp_data = {"status": "started"}

        with patch(HTTPX_PATCH) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = make_mock_response(resp_data)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await run_casita_scraping()
            assert result == resp_data

    @pytest.mark.asyncio
    async def test_run_summary_success(self):
        """Triggers summary generation successfully."""
        resp_data = {"status": "started"}

        with patch(HTTPX_PATCH) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = make_mock_response(resp_data)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await run_casita_summary()
            assert result == resp_data
