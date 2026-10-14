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
from collections import defaultdict
from contextlib import asynccontextmanager

from config import DB_PATH, LOG_LEVEL, PORT, SERVICE_NAME
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# ═══════════════════════════════════════════════════════════════════════════════
# Input validation (M-7)
# ═══════════════════════════════════════════════════════════════════════════════
_VALID_CONTAINER_NAME = re.compile(r"^[a-zA-Z0-9_-]+$")
_VALID_METRIC_NAME = re.compile(r"^[a-zA-Z0-9_.-]+$")


def _validate_container_name(name: str) -> bool:
    """Validate container name: alphanumeric, underscore, hyphen; max 64 chars."""
    return bool(name and len(name) <= 64 and _VALID_CONTAINER_NAME.match(name))


def _validate_metric_name(name: str) -> bool:
    """Validate metric name: alphanumeric, underscore, hyphen, dot; max 128 chars."""
    return bool(name and len(name) <= 128 and _VALID_METRIC_NAME.match(name))


# ═══════════════════════════════════════════════════════════════════════════════
# Rate limiting (M-8) — simple in-memory, per-IP
# ═══════════════════════════════════════════════════════════════════════════════
_rate_limit: dict[str, list[float]] = defaultdict(list)
MAX_REQUESTS_PER_MINUTE = 60


def _check_rate_limit(client_ip: str) -> bool:
    """Return True if request is allowed, False if rate-limited."""
    now = time.time()
    # Prune timestamps older than 60 seconds
    _rate_limit[client_ip] = [t for t in _rate_limit[client_ip] if now - t < 60]
    if len(_rate_limit[client_ip]) >= MAX_REQUESTS_PER_MINUTE:
        return False
    _rate_limit[client_ip].append(now)
    return True


def _get_client_ip(request: Request) -> str:
    """Extract client IP from request, respecting X-Forwarded-For if present."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        # Take the first IP in the chain (original client)
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# Shared libs live at /app/libs in the container; add to path for imports.
_LIBS_PATH = os.environ.get("LIBS_PATH", "/app/libs")
if _LIBS_PATH not in sys.path:
    sys.path.insert(0, _LIBS_PATH)

from collector import Collector  # noqa: E402

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Single collector instance for the process lifetime.
collector = Collector()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start/stop the collector background tasks with the app."""
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
async def rate_limit_middleware(request: Request, call_next):
    """Apply rate limiting to all endpoints except health checks."""
    # Skip rate limiting for health endpoints (needed for monitoring/CI)
    if request.url.path in ("/health", "/api/health/metrics"):
        return await call_next(request)

    client_ip = _get_client_ip(request)
    if not _check_rate_limit(client_ip):
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded. Try again later."},
        )

    return await call_next(request)


# ═══════════════════════════════════════════════════════════════════════════════
# Health
# ═══════════════════════════════════════════════════════════════════════════════
def _db_ok() -> bool:
    """Return True if the SQLite store answers a trivial query."""
    try:
        collector.store.count()
        return True
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("db health check failed: %s", exc)
        return False


def _health_payload() -> dict:
    """Build the health dict exercising DB + collector liveness."""
    return {
        "online": True,
        "service": SERVICE_NAME,
        "db_ok": _db_ok(),
        "collector_last_tick_age_s": collector.last_tick_age_s(),
        "db_path": DB_PATH,
    }


@app.get("/health")
async def health() -> dict:
    """Health check — exercises the DB and reports collector liveness."""
    return _health_payload()


@app.get("/api/health/metrics")
async def health_alias() -> dict:
    """Health check alias — matches the path expected by the dashboard/CI."""
    return _health_payload()


# ═══════════════════════════════════════════════════════════════════════════════
# Metrics read API
# ═══════════════════════════════════════════════════════════════════════════════
@app.get("/api/metrics/latest")
async def get_latest() -> dict:
    """Return the newest sample for every known series (from the ring buffer)."""
    return {"ts": int(time.time()), "series": collector.ring.latest()}


_WINDOW_SECONDS = {"1h": 3600, "24h": 86400, "7d": 604800, "30d": 2592000}


def _parse_since(since: str | None) -> int | None:
    """Parse a ``since`` query value.

    Accepts an absolute unix timestamp (e.g. ``1760368800``) or a relative
    offset like ``-1h`` / ``-30m`` / ``-7d``.
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
        mult = {"s": 1, "m": 60, "h": 3600, "d": 86400}.get(unit)
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
) -> dict:
    """Return one time-ranged series.

    ``resolution=hi`` reads the in-memory ring buffer (30 s points, last 2 h);
    ``resolution=rollup`` reads SQLite (5-min avg/max, 30-day history).
    """
    # Validate label if provided (may be container name)
    if label and not _validate_container_name(label):
        raise HTTPException(
            400,
            "Invalid label: must be alphanumeric, underscore, or hyphen (max 64 chars)",
        )

    # Validate metric name
    if not _validate_metric_name(metric):
        raise HTTPException(
            400,
            "Invalid metric: must be alphanumeric, underscore, hyphen, or dot (max 128 chars)",
        )

    since_ts = _parse_since(since)
    until_ts = _parse_since(until)

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
) -> dict:
    """Return min/avg/max per metric over a window (rollup-backed)."""
    seconds = _WINDOW_SECONDS[window]
    since_ts = int(time.time()) - seconds
    rows = collector.store.summary(since_ts)
    return {"window": window, "metrics": rows}


# ═══════════════════════════════════════════════════════════════════════════════
# Alerts API (Wave 3.3)
# ═══════════════════════════════════════════════════════════════════════════════
@app.get("/api/metrics/alerts")
async def get_alerts() -> dict:
    """Return the currently-firing alerts (anti-flap active set)."""
    return {
        "ts": int(time.time()),
        "active": collector.alert_engine.active_alerts(),
    }


@app.get("/api/metrics/alerts/history")
async def get_alerts_history(
    days: int = Query(7, ge=1, le=90, description="Look-back window in days"),
) -> dict:
    """Return the alert audit trail (fired/resolved events) for the last N days."""
    events = collector.alert_engine.store.history(days=days)
    return {"days": days, "count": len(events), "events": events}


@app.get("/api/metrics/thresholds")
async def get_thresholds() -> dict:
    """Return the current alert threshold rule set."""
    return {"thresholds": collector.alert_engine.get_thresholds()}


class ThresholdUpdate(BaseModel):
    """Runtime threshold patch.

    Maps rule key → fields to override, e.g.::

        {"updates": {"host_temp": {"value": 70, "critical_value": 78}}}
    """

    updates: dict[str, dict]


@app.put("/api/metrics/thresholds")
async def put_thresholds(payload: ThresholdUpdate) -> dict:
    """Patch alert thresholds at runtime (SUPER-gated at the proxy)."""
    try:
        updated = collector.alert_engine.set_thresholds(payload.updates)
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"thresholds": updated}


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)  # noqa: S104  # nosec B104
