"""Tests for the metrics-service health check (api.health.get_metrics_health)."""

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
async def test_metrics_health_online_passes_through_fields():
    async def mock_get(url):
        assert "metrics-service:8011/health" in url
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "online": True,
            "db_ok": True,
            "collector_last_tick_age_s": 12.3,
        }
        return resp

    with patch("httpx.AsyncClient", return_value=_make_mock_client(mock_get)):
        result = await health.get_metrics_health()

    assert result["online"] is True
    assert result["db_ok"] is True
    assert result["collector_last_tick_age_s"] == 12.3


@pytest.mark.asyncio
async def test_metrics_health_non_200_marks_offline():
    async def mock_get(url):
        resp = MagicMock()
        resp.status_code = 503
        return resp

    with patch("httpx.AsyncClient", return_value=_make_mock_client(mock_get)):
        result = await health.get_metrics_health()

    assert result["online"] is False
    assert "HTTP 503" in result["error"]


@pytest.mark.asyncio
async def test_metrics_health_connect_error():
    import httpx

    async def mock_get(url):
        raise httpx.ConnectError("down")

    with patch("httpx.AsyncClient", return_value=_make_mock_client(mock_get)):
        result = await health.get_metrics_health()

    assert result["online"] is False
    assert "Cannot connect to metrics-service" in result["error"]
