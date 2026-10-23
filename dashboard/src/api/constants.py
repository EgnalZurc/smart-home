"""Shared constants for the dashboard API.

Centralizes configuration values used across multiple modules to avoid
magic numbers and ensure consistency.
"""

# ── Health Check Configuration ────────────────────────────────────────────────
#
# Time-to-live for cached health check results. Health checks are expensive
# (one HTTP request per service) and the dashboard polls frequently.
# This cache prevents hammering backend services while keeping status fresh.
HEALTH_CACHE_TTL_SECONDS: float = 5.0

# ── WebSocket Broadcast Configuration ─────────────────────────────────────────
#
# Interval between health status broadcasts to connected WebSocket clients.
# Matches the health cache TTL so each broadcast reflects a fresh cache entry
# without issuing extra backend requests.
WS_BROADCAST_INTERVAL_SECONDS: float = 5.0
