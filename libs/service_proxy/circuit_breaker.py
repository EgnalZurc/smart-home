"""Circuit breaker implementation for service proxies.

Prevents cascading failures by temporarily stopping requests to failing services.
"""

import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation, requests pass through
    OPEN = "open"  # Service failing, requests rejected immediately
    HALF_OPEN = "half_open"  # Testing if service recovered


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker.

    Attributes:
        failure_threshold: Number of failures before opening circuit
        success_threshold: Number of successes in half-open before closing
        timeout: Seconds to wait before transitioning from open to half-open
        excluded_exceptions: Exception types that don't count as failures
    """

    failure_threshold: int = 5
    success_threshold: int = 2
    timeout: float = 30.0
    excluded_exceptions: tuple = ()


class CircuitBreaker:
    """Circuit breaker for protecting against cascading failures.

    Example:
        ```python
        breaker = CircuitBreaker(name="my-service")

        async def make_request():
            if not breaker.allow_request():
                raise HTTPException(503, "Service temporarily unavailable")
            try:
                result = await do_request()
                breaker.record_success()
                return result
            except Exception as e:
                breaker.record_failure()
                raise
        ```
    """

    def __init__(
        self,
        name: str,
        config: CircuitBreakerConfig | None = None,
        on_state_change: Callable[[str, CircuitState, CircuitState], None] | None = None,
    ):
        """Initialize circuit breaker.

        Args:
            name: Name for logging/identification
            config: Configuration options
            on_state_change: Callback when state changes (name, old_state, new_state)
        """
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self.on_state_change = on_state_change

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float = 0

    @property
    def state(self) -> CircuitState:
        """Current circuit state."""
        return self._state

    @property
    def is_closed(self) -> bool:
        """True if circuit is closed (normal operation)."""
        return self._state == CircuitState.CLOSED

    @property
    def is_open(self) -> bool:
        """True if circuit is open (rejecting requests)."""
        return self._state == CircuitState.OPEN

    def allow_request(self) -> bool:
        """Check if a request should be allowed.

        Returns:
            True if request should proceed, False if circuit is open
        """
        if self._state == CircuitState.CLOSED:
            return True

        if self._state == CircuitState.OPEN:
            # Check if timeout has passed
            if time.time() - self._last_failure_time >= self.config.timeout:
                self._transition_to(CircuitState.HALF_OPEN)
                return True
            return False

        # Half-open: allow request to test service
        return True

    def record_success(self) -> None:
        """Record a successful request."""
        if self._state == CircuitState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self.config.success_threshold:
                self._transition_to(CircuitState.CLOSED)
        elif self._state == CircuitState.CLOSED:
            # Reset failure count on success
            self._failure_count = 0

    def record_failure(self, exception: Exception | None = None) -> None:
        """Record a failed request.

        Args:
            exception: The exception that caused the failure (optional)
        """
        # Check if exception is excluded
        if exception and isinstance(exception, self.config.excluded_exceptions):
            return

        self._last_failure_time = time.time()

        if self._state == CircuitState.HALF_OPEN:
            # Any failure in half-open reopens the circuit
            self._transition_to(CircuitState.OPEN)
        elif self._state == CircuitState.CLOSED:
            self._failure_count += 1
            if self._failure_count >= self.config.failure_threshold:
                self._transition_to(CircuitState.OPEN)

    def reset(self) -> None:
        """Manually reset the circuit to closed state."""
        self._transition_to(CircuitState.CLOSED)

    def _transition_to(self, new_state: CircuitState) -> None:
        """Transition to a new state."""
        if self._state == new_state:
            return

        old_state = self._state
        self._state = new_state

        # Reset counters based on new state
        if new_state == CircuitState.CLOSED:
            self._failure_count = 0
            self._success_count = 0
        elif new_state == CircuitState.HALF_OPEN:
            self._success_count = 0

        logger.info(
            "Circuit breaker '%s' state changed: %s -> %s",
            self.name,
            old_state.value,
            new_state.value,
        )

        if self.on_state_change:
            self.on_state_change(self.name, old_state, new_state)


class CircuitBreakerRegistry:
    """Registry of circuit breakers for multiple services.

    Example:
        ```python
        registry = CircuitBreakerRegistry()

        # Get or create breaker for a service
        breaker = registry.get("my-service")
        ```
    """

    def __init__(self, default_config: CircuitBreakerConfig | None = None):
        """Initialize registry.

        Args:
            default_config: Default configuration for new breakers
        """
        self.default_config = default_config or CircuitBreakerConfig()
        self._breakers: dict[str, CircuitBreaker] = {}

    def get(
        self,
        name: str,
        config: CircuitBreakerConfig | None = None,
    ) -> CircuitBreaker:
        """Get or create a circuit breaker for a service.

        Args:
            name: Service name
            config: Override default config for this breaker

        Returns:
            CircuitBreaker instance
        """
        if name not in self._breakers:
            self._breakers[name] = CircuitBreaker(
                name=name,
                config=config or self.default_config,
            )
        return self._breakers[name]

    def get_all_states(self) -> dict[str, str]:
        """Get states of all registered breakers.

        Returns:
            Dict of {name: state_value}
        """
        return {name: b.state.value for name, b in self._breakers.items()}

    def reset_all(self) -> None:
        """Reset all breakers to closed state."""
        for breaker in self._breakers.values():
            breaker.reset()
