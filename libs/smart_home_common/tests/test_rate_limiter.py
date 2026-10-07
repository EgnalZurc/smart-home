"""
Tests for smart_home_common/rate_limiter.py.

Covers:
- InMemoryRateLimiter: initialization, is_allowed, get_status, reset, window reset
- SqliteRateLimiter: initialization, is_allowed, get_status, reset, cleanup_expired
- Thread safety
- Edge cases
"""

import sqlite3
import threading
import time
from datetime import datetime

import pytest


class TestRateLimitStatus:
    """Tests for RateLimitStatus named tuple."""

    def test_status_fields(self):
        """RateLimitStatus has expected fields."""
        from smart_home_common.rate_limiter import RateLimitStatus

        status = RateLimitStatus(
            allowed=True,
            remaining=5,
            reset_at=datetime.now(),
        )
        assert status.allowed is True
        assert status.remaining == 5
        assert isinstance(status.reset_at, datetime)


class TestInMemoryRateLimiter:
    """Tests for InMemoryRateLimiter."""

    def test_init_with_defaults(self):
        """InMemoryRateLimiter initializes with defaults."""
        from smart_home_common.rate_limiter import InMemoryRateLimiter

        limiter = InMemoryRateLimiter()
        assert limiter.max_requests == 20
        assert limiter.window_seconds == 60

    def test_init_with_custom_values(self):
        """InMemoryRateLimiter initializes with custom values."""
        from smart_home_common.rate_limiter import InMemoryRateLimiter

        limiter = InMemoryRateLimiter(max_requests=10, window_seconds=30)
        assert limiter.max_requests == 10
        assert limiter.window_seconds == 30

    def test_first_request_allowed(self):
        """First request from a key is allowed."""
        from smart_home_common.rate_limiter import InMemoryRateLimiter

        limiter = InMemoryRateLimiter(max_requests=5, window_seconds=60)
        assert limiter.is_allowed("ip1") is True

    def test_within_limit_allowed(self):
        """Requests within limit are allowed."""
        from smart_home_common.rate_limiter import InMemoryRateLimiter

        limiter = InMemoryRateLimiter(max_requests=5, window_seconds=60)

        for i in range(5):
            assert limiter.is_allowed("ip1") is True, f"Request {i + 1} should be allowed"

    def test_exceeding_limit_blocked(self):
        """Requests exceeding limit are blocked."""
        from smart_home_common.rate_limiter import InMemoryRateLimiter

        limiter = InMemoryRateLimiter(max_requests=3, window_seconds=60)

        # Use up all attempts
        for _ in range(3):
            limiter.is_allowed("ip1")

        # Next request should be blocked
        assert limiter.is_allowed("ip1") is False

    def test_different_keys_independent(self):
        """Different keys have independent limits."""
        from smart_home_common.rate_limiter import InMemoryRateLimiter

        limiter = InMemoryRateLimiter(max_requests=2, window_seconds=60)

        # Exhaust ip1
        limiter.is_allowed("ip1")
        limiter.is_allowed("ip1")
        assert limiter.is_allowed("ip1") is False

        # ip2 should still be allowed
        assert limiter.is_allowed("ip2") is True

    def test_get_status_new_key(self):
        """get_status returns full allowance for new key."""
        from smart_home_common.rate_limiter import InMemoryRateLimiter

        limiter = InMemoryRateLimiter(max_requests=10, window_seconds=60)
        status = limiter.get_status("new_ip")

        assert status.allowed is True
        assert status.remaining == 10

    def test_get_status_after_requests(self):
        """get_status shows correct remaining after requests."""
        from smart_home_common.rate_limiter import InMemoryRateLimiter

        limiter = InMemoryRateLimiter(max_requests=5, window_seconds=60)

        limiter.is_allowed("ip1")
        limiter.is_allowed("ip1")
        limiter.is_allowed("ip1")

        status = limiter.get_status("ip1")
        assert status.remaining == 2
        assert status.allowed is True

    def test_get_status_when_exhausted(self):
        """get_status shows not allowed when exhausted."""
        from smart_home_common.rate_limiter import InMemoryRateLimiter

        limiter = InMemoryRateLimiter(max_requests=2, window_seconds=60)

        limiter.is_allowed("ip1")
        limiter.is_allowed("ip1")

        status = limiter.get_status("ip1")
        assert status.remaining == 0
        assert status.allowed is False

    def test_reset_clears_limit(self):
        """reset clears the limit for a key."""
        from smart_home_common.rate_limiter import InMemoryRateLimiter

        limiter = InMemoryRateLimiter(max_requests=2, window_seconds=60)

        # Exhaust limit
        limiter.is_allowed("ip1")
        limiter.is_allowed("ip1")
        assert limiter.is_allowed("ip1") is False

        # Reset and verify allowed again
        limiter.reset("ip1")
        assert limiter.is_allowed("ip1") is True

    def test_reset_nonexistent_key_no_error(self):
        """reset on nonexistent key does not raise."""
        from smart_home_common.rate_limiter import InMemoryRateLimiter

        limiter = InMemoryRateLimiter()
        limiter.reset("nonexistent")  # Should not raise

    def test_window_reset_after_timeout(self):
        """Window resets after timeout period."""
        from smart_home_common.rate_limiter import InMemoryRateLimiter

        limiter = InMemoryRateLimiter(max_requests=2, window_seconds=1)

        # Exhaust limit
        limiter.is_allowed("ip1")
        limiter.is_allowed("ip1")
        assert limiter.is_allowed("ip1") is False

        # Wait for window to expire
        time.sleep(1.1)

        # Should be allowed again
        assert limiter.is_allowed("ip1") is True

    def test_thread_safety(self):
        """InMemoryRateLimiter is thread-safe."""
        from smart_home_common.rate_limiter import InMemoryRateLimiter

        limiter = InMemoryRateLimiter(max_requests=100, window_seconds=60)
        results = []

        def make_requests():
            for _ in range(50):
                results.append(limiter.is_allowed("shared_ip"))

        threads = [threading.Thread(target=make_requests) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should have exactly 100 True and 100 False
        assert sum(results) == 100
        assert len(results) == 200


class TestSqliteRateLimiter:
    """Tests for SqliteRateLimiter."""

    @pytest.fixture
    def db_path(self, tmp_path):
        """Provide a temporary database path."""
        return str(tmp_path / "rate_limits.db")

    def test_init_creates_table(self, db_path):
        """SqliteRateLimiter creates the rate_limits table."""
        from smart_home_common.rate_limiter import SqliteRateLimiter

        SqliteRateLimiter(db_path, max_requests=10, window_seconds=60)

        conn = sqlite3.connect(db_path)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='rate_limits'"
        )
        assert cursor.fetchone() is not None
        conn.close()

    def test_custom_table_name(self, db_path):
        """SqliteRateLimiter uses custom table name."""
        from smart_home_common.rate_limiter import SqliteRateLimiter

        SqliteRateLimiter(db_path, max_requests=10, window_seconds=60, table_name="custom_limits")

        conn = sqlite3.connect(db_path)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='custom_limits'"
        )
        assert cursor.fetchone() is not None
        conn.close()

    def test_first_request_allowed(self, db_path):
        """First request is allowed."""
        from smart_home_common.rate_limiter import SqliteRateLimiter

        limiter = SqliteRateLimiter(db_path, max_requests=5, window_seconds=60)
        assert limiter.is_allowed("ip1") is True

    def test_within_limit_allowed(self, db_path):
        """Requests within limit are allowed."""
        from smart_home_common.rate_limiter import SqliteRateLimiter

        limiter = SqliteRateLimiter(db_path, max_requests=5, window_seconds=60)

        for _ in range(5):
            assert limiter.is_allowed("ip1") is True

    def test_exceeding_limit_blocked(self, db_path):
        """Requests exceeding limit are blocked."""
        from smart_home_common.rate_limiter import SqliteRateLimiter

        limiter = SqliteRateLimiter(db_path, max_requests=3, window_seconds=60)

        for _ in range(3):
            limiter.is_allowed("ip1")

        assert limiter.is_allowed("ip1") is False

    def test_persistence_across_instances(self, db_path):
        """Rate limit persists across limiter instances."""
        from smart_home_common.rate_limiter import SqliteRateLimiter

        # First instance exhausts limit
        limiter1 = SqliteRateLimiter(db_path, max_requests=2, window_seconds=60)
        limiter1.is_allowed("ip1")
        limiter1.is_allowed("ip1")

        # Second instance should see the exhausted limit
        limiter2 = SqliteRateLimiter(db_path, max_requests=2, window_seconds=60)
        assert limiter2.is_allowed("ip1") is False

    def test_get_status(self, db_path):
        """get_status returns correct values."""
        from smart_home_common.rate_limiter import SqliteRateLimiter

        limiter = SqliteRateLimiter(db_path, max_requests=5, window_seconds=60)

        limiter.is_allowed("ip1")
        limiter.is_allowed("ip1")

        status = limiter.get_status("ip1")
        assert status.remaining == 3
        assert status.allowed is True

    def test_reset(self, db_path):
        """reset clears the limit."""
        from smart_home_common.rate_limiter import SqliteRateLimiter

        limiter = SqliteRateLimiter(db_path, max_requests=2, window_seconds=60)

        limiter.is_allowed("ip1")
        limiter.is_allowed("ip1")
        assert limiter.is_allowed("ip1") is False

        limiter.reset("ip1")
        assert limiter.is_allowed("ip1") is True

    def test_window_reset(self, db_path):
        """Window resets after timeout."""
        from smart_home_common.rate_limiter import SqliteRateLimiter

        limiter = SqliteRateLimiter(db_path, max_requests=2, window_seconds=1)

        limiter.is_allowed("ip1")
        limiter.is_allowed("ip1")
        assert limiter.is_allowed("ip1") is False

        time.sleep(1.1)
        assert limiter.is_allowed("ip1") is True

    def test_cleanup_expired(self, db_path):
        """cleanup_expired removes old entries."""
        from smart_home_common.rate_limiter import SqliteRateLimiter

        limiter = SqliteRateLimiter(db_path, max_requests=5, window_seconds=1)

        # Create some entries
        limiter.is_allowed("ip1")
        limiter.is_allowed("ip2")

        # Wait for them to expire
        time.sleep(1.1)

        removed = limiter.cleanup_expired()
        assert removed == 2

        # Verify entries are gone
        conn = sqlite3.connect(db_path)
        cursor = conn.execute("SELECT COUNT(*) FROM rate_limits")
        count = cursor.fetchone()[0]
        conn.close()
        assert count == 0

    def test_cleanup_expired_keeps_active(self, db_path):
        """cleanup_expired keeps active entries."""
        from smart_home_common.rate_limiter import SqliteRateLimiter

        limiter = SqliteRateLimiter(db_path, max_requests=5, window_seconds=60)

        limiter.is_allowed("active_ip")

        removed = limiter.cleanup_expired()
        assert removed == 0

        # Verify entry still exists
        conn = sqlite3.connect(db_path)
        cursor = conn.execute("SELECT COUNT(*) FROM rate_limits")
        count = cursor.fetchone()[0]
        conn.close()
        assert count == 1


class TestBaseRateLimiter:
    """Tests for BaseRateLimiter abstract class."""

    def test_cannot_instantiate_directly(self):
        """BaseRateLimiter cannot be instantiated directly."""
        from smart_home_common.rate_limiter import BaseRateLimiter

        with pytest.raises(TypeError):
            BaseRateLimiter(max_requests=10, window_seconds=60)
