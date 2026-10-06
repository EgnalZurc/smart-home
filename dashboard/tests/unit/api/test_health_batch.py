"""Tests for the batch health endpoint /api/health/all."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import httpx


@pytest.mark.asyncio
async def test_get_all_health_all_services_online():
    """Test batch health check when all services respond successfully."""
    from api.health import get_all_health

    # Mock httpx.AsyncClient to return success for all services
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"online": True}

    mock_zigbee_response = MagicMock()
    mock_zigbee_response.json.return_value = {"online": True, "mqtt_connected": True, "active_sensors": 5}

    mock_immich_response = MagicMock()
    mock_immich_response.status_code = 200
    mock_immich_response.json.return_value = {"res": "pong"}

    async def mock_get(url):
        if "zigbee" in url:
            return mock_zigbee_response
        if "immich" in url or "2283" in url:
            return mock_immich_response
        return mock_response

    mock_client = AsyncMock()
    mock_client.get = mock_get
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await get_all_health()

    # Verify all services are checked
    assert "backend" in result
    assert "zigbee" in result
    assert "ac" in result
    assert "vacaciones" in result
    assert "immich" in result
    assert "casita" in result
    assert "baby-gifts" in result
    assert "portfolio" in result
    assert "passwords" in result
    assert "ai" in result
    assert "valheim" in result

    # Backend is always online (no external call)
    assert result["backend"]["online"] is True


@pytest.mark.asyncio
async def test_get_all_health_handles_exceptions():
    """Test that exceptions from individual health checks are handled gracefully."""
    from api.health import get_all_health

    # Mock to raise exception for all external calls
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await get_all_health()

    # Backend should still be online (no external dependency)
    assert result["backend"]["online"] is True

    # Other services should be offline due to connection errors
    assert result["zigbee"]["online"] is False
    assert result["ac"]["online"] is False


@pytest.mark.asyncio
async def test_get_all_health_partial_failures():
    """Test batch health check with some services failing."""
    from api.health import get_all_health

    call_count = 0

    async def mock_get(url):
        nonlocal call_count
        call_count += 1
        if "ac-service" in url:
            raise httpx.ConnectError("Service down")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"online": True, "mqtt_connected": True, "res": "pong"}
        return mock_resp

    mock_client = AsyncMock()
    mock_client.get = mock_get
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await get_all_health()

    # Backend always online
    assert result["backend"]["online"] is True
    # AC should be offline due to error
    assert result["ac"]["online"] is False
    # Other services should be online
    assert result["vacaciones"]["online"] is True


@pytest.mark.asyncio
async def test_get_all_health_returns_all_keys():
    """Test that the response includes all expected service keys."""
    from api.health import get_all_health

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=httpx.ConnectError("offline"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await get_all_health()

    expected_keys = [
        "backend", "zigbee", "ac", "vacaciones", "immich",
        "casita", "baby-gifts", "portfolio", "passwords", "ai", "valheim"
    ]

    for key in expected_keys:
        assert key in result, f"Missing key: {key}"
        assert "online" in result[key] or "error" in result[key]
