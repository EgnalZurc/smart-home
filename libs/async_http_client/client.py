"""
Async HTTP client for service-to-service communication.

Provides standardized error handling, converting httpx exceptions
to FastAPI HTTPExceptions with appropriate status codes.

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
            async with httpx.AsyncClient(timeout=self.config.timeout) as client:
                response = await client.get(url, headers=self._headers(), params=params)
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
            async with httpx.AsyncClient(timeout=self.config.timeout) as client:
                response = await client.post(url, headers=self._headers(), data=data)
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
            async with httpx.AsyncClient(timeout=self.config.timeout) as client:
                response = await client.delete(url, headers=self._headers())
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
