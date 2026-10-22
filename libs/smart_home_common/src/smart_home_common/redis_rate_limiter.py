"""
Redis-backed rate limiter for persistent rate limiting across container restarts.

Usage:
    from smart_home_common.redis_rate_limiter import RedisRateLimiter

    limiter = RedisRateLimiter(
        redis_url="redis://redis:6379/0",
        max_requests=20,
        window_seconds=60
    )
    if limiter.is_allowed("192.168.1.1"):
        # Process request
    else:
        # Return 429 Too Many Requests
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from .rate_limiter import BaseRateLimiter, RateLimitStatus

if TYPE_CHECKING:
    import redis as redis_module

logger = logging.getLogger(__name__)

# Redis is an optional dependency - graceful fallback if unavailable
try:
    import redis

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    redis = None  # type: ignore[assignment]


class RedisRateLimiter(BaseRateLimiter):
    """Redis-backed rate limiter with persistence across restarts.

    Uses Redis INCR + EXPIRE for atomic rate limiting. Falls back to
    allowing all requests if Redis is unavailable (with a warning log).
    """

    def __init__(
        self,
        max_requests: int = 20,
        window_seconds: int = 60,
        redis_url: str = "redis://redis:6379/0",
        key_prefix: str = "rate_limit:",
    ):
        """Initialize Redis rate limiter.

        Args:
            max_requests: Maximum requests allowed per window
            window_seconds: Window duration in seconds
            redis_url: Redis connection URL
            key_prefix: Prefix for Redis keys
        """
        super().__init__(max_requests, window_seconds)
        self._redis_url = redis_url
        self._key_prefix = key_prefix
        self._client: redis_module.Redis | None = None
        self._connection_warned = False

        if not REDIS_AVAILABLE:
            logger.warning("redis package not installed. RedisRateLimiter will allow all requests.")
            return

        try:
            self._client = redis.from_url(redis_url, decode_responses=True)
            # Test connection
            self._client.ping()
            logger.debug("RedisRateLimiter connected to %s", redis_url)
        except redis.RedisError as e:
            logger.warning(
                "Failed to connect to Redis at %s: %s. Rate limiter will allow all requests.",
                redis_url,
                e,
            )
            self._client = None

    def _get_key(self, key: str) -> str:
        """Generate the full Redis key for a rate limit entry."""
        return f"{self._key_prefix}{key}"

    def _is_redis_available(self) -> bool:
        """Check if Redis connection is available."""
        if self._client is None:
            return False
        try:
            self._client.ping()
            return True
        except redis.RedisError as e:
            if not self._connection_warned:
                logger.warning("Redis connection lost: %s. Allowing all requests.", e)
                self._connection_warned = True
            return False

    def is_allowed(self, key: str) -> bool:
        """Check if request is allowed and record the attempt.

        Uses Redis INCR + EXPIRE for atomic rate limiting. If Redis is
        unavailable, logs a warning and returns True (fail-open).
        """
        if not self._is_redis_available():
            return True

        redis_key = self._get_key(key)

        try:
            # Atomic increment
            current = self._client.incr(redis_key)  # type: ignore[union-attr]

            # Set expiry on first request in window
            if current == 1:
                self._client.expire(redis_key, self._window_seconds)  # type: ignore[union-attr]

            return current <= self._max_requests
        except redis.RedisError as e:
            logger.warning("Redis error during rate limit check: %s. Allowing request.", e)
            return True

    def get_status(self, key: str) -> RateLimitStatus:
        """Get current rate limit status for a key."""
        now = datetime.now()

        if not self._is_redis_available():
            return RateLimitStatus(
                allowed=True,
                remaining=self._max_requests,
                reset_at=now + timedelta(seconds=self._window_seconds),
            )

        redis_key = self._get_key(key)

        try:
            # Get current count and TTL
            current = self._client.get(redis_key)  # type: ignore[union-attr]
            ttl = self._client.ttl(redis_key)  # type: ignore[union-attr]

            if current is None:
                # No entry yet
                return RateLimitStatus(
                    allowed=True,
                    remaining=self._max_requests,
                    reset_at=now + timedelta(seconds=self._window_seconds),
                )

            count = int(current)
            remaining = max(0, self._max_requests - count)

            # TTL of -1 means key exists but has no expiry, -2 means key doesn't exist
            if ttl > 0:
                reset_at = now + timedelta(seconds=ttl)
            else:
                reset_at = now + timedelta(seconds=self._window_seconds)

            return RateLimitStatus(
                allowed=remaining > 0,
                remaining=remaining,
                reset_at=reset_at,
            )
        except redis.RedisError as e:
            logger.warning("Redis error getting status: %s. Returning default.", e)
            return RateLimitStatus(
                allowed=True,
                remaining=self._max_requests,
                reset_at=now + timedelta(seconds=self._window_seconds),
            )

    def reset(self, key: str) -> None:
        """Reset rate limit for a specific key."""
        if not self._is_redis_available():
            return

        redis_key = self._get_key(key)

        try:
            self._client.delete(redis_key)  # type: ignore[union-attr]
        except redis.RedisError as e:
            logger.warning("Redis error resetting key %s: %s", key, e)
