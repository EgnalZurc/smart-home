"""metrics-service — Pi host, Docker and service-health time-series collector.

Infrastructure service (not user-facing, not in APP_CATALOGUE). Reached only
through the backend proxy under ``/api/metrics/*``.

Endpoints (served on :8011):
  GET /health                      → {online, service, db_ok, collector_last_tick_age_s}
  GET /api/health/metrics          → health alias for dashboard catalogue / CI
  GET /api/metrics/latest          → newest sample per series (ring buffer)
  GET /api/metrics/series          → one series, time-ranged (hi | rollup)
  GET /api/metrics/summary         → min/avg/max per metric over a window
"""

from __future__ import annotations

import logging
import os
import re
import sys
import time
from contextlib import asynccontextmanager
from typing import Any

from config import (
    DB_PATH,
    LOG_LEVEL,
    MAX_CONTAINER_NAME_LEN,
    MAX_METRIC_NAME_LEN,
    MAX_RATE_LIMIT_ENTRIES,
    MAX_REQUESTS_PER_MINUTE,
    PORT,
    RATE_LIMIT_WINDOW_S,
    SERVICE_NAME,
    SUMMARY_WINDOWS,
    TIME_OFFSET_MULTIPLIERS,
)
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# ═══════════════════════════════════════════════════════════════════════════════
# Input validation (M-7)
# ═══════════════════════════════════════════════════════════════════════════════
_VALID_CONTAINER_NAME: re.Pattern[str] = re.compile(r"^[a-zA-Z0-9_-]+$")
_VALID_METRIC_NAME: re.Pattern[str] = re.compile(r"^[a-zA-Z0-9_.-]+$")


def _validate_container_name(name: str) -> bool:
    """Validate container name: alphanumeric, underscore, hyphen.

    Args:
        name: The container name to validate.

    Returns:
        True if valid (non-empty, max length, matches pattern), False otherwise.
    """
    return bool(
        name
        and len(name) <= MAX_CONTAINER_NAME_LEN
        and _VALID_CONTAINER_NAME.match(name)
    )


def _validate_metric_name(name: str) -> bool:
    """Validate metric name: alphanumeric, underscore, hyphen, dot.

    Args:
        name: The metric name to validate.

    Returns:
        True if valid (non-empty, max length, matches pattern), False otherwise.
    """
    return bool(
        name and len(name) <= MAX_METRIC_NAME_LEN and _VALID_METRIC_NAME.match(name)
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Rate limiting (M-8) — using shared library InMemoryRateLimiter
# ═══════════════════════════════════════════════════════════════════════════════

# Shared libs live at /app/libs in the container; add to path for imports.
_LIBS_PATH = os.environ.get("LIBS_PATH", "/app/libs")
if _LIBS_PATH not in sys.path:
    sys.path.insert(0, _LIBS_PATH)

from collector import Collector  # noqa: E402
from smart_home_common.rate_limiter import InMemoryRateLimiter  # noqa: E402

# Rate limiter instance: configured via config.py with LRU eviction
rate_limiter = InMemoryRateLimiter(
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
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        # Take the first IP in the chain (original client)
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Single collector instance for the process lifetime.
collector = Collector()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start/stop the collector background tasks with the app.

    Args:
        app: The FastAPI application instance.

    Yields:
        Control to the application after starting the collector.
    """
    logger.info("Starting %s...", SERVICE_NAME)
    await collector.start()
    yield
    logger.info("Shutting down %s...", SERVICE_NAME)
    await collector.stop()


app = FastAPI(
    title="Metrics Service",
    description="Pi host, Docker and service-health time-series collector",
    version="1.0.0",
    docs_url="/swagger",
    redoc_url="/redoc",
    lifespan=lifespan,
)


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next) -> JSONResponse:
    """Apply rate limiting to all endpoints except health checks.

    Args:
        request: The incoming request.
        call_next: The next middleware/handler in the chain.

    Returns:
        The response from the next handler, or a 429 response if rate-limited.
    """
    # Skip rate limiting for health endpoints (needed for monitoring/CI)
    if request.url.path in ("/health", "/api/health/metrics"):
        return await call_next(request)

    client_ip = _get_client_ip(request)
    if not rate_limiter.is_allowed(client_ip):
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded. Try again later."},
        )

    return await call_next(request)


# ═══════════════════════════════════════════════════════════════════════════════
# Health
# ═══════════════════════════════════════════════════════════════════════════════
# Type alias for health payload structure
HealthPayload = dict[str, bool | str | float | None]


def _db_ok() -> bool:
    """Check if the SQLite store answers a trivial query.

    Returns:
        True if the database is accessible and responds to queries.
    """
    try:
        collector.store.count()
        return True
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("[HealthCheck] Database query failed: %s", exc)
        return False


def _health_payload() -> HealthPayload:
    """Build the health dict exercising DB + collector liveness.

    Returns:
        Dict containing online status, service name, db status,
        collector tick age, and database path.
    """
    return {
        "online": True,
        "service": SERVICE_NAME,
        "db_ok": _db_ok(),
        "collector_last_tick_age_s": collector.last_tick_age_s(),
        "db_path": DB_PATH,
    }


@app.get("/health")
async def health() -> HealthPayload:
    """Health check — exercises the DB and reports collector liveness.

    Returns:
        Health status payload with online, service, db_ok, and tick age.
    """
    return _health_payload()


@app.get("/api/health/metrics")
async def health_alias() -> HealthPayload:
    """Health check alias — matches the path expected by the dashboard/CI.

    Returns:
        Health status payload (same as /health).
    """
    return _health_payload()


# ═══════════════════════════════════════════════════════════════════════════════
# Metrics read API
# ═══════════════════════════════════════════════════════════════════════════════
# Type aliases for API responses
LatestResponse = dict[str, int | dict[str, dict[str, Any]]]
SeriesResponse = dict[str, str | list[dict[str, int | float]]]
SummaryResponse = dict[str, str | list[dict[str, Any]]]


@app.get("/api/metrics/latest")
async def get_latest() -> LatestResponse:
    """Return the newest sample for every known series (from the ring buffer).

    Returns:
        Dict with timestamp and series map of latest values.
    """
    return {"ts": int(time.time()), "series": collector.ring.latest()}


def _parse_since(since: str | None) -> int | None:
    """Parse a ``since`` query value.

    Accepts an absolute unix timestamp (e.g. ``1760368800``) or a relative
    offset like ``-1h`` / ``-30m`` / ``-7d``.

    Args:
        since: The since value to parse, or None.

    Returns:
        Unix timestamp as int, or None if input was None.

    Raises:
        HTTPException: If the since value is invalid.
    """
    if since is None:
        return None
    since = since.strip()
    if since.startswith("-"):
        unit = since[-1]
        try:
            amount = int(since[1:-1])
        except ValueError as exc:
            raise HTTPException(400, f"Invalid since offset: {since}") from exc
        mult = TIME_OFFSET_MULTIPLIERS.get(unit)
        if mult is None:
            raise HTTPException(400, f"Invalid since unit: {since}")
        return int(time.time()) - amount * mult
    try:
        return int(since)
    except ValueError as exc:
        raise HTTPException(400, f"Invalid since: {since}") from exc


@app.get("/api/metrics/series")
async def get_series(
    metric: str = Query(..., description="Metric name, e.g. host.ram.percent"),
    label: str = Query("", description="Series label (container/service key)"),
    since: str | None = Query(None, description="Unix ts or relative, e.g. -1h"),
    until: str | None = Query(None, description="Unix ts upper bound"),
    resolution: str = Query("hi", pattern="^(hi|rollup)$"),
) -> SeriesResponse:
    """Return one time-ranged series.

    ``resolution=hi`` reads the in-memory ring buffer (30 s points, last 2 h);
    ``resolution=rollup`` reads SQLite (5-min avg/max, 30-day history).

    Args:
        metric: Metric name to query.
        label: Series label (container/service key), empty for host metrics.
        since: Unix timestamp or relative offset (e.g. -1h) for lower bound.
        until: Unix timestamp or relative offset for upper bound.
        resolution: "hi" for ring buffer, "rollup" for SQLite.

    Returns:
        Dict containing metric, label, resolution, and list of points.

    Raises:
        HTTPException: If label or metric validation fails.
    """
    # Validate label if provided (may be container name)
    if label and not _validate_container_name(label):
        raise HTTPException(
            400,
            f"Invalid label: must be alphanumeric, underscore, or hyphen "
            f"(max {MAX_CONTAINER_NAME_LEN} chars)",
        )

    # Validate metric name
    if not _validate_metric_name(metric):
        raise HTTPException(
            400,
            f"Invalid metric: must be alphanumeric, underscore, hyphen, or dot "
            f"(max {MAX_METRIC_NAME_LEN} chars)",
        )

    since_ts = _parse_since(since)
    until_ts = _parse_since(until)

    points: list[dict[str, int | float]]
    if resolution == "hi":
        pts = collector.ring.series(metric, label, since=since_ts, until=until_ts)
        points = [{"ts": ts, "value": v} for (ts, v) in pts]
    else:
        points = collector.store.series(metric, label, since=since_ts, until=until_ts)

    return {
        "metric": metric,
        "label": label,
        "resolution": resolution,
        "points": points,
    }


@app.get("/api/metrics/summary")
async def get_summary(
    window: str = Query("24h", pattern="^(1h|24h|7d|30d)$"),
) -> SummaryResponse:
    """Return min/avg/max per metric over a window (rollup-backed).

    Args:
        window: Time window preset (1h, 24h, 7d, or 30d).

    Returns:
        Dict containing window and list of metric summaries.
    """
    seconds = SUMMARY_WINDOWS[window]
    since_ts = int(time.time()) - seconds
    rows = collector.store.summary(since_ts)
    return {"window": window, "metrics": rows}


# ═══════════════════════════════════════════════════════════════════════════════
# Alerts API (Wave 3.3)
# ═══════════════════════════════════════════════════════════════════════════════
# Type aliases for alerts API responses
AlertsResponse = dict[str, int | list[dict[str, Any]]]
AlertsHistoryResponse = dict[str, int | list[dict[str, Any]]]
ThresholdsResponse = dict[str, list[dict[str, Any]]]


@app.get("/api/metrics/alerts")
async def get_alerts() -> AlertsResponse:
    """Return the currently-firing alerts (anti-flap active set).

    Returns:
        Dict with timestamp and list of active alerts.
    """
    return {
        "ts": int(time.time()),
        "active": collector.alert_engine.active_alerts(),
    }


@app.get("/api/metrics/alerts/history")
async def get_alerts_history(
    days: int = Query(7, ge=1, le=90, description="Look-back window in days"),
) -> AlertsHistoryResponse:
    """Return the alert audit trail (fired/resolved events) for the last N days.

    Args:
        days: Number of days to look back (1-90).

    Returns:
        Dict containing days, count, and list of alert events.
    """
    events = collector.alert_engine.store.history(days=days)
    return {"days": days, "count": len(events), "events": events}


class DismissAlertRequest(BaseModel):
    """Request body for dismissing an alert."""

    fingerprint: str


@app.post("/api/metrics/alerts/dismiss")
async def dismiss_alert(body: DismissAlertRequest) -> dict[str, str]:
    """Manually dismiss an active alert by fingerprint.

    The alert is resolved as if the condition cleared naturally, with a
    'dismissed' event recorded in the history. If the underlying condition
    still breaches, the alert will re-fire on the next collector tick.

    Args:
        body: DismissAlertRequest containing the fingerprint to dismiss.

    Returns:
        Dict with status and fingerprint.

    Raises:
        HTTPException: 404 if the fingerprint is not found in active alerts.
    """
    if collector.alert_engine.dismiss_alert(body.fingerprint):
        return {"status": "dismissed", "fingerprint": body.fingerprint}
    raise HTTPException(status_code=404, detail="Alert not found or already resolved")


@app.get("/api/metrics/thresholds")
async def get_thresholds() -> ThresholdsResponse:
    """Return the current alert threshold rule set.

    Returns:
        Dict containing the list of threshold rules.
    """
    return {"thresholds": collector.alert_engine.get_thresholds()}


class ThresholdUpdate(BaseModel):
    """Runtime threshold patch.

    Maps rule key → fields to override, e.g.::

        {"updates": {"host_temp": {"value": 70, "critical_value": 78}}}

    Attributes:
        updates: Dict mapping rule keys to fields to override.
    """

    updates: dict[str, dict[str, float | int | bool | None]]


@app.put("/api/metrics/thresholds")
async def put_thresholds(payload: ThresholdUpdate) -> ThresholdsResponse:
    """Patch alert thresholds at runtime (SUPER-gated at the proxy).

    Args:
        payload: ThresholdUpdate containing the updates to apply.

    Returns:
        Dict containing the updated thresholds.

    Raises:
        HTTPException: If a rule key is unknown or a value is invalid.
    """
    try:
        updated = collector.alert_engine.set_thresholds(payload.updates)
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"thresholds": updated}


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)  # noqa: S104  # nosec B104
