"""
Async HTTP client for service-to-service communication.

Provides standardized error handling, converting httpx exceptions
to FastAPI HTTPExceptions with appropriate status codes.

A single underlying ``httpx.AsyncClient`` is held per ``AsyncServiceClient``
instance and reused across all requests, so TCP (and TLS) connections are
pooled instead of being opened and closed on every call. Create one client
per backend at module/app level and reuse it; call ``aclose()`` (or use the
async context manager) on shutdown to release pooled connections.

Usage:
    from libs.async_http_client import AsyncServiceClient, ServiceClientConfig

    config = ServiceClientConfig(
        base_url="http://backend:8080",
        token="secret",
        timeout=30.0,
    )
    client = AsyncServiceClient(config)

    # In an async endpoint:
    data = await client.get("/api/status")
    result = await client.post("/api/action", data={"key": "value"})

    # On application shutdown:
    await client.aclose()
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import httpx
from fastapi import HTTPException

logger = logging.getLogger(__name__)


@dataclass
class ServiceClientConfig:
    """Configuration for async service client."""

    base_url: str
    token: str = ""
    token_header: str = "X-Api-Token"
    timeout: float = 30.0
    extra_headers: dict[str, str] = field(default_factory=dict)


class AsyncServiceClient:
    """
    Async HTTP client for calling backend services.

    Converts connection errors and timeouts to appropriate HTTP status codes:
    - ConnectError → 503 Service Unavailable
    - TimeoutException → 504 Gateway Timeout
    - HTTPStatusError → forwards the upstream status code

    Example:
        client = AsyncServiceClient(ServiceClientConfig(
            base_url="http://pc-agent:8090",
            token=os.environ.get("PC_AGENT_TOKEN", ""),
        ))

        @app.get("/api/status")
        async def get_status():
            return await client.get("/status")
    """

    def __init__(self, config: ServiceClientConfig):
        self.config = config
        # A single long-lived httpx.AsyncClient is reused across all requests so
        # that TCP (and TLS) connections are pooled instead of being opened and
        # torn down per call. Created lazily on first use so instantiating the
        # client does not require a running event loop.
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        """Return the shared httpx.AsyncClient, creating it on first use.

        The base_url and default headers are baked into the client so every
        request reuses the same connection pool.
        """
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.config.base_url,
                headers=self._headers(),
                timeout=self.config.timeout,
            )
        return self._client

    async def aclose(self) -> None:
        """Close the underlying client and release pooled connections."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    async def __aenter__(self) -> AsyncServiceClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    def _headers(self) -> dict[str, str]:
        """Build request headers including auth token if configured."""
        headers = dict(self.config.extra_headers)
        if self.config.token:
            headers[self.config.token_header] = self.config.token
        return headers

    async def get(self, path: str, params: dict | None = None) -> dict:
        """
        GET request to the configured service.

        Args:
            path: URL path (appended to base_url).
            params: Optional query parameters.

        Returns:
            JSON response as dict.

        Raises:
            HTTPException: With 503 (unreachable), 504 (timeout),
                          or upstream status code on error.
        """
        url = f"{self.config.base_url}{path}"
        try:
            client = self._get_client()
            response = await client.get(path, params=params)
            response.raise_for_status()
            return response.json()
        except httpx.ConnectError as e:
            logger.warning("Service unreachable: %s - %s", url, e)
            raise HTTPException(503, "Service unreachable")
        except httpx.TimeoutException:
            logger.warning("Service timeout: %s", url)
            raise HTTPException(504, "Service timeout")
        except httpx.HTTPStatusError as e:
            raise HTTPException(e.response.status_code, e.response.text)

    async def post(self, path: str, data: dict | None = None) -> dict:
        """
        POST request to the configured service.

        Args:
            path: URL path (appended to base_url).
            data: Form data to send.

        Returns:
            JSON response as dict.

        Raises:
            HTTPException: With 503 (unreachable), 504 (timeout),
                          or upstream status code on error.
        """
        url = f"{self.config.base_url}{path}"
        try:
            client = self._get_client()
            response = await client.post(path, data=data)
            response.raise_for_status()
            return response.json()
        except httpx.ConnectError as e:
            logger.warning("Service unreachable: %s - %s", url, e)
            raise HTTPException(503, "Service unreachable")
        except httpx.TimeoutException:
            logger.warning("Service timeout: %s", url)
            raise HTTPException(504, "Service timeout")
        except httpx.HTTPStatusError as e:
            raise HTTPException(e.response.status_code, e.response.text)

    async def delete(self, path: str) -> dict:
        """
        DELETE request to the configured service.

        Args:
            path: URL path (appended to base_url).

        Returns:
            JSON response as dict.

        Raises:
            HTTPException: With 503 (unreachable), 504 (timeout),
                          or upstream status code on error.
        """
        url = f"{self.config.base_url}{path}"
        try:
            client = self._get_client()
            response = await client.delete(path)
            response.raise_for_status()
            return response.json()
        except httpx.ConnectError as e:
            logger.warning("Service unreachable: %s - %s", url, e)
            raise HTTPException(503, "Service unreachable")
        except httpx.TimeoutException:
            logger.warning("Service timeout: %s", url)
            raise HTTPException(504, "Service timeout")
        except httpx.HTTPStatusError as e:
            raise HTTPException(e.response.status_code, e.response.text)
