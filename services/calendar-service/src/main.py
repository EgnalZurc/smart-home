"""calendar-service — Google Calendar sync, dashboard agenda + Telegram reminders.

Scaffold (Task 8.2): FastAPI app with the health endpoint wired to the real
DB-aware checks the design calls for, plus the read-API surface stubbed so the
contract and routing exist. The Google sync loop, reminder tick and prune loop
(design §4.1) land in later tasks — the lifespan currently just opens the store
and records startup time so the health probe is meaningful from day one.

Endpoints (served on :8014):
  GET /health                      → HealthResponse (db_ok, google_auth_ok, …)
  GET /api/health/calendar         → health alias for the dashboard catalogue/CI
  GET /api/calendar/upcoming       → next N events (widget 1)  [scaffold stub]
  GET /api/calendar/today          → today's agenda (widget 2) [scaffold stub]

All data endpoints are SUPER-gated at the backend proxy; the browser never
talks to :8014 directly (design §7).
"""

from __future__ import annotations

import logging
import os
import sys
import time
from contextlib import asynccontextmanager

from config import (
    LOG_LEVEL,
    PORT,
    SERVICE_NAME,
    TOKEN_PATH,
)
from fastapi import FastAPI, Query

# Shared libs live at /app/libs in the container; add to path for imports.
_LIBS_PATH = os.environ.get("LIBS_PATH", "/app/libs")
if _LIBS_PATH not in sys.path:
    sys.path.insert(0, _LIBS_PATH)

from database import CalendarStore  # noqa: E402
from models import HealthResponse  # noqa: E402

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Single store instance for the process lifetime.
store = CalendarStore()

# Module-level liveness markers. The sync loop / reminder tick (later tasks)
# update these; until then they stay None so the health probe honestly reports
# "no sync has run yet" rather than a fake-green value.
_last_sync_ts: float | None = None
_last_sync_ok: bool | None = None
_last_reminder_tick_ts: float | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Open the store on startup; background loops are added in later tasks."""
    logger.info("Starting %s...", SERVICE_NAME)
    # Touch the store so a broken bind-mount surfaces immediately as db_ok=false.
    try:
        store.count()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("initial store check failed: %s", exc)
    yield
    logger.info("Shutting down %s...", SERVICE_NAME)


app = FastAPI(
    title="Calendar Service",
    description="Google Calendar sync, dashboard agenda and Telegram reminders",
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


def _google_auth_ok() -> bool:
    """Return True if an OAuth refresh token is present.

    Scaffold: presence of ``token.json`` is a proxy for "authorized". A later
    task validates/refreshes the token and reports a true auth check so a
    revoked token turns the health step red (design §2.1, §11).
    """
    try:
        return os.path.exists(TOKEN_PATH)
    except OSError:  # pragma: no cover - defensive
        return False


def _age_s(ts: float | None) -> float | None:
    """Seconds since ``ts`` (monotonic), or None if never set."""
    if ts is None:
        return None
    return round(time.monotonic() - ts, 1)


def _health_payload() -> HealthResponse:
    """Build the health response exercising DB + auth + loop liveness."""
    return HealthResponse(
        online=True,
        service=SERVICE_NAME,
        db_ok=_db_ok(),
        google_auth_ok=_google_auth_ok(),
        last_sync_ok=_last_sync_ok,
        last_sync_age_s=_age_s(_last_sync_ts),
        reminder_tick_age_s=_age_s(_last_reminder_tick_ts),
    )


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Health check — exercises the DB and reports auth + loop liveness."""
    return _health_payload()


@app.get("/api/health/calendar", response_model=HealthResponse)
async def health_alias() -> HealthResponse:
    """Health check alias — matches the path the dashboard/CI expect."""
    return _health_payload()


# ═══════════════════════════════════════════════════════════════════════════════
# Calendar read API (scaffold stubs — populated once the sync loop lands)
# ═══════════════════════════════════════════════════════════════════════════════
@app.get("/api/calendar/upcoming")
async def get_upcoming(
    limit: int = Query(5, ge=1, le=50, description="Max events to return"),
) -> dict:
    """Return the next ``limit`` upcoming events across enabled calendars.

    Reads from the local cache (never blocks on Google). Empty until the sync
    loop populates the store in a later task.
    """
    now = int(time.time())
    return {"ts": now, "events": store.upcoming(now=now, limit=limit)}


@app.get("/api/calendar/today")
async def get_today() -> dict:
    """Return today's agenda (local-tz day window), ordered by start time.

    Scaffold: returns the cached upcoming slice; the local-tz day-window filter
    lands with the sync loop in a later task.
    """
    now = int(time.time())
    return {"ts": now, "events": store.upcoming(now=now, limit=50)}


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)  # noqa: S104  # nosec B104
