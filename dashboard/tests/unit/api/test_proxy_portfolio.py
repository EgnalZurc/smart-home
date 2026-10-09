"""Unit tests for api/proxy/portfolio.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from httpx import Response

from api.proxy.portfolio import (
    get_portfolio_crypto,
    get_portfolio_etf,
    get_portfolio_notification_status,
    get_portfolio_schedule,
    get_portfolio_summary,
    refresh_portfolio,
    refresh_portfolio_monitor,
    reload_portfolio_config,
    router,
    test_portfolio_notification as send_test_notification,
)


def make_mock_response(data, status_code=200):
    """Create a mock HTTP response."""
    resp = MagicMock(spec=Response)
    resp.status_code = status_code
    resp.json.return_value = data
    resp.text = str(data)
    return resp


def make_mock_request():
    """Create a mock FastAPI request."""
    return MagicMock()


# All tests mock httpx at the base module level since ServiceProxy uses httpx
HTTPX_PATCH = "libs.service_proxy.proxy.httpx.AsyncClient"


class TestGetEndpoints:
    """Tests for GET endpoints."""

    @pytest.mark.asyncio
    async def test_get_summary_success(self):
        """Returns full portfolio summary."""
        summary = {"etf": {"total": 1000}, "crypto": {"total": 500}}
        with patch(HTTPX_PATCH) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = make_mock_response(summary)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await get_portfolio_summary()
            assert result == summary

    @pytest.mark.asyncio
    async def test_get_summary_service_error(self):
        """Raises 503 when service unavailable."""
        with patch(HTTPX_PATCH) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.side_effect = Exception("Connection refused")
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await get_portfolio_summary()
            assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_get_etf_success(self):
        """Returns ETF portfolio."""
        etf = {"positions": [], "total": 1000}
        with patch(HTTPX_PATCH) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = make_mock_response(etf)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await get_portfolio_etf()
            assert result == etf

    @pytest.mark.asyncio
    async def test_get_crypto_success(self):
        """Returns crypto portfolio."""
        crypto = {"positions": [], "total": 500}
        with patch(HTTPX_PATCH) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = make_mock_response(crypto)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await get_portfolio_crypto()
            assert result == crypto

    @pytest.mark.asyncio
    async def test_get_schedule_success(self):
        """Returns monitoring schedule."""
        schedule = {"cron": "0 8 * * *"}
        with patch(HTTPX_PATCH) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = make_mock_response(schedule)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await get_portfolio_schedule()
            assert result == schedule

    @pytest.mark.asyncio
    async def test_get_notification_status_success(self):
        """Returns notification status."""
        status = {"enabled": True, "last_sent": "2024-01-01"}
        with patch(HTTPX_PATCH) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = make_mock_response(status)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await get_portfolio_notification_status()
            assert result == status


class TestPostEndpoints:
    """Tests for POST endpoints."""

    @pytest.mark.asyncio
    async def test_refresh_all_success(self):
        """Refreshes all monitors."""
        request = make_mock_request()
        resp_data = {"status": "refreshed"}
        with patch(HTTPX_PATCH) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = make_mock_response(resp_data)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await refresh_portfolio(request)
            assert result == resp_data

    @pytest.mark.asyncio
    async def test_refresh_monitor_success(self):
        """Refreshes specific monitor."""
        request = make_mock_request()
        resp_data = {"status": "refreshed", "monitor": "etf"}
        with patch(HTTPX_PATCH) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = make_mock_response(resp_data)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await refresh_portfolio_monitor("etf", request)
            assert result == resp_data

    @pytest.mark.asyncio
    async def test_refresh_monitor_not_found(self):
        """Returns error for unknown monitor."""
        request = make_mock_request()
        with patch(HTTPX_PATCH) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = make_mock_response(
                {"detail": "Monitor not found"}, status_code=404
            )
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await refresh_portfolio_monitor("unknown", request)
            assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_reload_config_success(self):
        """Reloads configuration."""
        request = make_mock_request()
        resp_data = {"status": "reloaded"}
        with patch(HTTPX_PATCH) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = make_mock_response(resp_data)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await reload_portfolio_config(request)
            assert result == resp_data

    @pytest.mark.asyncio
    async def test_send_notification_success(self):
        """Sends test notification."""
        request = make_mock_request()
        resp_data = {"status": "sent"}
        with patch(HTTPX_PATCH) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = make_mock_response(resp_data)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await send_test_notification(request)
            assert result == resp_data

    @pytest.mark.asyncio
    async def test_send_notification_telegram_error(self):
        """Returns error when Telegram fails."""
        request = make_mock_request()
        with patch(HTTPX_PATCH) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = make_mock_response(
                {"detail": "Telegram API error"}, status_code=500
            )
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await send_test_notification(request)
            assert exc.value.status_code == 500
