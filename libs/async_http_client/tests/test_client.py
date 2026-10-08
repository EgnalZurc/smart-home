"""Tests for AsyncServiceClient."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import HTTPException

from libs.async_http_client.client import AsyncServiceClient, ServiceClientConfig


def _patch_httpx():
    """Patch httpx.AsyncClient to return a reusable mock client.

    The mock reports ``is_closed = False`` so AsyncServiceClient treats it as a
    live, reusable instance (connection pooling), and ``aclose`` is awaitable.
    Returns the (patch_context, mock_client_class, mock_client) tuple.
    """
    patcher = patch("httpx.AsyncClient")
    mock_client_class = patcher.start()
    mock_client = AsyncMock()
    mock_client.is_closed = False
    mock_client_class.return_value = mock_client
    return patcher, mock_client_class, mock_client


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


class TestAsyncServiceClientPooling:
    """Tests for connection pooling / client lifecycle."""

    @pytest.fixture
    def client(self):
        """Create a test client."""
        config = ServiceClientConfig(
            base_url="http://backend:8080",
            token="test-token",
        )
        return AsyncServiceClient(config)

    def test_client_not_created_on_init(self, client):
        """The underlying httpx client is created lazily, not at construction."""
        assert client._client is None

    def test_get_client_is_created_with_base_url_and_headers(self, client):
        """The shared client is built once with base_url, headers and timeout."""
        patcher, mock_client_class, mock_client = _patch_httpx()
        try:
            got = client._get_client()
            assert got is mock_client
            mock_client_class.assert_called_once_with(
                base_url="http://backend:8080",
                headers={"X-Api-Token": "test-token"},
                timeout=30.0,
            )
        finally:
            patcher.stop()

    def test_get_client_reuses_same_instance(self, client):
        """Repeated calls return the same client (pooled connections)."""
        patcher, mock_client_class, mock_client = _patch_httpx()
        try:
            first = client._get_client()
            second = client._get_client()
            assert first is second
            mock_client_class.assert_called_once()
        finally:
            patcher.stop()

    def test_get_client_recreates_when_closed(self, client):
        """A closed client is rebuilt on next use."""
        patcher, mock_client_class, mock_client = _patch_httpx()
        try:
            first = client._get_client()
            first.is_closed = True
            second = client._get_client()
            assert second is mock_client
            assert mock_client_class.call_count == 2
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_aclose_closes_underlying_client(self, client):
        """aclose should close the live client and clear the reference."""
        patcher, _mock_client_class, mock_client = _patch_httpx()
        try:
            client._get_client()
            await client.aclose()
            mock_client.aclose.assert_awaited_once()
            assert client._client is None
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_aclose_is_noop_when_no_client(self, client):
        """aclose should be safe when no client was ever created."""
        await client.aclose()
        assert client._client is None

    @pytest.mark.asyncio
    async def test_aclose_skips_already_closed_client(self, client):
        """aclose should not re-close an already closed client."""
        patcher, _mock_client_class, mock_client = _patch_httpx()
        try:
            client._get_client()
            mock_client.is_closed = True
            await client.aclose()
            mock_client.aclose.assert_not_awaited()
            assert client._client is None
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_context_manager_closes_client(self, client):
        """Using the client as an async context manager closes it on exit."""
        patcher, _mock_client_class, mock_client = _patch_httpx()
        try:
            async with client as ctx:
                assert ctx is client
                client._get_client()
            mock_client.aclose.assert_awaited_once()
            assert client._client is None
        finally:
            patcher.stop()


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
        patcher, _mock_client_class, mock_client = _patch_httpx()
        try:
            mock_response = MagicMock()
            mock_response.json.return_value = {"status": "ok"}
            mock_response.raise_for_status = MagicMock()
            mock_client.get.return_value = mock_response

            result = await client.get("/api/status")

            assert result == {"status": "ok"}
            mock_client.get.assert_called_once()
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_get_with_params(self, client):
        """GET should pass query params."""
        patcher, _mock_client_class, mock_client = _patch_httpx()
        try:
            mock_response = MagicMock()
            mock_response.json.return_value = {"lines": ["log1", "log2"]}
            mock_response.raise_for_status = MagicMock()
            mock_client.get.return_value = mock_response

            result = await client.get("/api/logs", params={"lines": "50"})

            assert result == {"lines": ["log1", "log2"]}
            call_kwargs = mock_client.get.call_args.kwargs
            assert call_kwargs["params"] == {"lines": "50"}
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_get_connect_error(self, client):
        """GET should raise 503 on connection error."""
        patcher, _mock_client_class, mock_client = _patch_httpx()
        try:
            mock_client.get.side_effect = httpx.ConnectError("Connection refused")

            with pytest.raises(HTTPException) as exc_info:
                await client.get("/api/status")

            assert exc_info.value.status_code == 503
            assert "unreachable" in exc_info.value.detail.lower()
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_get_timeout(self, client):
        """GET should raise 504 on timeout."""
        patcher, _mock_client_class, mock_client = _patch_httpx()
        try:
            mock_client.get.side_effect = httpx.TimeoutException("Timed out")

            with pytest.raises(HTTPException) as exc_info:
                await client.get("/api/status")

            assert exc_info.value.status_code == 504
            assert "timeout" in exc_info.value.detail.lower()
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_get_http_error(self, client):
        """GET should forward upstream HTTP errors."""
        patcher, _mock_client_class, mock_client = _patch_httpx()
        try:
            mock_response = MagicMock()
            mock_response.status_code = 404
            mock_response.text = "Not found"
            mock_client.get.side_effect = httpx.HTTPStatusError(
                "Not found",
                request=MagicMock(),
                response=mock_response,
            )

            with pytest.raises(HTTPException) as exc_info:
                await client.get("/api/missing")

            assert exc_info.value.status_code == 404
        finally:
            patcher.stop()


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
        patcher, _mock_client_class, mock_client = _patch_httpx()
        try:
            mock_response = MagicMock()
            mock_response.json.return_value = {"result": "started"}
            mock_response.raise_for_status = MagicMock()
            mock_client.post.return_value = mock_response

            result = await client.post("/api/start", data={"world": "test"})

            assert result == {"result": "started"}
            call_kwargs = mock_client.post.call_args.kwargs
            assert call_kwargs["data"] == {"world": "test"}
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_post_connect_error(self, client):
        """POST should raise 503 on connection error."""
        patcher, _mock_client_class, mock_client = _patch_httpx()
        try:
            mock_client.post.side_effect = httpx.ConnectError("Connection refused")

            with pytest.raises(HTTPException) as exc_info:
                await client.post("/api/start")

            assert exc_info.value.status_code == 503
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_post_timeout(self, client):
        """POST should raise 504 on timeout."""
        patcher, _mock_client_class, mock_client = _patch_httpx()
        try:
            mock_client.post.side_effect = httpx.TimeoutException("Timed out")

            with pytest.raises(HTTPException) as exc_info:
                await client.post("/api/start")

            assert exc_info.value.status_code == 504
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_post_http_error(self, client):
        """POST should forward upstream HTTP errors."""
        patcher, _mock_client_class, mock_client = _patch_httpx()
        try:
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_response.text = "Server error"
            mock_client.post.side_effect = httpx.HTTPStatusError(
                "Server error",
                request=MagicMock(),
                response=mock_response,
            )

            with pytest.raises(HTTPException) as exc_info:
                await client.post("/api/start")

            assert exc_info.value.status_code == 500
        finally:
            patcher.stop()


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
        patcher, _mock_client_class, mock_client = _patch_httpx()
        try:
            mock_response = MagicMock()
            mock_response.json.return_value = {"deleted": True}
            mock_response.raise_for_status = MagicMock()
            mock_client.delete.return_value = mock_response

            result = await client.delete("/api/worlds/test")

            assert result == {"deleted": True}
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_delete_connect_error(self, client):
        """DELETE should raise 503 on connection error."""
        patcher, _mock_client_class, mock_client = _patch_httpx()
        try:
            mock_client.delete.side_effect = httpx.ConnectError("Connection refused")

            with pytest.raises(HTTPException) as exc_info:
                await client.delete("/api/worlds/test")

            assert exc_info.value.status_code == 503
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_delete_timeout(self, client):
        """DELETE should raise 504 on timeout."""
        patcher, _mock_client_class, mock_client = _patch_httpx()
        try:
            mock_client.delete.side_effect = httpx.TimeoutException("Timed out")

            with pytest.raises(HTTPException) as exc_info:
                await client.delete("/api/worlds/test")

            assert exc_info.value.status_code == 504
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_delete_http_error(self, client):
        """DELETE should forward upstream HTTP errors."""
        patcher, _mock_client_class, mock_client = _patch_httpx()
        try:
            mock_response = MagicMock()
            mock_response.status_code = 404
            mock_response.text = "Not found"
            mock_client.delete.side_effect = httpx.HTTPStatusError(
                "Not found",
                request=MagicMock(),
                response=mock_response,
            )

            with pytest.raises(HTTPException) as exc_info:
                await client.delete("/api/worlds/test")

            assert exc_info.value.status_code == 404
        finally:
            patcher.stop()
