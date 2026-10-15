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

    # With size limit to prevent unbounded memory growth
    cache = TTLCache(default_ttl_seconds=300, maxsize=100)
"""

import threading
from datetime import UTC, datetime, timedelta
from typing import Any


class TTLCache:
    """Simple thread-safe in-memory cache with per-entry TTL expiration.

    Supports optional size limits to prevent unbounded memory growth.
    When maxsize is reached, expired entries are evicted first, then
    the oldest entries are removed to make room.
    """

    def __init__(self, default_ttl_seconds: int = 300, maxsize: int | None = None):
        """Initialize the cache.

        Args:
            default_ttl_seconds: TTL applied to entries that do not specify one.
            maxsize: Maximum number of entries. None means unlimited.
        """
        self._cache: dict[str, tuple[Any, datetime]] = {}
        self._default_ttl = default_ttl_seconds
        self._maxsize = maxsize
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
            # If maxsize is set, ensure we have room
            if self._maxsize is not None and key not in self._cache:
                self._evict_if_needed()
            self._cache[key] = (value, expires_at)

    def _evict_if_needed(self) -> None:
        """Evict entries if cache is at capacity. Must be called with lock held."""
        if self._maxsize is None or len(self._cache) < self._maxsize:
            return

        now = datetime.now(UTC)

        # First pass: remove expired entries
        expired_keys = [k for k, (_, exp) in self._cache.items() if now >= exp]
        for key in expired_keys:
            del self._cache[key]

        # If still at capacity, remove oldest entries (by expiration time)
        while len(self._cache) >= self._maxsize:
            # Find the entry that expires soonest (oldest effective entry)
            oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k][1])
            del self._cache[oldest_key]

    def cleanup_expired(self) -> int:
        """Remove all expired entries and return the count removed.

        Call periodically to reclaim memory from expired entries that
        haven't been accessed (and thus not lazily evicted).
        """
        with self._lock:
            now = datetime.now(UTC)
            expired_keys = [k for k, (_, exp) in self._cache.items() if now >= exp]
            for key in expired_keys:
                del self._cache[key]
            return len(expired_keys)

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

    def __len__(self) -> int:
        """Return number of entries (including expired ones not yet evicted)."""
        with self._lock:
            return len(self._cache)
