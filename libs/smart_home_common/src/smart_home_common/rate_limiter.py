"""
Rate limiting utilities for smart-home services.

Provides both in-memory and SQLite-backed rate limiters for protecting
endpoints from abuse.

Usage:
    # In-memory (resets on restart)
    from smart_home_common.rate_limiter import InMemoryRateLimiter

    limiter = InMemoryRateLimiter(max_requests=20, window_seconds=60)
    if limiter.is_allowed("192.168.1.1"):
        # Process request
    else:
        # Return 429 Too Many Requests

    # SQLite-backed (persistent across restarts)
    from smart_home_common.rate_limiter import SqliteRateLimiter

    limiter = SqliteRateLimiter(
        db_path="/data/rate_limits.db",
        max_requests=20,
        window_seconds=60
    )
    if limiter.is_allowed("192.168.1.1"):
        # Process request
"""

import logging
import sqlite3
import threading
from abc import ABC, abstractmethod
from collections import defaultdict
from datetime import datetime
from typing import NamedTuple

logger = logging.getLogger(__name__)


class RateLimitStatus(NamedTuple):
    """Status of a rate limit check."""

    allowed: bool
    """Whether the request is allowed."""

    remaining: int
    """Number of requests remaining in the current window."""

    reset_at: datetime
    """When the current window resets."""


class BaseRateLimiter(ABC):
    """Abstract base class for rate limiters."""

    def __init__(self, max_requests: int, window_seconds: int):
        """Initialize rate limiter.

        Args:
            max_requests: Maximum requests allowed per window
            window_seconds: Window duration in seconds
        """
        self._max_requests = max_requests
        self._window_seconds = window_seconds

    @property
    def max_requests(self) -> int:
        """Maximum requests allowed per window."""
        return self._max_requests

    @property
    def window_seconds(self) -> int:
        """Window duration in seconds."""
        return self._window_seconds

    @abstractmethod
    def is_allowed(self, key: str) -> bool:
        """Check if a request is allowed and record the attempt.

        Args:
            key: Identifier (usually IP address or user ID)

        Returns:
            True if the request is allowed, False if rate limited
        """
        pass

    @abstractmethod
    def get_status(self, key: str) -> RateLimitStatus:
        """Get current rate limit status for a key.

        Args:
            key: Identifier (usually IP address or user ID)

        Returns:
            RateLimitStatus with allowed, remaining, and reset_at
        """
        pass

    @abstractmethod
    def reset(self, key: str) -> None:
        """Reset rate limit for a specific key.

        Args:
            key: Identifier to reset
        """
        pass


class InMemoryRateLimiter(BaseRateLimiter):
    """Thread-safe in-memory rate limiter.

    Data is lost on process restart. Use SqliteRateLimiter for persistence.
    """

    def __init__(self, max_requests: int = 20, window_seconds: int = 60):
        super().__init__(max_requests, window_seconds)
        self._lock = threading.Lock()
        # key -> {"count": int, "window_start": datetime}
        self._data: dict[str, dict] = defaultdict(
            lambda: {"count": 0, "window_start": datetime.now()}
        )

    def is_allowed(self, key: str) -> bool:
        """Check if request is allowed and record the attempt."""
        with self._lock:
            now = datetime.now()
            entry = self._data[key]

            # Check if window has expired
            elapsed = (now - entry["window_start"]).total_seconds()
            if elapsed > self._window_seconds:
                # Reset window
                entry["count"] = 1
                entry["window_start"] = now
                return True

            # Check if limit exceeded
            if entry["count"] >= self._max_requests:
                return False

            # Record attempt
            entry["count"] += 1
            return True

    def get_status(self, key: str) -> RateLimitStatus:
        """Get current rate limit status."""
        with self._lock:
            now = datetime.now()
            entry = self._data[key]

            elapsed = (now - entry["window_start"]).total_seconds()
            if elapsed > self._window_seconds:
                # Window expired, would reset on next request
                from datetime import timedelta

                return RateLimitStatus(
                    allowed=True,
                    remaining=self._max_requests,
                    reset_at=now + timedelta(seconds=self._window_seconds),
                )

            remaining = max(0, self._max_requests - entry["count"])
            from datetime import timedelta

            reset_at = entry["window_start"] + timedelta(seconds=self._window_seconds)

            return RateLimitStatus(
                allowed=remaining > 0,
                remaining=remaining,
                reset_at=reset_at,
            )

    def reset(self, key: str) -> None:
        """Reset rate limit for a key."""
        with self._lock:
            if key in self._data:
                del self._data[key]


class SqliteRateLimiter(BaseRateLimiter):
    """SQLite-backed rate limiter with persistence across restarts.

    Thread-safe via SQLite's connection-per-call pattern.
    """

    def __init__(
        self,
        db_path: str,
        max_requests: int = 20,
        window_seconds: int = 60,
        table_name: str = "rate_limits",
    ):
        """Initialize SQLite rate limiter.

        Args:
            db_path: Path to SQLite database file
            max_requests: Maximum requests allowed per window
            window_seconds: Window duration in seconds
            table_name: Name of the rate limits table
        """
        super().__init__(max_requests, window_seconds)
        self._db_path = db_path
        self._table_name = table_name
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """Get a database connection."""
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Initialize the database table."""
        conn = self._get_conn()
        try:
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self._table_name} (
                    key TEXT PRIMARY KEY,
                    attempts INTEGER DEFAULT 0,
                    window_start TEXT NOT NULL
                )
            """)
            conn.commit()
        finally:
            conn.close()

    def is_allowed(self, key: str) -> bool:
        """Check if request is allowed and record the attempt."""
        conn = self._get_conn()
        try:
            now = datetime.now()
            row = conn.execute(
                f"SELECT attempts, window_start FROM {self._table_name} WHERE key = ?",
                (key,),
            ).fetchone()

            if row:
                window_start = datetime.fromisoformat(row["window_start"])
                elapsed = (now - window_start).total_seconds()

                if elapsed > self._window_seconds:
                    # Reset window
                    sql = (
                        f"UPDATE {self._table_name} "
                        "SET attempts = 1, window_start = ? WHERE key = ?"
                    )
                    conn.execute(sql, (now.isoformat(), key))
                    conn.commit()
                    return True

                if row["attempts"] >= self._max_requests:
                    return False

                # Increment attempts
                sql = f"UPDATE {self._table_name} SET attempts = attempts + 1 WHERE key = ?"
                conn.execute(sql, (key,))
                conn.commit()
                return True
            else:
                # First attempt from this key
                sql = (
                    f"INSERT INTO {self._table_name} (key, attempts, window_start) VALUES (?, 1, ?)"
                )
                conn.execute(sql, (key, now.isoformat()))
                conn.commit()
                return True
        finally:
            conn.close()

    def get_status(self, key: str) -> RateLimitStatus:
        """Get current rate limit status."""
        conn = self._get_conn()
        try:
            now = datetime.now()
            row = conn.execute(
                f"SELECT attempts, window_start FROM {self._table_name} WHERE key = ?",
                (key,),
            ).fetchone()

            if not row:
                from datetime import timedelta

                return RateLimitStatus(
                    allowed=True,
                    remaining=self._max_requests,
                    reset_at=now + timedelta(seconds=self._window_seconds),
                )

            window_start = datetime.fromisoformat(row["window_start"])
            elapsed = (now - window_start).total_seconds()

            if elapsed > self._window_seconds:
                from datetime import timedelta

                return RateLimitStatus(
                    allowed=True,
                    remaining=self._max_requests,
                    reset_at=now + timedelta(seconds=self._window_seconds),
                )

            remaining = max(0, self._max_requests - row["attempts"])
            from datetime import timedelta

            reset_at = window_start + timedelta(seconds=self._window_seconds)

            return RateLimitStatus(
                allowed=remaining > 0,
                remaining=remaining,
                reset_at=reset_at,
            )
        finally:
            conn.close()

    def reset(self, key: str) -> None:
        """Reset rate limit for a key."""
        conn = self._get_conn()
        try:
            conn.execute(f"DELETE FROM {self._table_name} WHERE key = ?", (key,))
            conn.commit()
        finally:
            conn.close()

    def cleanup_expired(self) -> int:
        """Remove expired entries from the database.

        Returns:
            Number of entries removed
        """
        conn = self._get_conn()
        try:
            from datetime import timedelta

            cutoff = (datetime.now() - timedelta(seconds=self._window_seconds)).isoformat()
            cursor = conn.execute(
                f"DELETE FROM {self._table_name} WHERE window_start < ?", (cutoff,)
            )
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()
