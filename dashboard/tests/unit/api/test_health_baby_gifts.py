"""Tests for the baby-gifts-service health check (api.health.get_baby_gifts_health)."""

from unittest.mock import AsyncMock, MagicMock, patch

import api.health as health
import pytest


# This file tests the health probe, not an authenticated route; no-op the
# root autouse mock_require_super to avoid proxy import coupling.
@pytest.fixture(autouse=True)
def mock_require_super():
    """No-op override of the root fixture."""
    yield


def _make_mock_client(mock_get):
    mock_client = AsyncMock()
    mock_client.get = mock_get
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    return mock_client


@pytest.mark.asyncio
async def test_baby_gifts_health_online():
    """Test baby-gifts health check returns online when service responds."""

    async def mock_get(url):
        assert "baby-gifts-service:8004/health" in url
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"online": True}
        return resp

    with patch("httpx.AsyncClient", return_value=_make_mock_client(mock_get)):
        result = await health.get_baby_gifts_health()

    assert result["online"] is True


@pytest.mark.asyncio
async def test_baby_gifts_health_non_200_marks_offline():
    """Test baby-gifts health check marks offline on non-200 response."""

    async def mock_get(url):
        resp = MagicMock()
        resp.status_code = 503
        return resp

    with patch("httpx.AsyncClient", return_value=_make_mock_client(mock_get)):
        result = await health.get_baby_gifts_health()

    assert result["online"] is False
    assert "HTTP 503" in result["error"]


@pytest.mark.asyncio
async def test_baby_gifts_health_connect_error():
    """Test baby-gifts health check handles connection errors."""
    import httpx

    async def mock_get(url):
        raise httpx.ConnectError("down")

    with patch("httpx.AsyncClient", return_value=_make_mock_client(mock_get)):
        result = await health.get_baby_gifts_health()

    assert result["online"] is False
    assert "Cannot connect to baby-gifts-service" in result["error"]


@pytest.mark.asyncio
async def test_baby_gifts_health_timeout():
    """Test baby-gifts health check handles timeouts."""
    import httpx

    async def mock_get(url):
        raise httpx.TimeoutException("timeout")

    with patch("httpx.AsyncClient", return_value=_make_mock_client(mock_get)):
        result = await health.get_baby_gifts_health()

    assert result["online"] is False
    assert "Timeout" in result["error"]
