"""energy-monitor — Shelly EM power/energy time-series collector (scaffold).

Infrastructure service (not user-facing, not stoppable; see design §1.2/§10).
Reached only through the backend proxy under ``/api/energy/*``. The browser
never talks to :8012 directly.

This is the *scaffold*: it stands up the FastAPI app, the SQLite store and the
health surface the dashboard/CI expect. The Shelly polling collector, the alert
engine and the full read API (``/api/energy/power``, ``/consumption``,
``/summary``) arrive in later tasks — their routes are stubbed here so the
contract is visible and testable.

Endpoints (served on :8012):
  GET /health               → {online, service, db_ok, meter_online, ...}
  GET /api/health/energy     → health alias for the dashboard catalogue / CI
  GET /api/energy/current    → newest power per channel (empty until collector)
"""

from __future__ import annotations

import logging
import os
import sys
import time
from contextlib import asynccontextmanager

from config import DB_PATH, LOG_LEVEL, PORT, SERVICE_NAME
from fastapi import FastAPI

# Shared libs live at /app/libs in the container; add to path for imports.
_LIBS_PATH = os.environ.get("LIBS_PATH", "/app/libs")
if _LIBS_PATH not in sys.path:
    sys.path.insert(0, _LIBS_PATH)

from database import EnergyStore  # noqa: E402

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Single store instance for the process lifetime. The collector (later task)
# will own the ring buffer and poll loop; the scaffold only needs the store so
# the health check can exercise the DB.
store = EnergyStore()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Open/close service resources with the app.

    The background collector is introduced in a later task; for the scaffold we
    just log start/stop and ensure the store (and its schema) is initialised.
    """
    logger.info("Starting %s...", SERVICE_NAME)
    # Touch the DB so the schema is created eagerly (surfaces a bad bind mount
    # as db_ok=false at the first health check rather than on first write).
    try:
        store.count()
    except Exception as exc:  # pragma: no cover - defensive startup log
        logger.warning("initial DB touch failed: %s", exc)
    yield
    logger.info("Shutting down %s...", SERVICE_NAME)


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
        store.count()
        return True
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("db health check failed: %s", exc)
        return False


def _health_payload() -> dict:
    """Build the health dict exercising DB liveness.

    ``meter_online`` and ``collector_last_tick_age_s`` are part of the design's
    health contract (§7/§10). Until the collector exists they report their
    "no data yet" values (``None``) so the shape is stable for the dashboard
    and CI, and turns informative automatically once polling is wired in.
    """
    return {
        "online": True,
        "service": SERVICE_NAME,
        "db_ok": _db_ok(),
        "meter_online": None,
        "collector_last_tick_age_s": None,
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

    Scaffold stub: with no collector running yet there are no live readings, so
    this returns an empty channel set. The full implementation (reading the
    ring buffer) lands with the collector task.
    """
    return {
        "ts": int(time.time()),
        "total_w": 0.0,
        "channels": {},
        "meter_online": None,
    }


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)  # noqa: S104  # nosec B104
