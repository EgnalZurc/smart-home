"""Tests for AsyncServiceClient."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import HTTPException

from libs.async_http_client.client import AsyncServiceClient, ServiceClientConfig


class TestServiceClientConfig:
    """Tests for ServiceClientConfig."""

    def test_default_values(self):
        """Config should have sensible defaults."""
        config = ServiceClientConfig(base_url="http://test:8080")
        assert config.base_url == "http://test:8080"
        assert config.token == ""
        assert config.token_header == "X-Api-Token"
        assert config.timeout == 30.0
        assert config.extra_headers == {}

    def test_custom_values(self):
        """Config should accept custom values."""
        config = ServiceClientConfig(
            base_url="http://custom:9090",
            token="secret123",
            token_header="Authorization",
            timeout=60.0,
            extra_headers={"X-Custom": "value"},
        )
        assert config.base_url == "http://custom:9090"
        assert config.token == "secret123"
        assert config.token_header == "Authorization"
        assert config.timeout == 60.0
        assert config.extra_headers == {"X-Custom": "value"}


class TestAsyncServiceClientHeaders:
    """Tests for header building."""

    def test_headers_without_token(self):
        """Headers should be empty when no token configured."""
        config = ServiceClientConfig(base_url="http://test:8080")
        client = AsyncServiceClient(config)
        assert client._headers() == {}

    def test_headers_with_token(self):
        """Headers should include token when configured."""
        config = ServiceClientConfig(
            base_url="http://test:8080",
            token="secret",
        )
        client = AsyncServiceClient(config)
        assert client._headers() == {"X-Api-Token": "secret"}

    def test_headers_with_custom_token_header(self):
        """Headers should use custom token header name."""
        config = ServiceClientConfig(
            base_url="http://test:8080",
            token="bearer-token",
            token_header="Authorization",
        )
        client = AsyncServiceClient(config)
        assert client._headers() == {"Authorization": "bearer-token"}

    def test_headers_with_extra_headers(self):
        """Headers should include extra headers."""
        config = ServiceClientConfig(
            base_url="http://test:8080",
            token="secret",
            extra_headers={"X-Request-Id": "123"},
        )
        client = AsyncServiceClient(config)
        headers = client._headers()
        assert headers["X-Api-Token"] == "secret"
        assert headers["X-Request-Id"] == "123"


class TestAsyncServiceClientGet:
    """Tests for GET requests."""

    @pytest.fixture
    def client(self):
        """Create a test client."""
        config = ServiceClientConfig(
            base_url="http://backend:8080",
            token="test-token",
        )
        return AsyncServiceClient(config)

    @pytest.mark.asyncio
    async def test_get_success(self, client):
        """GET should return JSON response on success."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"status": "ok"}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await client.get("/api/status")

            assert result == {"status": "ok"}
            mock_client.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_with_params(self, client):
        """GET should pass query params."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"lines": ["log1", "log2"]}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await client.get("/api/logs", params={"lines": "50"})

            assert result == {"lines": ["log1", "log2"]}
            call_kwargs = mock_client.get.call_args.kwargs
            assert call_kwargs["params"] == {"lines": "50"}

    @pytest.mark.asyncio
    async def test_get_connect_error(self, client):
        """GET should raise 503 on connection error."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get.side_effect = httpx.ConnectError("Connection refused")
            mock_client_class.return_value.__aenter__.return_value = mock_client

            with pytest.raises(HTTPException) as exc_info:
                await client.get("/api/status")

            assert exc_info.value.status_code == 503
            assert "unreachable" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_get_timeout(self, client):
        """GET should raise 504 on timeout."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get.side_effect = httpx.TimeoutException("Timed out")
            mock_client_class.return_value.__aenter__.return_value = mock_client

            with pytest.raises(HTTPException) as exc_info:
                await client.get("/api/status")

            assert exc_info.value.status_code == 504
            assert "timeout" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_get_http_error(self, client):
        """GET should forward upstream HTTP errors."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.text = "Not found"

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get.side_effect = httpx.HTTPStatusError(
                "Not found",
                request=MagicMock(),
                response=mock_response,
            )
            mock_client_class.return_value.__aenter__.return_value = mock_client

            with pytest.raises(HTTPException) as exc_info:
                await client.get("/api/missing")

            assert exc_info.value.status_code == 404


class TestAsyncServiceClientPost:
    """Tests for POST requests."""

    @pytest.fixture
    def client(self):
        """Create a test client."""
        config = ServiceClientConfig(base_url="http://backend:8080")
        return AsyncServiceClient(config)

    @pytest.mark.asyncio
    async def test_post_success(self, client):
        """POST should return JSON response on success."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": "started"}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await client.post("/api/start", data={"world": "test"})

            assert result == {"result": "started"}
            call_kwargs = mock_client.post.call_args.kwargs
            assert call_kwargs["data"] == {"world": "test"}

    @pytest.mark.asyncio
    async def test_post_connect_error(self, client):
        """POST should raise 503 on connection error."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post.side_effect = httpx.ConnectError("Connection refused")
            mock_client_class.return_value.__aenter__.return_value = mock_client

            with pytest.raises(HTTPException) as exc_info:
                await client.post("/api/start")

            assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_post_timeout(self, client):
        """POST should raise 504 on timeout."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post.side_effect = httpx.TimeoutException("Timed out")
            mock_client_class.return_value.__aenter__.return_value = mock_client

            with pytest.raises(HTTPException) as exc_info:
                await client.post("/api/start")

            assert exc_info.value.status_code == 504


class TestAsyncServiceClientDelete:
    """Tests for DELETE requests."""

    @pytest.fixture
    def client(self):
        """Create a test client."""
        config = ServiceClientConfig(base_url="http://backend:8080")
        return AsyncServiceClient(config)

    @pytest.mark.asyncio
    async def test_delete_success(self, client):
        """DELETE should return JSON response on success."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"deleted": True}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.delete.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await client.delete("/api/worlds/test")

            assert result == {"deleted": True}

    @pytest.mark.asyncio
    async def test_delete_connect_error(self, client):
        """DELETE should raise 503 on connection error."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.delete.side_effect = httpx.ConnectError("Connection refused")
            mock_client_class.return_value.__aenter__.return_value = mock_client

            with pytest.raises(HTTPException) as exc_info:
                await client.delete("/api/worlds/test")

            assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_delete_timeout(self, client):
        """DELETE should raise 504 on timeout."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.delete.side_effect = httpx.TimeoutException("Timed out")
            mock_client_class.return_value.__aenter__.return_value = mock_client

            with pytest.raises(HTTPException) as exc_info:
                await client.delete("/api/worlds/test")

            assert exc_info.value.status_code == 504
