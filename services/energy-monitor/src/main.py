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
import sys
from contextlib import asynccontextmanager

from config import LOG_LEVEL, PORT, SERVICE_NAME
from fastapi import FastAPI, HTTPException, Query

# Shared libs live at /app/libs in the container; add to path for imports.
_LIBS_PATH = os.environ.get("LIBS_PATH", "/app/libs")
if _LIBS_PATH not in sys.path:
    sys.path.insert(0, _LIBS_PATH)

from alerts import AlertEngine  # noqa: E402
from collector import Collector  # noqa: E402
from database import VALID_PERIODS  # noqa: E402

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
_logger = logging.getLogger(__name__)

# Single collector instance for the process lifetime. It owns the SQLite store,
# the per-channel ring buffer and the Shelly poll loops.
_collector = Collector()
_alert_engine = AlertEngine(_collector.store)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Start/stop the collector background tasks with the app."""
    _logger.info("Starting %s...", SERVICE_NAME)
    # Touch the DB so the schema is created eagerly (surfaces a bad bind mount
    # as db_ok=false at the first health check rather than on first write).
    try:
        _collector.store.count()
    except Exception as exc:  # pragma: no cover - defensive startup log
        _logger.warning("initial DB touch failed: %s", exc)
    await _collector.start()
    yield
    _logger.info("Shutting down %s...", SERVICE_NAME)
    await _collector.stop()


app = FastAPI(
    title="Energy Monitor",
    description="Shelly EM power/energy time-series collector",
    version="0.1.0",
    docs_url="/swagger",
    redoc_url="/redoc",
    lifespan=_lifespan,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Health
# ═══════════════════════════════════════════════════════════════════════════════
def _db_ok() -> bool:
    """Return True if the SQLite store answers a trivial query."""
    try:
        _collector.store.count()
        return True
    except Exception as exc:  # pragma: no cover - defensive
        _logger.warning("db health check failed: %s", exc)
        return False


def _health_payload() -> dict:
    """Build the health dict exercising DB + collector/meter liveness.

    ``meter_online`` is True once at least one device has answered a poll,
    ``collector_last_tick_age_s`` reports seconds since the last poll — both are
    part of the design's health contract (§7/§10).

    Note: db_path is intentionally omitted to avoid exposing internal paths.
    """
    return {
        "online": True,
        "service": SERVICE_NAME,
        "db_ok": _db_ok(),
        "meter_online": _collector.meter_online,
        "collector_last_tick_age_s": _collector.last_tick_age_s(),
    }


@app.get("/health")
async def health() -> dict:
    """Health check — exercises the DB and reports collector/meter liveness."""
    return _health_payload()


@app.get("/api/health/energy")
async def health_alias() -> dict:
    """Health check alias — matches the path expected by the dashboard/CI."""
    return _health_payload()


# ═══════════════════════════════════════════════════════════════════════════════
# Energy read API (scaffold stub)
# ═══════════════════════════════════════════════════════════════════════════════
@app.get("/api/energy/current")
async def get_current() -> dict:
    """Return the newest power reading per channel.

    Served live from the collector's ring buffer. Before the first successful
    poll (or with no devices configured) ``channels`` is empty and
    ``meter_online`` reflects collector state.
    """
    return _collector.current()


@app.get("/api/energy/history")
async def get_history(
    period: str = Query("day", description="Aggregation period"),
    count: int = Query(24, ge=1, le=1000, description="Number of periods"),
    channel: str | None = Query(
        None, description="Channel id, or omit for whole-home total"
    ),
) -> dict:
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
    series = _collector.store.consumption_by_period(period, count, channel=channel)
    return {
        "period": period,
        "channel": channel,
        "count": len(series),
        "series": series,
    }


@app.get("/api/energy/stats")
async def get_stats() -> dict:
    """Return month-to-date consumption statistics (whole-home total).

    Reports total, average daily, peak daily and peak instantaneous power for
    the current calendar month. Metrics are ``null`` until enough data exists.
    """
    return _collector.store.stats()


@app.get("/api/energy/alerts")
async def get_alerts(
    limit: int = Query(50, ge=1, le=500, description="Max events to return"),
) -> dict:
    """Return the most recent consumption-alert events (newest first)."""
    events = _collector.store.recent_alerts(limit)
    return {"count": len(events), "alerts": events}


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)  # noqa: S104  # nosec B104
