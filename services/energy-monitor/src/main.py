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
    """Return 429 with Retry-After header on rate limit breach."""
    return Response(
        content=f"Rate limit exceeded: {exc.detail}",
        status_code=429,
        headers={"Retry-After": "60"},
    )


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
    """Start/stop the collector background tasks with the app."""
    _logger.info("Starting %s...", SERVICE_NAME)
    # Touch the DB so the schema is created eagerly (surfaces a bad bind mount
    # as db_ok=false at the first health check rather than on first write).
    try:
        collector.store.count()
    except Exception as exc:  # pragma: no cover - defensive startup log
        _logger.warning("initial DB touch failed: %s", exc)
    await collector.start()
    yield
    _logger.info("Shutting down %s...", SERVICE_NAME)
    await collector.stop()


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


# ═══════════════════════════════════════════════════════════════════════════════
# Health (internal helpers)
# ═══════════════════════════════════════════════════════════════════════════════
def _db_ok() -> bool:
    """Return True if the SQLite store answers a trivial query."""
    try:
        collector.store.count()
        return True
    except Exception as exc:  # pragma: no cover - defensive
        _logger.warning("db health check failed: %s", exc)
        return False


def _health_payload() -> dict[str, Any]:
    """Build the health dict exercising DB + collector/meter liveness.

    ``meter_online`` is True once at least one device has answered a poll,
    ``collector_last_tick_age_s`` reports seconds since the last poll — both are
    part of the design's health contract (§7/§10).

    Note: Sensitive config values (DB_PATH, device credentials) are not exposed.
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
    """Health check — exercises the DB and reports collector/meter liveness."""
    return _health_payload()


@app.get("/api/health/energy")
@limiter.limit("60/minute")
async def health_alias(request: Request) -> dict[str, Any]:
    """Health check alias — matches the path expected by the dashboard/CI."""
    return _health_payload()


# ═══════════════════════════════════════════════════════════════════════════════
# Input validation (internal helpers)
# ═══════════════════════════════════════════════════════════════════════════════
def _validate_channel(channel: str | None) -> str | None:
    """Validate and sanitize channel parameter.

    Returns the channel if valid, raises HTTPException if malformed.
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
    """Return the newest power reading per channel.

    Served live from the collector's ring buffer. Before the first successful
    poll (or with no devices configured) ``channels`` is empty and
    ``meter_online`` reflects collector state.
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
    """Return consumption per period derived from the cumulative kWh counter.

    ``period`` must be one of ``hour``, ``day``, ``week``, ``month``. Buckets are
    calendar-aligned (UTC) and returned oldest → newest. A period with
    insufficient readings reports ``consumption_wh = null``.
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
    """Return month-to-date consumption statistics (whole-home total).

    Reports total, average daily, peak daily and peak instantaneous power for
    the current calendar month. Metrics are ``null`` until enough data exists.
    """
    return collector.store.stats()


@app.get("/api/energy/alerts")
@limiter.limit("60/minute")
async def get_alerts(
    request: Request,
    limit: int = Query(50, ge=1, le=500, description="Max events to return"),
) -> dict[str, Any]:
    """Return the most recent consumption-alert events (newest first)."""
    events: list[dict[str, object]] = collector.store.recent_alerts(limit)
    return {"count": len(events), "alerts": events}


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)  # noqa: S104  # nosec B104
