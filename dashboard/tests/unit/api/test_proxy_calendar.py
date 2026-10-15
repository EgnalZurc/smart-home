"""Unit tests for api/proxy/calendar.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from api.proxy.calendar import (
    get_calendar_config,
    get_today_events,
    post_calendar_config,
    router,
    trigger_calendar_sync,
)
from fastapi import HTTPException
from httpx import Response


def make_mock_response(data, status_code=200):
    """Create a mock HTTP response."""
    resp = MagicMock(spec=Response)
    resp.status_code = status_code
    resp.json.return_value = data
    resp.text = str(data)
    return resp


def make_mock_request(json_data=None, is_super=True):
    """Create a mock FastAPI request with SUPER user auth."""
    mock_req = MagicMock()
    if json_data is not None:
        mock_req.json = AsyncMock(return_value=json_data)
    return mock_req


HTTPX_PATCH = "libs.service_proxy.proxy.httpx.AsyncClient"
AUTH_PATCH = "api.proxy.calendar.require_super"


class TestGetConfig:
    """Tests for GET /api/settings/calendar/config."""

    @pytest.mark.asyncio
    async def test_get_config_success(self):
        """Returns calendar config for SUPER user."""
        config = {
            "sync_interval_s": 1800,
            "default_offsets_s": [86400, 7200, 1800],
            "calendars": [{"id": "test@gmail.com", "label": "Test", "enabled": True}],
        }
        with (
            patch(AUTH_PATCH) as mock_auth,
            patch(HTTPX_PATCH) as mock_client,
        ):
            mock_auth.return_value = "admin"
            mock_instance = AsyncMock()
            mock_instance.get.return_value = make_mock_response(config)
            mock_client.return_value.__aenter__.return_value = mock_instance

            req = make_mock_request()
            result = await get_calendar_config(req)
            assert result == config
            mock_auth.assert_called_once_with(req)

    @pytest.mark.asyncio
    async def test_get_config_not_super(self):
        """Raises 403 for non-SUPER user."""
        with patch(AUTH_PATCH) as mock_auth:
            mock_auth.side_effect = HTTPException(
                status_code=403, detail="Admin access required"
            )
            req = make_mock_request(is_super=False)

            with pytest.raises(HTTPException) as exc:
                await get_calendar_config(req)
            assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_get_config_service_unavailable(self):
        """Raises 503 when calendar-service is down."""
        with (
            patch(AUTH_PATCH) as mock_auth,
            patch(HTTPX_PATCH) as mock_client,
        ):
            mock_auth.return_value = "admin"
            mock_instance = AsyncMock()
            mock_instance.get.side_effect = Exception("Connection refused")
            mock_client.return_value.__aenter__.return_value = mock_instance

            req = make_mock_request()
            with pytest.raises(HTTPException) as exc:
                await get_calendar_config(req)
            assert exc.value.status_code == 503


class TestPostConfig:
    """Tests for POST /api/settings/calendar/config."""

    @pytest.mark.asyncio
    async def test_post_config_success(self):
        """Saves config successfully."""
        config = {"sync_interval_s": 3600}
        resp_data = {"status": "ok"}

        with (
            patch(AUTH_PATCH) as mock_auth,
            patch(HTTPX_PATCH) as mock_client,
        ):
            mock_auth.return_value = "admin"
            mock_instance = AsyncMock()
            mock_instance.post.return_value = make_mock_response(resp_data)
            mock_client.return_value.__aenter__.return_value = mock_instance

            req = make_mock_request(json_data=config)
            result = await post_calendar_config(req)
            assert result == resp_data

    @pytest.mark.asyncio
    async def test_post_config_not_super(self):
        """Raises 403 for non-SUPER user."""
        with patch(AUTH_PATCH) as mock_auth:
            mock_auth.side_effect = HTTPException(
                status_code=403, detail="Admin access required"
            )
            req = make_mock_request(json_data={})

            with pytest.raises(HTTPException) as exc:
                await post_calendar_config(req)
            assert exc.value.status_code == 403


class TestTriggerSync:
    """Tests for POST /api/settings/calendar/sync."""

    @pytest.mark.asyncio
    async def test_sync_success(self):
        """Triggers sync successfully."""
        resp_data = {"status": "sync_started", "calendars_synced": 2}

        with (
            patch(AUTH_PATCH) as mock_auth,
            patch(HTTPX_PATCH) as mock_client,
        ):
            mock_auth.return_value = "admin"
            mock_instance = AsyncMock()
            mock_instance.post.return_value = make_mock_response(resp_data)
            mock_client.return_value.__aenter__.return_value = mock_instance

            req = make_mock_request()
            result = await trigger_calendar_sync(req)
            assert result == resp_data

    @pytest.mark.asyncio
    async def test_sync_not_super(self):
        """Raises 403 for non-SUPER user."""
        with patch(AUTH_PATCH) as mock_auth:
            mock_auth.side_effect = HTTPException(
                status_code=403, detail="Admin access required"
            )
            req = make_mock_request()

            with pytest.raises(HTTPException) as exc:
                await trigger_calendar_sync(req)
            assert exc.value.status_code == 403


class TestGetTodayEvents:
    """Tests for GET /api/settings/calendar/today."""

    @pytest.mark.asyncio
    async def test_get_today_success(self):
        """Returns today's events."""
        events = {
            "date": "2026-10-15",
            "events": [
                {
                    "id": "evt1",
                    "summary": "Meeting",
                    "start_ts": 1729000000,
                    "end_ts": 1729003600,
                }
            ],
        }

        with (
            patch(AUTH_PATCH) as mock_auth,
            patch(HTTPX_PATCH) as mock_client,
        ):
            mock_auth.return_value = "admin"
            mock_instance = AsyncMock()
            mock_instance.get.return_value = make_mock_response(events)
            mock_client.return_value.__aenter__.return_value = mock_instance

            req = make_mock_request()
            result = await get_today_events(req)
            assert result == events

    @pytest.mark.asyncio
    async def test_get_today_empty(self):
        """Returns empty list when no events."""
        events = {"date": "2026-10-15", "events": []}

        with (
            patch(AUTH_PATCH) as mock_auth,
            patch(HTTPX_PATCH) as mock_client,
        ):
            mock_auth.return_value = "admin"
            mock_instance = AsyncMock()
            mock_instance.get.return_value = make_mock_response(events)
            mock_client.return_value.__aenter__.return_value = mock_instance

            req = make_mock_request()
            result = await get_today_events(req)
            assert result["events"] == []

    @pytest.mark.asyncio
    async def test_get_today_not_super(self):
        """Raises 403 for non-SUPER user."""
        with patch(AUTH_PATCH) as mock_auth:
            mock_auth.side_effect = HTTPException(
                status_code=403, detail="Admin access required"
            )
            req = make_mock_request()

            with pytest.raises(HTTPException) as exc:
                await get_today_events(req)
            assert exc.value.status_code == 403


class TestRouterRegistration:
    """Tests for router configuration."""

    def test_router_prefix(self):
        """Router has correct prefix."""
        assert router.prefix == "/api/settings/calendar"

    def test_router_tags(self):
        """Router has correct tags."""
        assert "Calendar Settings" in router.tags
