"""
HTTP client utilities with retry and backoff.

Provides a simple HTTP client with:
- Exponential backoff on rate limiting (429, 403)
- Configurable timeouts
- Logging of retry attempts
"""

from .client import RetryClient, get_with_retry

__all__ = ["RetryClient", "get_with_retry"]
