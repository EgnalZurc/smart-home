"""Tests for the circuit_breaker module."""

import time

import pytest
from circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerOpen,
    CircuitState,
    get_circuit_breaker,
)


class TestCircuitBreaker:
    """Tests for CircuitBreaker class."""

    def test_initial_state_is_closed(self):
        """Circuit breaker starts in closed state."""
        cb = CircuitBreaker("test_initial")
        assert cb.state == CircuitState.CLOSED

    def test_successful_call_passes_through(self):
        """Successful calls pass through normally."""
        cb = CircuitBreaker("test_success")
        result = cb.call(lambda: "success")
        assert result == "success"

    def test_failures_increment_counter(self):
        """Failed calls increment the failure counter."""
        cb = CircuitBreaker("test_failures", CircuitBreakerConfig(failure_threshold=5))
        for _ in range(3):
            with pytest.raises(ValueError):
                cb.call(lambda: (_ for _ in ()).throw(ValueError("test")))
        assert cb.get_status()["failure_count"] == 3

    def test_circuit_opens_after_threshold(self):
        """Circuit opens after reaching failure threshold."""
        cb = CircuitBreaker("test_open", CircuitBreakerConfig(failure_threshold=3))
        for _ in range(3):
            with pytest.raises(ValueError):
                cb.call(lambda: (_ for _ in ()).throw(ValueError("test")))
        assert cb.state == CircuitState.OPEN

    def test_open_circuit_rejects_calls(self):
        """Open circuit immediately rejects calls."""
        cb = CircuitBreaker(
            "test_reject", CircuitBreakerConfig(failure_threshold=2, recovery_timeout=60.0)
        )
        for _ in range(2):
            with pytest.raises(ValueError):
                cb.call(lambda: (_ for _ in ()).throw(ValueError("test")))
        with pytest.raises(CircuitBreakerOpen) as exc_info:
            cb.call(lambda: "should not run")
        assert "test_reject" in str(exc_info.value)

    def test_circuit_transitions_to_half_open(self):
        """Circuit transitions to half-open after recovery timeout."""
        cb = CircuitBreaker(
            "test_half_open", CircuitBreakerConfig(failure_threshold=2, recovery_timeout=0.1)
        )
        for _ in range(2):
            with pytest.raises(ValueError):
                cb.call(lambda: (_ for _ in ()).throw(ValueError("test")))
        time.sleep(0.15)
        result = cb.call(lambda: "recovered")
        assert result == "recovered"

    def test_half_open_success_closes_circuit(self):
        """Successful calls in half-open state close the circuit."""
        cb = CircuitBreaker(
            "test_close",
            CircuitBreakerConfig(failure_threshold=2, recovery_timeout=0.1, success_threshold=2),
        )
        for _ in range(2):
            with pytest.raises(ValueError):
                cb.call(lambda: (_ for _ in ()).throw(ValueError("test")))
        time.sleep(0.15)
        cb.call(lambda: "s1")
        cb.call(lambda: "s2")
        assert cb.state == CircuitState.CLOSED

    def test_half_open_failure_reopens_circuit(self):
        """Failed call in half-open state reopens the circuit."""
        cb = CircuitBreaker(
            "test_reopen", CircuitBreakerConfig(failure_threshold=2, recovery_timeout=0.1)
        )
        for _ in range(2):
            with pytest.raises(ValueError):
                cb.call(lambda: (_ for _ in ()).throw(ValueError("test")))
        time.sleep(0.15)
        with pytest.raises(RuntimeError):
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError("fail")))
        assert cb.state == CircuitState.OPEN

    def test_success_resets_failure_count(self):
        """Successful call resets failure count in closed state."""
        cb = CircuitBreaker("test_reset", CircuitBreakerConfig(failure_threshold=5))
        for _ in range(3):
            with pytest.raises(ValueError):
                cb.call(lambda: (_ for _ in ()).throw(ValueError("test")))
        cb.call(lambda: "success")
        assert cb.get_status()["failure_count"] == 0

    def test_manual_reset(self):
        """Manual reset returns circuit to closed state."""
        cb = CircuitBreaker("test_manual", CircuitBreakerConfig(failure_threshold=2))
        for _ in range(2):
            with pytest.raises(ValueError):
                cb.call(lambda: (_ for _ in ()).throw(ValueError("test")))
        cb.reset()
        assert cb.state == CircuitState.CLOSED


class TestCircuitBreakerGlobals:
    """Tests for global circuit breaker management."""

    def test_get_circuit_breaker_creates_singleton(self):
        """get_circuit_breaker returns the same instance for same name."""
        cb1 = get_circuit_breaker("singleton_test")
        cb2 = get_circuit_breaker("singleton_test")
        assert cb1 is cb2

    def test_get_circuit_breaker_different_names(self):
        """get_circuit_breaker returns different instances for different names."""
        cb1 = get_circuit_breaker("different_1")
        cb2 = get_circuit_breaker("different_2")
        assert cb1 is not cb2


class TestCircuitBreakerOpen:
    """Tests for CircuitBreakerOpen exception."""

    def test_exception_message(self):
        """Exception has informative message."""
        exc = CircuitBreakerOpen("test_service", 30.0)
        assert "test_service" in str(exc)

    def test_exception_attributes(self):
        """Exception has correct attributes."""
        exc = CircuitBreakerOpen("my_service", 45.5)
        assert exc.service == "my_service"
        assert exc.retry_after == 45.5
