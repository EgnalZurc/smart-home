"""Unit tests for api/proxy/portfolio.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from httpx import Response

from api.proxy.portfolio import (
    router,
    get_portfolio_summary,
    get_portfolio_etf,
    get_portfolio_crypto,
    refresh_portfolio,
    refresh_portfolio_monitor,
    get_portfolio_schedule,
    reload_portfolio_config,
    get_portfolio_notification_status,
    test_portfolio_notification,
)


def make_mock_response(data, status_code=200):
    """Create a mock HTTP response."""
    resp = MagicMock(spec=Response)
    resp.status_code = status_code
    resp.json.return_value = data
    return resp


class TestGetEndpoints:
    """Tests for GET endpoints."""

    @pytest.mark.asyncio
    async def test_get_summary_success(self):
        """Returns portfolio summary."""
        summary = {"total_value": 10000, "etf": {}, "crypto": {}}
        with patch("api.proxy.portfolio.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = make_mock_response(summary)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await get_portfolio_summary()
            assert result == summary

    @pytest.mark.asyncio
    async def test_get_summary_service_error(self):
        """Raises 503 when service unavailable."""
        with patch("api.proxy.portfolio.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.side_effect = Exception("Connection refused")
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await get_portfolio_summary()
            assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_get_etf_success(self):
        """Returns ETF portfolio."""
        etf = {"holdings": [], "total": 5000}
        with patch("api.proxy.portfolio.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = make_mock_response(etf)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await get_portfolio_etf()
            assert result == etf

    @pytest.mark.asyncio
    async def test_get_crypto_success(self):
        """Returns crypto staking data."""
        crypto = {"staking": [], "total": 2000}
        with patch("api.proxy.portfolio.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = make_mock_response(crypto)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await get_portfolio_crypto()
            assert result == crypto

    @pytest.mark.asyncio
    async def test_get_schedule_success(self):
        """Returns monitoring schedule."""
        schedule = {"etf": "daily", "crypto": "hourly"}
        with patch("api.proxy.portfolio.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = make_mock_response(schedule)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await get_portfolio_schedule()
            assert result == schedule

    @pytest.mark.asyncio
    async def test_get_notification_status_success(self):
        """Returns notification status."""
        status = {"telegram": True, "last_sent": "2024-01-01"}
        with patch("api.proxy.portfolio.httpx.AsyncClient") as mock_client:
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
        with patch("api.proxy.portfolio.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = make_mock_response({"refreshed": True})
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await refresh_portfolio()
            assert result["refreshed"] == True

    @pytest.mark.asyncio
    async def test_refresh_monitor_success(self):
        """Refreshes specific monitor."""
        with patch("api.proxy.portfolio.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = make_mock_response({"refreshed": "etf"})
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await refresh_portfolio_monitor("etf")
            assert result["refreshed"] == "etf"

    @pytest.mark.asyncio
    async def test_refresh_monitor_not_found(self):
        """Raises 404 for unknown monitor."""
        with patch("api.proxy.portfolio.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = make_mock_response(
                {"detail": "Monitor not found"}, 404
            )
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await refresh_portfolio_monitor("unknown")
            assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_reload_config_success(self):
        """Reloads config successfully."""
        with patch("api.proxy.portfolio.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = make_mock_response({"reloaded": True})
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await reload_portfolio_config()
            assert result["reloaded"] == True

    @pytest.mark.asyncio
    async def test_test_notification_success(self):
        """Sends test notification."""
        with patch("api.proxy.portfolio.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = make_mock_response({"sent": True})
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await test_portfolio_notification()
            assert result["sent"] == True

    @pytest.mark.asyncio
    async def test_test_notification_telegram_error(self):
        """Raises error when Telegram fails."""
        with patch("api.proxy.portfolio.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = make_mock_response(
                {"detail": "Telegram not configured"}, 400
            )
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await test_portfolio_notification()
            assert exc.value.status_code == 400


class TestRouterConfiguration:
    """Tests for router configuration."""

    def test_router_has_correct_prefix(self):
        """Router has /api/portfolio prefix."""
        assert router.prefix == "/api/portfolio"

    def test_router_has_portfolio_tag(self):
        """Router is tagged as Portfolio."""
        assert "Portfolio" in router.tags
