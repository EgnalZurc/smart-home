"""
Tests for smart_home_common/redis_rate_limiter.py.

Covers:
- RedisRateLimiter: initialization, is_allowed, get_status, reset
- Graceful fallback when Redis unavailable
- Redis error handling
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest


class TestRedisRateLimiter:
    """Tests for RedisRateLimiter."""

    @pytest.fixture
    def mock_redis_client(self):
        """Create a mock Redis client."""
        client = MagicMock()
        client.ping.return_value = True
        client.incr.return_value = 1
        client.expire.return_value = True
        client.get.return_value = None
        client.ttl.return_value = -2
        client.delete.return_value = 1
        return client

    @pytest.fixture
    def limiter_with_mock(self, mock_redis_client):
        """Create a RedisRateLimiter with mocked Redis."""
        with (
            patch("smart_home_common.redis_rate_limiter.redis") as mock_redis_module,
            patch("smart_home_common.redis_rate_limiter.REDIS_AVAILABLE", True),
        ):
            mock_redis_module.from_url.return_value = mock_redis_client
            mock_redis_module.RedisError = Exception

            from smart_home_common.redis_rate_limiter import RedisRateLimiter

            limiter = RedisRateLimiter(
                max_requests=5, window_seconds=60, redis_url="redis://localhost:6379/0"
            )
            return limiter

    def test_init_with_defaults(self, mock_redis_client):
        """RedisRateLimiter initializes with defaults."""
        with (
            patch("smart_home_common.redis_rate_limiter.redis") as mock_redis_module,
            patch("smart_home_common.redis_rate_limiter.REDIS_AVAILABLE", True),
        ):
            mock_redis_module.from_url.return_value = mock_redis_client
            mock_redis_module.RedisError = Exception

            from smart_home_common.redis_rate_limiter import RedisRateLimiter

            limiter = RedisRateLimiter()
            assert limiter.max_requests == 20
            assert limiter.window_seconds == 60

    def test_init_with_custom_values(self, mock_redis_client):
        """RedisRateLimiter initializes with custom values."""
        with (
            patch("smart_home_common.redis_rate_limiter.redis") as mock_redis_module,
            patch("smart_home_common.redis_rate_limiter.REDIS_AVAILABLE", True),
        ):
            mock_redis_module.from_url.return_value = mock_redis_client
            mock_redis_module.RedisError = Exception

            from smart_home_common.redis_rate_limiter import RedisRateLimiter

            limiter = RedisRateLimiter(
                max_requests=10,
                window_seconds=30,
                redis_url="redis://custom:6379/1",
                key_prefix="custom:",
            )
            assert limiter.max_requests == 10
            assert limiter.window_seconds == 30

    def test_first_request_allowed(self, limiter_with_mock, mock_redis_client):
        """First request from a key is allowed."""
        mock_redis_client.incr.return_value = 1
        assert limiter_with_mock.is_allowed("ip1") is True

    def test_within_limit_allowed(self, limiter_with_mock, mock_redis_client):
        """Requests within limit are allowed."""
        for i in range(1, 6):
            mock_redis_client.incr.return_value = i
            assert limiter_with_mock.is_allowed("ip1") is True, f"Request {i} should be allowed"

    def test_exceeding_limit_blocked(self, limiter_with_mock, mock_redis_client):
        """Requests exceeding limit are blocked."""
        mock_redis_client.incr.return_value = 6  # Exceeds max_requests=5
        assert limiter_with_mock.is_allowed("ip1") is False

    def test_expire_set_on_first_request(self, limiter_with_mock, mock_redis_client):
        """Expire is set only on the first request in window."""
        mock_redis_client.incr.return_value = 1
        limiter_with_mock.is_allowed("ip1")
        mock_redis_client.expire.assert_called_once()

        mock_redis_client.expire.reset_mock()
        mock_redis_client.incr.return_value = 2
        limiter_with_mock.is_allowed("ip1")
        mock_redis_client.expire.assert_not_called()

    def test_get_key_with_prefix(self, limiter_with_mock):
        """_get_key adds the configured prefix."""
        key = limiter_with_mock._get_key("test_ip")
        assert key == "rate_limit:test_ip"

    def test_get_status_new_key(self, limiter_with_mock, mock_redis_client):
        """get_status returns full allowance for new key."""
        mock_redis_client.get.return_value = None

        status = limiter_with_mock.get_status("new_ip")

        assert status.allowed is True
        assert status.remaining == 5

    def test_get_status_after_requests(self, limiter_with_mock, mock_redis_client):
        """get_status shows correct remaining after requests."""
        mock_redis_client.get.return_value = "3"
        mock_redis_client.ttl.return_value = 45

        status = limiter_with_mock.get_status("ip1")

        assert status.remaining == 2
        assert status.allowed is True

    def test_get_status_when_exhausted(self, limiter_with_mock, mock_redis_client):
        """get_status shows not allowed when exhausted."""
        mock_redis_client.get.return_value = "5"
        mock_redis_client.ttl.return_value = 30

        status = limiter_with_mock.get_status("ip1")

        assert status.remaining == 0
        assert status.allowed is False

    def test_get_status_reset_at_from_ttl(self, limiter_with_mock, mock_redis_client):
        """get_status calculates reset_at from TTL."""
        mock_redis_client.get.return_value = "2"
        mock_redis_client.ttl.return_value = 30

        before = datetime.now()
        status = limiter_with_mock.get_status("ip1")
        after = datetime.now()

        # reset_at should be ~30 seconds from now
        expected_min = before + timedelta(seconds=30)
        expected_max = after + timedelta(seconds=30)

        assert expected_min <= status.reset_at <= expected_max

    def test_reset_deletes_key(self, limiter_with_mock, mock_redis_client):
        """reset deletes the Redis key."""
        limiter_with_mock.reset("ip1")
        mock_redis_client.delete.assert_called_once_with("rate_limit:ip1")


class TestRedisRateLimiterFallback:
    """Tests for graceful fallback behavior."""

    def test_fallback_when_redis_not_installed(self):
        """Falls back gracefully when redis package not installed."""
        with patch("smart_home_common.redis_rate_limiter.REDIS_AVAILABLE", False):
            # Need to reload to pick up the patched constant
            import importlib

            import smart_home_common.redis_rate_limiter as rl_module

            importlib.reload(rl_module)

            # Create limiter - should not raise
            limiter = rl_module.RedisRateLimiter(max_requests=5, window_seconds=60)

            # Should allow all requests
            assert limiter.is_allowed("ip1") is True
            assert limiter.is_allowed("ip1") is True

            # Status should show full allowance
            status = limiter.get_status("ip1")
            assert status.allowed is True
            assert status.remaining == 5

            # Reset should not raise
            limiter.reset("ip1")

            # Restore module
            importlib.reload(rl_module)

    def test_fallback_when_connection_fails(self):
        """Falls back gracefully when Redis connection fails."""
        with (
            patch("smart_home_common.redis_rate_limiter.redis") as mock_redis_module,
            patch("smart_home_common.redis_rate_limiter.REDIS_AVAILABLE", True),
        ):
            mock_client = MagicMock()
            mock_client.ping.side_effect = Exception("Connection refused")
            mock_redis_module.from_url.return_value = mock_client
            mock_redis_module.RedisError = Exception

            from smart_home_common.redis_rate_limiter import RedisRateLimiter

            limiter = RedisRateLimiter(max_requests=5, window_seconds=60)

            # Should allow all requests
            assert limiter.is_allowed("ip1") is True

    def test_fallback_on_incr_error(self, mock_redis_client):
        """Falls back to allow on INCR error."""
        with (
            patch("smart_home_common.redis_rate_limiter.redis") as mock_redis_module,
            patch("smart_home_common.redis_rate_limiter.REDIS_AVAILABLE", True),
        ):
            mock_redis_module.from_url.return_value = mock_redis_client
            mock_redis_module.RedisError = Exception

            from smart_home_common.redis_rate_limiter import RedisRateLimiter

            limiter = RedisRateLimiter(max_requests=5, window_seconds=60)

            # First call succeeds
            assert limiter.is_allowed("ip1") is True

            # Simulate error on next call
            mock_redis_client.incr.side_effect = Exception("Redis error")
            assert limiter.is_allowed("ip1") is True  # Should still allow

    def test_fallback_on_get_status_error(self, mock_redis_client):
        """Falls back to default status on get error."""
        with (
            patch("smart_home_common.redis_rate_limiter.redis") as mock_redis_module,
            patch("smart_home_common.redis_rate_limiter.REDIS_AVAILABLE", True),
        ):
            mock_redis_module.from_url.return_value = mock_redis_client
            mock_redis_module.RedisError = Exception

            from smart_home_common.redis_rate_limiter import RedisRateLimiter

            limiter = RedisRateLimiter(max_requests=5, window_seconds=60)

            mock_redis_client.get.side_effect = Exception("Redis error")
            status = limiter.get_status("ip1")

            assert status.allowed is True
            assert status.remaining == 5

    @pytest.fixture
    def mock_redis_client(self):
        """Create a mock Redis client."""
        client = MagicMock()
        client.ping.return_value = True
        client.incr.return_value = 1
        client.expire.return_value = True
        client.get.return_value = None
        client.ttl.return_value = -2
        client.delete.return_value = 1
        return client


class TestRedisRateLimiterIntegration:
    """Integration-style tests verifying the full flow with mocked Redis."""

    @pytest.fixture
    def mock_redis_client(self):
        """Create a stateful mock Redis client."""
        storage = {}

        client = MagicMock()
        client.ping.return_value = True

        def incr(key):
            if key not in storage:
                storage[key] = {"count": 0, "ttl": None}
            storage[key]["count"] += 1
            return storage[key]["count"]

        def expire(key, ttl):
            if key in storage:
                storage[key]["ttl"] = ttl
            return True

        def get(key):
            if key in storage:
                return str(storage[key]["count"])
            return None

        def ttl(key):
            if key in storage and storage[key]["ttl"] is not None:
                return storage[key]["ttl"]
            return -2

        def delete(key):
            if key in storage:
                del storage[key]
                return 1
            return 0

        client.incr = MagicMock(side_effect=incr)
        client.expire = MagicMock(side_effect=expire)
        client.get = MagicMock(side_effect=get)
        client.ttl = MagicMock(side_effect=ttl)
        client.delete = MagicMock(side_effect=delete)

        return client

    def test_full_flow_with_stateful_mock(self, mock_redis_client):
        """Test full rate limiting flow with stateful mock."""
        with (
            patch("smart_home_common.redis_rate_limiter.redis") as mock_redis_module,
            patch("smart_home_common.redis_rate_limiter.REDIS_AVAILABLE", True),
        ):
            mock_redis_module.from_url.return_value = mock_redis_client
            mock_redis_module.RedisError = Exception

            from smart_home_common.redis_rate_limiter import RedisRateLimiter

            limiter = RedisRateLimiter(max_requests=3, window_seconds=60)

            # First 3 requests should be allowed
            assert limiter.is_allowed("ip1") is True
            assert limiter.is_allowed("ip1") is True
            assert limiter.is_allowed("ip1") is True

            # 4th should be blocked
            assert limiter.is_allowed("ip1") is False

            # Check status
            status = limiter.get_status("ip1")
            assert status.remaining == 0
            assert status.allowed is False

            # Reset and try again
            limiter.reset("ip1")
            assert limiter.is_allowed("ip1") is True

            # Different key should have independent limit
            assert limiter.is_allowed("ip2") is True

    def test_independent_keys(self, mock_redis_client):
        """Different keys have independent rate limits."""
        with (
            patch("smart_home_common.redis_rate_limiter.redis") as mock_redis_module,
            patch("smart_home_common.redis_rate_limiter.REDIS_AVAILABLE", True),
        ):
            mock_redis_module.from_url.return_value = mock_redis_client
            mock_redis_module.RedisError = Exception

            from smart_home_common.redis_rate_limiter import RedisRateLimiter

            limiter = RedisRateLimiter(max_requests=2, window_seconds=60)

            # Exhaust ip1
            limiter.is_allowed("ip1")
            limiter.is_allowed("ip1")
            assert limiter.is_allowed("ip1") is False

            # ip2 should still be allowed
            assert limiter.is_allowed("ip2") is True
            assert limiter.is_allowed("ip2") is True
            assert limiter.is_allowed("ip2") is False
