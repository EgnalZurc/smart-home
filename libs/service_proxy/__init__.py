"""Shared HTTP service proxy library.

Provides ServiceProxy base class for proxying requests to internal services.
"""

from .circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerRegistry,
    CircuitState,
)
from .proxy import HTTPException, ServiceProxy

__all__ = [
    "ServiceProxy",
    "HTTPException",
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "CircuitBreakerRegistry",
    "CircuitState",
]
