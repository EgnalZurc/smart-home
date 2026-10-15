"""Smart Home Common Library - Shared utilities for all services."""

from .cache import TTLCache
from .rate_limiter import (
    BaseRateLimiter,
    InMemoryRateLimiter,
    RateLimitStatus,
    SqliteRateLimiter,
)
from .redis_rate_limiter import RedisRateLimiter
from .singleton import ensure_singleton
from .sqlite_helpers import (
    SqliteHelper,
    open_connection,
    sqlite_connection,
)
from .telegram import TelegramNotifier, TelegramResult

__version__ = "0.1.0"

__all__ = [
    "BaseRateLimiter",
    "InMemoryRateLimiter",
    "RateLimitStatus",
    "RedisRateLimiter",
    "SqliteHelper",
    "SqliteRateLimiter",
    "TTLCache",
    "TelegramNotifier",
    "TelegramResult",
    "ensure_singleton",
    "open_connection",
    "sqlite_connection",
]
