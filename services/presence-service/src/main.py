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

from config import DB_PATH, LOG_LEVEL, PORT, SERVICE_NAME
from database import PresenceStore
from fastapi import FastAPI

# Shared libs live at /app/libs in the container; add to path for imports.
_LIBS_PATH: str = os.environ.get("LIBS_PATH", "/app/libs")
if _LIBS_PATH not in sys.path:
    sys.path.insert(0, _LIBS_PATH)

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger: logging.Logger = logging.getLogger(__name__)

# Single durable store for the process lifetime.
store: PresenceStore = PresenceStore(DB_PATH)

# Service start time, used as a liveness proxy until the engine tick loop exists.
_started_at: float = time.monotonic()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Start/stop background tasks with the app.

    Scaffold: no background loops yet. Later tasks start the router poll loop,
    the MQTT handler and the engine tick here, and stop them on shutdown.
    """
    logger.info("Starting %s...", SERVICE_NAME)
    yield
    logger.info("Shutting down %s...", SERVICE_NAME)


app: FastAPI = FastAPI(
    title="Presence Service",
    description="Multi-signal household presence detection (router + BLE + motion)",
    version="0.1.0",
    docs_url="/swagger",
    redoc_url="/redoc",
    lifespan=lifespan,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Health
# ═══════════════════════════════════════════════════════════════════════════════
def _last_tick_age_s() -> float | None:
    """Seconds since the last engine tick.

    Scaffold: the engine tick loop does not exist yet, so this reports the
    service uptime as a liveness proxy. Replaced by the real tick age once the
    engine loop lands.
    """
    return round(time.monotonic() - _started_at, 1)


def _health_payload() -> dict[str, Any]:
    """Build the health dict exercising the DB and source liveness.

    ``router_online`` / ``mqtt_online`` are ``None`` in the scaffold (their
    collectors do not exist yet); once the sources land they report the real
    router-poll and broker-connection status so a dead source turns the health
    step red (design §11).
    """
    return {
        "online": True,
        "service": SERVICE_NAME,
        "db_ok": store.db_ok(),
        "router_online": None,
        "mqtt_online": None,
        "last_tick_age_s": _last_tick_age_s(),
        "db_path": DB_PATH,
    }


@app.get("/health")
async def health() -> dict[str, Any]:
    """Health check — exercises the DB and reports source liveness."""
    return _health_payload()


@app.get("/api/health/presence")
async def health_alias() -> dict[str, Any]:
    """Health check alias — matches the path expected by the dashboard/CI."""
    return _health_payload()


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)  # noqa: S104  # nosec B104
