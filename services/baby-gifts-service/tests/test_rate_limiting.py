"""Unit tests for rate limiting functionality."""


class TestRateLimiting:
    """Tests for rate limiting functionality."""

    def test_first_request_allowed(self, tmp_data_dir):
        """First request from an IP should be allowed."""
        from gifts_controller import check_rate_limit

        result = check_rate_limit("192.168.1.1")
        assert result is True

    def test_within_limit_allowed(self, tmp_data_dir):
        """Requests within limit should be allowed."""
        import config

        from gifts_controller import check_rate_limit

        ip = "192.168.1.2"

        # Make requests up to limit
        for _ in range(config.RATE_LIMIT_ATTEMPTS):
            result = check_rate_limit(ip)
            assert result is True

    def test_exceeding_limit_blocked(self, tmp_data_dir):
        """Requests exceeding limit should be blocked."""
        import config

        from gifts_controller import check_rate_limit

        ip = "192.168.1.3"

        # Use up all attempts
        for _ in range(config.RATE_LIMIT_ATTEMPTS):
            check_rate_limit(ip)

        # Next request should be blocked
        result = check_rate_limit(ip)
        assert result is False

    def test_different_ips_independent(self, tmp_data_dir):
        """Different IPs should have independent limits."""
        import config

        from gifts_controller import check_rate_limit

        ip1 = "192.168.1.4"
        ip2 = "192.168.1.5"

        # Exhaust IP1's limit
        for _ in range(config.RATE_LIMIT_ATTEMPTS):
            check_rate_limit(ip1)

        # IP2 should still be allowed
        result = check_rate_limit(ip2)
        assert result is True


class TestHealthCheck:
    """Tests for health check functionality."""

    def test_is_healthy_returns_true(self, tmp_data_dir):
        """is_healthy should return True when DB is accessible."""
        from gifts_controller import is_healthy

        result = is_healthy()
        assert result is True


class TestRateLimitWindowReset:
    """Tests for rate limit window reset."""

    def test_window_reset_after_timeout(self, tmp_data_dir):
        """Rate limit window should reset after timeout."""
        from datetime import datetime, timedelta

        import config

        from gifts_controller import (
            _get_db,
            check_rate_limit,
        )

        ip = "192.168.1.100"

        # Exhaust rate limit
        for _ in range(config.RATE_LIMIT_ATTEMPTS):
            check_rate_limit(ip)

        # Should be blocked
        assert check_rate_limit(ip) is False

        # Manually set window_start to past (simulate timeout)
        conn = _get_db()
        past_time = (datetime.now() - timedelta(seconds=120)).isoformat()
        conn.execute(
            "UPDATE rate_limits SET window_start = ? WHERE ip = ?",
            (past_time, ip),
        )
        conn.commit()
        conn.close()

        # Should be allowed again (window reset)
        assert check_rate_limit(ip) is True
