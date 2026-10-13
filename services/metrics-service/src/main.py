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
import sys
import time
from contextlib import asynccontextmanager

from config import DB_PATH, LOG_LEVEL, PORT, SERVICE_NAME
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

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
