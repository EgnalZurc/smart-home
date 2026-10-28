"""presence-service — fuses router/ARP, BLE and Zigbee-motion signals into a
per-person home/away/sleeping state and publishes it for automations.

See ``docs/designs/presence-service-design.md``. This is the SCAFFOLD: it wires
the FastAPI app, the DB-backed health endpoint and the lifespan hook. The
inference engine, MQTT handler, router poller and notifier are added in later
tasks; their background loops will be started from the lifespan below.

Endpoints (served on :8013):
  GET /health                  → {online, service, db_ok, router_online,
                                  mqtt_online, last_tick_age_s}
  GET /api/health/presence     → health alias for dashboard catalogue / CI
"""

from __future__ import annotations

import logging
import os
import sys
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from config import (
    DB_PATH,
    LOG_LEVEL,
    MAX_RATE_LIMIT_ENTRIES,
    MAX_REQUESTS_PER_MINUTE,
    PORT,
    RATE_LIMIT_WINDOW_S,
    SERVICE_NAME,
)
from database import PresenceStore
from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

# Shared libs live at /app/libs in the container; add to path for imports.
_LIBS_PATH: str = os.environ.get("LIBS_PATH", "/app/libs")
if _LIBS_PATH not in sys.path:
    sys.path.insert(0, _LIBS_PATH)

from smart_home_common.rate_limiter import InMemoryRateLimiter  # noqa: E402

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger: logging.Logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════════════════
UNKNOWN_CLIENT_IP: str = "unknown"  # Fallback when client IP cannot be determined

# ═══════════════════════════════════════════════════════════════════════════════
# Rate Limiting — protects health endpoints from DoS via request spam
# ═══════════════════════════════════════════════════════════════════════════════
rate_limiter: InMemoryRateLimiter = InMemoryRateLimiter(
    max_requests=MAX_REQUESTS_PER_MINUTE,
    window_seconds=RATE_LIMIT_WINDOW_S,
    max_entries=MAX_RATE_LIMIT_ENTRIES,
)


def _get_client_ip(request: Request) -> str:
    """Extract client IP from request, respecting X-Forwarded-For if present.

    Args:
        request: The FastAPI request object.

    Returns:
        The client IP address as a string, or "unknown" if not determinable.
    """
    forwarded: str | None = request.headers.get("x-forwarded-for")
    if forwarded:
        # Take the first IP in the chain (original client)
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else UNKNOWN_CLIENT_IP


# Single durable store for the process lifetime.
store: PresenceStore = PresenceStore(DB_PATH)

# Service start time, used as a liveness proxy until the engine tick loop exists.
_started_at: float = time.monotonic()


# ═══════════════════════════════════════════════════════════════════════════════
# Security Headers Middleware
# ═══════════════════════════════════════════════════════════════════════════════
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware that adds security headers to all HTTP responses.

    Adds the following headers to mitigate common web vulnerabilities:
    - X-Content-Type-Options: nosniff — prevents MIME-type sniffing
    - X-Frame-Options: DENY — prevents clickjacking via iframes
    - Content-Security-Policy: default-src 'self' — restricts resource loading
    - X-XSS-Protection: 1; mode=block — enables XSS filter (legacy browsers)
    - Referrer-Policy: strict-origin-when-cross-origin — limits referrer leakage
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Process the request and add security headers to the response.

        Args:
            request: The incoming HTTP request.
            call_next: The next middleware or route handler in the chain.

        Returns:
            The HTTP response with security headers added.
        """
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "default-src 'self'"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response


# ═══════════════════════════════════════════════════════════════════════════════
# Rate Limit Middleware
# ═══════════════════════════════════════════════════════════════════════════════
class RateLimitMiddleware(BaseHTTPMiddleware):
    """Middleware that applies rate limiting to all endpoints.

    Unlike other services that skip health endpoints, this service applies rate
    limiting to ALL endpoints including /health and /api/health/presence because
    they execute database queries (db_ok) on every call. Without rate limiting,
    an attacker could DoS the service by spamming health endpoints.

    Rate limit: 30 requests per minute per client IP (configurable via env vars).
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Apply rate limiting and process the request.

        Args:
            request: The incoming HTTP request.
            call_next: The next middleware or route handler in the chain.

        Returns:
            The HTTP response, or a 429 response if rate limit is exceeded.
        """
        client_ip: str = _get_client_ip(request)
        if not rate_limiter.is_allowed(client_ip):
            logger.warning(
                "Rate limit exceeded for IP %s on %s",
                client_ip,
                request.url.path,
            )
            return Response(
                content='{"detail":"Rate limit exceeded. Try again later."}',
                status_code=429,
                media_type="application/json",
            )
        return await call_next(request)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application startup and shutdown lifecycle.

    Start/stop background tasks with the app. Scaffold: no background loops yet.
    Later tasks start the router poll loop, the MQTT handler and the engine tick
    here, and stop them on shutdown.

    Args:
        app: The FastAPI application instance.

    Yields:
        None — control returns to the application during its lifetime.
    """
    logger.info("Starting %s on port %d...", SERVICE_NAME, PORT)
    yield
    logger.info("Shutting down %s gracefully...", SERVICE_NAME)


app: FastAPI = FastAPI(
    title="Presence Service",
    description="Multi-signal household presence detection (router + BLE + motion)",
    version="0.1.0",
    docs_url="/swagger",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Register security headers middleware.
app.add_middleware(SecurityHeadersMiddleware)

# Register rate limit middleware (applies to ALL endpoints including health).
app.add_middleware(RateLimitMiddleware)


# ═══════════════════════════════════════════════════════════════════════════════
# Health
# ═══════════════════════════════════════════════════════════════════════════════
def _last_tick_age_s() -> float | None:
    """Calculate seconds since the last engine tick.

    Scaffold: the engine tick loop does not exist yet, so this reports the
    service uptime as a liveness proxy. Replaced by the real tick age once the
    engine loop lands.

    Returns:
        The number of seconds since the service started (as a float rounded to
        one decimal place), or None if timing information is unavailable.
    """
    return round(time.monotonic() - _started_at, 1)


def _health_payload() -> dict[str, Any]:
    """Build the health check response payload.

    Exercises the database connection and reports source liveness status.
    ``router_online`` / ``mqtt_online`` are ``None`` in the scaffold (their
    collectors do not exist yet); once the sources land they report the real
    router-poll and broker-connection status so a dead source turns the health
    step red (design §11).

    Returns:
        A dictionary containing:
        - online: Always True if the service is responding
        - service: The service name identifier
        - db_ok: Whether the database is accessible and responding
        - router_online: Router connection status (None in scaffold)
        - mqtt_online: MQTT broker connection status (None in scaffold)
        - last_tick_age_s: Seconds since last engine tick (or uptime in scaffold)
        - db_path: Path to the SQLite database file
    """
    db_status: bool = store.db_ok()
    if not db_status:
        logger.warning("Health check: database is not responding at %s", DB_PATH)
    return {
        "online": True,
        "service": SERVICE_NAME,
        "db_ok": db_status,
        "router_online": None,
        "mqtt_online": None,
        "last_tick_age_s": _last_tick_age_s(),
        "db_path": DB_PATH,
    }


@app.get("/health")
async def health() -> dict[str, Any]:
    """Health check endpoint — exercises the DB and reports source liveness.

    Returns:
        A dictionary containing the service health status including database
        connectivity, source collector status, and timing information.
    """
    logger.debug("Health check requested")
    return _health_payload()


@app.get("/api/health/presence")
async def health_alias() -> dict[str, Any]:
    """Health check alias — matches the path expected by the dashboard/CI.

    This endpoint provides the same information as /health but at a path that
    conforms to the dashboard's service health catalogue routing convention.

    Returns:
        A dictionary containing the service health status (identical to /health).
    """
    logger.debug("Health alias check requested")
    return _health_payload()


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)  # noqa: S104  # nosec B104
