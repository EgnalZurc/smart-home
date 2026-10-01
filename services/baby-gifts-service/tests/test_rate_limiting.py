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
        from gifts_controller import RATE_LIMIT_ATTEMPTS, check_rate_limit
        
        ip = "192.168.1.2"
        
        # Make requests up to limit
        for _ in range(RATE_LIMIT_ATTEMPTS):
            result = check_rate_limit(ip)
            assert result is True

    def test_exceeding_limit_blocked(self, tmp_data_dir):
        """Requests exceeding limit should be blocked."""
        from gifts_controller import RATE_LIMIT_ATTEMPTS, check_rate_limit
        
        ip = "192.168.1.3"
        
        # Use up all attempts
        for _ in range(RATE_LIMIT_ATTEMPTS):
            check_rate_limit(ip)
        
        # Next request should be blocked
        result = check_rate_limit(ip)
        assert result is False

    def test_different_ips_independent(self, tmp_data_dir):
        """Different IPs should have independent limits."""
        from gifts_controller import RATE_LIMIT_ATTEMPTS, check_rate_limit
        
        ip1 = "192.168.1.4"
        ip2 = "192.168.1.5"
        
        # Exhaust IP1's limit
        for _ in range(RATE_LIMIT_ATTEMPTS):
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
