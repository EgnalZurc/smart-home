"""
HTTP client with exponential backoff retry on rate limiting.

Usage:
    from libs.http_client import get_with_retry, RetryClient

    # Simple function
    response = get_with_retry("https://api.example.com/data")

    # Reusable client with custom headers
    client = RetryClient(default_headers={"Authorization": "Bearer token"})
    response = client.get("https://api.example.com/data")
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import requests

logger = logging.getLogger(__name__)

# Default retry configuration
DEFAULT_TIMEOUT = 15
DEFAULT_RETRIES = 3
DEFAULT_BACKOFF = 5.0
RETRYABLE_STATUS_CODES = (429, 403)


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""

    timeout: int = DEFAULT_TIMEOUT
    max_retries: int = DEFAULT_RETRIES
    initial_backoff: float = DEFAULT_BACKOFF
    retryable_codes: tuple[int, ...] = RETRYABLE_STATUS_CODES


@dataclass
class RetryClient:
    """
    HTTP client with built-in exponential backoff retry.

    Automatically retries on rate limiting (429) and forbidden (403) responses
    with exponential backoff between attempts.

    Example:
        client = RetryClient(
            default_headers={"x-api-key": "secret"},
            config=RetryConfig(max_retries=5),
        )
        response = client.get("https://api.example.com/data")
    """

    default_headers: dict[str, str] = field(default_factory=dict)
    config: RetryConfig = field(default_factory=RetryConfig)

    def get(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
    ) -> requests.Response:
        """
        Perform GET request with retry on rate limiting.

        Args:
            url: Target URL.
            headers: Additional headers (merged with default_headers).
            params: Query parameters.

        Returns:
            Response object.

        Raises:
            requests.HTTPError: If all retries fail.
            requests.RequestException: On other request failures.
        """
        merged_headers = {**self.default_headers, **(headers or {})}
        delay = self.config.initial_backoff

        for attempt in range(1, self.config.max_retries + 1):
            response = requests.get(
                url,
                headers=merged_headers,
                params=params,
                timeout=self.config.timeout,
            )

            if response.status_code in self.config.retryable_codes:
                logger.debug(
                    "[http] Rate limited (%d), retrying in %.0fs (attempt %d/%d)",
                    response.status_code,
                    delay,
                    attempt,
                    self.config.max_retries,
                )
                time.sleep(delay)
                delay *= 2
                continue

            response.raise_for_status()
            return response

        # Last attempt failed - raise the error
        response.raise_for_status()
        return response


def get_with_retry(
    url: str,
    headers: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    max_retries: int = DEFAULT_RETRIES,
    initial_backoff: float = DEFAULT_BACKOFF,
) -> requests.Response:
    """
    Simple GET request with retry on rate limiting.

    Convenience function that creates a temporary RetryClient.

    Args:
        url: Target URL.
        headers: Request headers.
        params: Query parameters.
        timeout: Request timeout in seconds.
        max_retries: Maximum number of retry attempts.
        initial_backoff: Initial delay between retries (doubles each attempt).

    Returns:
        Response object.

    Raises:
        requests.HTTPError: If all retries fail.
        requests.RequestException: On other request failures.
    """
    client = RetryClient(
        default_headers=headers or {},
        config=RetryConfig(
            timeout=timeout,
            max_retries=max_retries,
            initial_backoff=initial_backoff,
        ),
    )
    return client.get(url, params=params)
