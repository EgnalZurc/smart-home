"""energy-monitor — Shelly EM power/energy time-series collector.

Infrastructure service (not user-facing, not stoppable; see design §1.2/§10).
Reached only through the backend proxy under ``/api/energy/*``. The browser
never talks to :8012 directly.

Stands up the FastAPI app, the SQLite store and the Shelly polling collector.
The collector (``collector.py``) polls every device in ``ENERGY_DEVICES`` and
persists power rollups + hourly energy snapshots; the alert engine and the full
read API (``/api/energy/power``, ``/consumption``, ``/summary``) arrive in later
tasks — their routes are stubbed here so the contract is visible and testable.

Endpoints (served on :8012):
  GET /health               → {online, service, db_ok, meter_online, ...}
  GET /api/health/energy     → health alias for the dashboard catalogue / CI
  GET /api/energy/current    → newest power per channel (live from the collector)

Thresholds and Configuration:
  Alert thresholds are configurable via environment variables (see config.py):
    - ENERGY_POWER_ALERT_W: Power spike threshold in watts (default: 3500W)
    - ENERGY_DAILY_KWH_ALERT: Daily energy budget in kWh (default: 20 kWh)
    - ENERGY_MONTHLY_KWH_ALERT: Monthly energy budget in kWh (default: 400 kWh)
  Set any threshold to 0 to disable that alert rule.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from config import LOG_LEVEL, PORT, SERVICE_NAME
from fastapi import FastAPI, HTTPException, Query, Request, Response
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

# Shared libs live at /app/libs in the container; add to path for imports.
_LIBS_PATH: str = os.environ.get("LIBS_PATH", "/app/libs")
if _LIBS_PATH not in sys.path:
    sys.path.insert(0, _LIBS_PATH)

from alerts import AlertEngine  # noqa: E402
from collector import Collector  # noqa: E402
from database import VALID_PERIODS  # noqa: E402

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
_logger: logging.Logger = logging.getLogger(__name__)

# ── Rate limiting ─────────────────────────────────────────────────────────────
limiter: Limiter = Limiter(key_func=get_remote_address)


async def _rate_limit_exceeded_handler(
    request: Request, exc: RateLimitExceeded
) -> Response:
    """Handle rate limit exceeded errors with logging and proper response.

    Logs the rate limit violation for security monitoring and abuse detection,
    then returns a 429 response with Retry-After header.

    Args:
        request: The incoming HTTP request that exceeded the rate limit.
        exc: The RateLimitExceeded exception containing violation details.

    Returns:
        A 429 Too Many Requests response with Retry-After header set to 60s.
    """
    client_ip: str = get_remote_address(request) or "unknown"
    _logger.warning(
        "Rate limit exceeded for IP %s on %s %s: %s",
        client_ip,
        request.method,
        request.url.path,
        exc.detail,
    )
    return Response(
        content=f"Rate limit exceeded: {exc.detail}",
        status_code=429,
        headers={"Retry-After": "60"},
    )


# ── Security headers middleware ───────────────────────────────────────────────
async def security_headers_middleware(request: Request, call_next: Any) -> Response:
    """Add security headers to all HTTP responses.

    Applies standard security headers to mitigate common web vulnerabilities:
    - X-Content-Type-Options: Prevents MIME-type sniffing
    - X-Frame-Options: Prevents clickjacking via iframe embedding
    - Content-Security-Policy: Restricts resource loading sources
    - X-XSS-Protection: Legacy XSS filter (for older browsers)
    - Referrer-Policy: Controls referrer information leakage

    Args:
        request: The incoming HTTP request.
        call_next: The next middleware or route handler in the chain.

    Returns:
        The response with security headers added.
    """
    response: Response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = "default-src 'self'"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


# ── Input validation constants (private) ──────────────────────────────────────
_MAX_CHANNEL_LEN: int = 64
_CHANNEL_PATTERN: re.Pattern[str] = re.compile(r"^[a-zA-Z0-9_:\-]+$")

# Single collector instance for the process lifetime. It owns the SQLite store,
# the per-channel ring buffer and the Shelly poll loops.
# Note: Kept module-level for test access; internal helpers are prefixed with _.
collector: Collector = Collector()
alert_engine: AlertEngine = AlertEngine(collector.store)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage application lifecycle: start and stop background tasks.

    Initializes the database connection on startup and manages the collector's
    background polling tasks. On shutdown, gracefully stops all background tasks.

    Args:
        app: The FastAPI application instance.

    Yields:
        Control to the application during its runtime.

    Note:
        Database initialization errors are logged but don't prevent startup,
        allowing the health endpoint to report db_ok=false.
    """
    _logger.info("Starting %s...", SERVICE_NAME)
    # Touch the DB so the schema is created eagerly (surfaces a bad bind mount
    # as db_ok=false at the first health check rather than on first write).
    try:
        collector.store.count()
    except (OSError, RuntimeError) as exc:  # pragma: no cover - defensive startup log
        _logger.warning("Initial DB touch failed: %s", exc)
    await collector.start()
    _logger.info("%s started successfully", SERVICE_NAME)
    yield
    _logger.info("Shutting down %s...", SERVICE_NAME)
    await collector.stop()
    _logger.info("%s shutdown complete", SERVICE_NAME)


app: FastAPI = FastAPI(
    title="Energy Monitor",
    description="Shelly EM power/energy time-series collector",
    version="0.1.0",
    docs_url="/swagger",
    redoc_url="/redoc",
    lifespan=_lifespan,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.middleware("http")(security_headers_middleware)


# ═══════════════════════════════════════════════════════════════════════════════
# Health (internal helpers)
# ═══════════════════════════════════════════════════════════════════════════════
def _db_ok() -> bool:
    """Check if the SQLite store is operational.

    Performs a trivial query against the database to verify connectivity
    and basic functionality.

    Returns:
        True if the database responds successfully, False otherwise.

    Note:
        Failures are logged at WARNING level for operational visibility.
    """
    try:
        collector.store.count()
        return True
    except (OSError, RuntimeError) as exc:  # pragma: no cover - defensive
        _logger.warning("DB health check failed: %s", exc)
        return False


def _health_payload() -> dict[str, Any]:
    """Build the health check response payload.

    Constructs a dictionary containing service health information including
    database status and collector/meter liveness indicators.

    Returns:
        A dictionary with keys:
        - online: Always True if the endpoint responds
        - service: The service name identifier
        - db_ok: Whether the SQLite store is operational
        - meter_online: Whether at least one device has answered a poll
        - collector_last_tick_age_s: Seconds since the last poll cycle

    Note:
        Sensitive configuration values (DB_PATH, device credentials) are
        intentionally not exposed in the response.
    """
    return {
        "online": True,
        "service": SERVICE_NAME,
        "db_ok": _db_ok(),
        "meter_online": collector.meter_online,
        "collector_last_tick_age_s": collector.last_tick_age_s(),
    }


@app.get("/health")
@limiter.limit("60/minute")
async def health(request: Request) -> dict[str, Any]:
    """Health check endpoint.

    Exercises the database and reports collector/meter liveness status.
    Used by orchestration systems (Docker, Kubernetes) and monitoring tools.

    Args:
        request: The incoming HTTP request.

    Returns:
        Health status dictionary with db_ok, meter_online, and timing info.
    """
    return _health_payload()


@app.get("/api/health/energy")
@limiter.limit("60/minute")
async def health_alias(request: Request) -> dict[str, Any]:
    """Health check alias at the dashboard/CI expected path.

    Provides the same health information as /health but at the path
    expected by the dashboard service catalog and CI verification.

    Args:
        request: The incoming HTTP request.

    Returns:
        Health status dictionary identical to /health endpoint.
    """
    return _health_payload()


# ═══════════════════════════════════════════════════════════════════════════════
# Input validation (internal helpers)
# ═══════════════════════════════════════════════════════════════════════════════
def _validate_channel(channel: str | None) -> str | None:
    """Validate and sanitize a channel parameter.

    Ensures the channel identifier meets format requirements to prevent
    injection attacks and invalid queries.

    Args:
        channel: The channel identifier to validate, or None.

    Returns:
        The validated channel string, or None if input was None/empty/whitespace.

    Raises:
        HTTPException: 422 if channel exceeds max length or contains
            invalid characters (only alphanumeric, underscore, colon,
            and dash are allowed).
    """
    if channel is None:
        return None
    channel = channel.strip()
    if not channel:
        return None
    if len(channel) > _MAX_CHANNEL_LEN:
        raise HTTPException(
            status_code=422,
            detail=f"channel must be at most {_MAX_CHANNEL_LEN} characters",
        )
    if not _CHANNEL_PATTERN.match(channel):
        raise HTTPException(
            status_code=422,
            detail="channel must contain only alphanumeric, underscore, colon, or dash",
        )
    return channel


# ═══════════════════════════════════════════════════════════════════════════════
# Energy read API
# ═══════════════════════════════════════════════════════════════════════════════
@app.get("/api/energy/current")
@limiter.limit("120/minute")
async def get_current(request: Request) -> dict[str, Any]:
    """Get the most recent power reading for each channel.

    Returns live data from the collector's ring buffer. Before the first
    successful poll or with no devices configured, the channels dict is empty.

    Args:
        request: The incoming HTTP request.

    Returns:
        Dictionary containing:
        - total_w: Sum of power across all channels
        - channels: Dict mapping channel IDs to their latest readings
        - meter_online: Whether the collector has received data from devices
        - ts: Unix timestamp of the reading
    """
    return collector.current()


@app.get("/api/energy/history")
@limiter.limit("60/minute")
async def get_history(
    request: Request,
    period: str = Query("day", description="Aggregation period"),
    count: int = Query(24, ge=1, le=1000, description="Number of periods"),
    channel: str | None = Query(
        None, description="Channel id, or omit for whole-home total"
    ),
) -> dict[str, Any]:
    """Get historical consumption data aggregated by time period.

    Returns consumption per period derived from the cumulative kWh counter.
    Buckets are calendar-aligned (UTC) and returned oldest to newest.

    Args:
        request: The incoming HTTP request.
        period: Aggregation period - one of 'hour', 'day', 'week', 'month'.
        count: Number of periods to return (1-1000).
        channel: Specific channel ID, or None for whole-home total.

    Returns:
        Dictionary containing:
        - period: The aggregation period used
        - channel: The channel filter (or None for whole-home)
        - count: Number of data points returned
        - series: List of consumption records with timestamps

    Raises:
        HTTPException: 422 if period is invalid or channel format is wrong.
    """
    if period not in VALID_PERIODS:
        raise HTTPException(
            status_code=422,
            detail=f"period must be one of {list(VALID_PERIODS)}",
        )
    validated_channel: str | None = _validate_channel(channel)
    series: list[dict[str, float | int | None]] = collector.store.consumption_by_period(
        period, count, channel=validated_channel
    )
    return {
        "period": period,
        "channel": validated_channel,
        "count": len(series),
        "series": series,
    }


@app.get("/api/energy/stats")
@limiter.limit("60/minute")
async def get_stats(request: Request) -> dict[str, float | int | None]:
    """Get month-to-date consumption statistics.

    Returns aggregate statistics for the current calendar month including
    total consumption, daily averages, and peak values.

    Args:
        request: The incoming HTTP request.

    Returns:
        Dictionary containing:
        - month_start: Start date of the current month
        - days_elapsed: Number of days with data
        - total_kwh: Total consumption this month (or None if insufficient data)
        - avg_daily_kwh: Average daily consumption
        - peak_daily_kwh: Highest single-day consumption
        - peak_power_w: Highest instantaneous power recorded
    """
    return collector.store.stats()


@app.get("/api/energy/alerts")
@limiter.limit("60/minute")
async def get_alerts(
    request: Request,
    limit: int = Query(50, ge=1, le=500, description="Max events to return"),
) -> dict[str, Any]:
    """Get recent consumption alert events.

    Returns the most recent alert events (newest first) from the alert
    audit trail. Alerts are triggered by threshold violations.

    Args:
        request: The incoming HTTP request.
        limit: Maximum number of events to return (1-500).

    Returns:
        Dictionary containing:
        - count: Number of events returned
        - alerts: List of alert event records
    """
    events: list[dict[str, object]] = collector.store.recent_alerts(limit)
    return {"count": len(events), "alerts": events}


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)  # noqa: S104  # nosec B104
