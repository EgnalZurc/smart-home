"""Unit tests for api/metrics.py (SUPER-gated metrics-service proxy)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from api.metrics import (
    get_metrics_latest,
    get_metrics_series,
    get_metrics_summary,
    router,
)
from fastapi import HTTPException
from httpx import Response

# ServiceProxy builds its own httpx.AsyncClient; patch at the library level.
HTTPX_PATCH = "libs.service_proxy.proxy.httpx.AsyncClient"


def _mock_response(data, status_code=200):
    resp = MagicMock(spec=Response)
    resp.status_code = status_code
    resp.json.return_value = data
    resp.text = str(data)
    return resp


def _request():
    return MagicMock()


def test_router_prefix_and_tag():
    assert router.prefix == "/api/metrics"
    assert "Metrics" in router.tags


@pytest.mark.asyncio
async def test_latest_proxies_payload():
    payload = {"ts": 1, "series": {"host.ram.percent|": {"value": 61.2}}}
    with patch(HTTPX_PATCH) as mock_client:
        inst = AsyncMock()
        inst.get.return_value = _mock_response(payload)
        mock_client.return_value.__aenter__.return_value = inst

        result = await get_metrics_latest(_request())
    assert result == payload


@pytest.mark.asyncio
async def test_series_forwards_query_params():
    payload = {"metric": "host.ram.percent", "points": []}
    with patch(HTTPX_PATCH) as mock_client:
        inst = AsyncMock()
        inst.get.return_value = _mock_response(payload)
        mock_client.return_value.__aenter__.return_value = inst

        result = await get_metrics_series(
            _request(),
            metric="host.ram.percent",
            label="",
            since="-1h",
            until=None,
            resolution="hi",
        )
    assert result == payload
    # Verify the proxied call carried the query params through.
    _args, kwargs = inst.get.call_args
    assert kwargs["params"]["metric"] == "host.ram.percent"
    assert kwargs["params"]["since"] == "-1h"
    assert kwargs["params"]["resolution"] == "hi"
    assert "until" not in kwargs["params"]


@pytest.mark.asyncio
async def test_summary_forwards_window():
    payload = {"window": "24h", "metrics": []}
    with patch(HTTPX_PATCH) as mock_client:
        inst = AsyncMock()
        inst.get.return_value = _mock_response(payload)
        mock_client.return_value.__aenter__.return_value = inst

        result = await get_metrics_summary(_request(), window="24h")
    assert result == payload
    _args, kwargs = inst.get.call_args
    assert kwargs["params"]["window"] == "24h"


@pytest.mark.asyncio
async def test_series_service_unavailable_raises_503():
    with patch(HTTPX_PATCH) as mock_client:
        inst = AsyncMock()
        inst.get.side_effect = Exception("Connection refused")
        mock_client.return_value.__aenter__.return_value = inst

        with pytest.raises(HTTPException) as exc:
            await get_metrics_series(
                _request(),
                metric="m",
                label="",
                since=None,
                until=None,
                resolution="hi",
            )
    assert exc.value.status_code == 503
