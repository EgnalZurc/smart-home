"""Shared constants for the dashboard API.

Centralizes configuration values used across multiple modules to avoid
magic numbers and ensure consistency.
"""

import os

# -- Health Check Configuration ------------------------------------------------
#
# Time-to-live for cached health check results. Health checks are expensive
# (one HTTP request per service) and the dashboard polls frequently.
# This cache prevents hammering backend services while keeping status fresh.
# Configurable via HEALTH_CACHE_TTL environment variable (default: 5.0 seconds).
HEALTH_CACHE_TTL_SECONDS: float = float(os.environ.get("HEALTH_CACHE_TTL", "5.0"))

# Maximum number of entries allowed in the health cache. Provides an upper bound
# to prevent unbounded memory growth from orphaned service keys. In practice,
# the cache holds ~15 entries (one per monitored service), so 100 is generous.
# Configurable via HEALTH_CACHE_MAX_ENTRIES environment variable.
HEALTH_CACHE_MAX_ENTRIES: int = int(os.environ.get("HEALTH_CACHE_MAX_ENTRIES", "100"))

# -- WebSocket Broadcast Configuration -----------------------------------------
#
# Interval between health status broadcasts to connected WebSocket clients.
# Matches the health cache TTL so each broadcast reflects a fresh cache entry
# without issuing extra backend requests.
WS_BROADCAST_INTERVAL_SECONDS: float = float(
    os.environ.get("WS_BROADCAST_INTERVAL", "5.0")
)

# -- Rate Limiter Configuration ------------------------------------------------
#
# Login rate limiter settings for brute-force protection.
# Configurable via environment variables:
# - LOGIN_RATE_LIMIT_MAX_REQUESTS: maximum failed attempts (default: 5)
# - LOGIN_RATE_LIMIT_WINDOW_SECONDS: time window in seconds (default: 300)
LOGIN_RATE_LIMIT_MAX_REQUESTS: int = int(
    os.environ.get("LOGIN_RATE_LIMIT_MAX_REQUESTS", "5")
)
LOGIN_RATE_LIMIT_WINDOW_SECONDS: int = int(
    os.environ.get("LOGIN_RATE_LIMIT_WINDOW_SECONDS", "300")
)

# -- PC Agent Configuration ----------------------------------------------------
#
# Default MAC address for EgnalPC (Valheim server host).
# Configurable via EGNALPC_MAC environment variable.
# Used for Wake-on-LAN functionality.
EGNALPC_MAC: str = os.environ.get("EGNALPC_MAC", "04:7C:16:EB:72:4E")

# -- IP Address Constants ------------------------------------------------------
#
# Placeholder for unknown client IP addresses. Used when the IP cannot be
# determined from request headers (e.g., missing X-Forwarded-For behind proxy).
UNKNOWN_IP: str = "unknown"
