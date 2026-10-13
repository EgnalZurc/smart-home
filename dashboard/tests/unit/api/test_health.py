"""Tests for the health check caching layer in api.health.

These complement test_health_batch.py (which covers the /all aggregation) by
focusing specifically on the TTL cache that sits in front of each individual
health check, so repeated polls within HEALTH_CACHE_TTL reuse the last result
instead of issuing a fresh HTTP request.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import api.health as health


# Override the root conftest's mock_require_super fixture which fails when
# trying to patch api.proxy.pc (module import issues in test isolation).
# This file tests the caching layer, not authenticated routes, so we don't
# need those mocks.
@pytest.fixture(autouse=True)
def mock_require_super():
    """No-op override of root fixture to avoid proxy module import errors."""
    yield


def _make_mock_client(mock_get):
    """Build an AsyncClient mock whose .get delegates to ``mock_get``."""
    mock_client = AsyncMock()
    mock_client.get = mock_get
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    return mock_client


@pytest.mark.asyncio
async def test_two_calls_within_ttl_make_one_real_request():
    """Two consecutive calls < TTL apart should only issue ONE real request."""
    call_count = 0

    async def mock_get(url):
        nonlocal call_count
        call_count += 1
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"online": True}
        return resp

    mock_client = _make_mock_client(mock_get)

    with patch("httpx.AsyncClient", return_value=mock_client):
        first = await health.get_ac_health()
        second = await health.get_ac_health()

    # Only one real HTTP request was made; the second call hit the cache.
    assert call_count == 1
    # Both callers got valid results with the expected base fields.
    assert first["online"] is True
    assert first["melcloud_connected"] is None
    assert "latency_ms" in first
    # Second call is from cache
    assert second["online"] is True
    assert second["cached"] is True
    assert second["latency_ms"] == 0


@pytest.mark.asyncio
async def test_cache_expires_after_ttl():
    """Once the cached entry is older than the TTL, a fresh request is made."""
    call_count = 0

    async def mock_get(url):
        nonlocal call_count
        call_count += 1
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"online": True}
        return resp

    mock_client = _make_mock_client(mock_get)

    with patch("httpx.AsyncClient", return_value=mock_client):
        await health.get_ac_health()
        assert call_count == 1

        # Age the cached timestamp beyond the TTL without sleeping.
        _ts, data = health._health_cache["ac"]
        health._health_cache["ac"] = (_ts - health.HEALTH_CACHE_TTL - 1.0, data)

        await health.get_ac_health()

    # The expired entry forced a second real request.
    assert call_count == 2


@pytest.mark.asyncio
async def test_cache_is_per_service_key():
    """Each service key is cached independently; one does not serve another."""
    seen_urls = []

    async def mock_get(url):
        seen_urls.append(url)
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"online": True}
        return resp

    mock_client = _make_mock_client(mock_get)

    with patch("httpx.AsyncClient", return_value=mock_client):
        await health.get_ac_health()
        await health.get_vacaciones_health()

    # Two distinct services -> two distinct cache keys -> two real requests.
    assert len(seen_urls) == 2
    assert "ac" in health._health_cache
    assert "vacaciones" in health._health_cache


@pytest.mark.asyncio
async def test_cached_health_check_helper_caches_result():
    """The helper itself returns cached data without re-invoking check_fn."""
    call_count = 0

    async def check_fn():
        nonlocal call_count
        call_count += 1
        return {"online": True, "value": call_count}

    first = await health._cached_health_check("probe", check_fn)
    second = await health._cached_health_check("probe", check_fn)

    assert call_count == 1
    assert first["online"] is True
    assert first["value"] == 1
    assert "latency_ms" in first
    # Second call returns cached data with latency_ms=0
    assert second["online"] is True
    assert second["cached"] is True
    assert second["latency_ms"] == 0


@pytest.mark.asyncio
async def test_error_results_are_also_cached():
    """A failing check is cached too, so a flapping service isn't hammered."""
    import httpx

    call_count = 0

    async def mock_get(url):
        nonlocal call_count
        call_count += 1
        raise httpx.ConnectError("down")

    mock_client = _make_mock_client(mock_get)

    with patch("httpx.AsyncClient", return_value=mock_client):
        first = await health.get_ac_health()
        second = await health.get_ac_health()

    assert call_count == 1
    assert first["online"] is False
    assert first["error"] == "Cannot connect to ac-service"
    assert "latency_ms" in first
    # Second call is from cache
    assert second["online"] is False
    assert second["cached"] is True
    assert second["latency_ms"] == 0



@pytest.mark.asyncio
async def test_latency_ms_included_in_result():
    """The result dict includes latency_ms for both cache hits and misses."""

    async def mock_get(url):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"online": True}
        return resp

    mock_client = _make_mock_client(mock_get)

    with patch("httpx.AsyncClient", return_value=mock_client):
        # First call: cache miss, should have real latency > 0 (or 0 if very fast)
        first = await health.get_ac_health()
        assert "latency_ms" in first
        assert isinstance(first["latency_ms"], int)
        # Cache miss should not have 'cached' key or it should be absent
        assert first.get("cached") is not True

        # Second call: cache hit, latency_ms should be 0 and cached=True
        second = await health.get_ac_health()
        assert second["latency_ms"] == 0
        assert second["cached"] is True
