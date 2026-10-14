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

from config import DB_PATH, LOG_LEVEL, PORT, SERVICE_NAME
from fastapi import FastAPI

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

# Single collector instance for the process lifetime. It owns the SQLite store,
# the per-channel ring buffer and the Shelly poll loops.
collector = Collector()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start/stop the collector background tasks with the app."""
    logger.info("Starting %s...", SERVICE_NAME)
    # Touch the DB so the schema is created eagerly (surfaces a bad bind mount
    # as db_ok=false at the first health check rather than on first write).
    try:
        collector.store.count()
    except Exception as exc:  # pragma: no cover - defensive startup log
        logger.warning("initial DB touch failed: %s", exc)
    await collector.start()
    yield
    logger.info("Shutting down %s...", SERVICE_NAME)
    await collector.stop()


app = FastAPI(
    title="Energy Monitor",
    description="Shelly EM power/energy time-series collector",
    version="0.1.0",
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
    """Build the health dict exercising DB + collector/meter liveness.

    ``meter_online`` is True once at least one device has answered a poll,
    ``collector_last_tick_age_s`` reports seconds since the last poll — both are
    part of the design's health contract (§7/§10).
    """
    return {
        "online": True,
        "service": SERVICE_NAME,
        "db_ok": _db_ok(),
        "meter_online": collector.meter_online,
        "collector_last_tick_age_s": collector.last_tick_age_s(),
        "db_path": DB_PATH,
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
    return collector.current()


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)  # noqa: S104  # nosec B104
