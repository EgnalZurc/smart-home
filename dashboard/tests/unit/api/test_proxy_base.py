"""Tests for api/proxy/base.py (ServiceProxy class)."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import HTTPException

from api.proxy.base import ServiceProxy


class TestServiceProxyInit:
    """Tests for ServiceProxy initialization."""

    def test_default_timeout(self):
        """Default timeout should be 5.0 seconds."""
        proxy = ServiceProxy("http://service:8000")
        assert proxy.timeout == 5.0

    def test_custom_timeout(self):
        """Custom timeout should be respected."""
        proxy = ServiceProxy("http://service:8000", timeout=10.0)
        assert proxy.timeout == 10.0

    def test_strips_trailing_slash_from_url(self):
        """Trailing slash should be stripped from service URL."""
        proxy = ServiceProxy("http://service:8000/")
        assert proxy.service_url == "http://service:8000"


class TestServiceProxyGet:
    """Tests for ServiceProxy.get method."""

    @pytest.mark.asyncio
    async def test_successful_get(self):
        """GET request should return JSON response."""
        proxy = ServiceProxy("http://service:8000")

        mock_response = MagicMock()
        mock_response.json.return_value = {"status": "ok"}
        mock_response.status_code = 200

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await proxy.get("/api/test")

            assert result == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_get_with_params(self):
        """GET request should pass query params."""
        proxy = ServiceProxy("http://service:8000")

        mock_response = MagicMock()
        mock_response.json.return_value = {"data": []}
        mock_response.status_code = 200

        with patch("httpx.AsyncClient") as mock_client:
            mock_get = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.get = mock_get

            await proxy.get("/api/items", params={"page": "1"})

            mock_get.assert_called_once()
            call_kwargs = mock_get.call_args.kwargs
            assert call_kwargs["params"] == {"page": "1"}

    @pytest.mark.asyncio
    async def test_get_raises_on_4xx_error(self):
        """GET should raise HTTPException on 4xx errors."""
        proxy = ServiceProxy("http://service:8000")

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.json.return_value = {"detail": "Not found"}

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            with pytest.raises(HTTPException) as exc_info:
                await proxy.get("/api/missing")

            assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_returns_default_on_error_when_configured(self):
        """GET should return default value when raise_on_error=False."""
        proxy = ServiceProxy("http://service:8000")

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                side_effect=Exception("Connection refused")
            )

            result = await proxy.get(
                "/api/test",
                raise_on_error=False,
                default_on_error={"error": "unavailable"},
            )

            assert result == {"error": "unavailable"}

    @pytest.mark.asyncio
    async def test_get_raises_503_on_connection_error(self):
        """GET should raise 503 on connection errors."""
        proxy = ServiceProxy("http://service:8000")

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                side_effect=Exception("Connection refused")
            )

            with pytest.raises(HTTPException) as exc_info:
                await proxy.get("/api/test")

            assert exc_info.value.status_code == 503


class TestServiceProxyPost:
    """Tests for ServiceProxy.post method."""

    @pytest.mark.asyncio
    async def test_successful_post_with_json(self):
        """POST request should send JSON body."""
        proxy = ServiceProxy("http://service:8000")

        mock_response = MagicMock()
        mock_response.json.return_value = {"id": 123}
        mock_response.status_code = 201

        with patch("httpx.AsyncClient") as mock_client:
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            result = await proxy.post("/api/items", json={"name": "test"})

            assert result == {"id": 123}
            mock_post.assert_called_once()
            call_kwargs = mock_post.call_args.kwargs
            assert call_kwargs["json"] == {"name": "test"}

    @pytest.mark.asyncio
    async def test_post_raises_on_error(self):
        """POST should raise HTTPException on errors."""
        proxy = ServiceProxy("http://service:8000")

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {"detail": "Invalid data"}

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            with pytest.raises(HTTPException) as exc_info:
                await proxy.post("/api/items", json={})

            assert exc_info.value.status_code == 400


class TestServiceProxyPut:
    """Tests for ServiceProxy.put method."""

    @pytest.mark.asyncio
    async def test_successful_put(self):
        """PUT request should send JSON body."""
        proxy = ServiceProxy("http://service:8000")

        mock_response = MagicMock()
        mock_response.json.return_value = {"updated": True}
        mock_response.status_code = 200

        with patch("httpx.AsyncClient") as mock_client:
            mock_put = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.put = mock_put

            result = await proxy.put("/api/items/1", json={"name": "updated"})

            assert result == {"updated": True}


class TestServiceProxyDelete:
    """Tests for ServiceProxy.delete method."""

    @pytest.mark.asyncio
    async def test_successful_delete(self):
        """DELETE request should return JSON response."""
        proxy = ServiceProxy("http://service:8000")

        mock_response = MagicMock()
        mock_response.json.return_value = {"deleted": True}
        mock_response.status_code = 200

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.delete = AsyncMock(
                return_value=mock_response
            )

            result = await proxy.delete("/api/items/1")

            assert result == {"deleted": True}


class TestServiceProxyForwardRequest:
    """Tests for ServiceProxy.forward_request method."""

    @pytest.mark.asyncio
    async def test_forwards_get_request(self):
        """Should forward GET request preserving query string."""
        proxy = ServiceProxy("http://service:8000")

        mock_request = MagicMock()
        mock_request.method = "GET"
        mock_request.url.query = "page=1&limit=10"

        mock_response = MagicMock()
        mock_response.json.return_value = {"items": []}
        mock_response.status_code = 200

        with patch("httpx.AsyncClient") as mock_client:
            mock_req = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.request = mock_req

            result = await proxy.forward_request(mock_request, "/api/items")

            assert result == {"items": []}
            mock_req.assert_called_once()
            call_args = mock_req.call_args
            assert "page=1&limit=10" in call_args[0][1]  # URL contains query string

    @pytest.mark.asyncio
    async def test_forwards_post_request_with_body(self):
        """Should forward POST request with JSON body."""
        proxy = ServiceProxy("http://service:8000")

        mock_request = MagicMock()
        mock_request.method = "POST"
        mock_request.url.query = ""
        mock_request.json = AsyncMock(return_value={"data": "test"})

        mock_response = MagicMock()
        mock_response.json.return_value = {"success": True}
        mock_response.status_code = 200

        with patch("httpx.AsyncClient") as mock_client:
            mock_req = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.request = mock_req

            result = await proxy.forward_request(mock_request, "/api/items")

            assert result == {"success": True}
            call_kwargs = mock_req.call_args.kwargs
            assert call_kwargs["json"] == {"data": "test"}
