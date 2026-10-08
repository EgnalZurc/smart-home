"""
In-memory TTL cache for smart-home services.

Provides a simple, thread-safe, in-memory cache where each entry expires after
a configurable time-to-live. Useful for collapsing bursts of identical requests
to rate-limited upstream APIs (CoinGecko, Yahoo Finance, ...) without affecting
the freshness guarantees the caller cares about.

Usage:
    from smart_home_common.cache import TTLCache

    cache = TTLCache(default_ttl_seconds=300)  # 5 min default
    cache.set("btc", {"price": 50000})
    value = cache.get("btc")        # -> {"price": 50000} (or None if expired)
    cache.set("ohlc", data, ttl_seconds=900)  # override TTL per entry
    cache.clear()
"""

import threading
from datetime import UTC, datetime, timedelta
from typing import Any


class TTLCache:
    """Simple thread-safe in-memory cache with per-entry TTL expiration."""

    def __init__(self, default_ttl_seconds: int = 300):
        """Initialize the cache.

        Args:
            default_ttl_seconds: TTL applied to entries that do not specify one.
        """
        self._cache: dict[str, tuple[Any, datetime]] = {}
        self._default_ttl = default_ttl_seconds
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        """Return the cached value if present and not expired, else None.

        Expired entries are evicted lazily on access.
        """
        with self._lock:
            if key not in self._cache:
                return None
            value, expires_at = self._cache[key]
            if datetime.now(UTC) >= expires_at:
                del self._cache[key]
                return None
            return value

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        """Store a value with a TTL.

        Args:
            key: Cache key.
            value: Value to store.
            ttl_seconds: TTL for this entry; falls back to the cache default.
        """
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        expires_at = datetime.now(UTC) + timedelta(seconds=ttl)
        with self._lock:
            self._cache[key] = (value, expires_at)

    def is_expired(self, key: str) -> bool:
        """Return True if the key is absent or its entry has expired.

        Does not evict the entry; use get() for lazy eviction.
        """
        with self._lock:
            if key not in self._cache:
                return True
            _value, expires_at = self._cache[key]
            return datetime.now(UTC) >= expires_at

    def clear(self) -> None:
        """Remove all cached entries."""
        with self._lock:
            self._cache.clear()
