"""
Portfolio Monitor — Circuit Breaker Implementation.

Implements the circuit breaker pattern for external API calls (CoinGecko, Yahoo Finance).
Prevents cascading failures by stopping requests to failing services.

States:
- CLOSED: Normal operation, requests pass through
- OPEN: Service is failing, requests are immediately rejected
- HALF_OPEN: Testing if service has recovered

Thread-safe implementation using locks.
"""

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker behavior."""

    failure_threshold: int = 5
    recovery_timeout: float = 60.0
    success_threshold: int = 2


class CircuitBreakerOpen(Exception):
    """Raised when circuit breaker is open and blocking requests."""

    def __init__(self, service: str, retry_after: float):
        self.service = service
        self.retry_after = retry_after
        super().__init__(
            f"Circuit breaker open for {service}. Retry after {retry_after:.0f}s"
        )


class CircuitBreaker:
    """Circuit breaker for protecting external API calls."""

    def __init__(self, name: str, config: CircuitBreakerConfig | None = None):
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float = 0
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        """Get current circuit state."""
        with self._lock:
            return self._state

    def get_status(self) -> dict:
        """Get circuit breaker status for monitoring."""
        with self._lock:
            retry_after = 0.0
            if self._state == CircuitState.OPEN:
                elapsed = time.time() - self._last_failure_time
                retry_after = max(0, self.config.recovery_timeout - elapsed)
            return {
                "name": self.name,
                "state": self._state.value,
                "failure_count": self._failure_count,
                "success_count": self._success_count,
                "retry_after": retry_after,
            }

    def _should_attempt(self) -> bool:
        """Check if we should attempt a request."""
        if self._state == CircuitState.CLOSED:
            return True
        if self._state == CircuitState.OPEN:
            elapsed = time.time() - self._last_failure_time
            if elapsed >= self.config.recovery_timeout:
                logger.info(
                    f"[circuit:{self.name}] Recovery timeout elapsed, "
                    "transitioning to HALF_OPEN"
                )
                self._state = CircuitState.HALF_OPEN
                self._success_count = 0
                return True
            return False
        return True

    def _record_success(self) -> None:
        """Record a successful call."""
        if self._state == CircuitState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self.config.success_threshold:
                logger.info(
                    f"[circuit:{self.name}] Service recovered, transitioning to CLOSED"
                )
                self._state = CircuitState.CLOSED
                self._failure_count = 0
        elif self._state == CircuitState.CLOSED:
            self._failure_count = 0

    def _record_failure(self) -> None:
        """Record a failed call."""
        self._failure_count += 1
        self._last_failure_time = time.time()
        if self._state == CircuitState.HALF_OPEN:
            logger.warning(
                f"[circuit:{self.name}] Failure in HALF_OPEN, reopening circuit"
            )
            self._state = CircuitState.OPEN
            self._success_count = 0
        elif (
            self._state == CircuitState.CLOSED
            and self._failure_count >= self.config.failure_threshold
        ):
            logger.warning(
                f"[circuit:{self.name}] Threshold reached ({self._failure_count}), "
                "opening circuit"
            )
            self._state = CircuitState.OPEN

    def call(self, func: Callable[[], T]) -> T:
        """Execute a function through the circuit breaker."""
        with self._lock:
            if not self._should_attempt():
                elapsed = time.time() - self._last_failure_time
                retry_after = max(0, self.config.recovery_timeout - elapsed)
                raise CircuitBreakerOpen(self.name, retry_after)
        try:
            result = func()
            with self._lock:
                self._record_success()
            return result
        except Exception:
            with self._lock:
                self._record_failure()
            raise

    def reset(self) -> None:
        """Manually reset the circuit breaker to closed state."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            logger.info(f"[circuit:{self.name}] Manually reset to CLOSED")


_circuit_breakers: dict[str, CircuitBreaker] = {}
_breakers_lock = threading.Lock()


def get_circuit_breaker(
    name: str, config: CircuitBreakerConfig | None = None
) -> CircuitBreaker:
    """Get or create a circuit breaker by name."""
    with _breakers_lock:
        if name not in _circuit_breakers:
            _circuit_breakers[name] = CircuitBreaker(name, config)
        return _circuit_breakers[name]


def get_all_circuit_statuses() -> dict[str, dict]:
    """Get status of all circuit breakers for health monitoring."""
    with _breakers_lock:
        return {name: cb.get_status() for name, cb in _circuit_breakers.items()}


def reset_all_circuits() -> None:
    """Reset all circuit breakers (for testing)."""
    with _breakers_lock:
        for cb in _circuit_breakers.values():
            cb.reset()


COINGECKO_BREAKER = get_circuit_breaker(
    "coingecko",
    CircuitBreakerConfig(failure_threshold=5, recovery_timeout=60.0, success_threshold=2),
)

YAHOO_BREAKER = get_circuit_breaker(
    "yahoo_finance",
    CircuitBreakerConfig(failure_threshold=5, recovery_timeout=30.0, success_threshold=2),
)

FEAR_GREED_BREAKER = get_circuit_breaker(
    "fear_greed",
    CircuitBreakerConfig(failure_threshold=3, recovery_timeout=120.0, success_threshold=1),
)
