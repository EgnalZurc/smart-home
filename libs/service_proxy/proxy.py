"""Base class for HTTP service proxies.

Provides common functionality for proxying requests to internal services,
reducing code duplication across proxy modules.

This is a framework-agnostic version that can be used with FastAPI, Starlette,
or other ASGI frameworks.
"""

import logging
from typing import Any, Protocol

import httpx

logger = logging.getLogger(__name__)


class HTTPException(Exception):
    """HTTP exception for proxy errors.

    Compatible with FastAPI's HTTPException but can be used standalone.
    """

    def __init__(self, status_code: int, detail: str = ""):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


class RequestProtocol(Protocol):
    """Protocol for request objects (FastAPI Request, Starlette Request, etc.)."""

    @property
    def method(self) -> str: ...

    @property
    def url(self) -> Any: ...

    async def json(self) -> dict: ...


class ServiceProxy:
    """Base class for service proxies with common HTTP operations.

    Attributes:
        service_url: Base URL of the target service
        timeout: HTTP timeout in seconds (default 5.0)

    Example:
        ```python
        from service_proxy import ServiceProxy

        class MyServiceProxy(ServiceProxy):
            def __init__(self):
                super().__init__("http://my-service:8000")

            async def get_items(self):
                return await self.get("/api/items")
        ```
    """

    def __init__(self, service_url: str, timeout: float = 5.0):
        """Initialize the proxy.

        Args:
            service_url: Base URL of the target service (e.g., "http://service:8000")
            timeout: HTTP timeout in seconds
        """
        self.service_url = service_url.rstrip("/")
        self.timeout = timeout

    async def get(
        self,
        path: str,
        *,
        params: dict | None = None,
        headers: dict | None = None,
        default_on_error: Any = None,
        raise_on_error: bool = True,
    ) -> Any:
        """Perform a GET request to the service.

        Args:
            path: Path relative to service_url (should start with /)
            params: Query parameters
            headers: Additional headers to send
            default_on_error: Value to return on error (if raise_on_error=False)
            raise_on_error: If True, raise HTTPException on error

        Returns:
            JSON response from the service

        Raises:
            HTTPException: If request fails and raise_on_error=True
        """
        url = f"{self.service_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(url, params=params, headers=headers)
                if resp.status_code >= 400:
                    if raise_on_error:
                        detail = self._extract_detail(resp)
                        raise HTTPException(status_code=resp.status_code, detail=detail)
                    return default_on_error
                return resp.json()
        except HTTPException:
            raise
        except Exception as e:
            logger.warning("Proxy GET %s failed: %s", url, e)
            if raise_on_error:
                raise HTTPException(status_code=503, detail=str(e))
            return default_on_error

    async def post(
        self,
        path: str,
        *,
        json: dict | None = None,
        data: dict | None = None,
        headers: dict | None = None,
        raise_on_error: bool = True,
    ) -> Any:
        """Perform a POST request to the service.

        Args:
            path: Path relative to service_url
            json: JSON body to send
            data: Form data to send
            headers: Additional headers to send
            raise_on_error: If True, raise HTTPException on error

        Returns:
            JSON response from the service
        """
        url = f"{self.service_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, json=json, data=data, headers=headers)
                if resp.status_code >= 400 and raise_on_error:
                    detail = self._extract_detail(resp)
                    raise HTTPException(status_code=resp.status_code, detail=detail)
                return resp.json()
        except HTTPException:
            raise
        except Exception as e:
            logger.warning("Proxy POST %s failed: %s", url, e)
            raise HTTPException(status_code=503, detail=str(e))

    async def put(
        self,
        path: str,
        *,
        json: dict | None = None,
        headers: dict | None = None,
        raise_on_error: bool = True,
    ) -> Any:
        """Perform a PUT request to the service.

        Args:
            path: Path relative to service_url
            json: JSON body to send
            headers: Additional headers to send
            raise_on_error: If True, raise HTTPException on error

        Returns:
            JSON response from the service
        """
        url = f"{self.service_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.put(url, json=json, headers=headers)
                if resp.status_code >= 400 and raise_on_error:
                    detail = self._extract_detail(resp)
                    raise HTTPException(status_code=resp.status_code, detail=detail)
                return resp.json()
        except HTTPException:
            raise
        except Exception as e:
            logger.warning("Proxy PUT %s failed: %s", url, e)
            raise HTTPException(status_code=503, detail=str(e))

    async def delete(
        self,
        path: str,
        *,
        headers: dict | None = None,
        raise_on_error: bool = True,
    ) -> Any:
        """Perform a DELETE request to the service.

        Args:
            path: Path relative to service_url
            headers: Additional headers to send
            raise_on_error: If True, raise HTTPException on error

        Returns:
            JSON response from the service
        """
        url = f"{self.service_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.delete(url, headers=headers)
                if resp.status_code >= 400 and raise_on_error:
                    detail = self._extract_detail(resp)
                    raise HTTPException(status_code=resp.status_code, detail=detail)
                return resp.json()
        except HTTPException:
            raise
        except Exception as e:
            logger.warning("Proxy DELETE %s failed: %s", url, e)
            raise HTTPException(status_code=503, detail=str(e))

    async def forward_request(
        self,
        request: RequestProtocol,
        path: str,
        *,
        method: str | None = None,
        timeout: float | None = None,
        headers: dict | None = None,
    ) -> Any:
        """Forward a request to the service, preserving body and query string.

        Args:
            request: Request object (FastAPI Request, Starlette Request)
            path: Path relative to service_url
            method: HTTP method (defaults to request.method)
            timeout: Override default timeout
            headers: Additional headers to send

        Returns:
            JSON response from the service
        """
        method = method or request.method
        url = f"{self.service_url}{path}"

        # Preserve query string
        qs = str(request.url.query)
        if qs:
            url = f"{url}?{qs}"

        try:
            async with httpx.AsyncClient(timeout=timeout or self.timeout) as client:
                if method in ("POST", "PUT", "PATCH"):
                    body = await request.json()
                    resp = await client.request(method, url, json=body, headers=headers)
                else:
                    resp = await client.request(method, url, headers=headers)

                if resp.status_code >= 400:
                    detail = self._extract_detail(resp)
                    raise HTTPException(status_code=resp.status_code, detail=detail)
                return resp.json()
        except HTTPException:
            raise
        except Exception as e:
            logger.warning("Proxy %s %s failed: %s", method, url, e)
            raise HTTPException(status_code=503, detail=str(e))

    @staticmethod
    def _extract_detail(resp: httpx.Response) -> str:
        """Extract error detail from response."""
        try:
            return resp.json().get("detail", resp.text)
        except Exception:
            return resp.text
