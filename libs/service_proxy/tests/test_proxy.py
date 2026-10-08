"""Tests for service_proxy library."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from service_proxy import ServiceProxy
from service_proxy.proxy import HTTPException


class TestServiceProxy:
    """Tests for ServiceProxy base class."""

    def test_init_strips_trailing_slash(self):
        """Service URL trailing slash is stripped."""
        proxy = ServiceProxy("http://service:8000/")
        assert proxy.service_url == "http://service:8000"

    def test_init_preserves_url_without_slash(self):
        """Service URL without trailing slash is preserved."""
        proxy = ServiceProxy("http://service:8000")
        assert proxy.service_url == "http://service:8000"

    def test_default_timeout(self):
        """Default timeout is 5.0 seconds."""
        proxy = ServiceProxy("http://service:8000")
        assert proxy.timeout == 5.0

    def test_custom_timeout(self):
        """Custom timeout is respected."""
        proxy = ServiceProxy("http://service:8000", timeout=10.0)
        assert proxy.timeout == 10.0


class MockResponse:
    """Mock httpx Response."""

    def __init__(self, json_data, status_code=200, text=""):
        self._json_data = json_data
        self.status_code = status_code
        self.text = text

    def json(self):
        return self._json_data


class MockAsyncClient:
    """Mock httpx AsyncClient as async context manager."""

    def __init__(self, response=None, exception=None):
        self.response = response or MockResponse({})
        self.exception = exception
        self.get_called_with = None
        self.post_called_with = None
        self.put_called_with = None
        self.delete_called_with = None
        self.request_called_with = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def get(self, url, **kwargs):
        self.get_called_with = (url, kwargs)
        if self.exception:
            raise self.exception
        return self.response

    async def post(self, url, **kwargs):
        self.post_called_with = (url, kwargs)
        if self.exception:
            raise self.exception
        return self.response

    async def put(self, url, **kwargs):
        self.put_called_with = (url, kwargs)
        if self.exception:
            raise self.exception
        return self.response

    async def delete(self, url, **kwargs):
        self.delete_called_with = (url, kwargs)
        if self.exception:
            raise self.exception
        return self.response

    async def request(self, method, url, **kwargs):
        self.request_called_with = (method, url, kwargs)
        if self.exception:
            raise self.exception
        return self.response


class TestServiceProxyGet:
    """Tests for ServiceProxy.get() method."""

    @pytest.mark.asyncio
    async def test_get_success(self):
        """GET request returns JSON on success."""
        proxy = ServiceProxy("http://service:8000")
        mock_client = MockAsyncClient(MockResponse({"key": "value"}))

        with patch.object(httpx, "AsyncClient", return_value=mock_client):
            result = await proxy.get("/api/test")

        assert result == {"key": "value"}

    @pytest.mark.asyncio
    async def test_get_with_params(self):
        """GET request forwards query parameters."""
        proxy = ServiceProxy("http://service:8000")
        mock_client = MockAsyncClient(MockResponse({"filtered": True}))

        with patch.object(httpx, "AsyncClient", return_value=mock_client):
            await proxy.get("/api/test", params={"page": 1})

        assert mock_client.get_called_with[1]["params"] == {"page": 1}

    @pytest.mark.asyncio
    async def test_get_error_raises_exception(self):
        """GET request raises HTTPException on 4xx/5xx."""
        proxy = ServiceProxy("http://service:8000")
        mock_client = MockAsyncClient(MockResponse({"detail": "Not found"}, 404))

        with patch.object(httpx, "AsyncClient", return_value=mock_client):
            with pytest.raises(HTTPException) as exc_info:
                await proxy.get("/api/test")

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Not found"

    @pytest.mark.asyncio
    async def test_get_error_returns_default(self):
        """GET request returns default on error when raise_on_error=False."""
        proxy = ServiceProxy("http://service:8000")
        mock_client = MockAsyncClient(MockResponse({}, 500))

        with patch.object(httpx, "AsyncClient", return_value=mock_client):
            result = await proxy.get(
                "/api/test", default_on_error={"fallback": True}, raise_on_error=False
            )

        assert result == {"fallback": True}

    @pytest.mark.asyncio
    async def test_get_network_error(self):
        """GET request raises 503 on network error."""
        proxy = ServiceProxy("http://service:8000")
        mock_client = MockAsyncClient(exception=Exception("Connection refused"))

        with patch.object(httpx, "AsyncClient", return_value=mock_client):
            with pytest.raises(HTTPException) as exc_info:
                await proxy.get("/api/test")

        assert exc_info.value.status_code == 503


class TestServiceProxyPost:
    """Tests for ServiceProxy.post() method."""

    @pytest.mark.asyncio
    async def test_post_with_json(self):
        """POST request sends JSON body."""
        proxy = ServiceProxy("http://service:8000")
        mock_client = MockAsyncClient(MockResponse({"id": "new-id"}, 201))

        with patch.object(httpx, "AsyncClient", return_value=mock_client):
            result = await proxy.post("/api/items", json={"name": "test"})

        assert result == {"id": "new-id"}
        assert mock_client.post_called_with[1]["json"] == {"name": "test"}

    @pytest.mark.asyncio
    async def test_post_error_raises(self):
        """POST request raises HTTPException on error."""
        proxy = ServiceProxy("http://service:8000")
        mock_client = MockAsyncClient(MockResponse({"detail": "Validation error"}, 400))

        with patch.object(httpx, "AsyncClient", return_value=mock_client):
            with pytest.raises(HTTPException) as exc_info:
                await proxy.post("/api/items", json={})

        assert exc_info.value.status_code == 400


class TestServiceProxyPut:
    """Tests for ServiceProxy.put() method."""

    @pytest.mark.asyncio
    async def test_put_success(self):
        """PUT request returns JSON on success."""
        proxy = ServiceProxy("http://service:8000")
        mock_client = MockAsyncClient(MockResponse({"updated": True}))

        with patch.object(httpx, "AsyncClient", return_value=mock_client):
            result = await proxy.put("/api/items/1", json={"name": "updated"})

        assert result == {"updated": True}


class TestServiceProxyDelete:
    """Tests for ServiceProxy.delete() method."""

    @pytest.mark.asyncio
    async def test_delete_success(self):
        """DELETE request returns JSON on success."""
        proxy = ServiceProxy("http://service:8000")
        mock_client = MockAsyncClient(MockResponse({"deleted": True}))

        with patch.object(httpx, "AsyncClient", return_value=mock_client):
            result = await proxy.delete("/api/items/1")

        assert result == {"deleted": True}


class TestServiceProxyForwardRequest:
    """Tests for ServiceProxy.forward_request() method."""

    @pytest.mark.asyncio
    async def test_forward_get_request(self):
        """Forward GET request preserves query string."""
        proxy = ServiceProxy("http://service:8000")
        mock_client = MockAsyncClient(MockResponse({"items": []}))

        mock_request = MagicMock()
        mock_request.method = "GET"
        mock_request.url.query = "page=1&limit=10"

        with patch.object(httpx, "AsyncClient", return_value=mock_client):
            result = await proxy.forward_request(mock_request, "/api/items")

        assert result == {"items": []}
        assert "page=1&limit=10" in mock_client.request_called_with[1]

    @pytest.mark.asyncio
    async def test_forward_post_preserves_body(self):
        """Forward POST request preserves JSON body."""
        proxy = ServiceProxy("http://service:8000")
        mock_client = MockAsyncClient(MockResponse({"id": "new"}, 201))

        mock_request = MagicMock()
        mock_request.method = "POST"
        mock_request.url.query = ""
        mock_request.json = AsyncMock(return_value={"name": "test"})

        with patch.object(httpx, "AsyncClient", return_value=mock_client):
            result = await proxy.forward_request(mock_request, "/api/items")

        assert mock_client.request_called_with[2]["json"] == {"name": "test"}


class TestHTTPException:
    """Tests for HTTPException class."""

    def test_exception_attributes(self):
        """HTTPException has status_code and detail."""
        exc = HTTPException(status_code=404, detail="Not found")
        assert exc.status_code == 404
        assert exc.detail == "Not found"

    def test_exception_str(self):
        """HTTPException string representation is the detail."""
        exc = HTTPException(status_code=500, detail="Server error")
        assert str(exc) == "Server error"
