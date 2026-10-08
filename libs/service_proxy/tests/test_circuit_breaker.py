"""Tests for circuit breaker module."""

import time
from unittest.mock import MagicMock

import pytest

from service_proxy.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerRegistry,
    CircuitState,
)


class TestCircuitBreakerConfig:
    """Tests for CircuitBreakerConfig."""

    def test_default_values(self):
        """Default config has sensible values."""
        config = CircuitBreakerConfig()
        assert config.failure_threshold == 5
        assert config.success_threshold == 2
        assert config.timeout == 30.0
        assert config.excluded_exceptions == ()

    def test_custom_values(self):
        """Custom config values are respected."""
        config = CircuitBreakerConfig(
            failure_threshold=3,
            success_threshold=1,
            timeout=10.0,
            excluded_exceptions=(ValueError,),
        )
        assert config.failure_threshold == 3
        assert config.success_threshold == 1
        assert config.timeout == 10.0
        assert config.excluded_exceptions == (ValueError,)


class TestCircuitBreaker:
    """Tests for CircuitBreaker."""

    def test_initial_state_is_closed(self):
        """Breaker starts in closed state."""
        breaker = CircuitBreaker(name="test")
        assert breaker.state == CircuitState.CLOSED
        assert breaker.is_closed
        assert not breaker.is_open

    def test_allow_request_when_closed(self):
        """Requests allowed when circuit is closed."""
        breaker = CircuitBreaker(name="test")
        assert breaker.allow_request() is True

    def test_record_success_resets_failure_count(self):
        """Success resets failure count in closed state."""
        breaker = CircuitBreaker(name="test")
        breaker._failure_count = 3
        breaker.record_success()
        assert breaker._failure_count == 0

    def test_opens_after_failure_threshold(self):
        """Circuit opens after reaching failure threshold."""
        config = CircuitBreakerConfig(failure_threshold=3)
        breaker = CircuitBreaker(name="test", config=config)

        for _ in range(3):
            breaker.record_failure()

        assert breaker.state == CircuitState.OPEN
        assert breaker.is_open

    def test_rejects_requests_when_open(self):
        """Requests rejected when circuit is open."""
        config = CircuitBreakerConfig(failure_threshold=1, timeout=60.0)
        breaker = CircuitBreaker(name="test", config=config)
        breaker.record_failure()

        assert breaker.allow_request() is False

    def test_transitions_to_half_open_after_timeout(self):
        """Circuit goes to half-open after timeout."""
        config = CircuitBreakerConfig(failure_threshold=1, timeout=0.01)
        breaker = CircuitBreaker(name="test", config=config)
        breaker.record_failure()

        # Wait for timeout
        time.sleep(0.02)

        assert breaker.allow_request() is True
        assert breaker.state == CircuitState.HALF_OPEN

    def test_closes_after_success_threshold_in_half_open(self):
        """Circuit closes after success threshold in half-open."""
        config = CircuitBreakerConfig(
            failure_threshold=1, success_threshold=2, timeout=0.01
        )
        breaker = CircuitBreaker(name="test", config=config)
        breaker.record_failure()

        # Wait for timeout to go half-open
        time.sleep(0.02)
        breaker.allow_request()

        # Record successes
        breaker.record_success()
        assert breaker.state == CircuitState.HALF_OPEN

        breaker.record_success()
        assert breaker.state == CircuitState.CLOSED

    def test_reopens_on_failure_in_half_open(self):
        """Circuit reopens on failure in half-open state."""
        config = CircuitBreakerConfig(failure_threshold=1, timeout=0.01)
        breaker = CircuitBreaker(name="test", config=config)
        breaker.record_failure()

        # Wait for timeout
        time.sleep(0.02)
        breaker.allow_request()  # Now half-open

        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

    def test_excluded_exceptions_not_counted(self):
        """Excluded exceptions don't count as failures."""
        config = CircuitBreakerConfig(
            failure_threshold=2, excluded_exceptions=(ValueError,)
        )
        breaker = CircuitBreaker(name="test", config=config)

        breaker.record_failure(ValueError("test"))
        breaker.record_failure(ValueError("test"))

        assert breaker.state == CircuitState.CLOSED

    def test_non_excluded_exceptions_counted(self):
        """Non-excluded exceptions count as failures."""
        config = CircuitBreakerConfig(
            failure_threshold=2, excluded_exceptions=(ValueError,)
        )
        breaker = CircuitBreaker(name="test", config=config)

        breaker.record_failure(TypeError("test"))
        breaker.record_failure(TypeError("test"))

        assert breaker.state == CircuitState.OPEN

    def test_reset_restores_closed_state(self):
        """Manual reset restores closed state."""
        config = CircuitBreakerConfig(failure_threshold=1)
        breaker = CircuitBreaker(name="test", config=config)
        breaker.record_failure()

        assert breaker.state == CircuitState.OPEN
        breaker.reset()
        assert breaker.state == CircuitState.CLOSED
        assert breaker._failure_count == 0

    def test_state_change_callback(self):
        """State change callback is invoked."""
        callback = MagicMock()
        config = CircuitBreakerConfig(failure_threshold=1)
        breaker = CircuitBreaker(name="test", config=config, on_state_change=callback)

        breaker.record_failure()

        callback.assert_called_once_with(
            "test", CircuitState.CLOSED, CircuitState.OPEN
        )


class TestCircuitBreakerRegistry:
    """Tests for CircuitBreakerRegistry."""

    def test_get_creates_new_breaker(self):
        """Get creates new breaker if not exists."""
        registry = CircuitBreakerRegistry()
        breaker = registry.get("service-a")

        assert breaker.name == "service-a"
        assert breaker.state == CircuitState.CLOSED

    def test_get_returns_same_breaker(self):
        """Get returns same breaker for same name."""
        registry = CircuitBreakerRegistry()
        breaker1 = registry.get("service-a")
        breaker2 = registry.get("service-a")

        assert breaker1 is breaker2

    def test_uses_default_config(self):
        """Registry uses default config for new breakers."""
        config = CircuitBreakerConfig(failure_threshold=10)
        registry = CircuitBreakerRegistry(default_config=config)
        breaker = registry.get("service-a")

        assert breaker.config.failure_threshold == 10

    def test_override_config_per_breaker(self):
        """Config can be overridden per breaker."""
        registry = CircuitBreakerRegistry()
        custom_config = CircuitBreakerConfig(failure_threshold=3)
        breaker = registry.get("service-a", config=custom_config)

        assert breaker.config.failure_threshold == 3

    def test_get_all_states(self):
        """Get all states returns dict of states."""
        registry = CircuitBreakerRegistry()
        registry.get("service-a")
        registry.get("service-b")

        states = registry.get_all_states()

        assert states == {"service-a": "closed", "service-b": "closed"}

    def test_reset_all(self):
        """Reset all resets all breakers."""
        config = CircuitBreakerConfig(failure_threshold=1)
        registry = CircuitBreakerRegistry(default_config=config)

        breaker_a = registry.get("service-a")
        breaker_b = registry.get("service-b")

        breaker_a.record_failure()
        breaker_b.record_failure()

        assert breaker_a.is_open
        assert breaker_b.is_open

        registry.reset_all()

        assert breaker_a.is_closed
        assert breaker_b.is_closed
