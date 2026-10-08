"""Smart Home Common Library - Shared utilities for all services."""

from .cache import TTLCache
from .rate_limiter import (
    BaseRateLimiter,
    InMemoryRateLimiter,
    RateLimitStatus,
    SqliteRateLimiter,
)
from .singleton import ensure_singleton
from .sqlite_helpers import (
    SqliteHelper,
    open_connection,
    sqlite_connection,
)

__version__ = "0.1.0"

__all__ = [
    "BaseRateLimiter",
    "InMemoryRateLimiter",
    "RateLimitStatus",
    "SqliteHelper",
    "SqliteRateLimiter",
    "TTLCache",
    "ensure_singleton",
    "open_connection",
    "sqlite_connection",
]
