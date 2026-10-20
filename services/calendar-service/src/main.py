"""calendar-service — Google Calendar sync, dashboard agenda + Telegram reminders.

Endpoints (served on :8014):
  GET /health                      → HealthResponse
  GET /api/health/calendar         → health alias
  GET /api/calendar/upcoming       → next N events
  GET /api/calendar/today          → today's agenda
  POST /api/calendar/sync          → trigger manual sync
  GET /api/calendar/config         → get config (SUPER)
  POST /api/calendar/config        → update config (SUPER)
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import sys
import threading
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

from config import (
    CALENDAR_API_KEY,
    CALENDAR_AUTH_DISABLED,
    CALENDAR_SEED,
    DEFAULT_OFFSETS,
    GOOGLE_OAUTH_CLIENT_ID,
    GOOGLE_OAUTH_CLIENT_SECRET,
    LOG_LEVEL,
    NOTIFY_ENABLED,
    PORT,
    PRUNE_INTERVAL_S,
    REMINDER_TICK_S,
    SERVICE_NAME,
    SYNC_HORIZON_DAYS,
    SYNC_INTERVAL_S,
    TOKEN_PATH,
    TZ,
)
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.responses import JSONResponse

_LIBS_PATH = os.environ.get("LIBS_PATH", "/app/libs")
if _LIBS_PATH not in sys.path:
    sys.path.insert(0, _LIBS_PATH)

from database import CalendarStore  # noqa: E402
from models import HealthResponse  # noqa: E402
from reminder_engine import check_and_send_reminders  # noqa: E402

try:
    from google_sync import GoogleAuthError, GoogleCalendarClient
except ImportError:
    GoogleCalendarClient = None  # type: ignore[misc,assignment]
    GoogleAuthError = Exception  # type: ignore[misc,assignment]

try:
    from smart_home_common.telegram import TelegramNotifier
except ImportError:
    TelegramNotifier = None  # type: ignore[misc,assignment]

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# Rate limiting
# ═══════════════════════════════════════════════════════════════════════════════
limiter = Limiter(key_func=get_remote_address)


# ═══════════════════════════════════════════════════════════════════════════════
# Authentication
# ═══════════════════════════════════════════════════════════════════════════════
_bearer_scheme = HTTPBearer(auto_error=False)


async def require_api_key(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> None:
    """Dependency that enforces bearer token auth for protected endpoints.

    Auth is ENABLED by default. Set CALENDAR_AUTH_DISABLED=true to disable.
    If auth is enabled but CALENDAR_API_KEY is not configured, returns HTTP 500
    (fail-secure: do not expose protected endpoints without explicit key).
    """
    if CALENDAR_AUTH_DISABLED:
        # Auth explicitly disabled — allow request (dev mode)
        return
    if not CALENDAR_API_KEY:
        # Auth enabled but no key configured — fail-secure
        raise HTTPException(
            status_code=500,
            detail="CALENDAR_API_KEY not configured",
        )
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not hmac.compare_digest(
        credentials.credentials.encode(), CALENDAR_API_KEY.encode()
    ):
        raise HTTPException(
            status_code=403,
            detail="Invalid API key",
        )


store = CalendarStore()
google_client: GoogleCalendarClient | None = None
telegram_notifier: TelegramNotifier | None = None

_last_sync_ts: float | None = None
_last_sync_ok: bool | None = None
_last_reminder_tick_ts: float | None = None
_shutdown = threading.Event()


# ═══════════════════════════════════════════════════════════════════════════════
# Background loops
# ═══════════════════════════════════════════════════════════════════════════════
def _sync_loop() -> None:
    """Sync enabled calendars every SYNC_INTERVAL_S seconds."""
    global _last_sync_ts, _last_sync_ok
    logger.info("Sync loop started (interval=%ds)", SYNC_INTERVAL_S)

    while not _shutdown.is_set():
        try:
            if google_client is None:
                logger.debug("Sync skipped: Google client not initialized")
                _last_sync_ok = False
            else:
                _do_sync()
                _last_sync_ok = True
        except Exception as exc:
            logger.exception("Sync loop error: %s", exc)
            _last_sync_ok = False
        finally:
            _last_sync_ts = time.monotonic()
        _shutdown.wait(SYNC_INTERVAL_S)
    logger.info("Sync loop stopped")


def _do_sync() -> None:
    """Perform one sync cycle for all enabled calendars."""
    if google_client is None:
        return
    calendars = store.get_enabled_calendars()
    if not calendars:
        logger.info("No enabled calendars to sync")
        return

    now = int(time.time())
    horizon = now + SYNC_HORIZON_DAYS * 86400

    for cal in calendars:
        try:
            events, new_token = google_client.sync_events(
                calendar_id=cal.id,
                sync_token=cal.sync_token,
                time_min=datetime.fromtimestamp(now, tz=ZoneInfo("UTC")),
                time_max=datetime.fromtimestamp(horizon, tz=ZoneInfo("UTC")),
            )
            for ev in events:
                # google_sync returns event_id, summary, start/end as ISO strings
                event_id = ev.get("event_id", "")
                store.upsert_event(
                    {
                        "uid": f"{cal.id}:{event_id}",
                        "calendar_id": cal.id,
                        "google_id": event_id,
                        "title": ev.get("summary", "(no title)"),
                        "start_ts": _parse_event_time_str(ev.get("start")),
                        "end_ts": _parse_event_time_str(ev.get("end")),
                        "all_day": ev.get("is_all_day", False),
                        "location": ev.get("location"),
                        "description": ev.get("description"),
                        "person_id": None,
                        "status": ev.get("status", "confirmed"),
                        "etag": None,  # not returned by google_sync
                    }
                )
            if new_token:
                store.update_sync_token(cal.id, new_token)
            logger.info("Synced %d events from %s", len(events), cal.label)
        except Exception as exc:
            logger.error("Error syncing calendar %s: %s", cal.id, exc)


def _parse_event_time_str(time_str: str | None) -> int:
    """Parse ISO datetime or date string to Unix timestamp.

    google_sync returns start/end as ISO strings (e.g. '2026-10-15T10:00:00+02:00'
    or '2026-10-15' for all-day events).
    """
    if not time_str:
        return 0
    try:
        # Try ISO datetime first (timed events)
        if "T" in time_str:
            dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
            return int(dt.timestamp())
        # Fall back to date-only (all-day events)
        dt = datetime.strptime(time_str, "%Y-%m-%d")
        dt = dt.replace(tzinfo=ZoneInfo(TZ))
        return int(dt.timestamp())
    except (ValueError, TypeError):
        return 0


def _parse_event_time(time_obj: dict) -> int:
    """Parse Google Calendar time object to Unix timestamp."""
    if "dateTime" in time_obj:
        dt = datetime.fromisoformat(time_obj["dateTime"].replace("Z", "+00:00"))
        return int(dt.timestamp())
    elif "date" in time_obj:
        dt = datetime.strptime(time_obj["date"], "%Y-%m-%d")
        dt = dt.replace(tzinfo=ZoneInfo(TZ))
        return int(dt.timestamp())
    return 0


def _reminder_loop() -> None:
    """Check for due reminders every REMINDER_TICK_S seconds."""
    global _last_reminder_tick_ts
    logger.info("Reminder loop started (interval=%ds)", REMINDER_TICK_S)

    while not _shutdown.is_set():
        try:
            if NOTIFY_ENABLED and telegram_notifier:
                result = check_and_send_reminders(store, telegram_notifier)
                if result["sent"] > 0:
                    logger.info("Sent %d reminders", result["sent"])
        except Exception as exc:
            logger.exception("Reminder loop error: %s", exc)
        finally:
            _last_reminder_tick_ts = time.monotonic()
        _shutdown.wait(REMINDER_TICK_S)
    logger.info("Reminder loop stopped")


def _prune_loop() -> None:
    """Prune old data every PRUNE_INTERVAL_S seconds."""
    logger.info("Prune loop started (interval=%ds)", PRUNE_INTERVAL_S)

    while not _shutdown.is_set():
        try:
            store.prune()
            logger.debug("Prune completed")
        except Exception as exc:
            logger.exception("Prune loop error: %s", exc)
        _shutdown.wait(PRUNE_INTERVAL_S)
    logger.info("Prune loop stopped")


# ═══════════════════════════════════════════════════════════════════════════════
# Lifespan
# ═══════════════════════════════════════════════════════════════════════════════
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize clients and start background loops."""
    global google_client, telegram_notifier

    logger.info("Starting %s...", SERVICE_NAME)

    try:
        store.count()
    except Exception as exc:
        logger.warning("Initial store check failed: %s", exc)

    store.seed_default_rules(offsets=DEFAULT_OFFSETS)

    if CALENDAR_SEED:
        try:
            seed_cals = json.loads(CALENDAR_SEED)
            for cal in seed_cals:
                store.upsert_calendar(
                    id=cal["id"],
                    label=cal.get("label", cal["id"]),
                    person_id=cal.get("person_id"),
                    enabled=cal.get("enabled", True),
                )
            logger.info("Seeded %d calendars", len(seed_cals))
        except Exception as exc:
            logger.warning("Failed to parse CALENDAR_SEED: %s", exc)

    if (
        GOOGLE_OAUTH_CLIENT_ID
        and GOOGLE_OAUTH_CLIENT_SECRET
        and GoogleCalendarClient is not None
    ):
        try:
            google_client = GoogleCalendarClient(
                client_id=GOOGLE_OAUTH_CLIENT_ID,
                client_secret=GOOGLE_OAUTH_CLIENT_SECRET,
                token_path=TOKEN_PATH,
            )
            if google_client.authenticate():
                logger.info("Google Calendar client authenticated")
            else:
                logger.warning("Google Calendar authentication failed")
                google_client = None
        except GoogleAuthError as exc:
            logger.warning("Google auth error: %s", exc)
            google_client = None
    else:
        logger.info("Google OAuth credentials not configured")

    if TelegramNotifier is not None:
        try:
            telegram_notifier = TelegramNotifier.from_env()
            logger.info("Telegram notifier initialized")
        except Exception as exc:
            logger.warning("Telegram notifier not available: %s", exc)

    _shutdown.clear()
    threads = [
        threading.Thread(target=_sync_loop, daemon=True, name="sync-loop"),
        threading.Thread(target=_reminder_loop, daemon=True, name="reminder-loop"),
        threading.Thread(target=_prune_loop, daemon=True, name="prune-loop"),
    ]
    for t in threads:
        t.start()

    yield

    logger.info("Shutting down %s...", SERVICE_NAME)
    _shutdown.set()
    for t in threads:
        t.join(timeout=5)


app = FastAPI(
    title="Calendar Service",
    version="0.2.0",
    docs_url="/swagger",
    redoc_url="/redoc",
    lifespan=lifespan,
)
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_exceeded_handler(
    request: Request, exc: RateLimitExceeded
) -> JSONResponse:
    """Return 429 with Retry-After header when rate limit is exceeded."""
    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded"},
        headers={"Retry-After": "60"},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Health
# ═══════════════════════════════════════════════════════════════════════════════
def _db_ok() -> bool:
    try:
        store.count()
        return True
    except Exception as exc:
        logger.warning("DB health check failed: %s", exc)
        return False


def _google_auth_ok() -> bool:
    return google_client is not None


def _age_s(ts: float | None) -> float | None:
    if ts is None:
        return None
    return round(time.monotonic() - ts, 1)


def _health_payload() -> HealthResponse:
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
    return _health_payload()


@app.get("/api/health/calendar", response_model=HealthResponse)
async def health_alias() -> HealthResponse:
    return _health_payload()


# ═══════════════════════════════════════════════════════════════════════════════
# Calendar read API
# ═══════════════════════════════════════════════════════════════════════════════
@app.get("/api/calendar/upcoming")
@limiter.limit("60/minute")
async def get_upcoming(
    request: Request,
    limit: int = Query(5, ge=1, le=50),
) -> dict:
    """Return the next ``limit`` upcoming events."""
    now = int(time.time())
    return {"ts": now, "events": store.upcoming(now=now, limit=limit)}


@app.get("/api/calendar/today")
@limiter.limit("60/minute")
async def get_today(request: Request) -> dict:
    """Return today's agenda."""
    tz = ZoneInfo(TZ)
    now_dt = datetime.now(tz)
    start_of_day = now_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day.replace(hour=23, minute=59, second=59)
    events = store.get_events_in_window(
        int(start_of_day.timestamp()), int(end_of_day.timestamp())
    )
    return {"ts": int(time.time()), "date": now_dt.date().isoformat(), "events": events}


@app.post("/api/calendar/sync", dependencies=[Depends(require_api_key)])
@limiter.limit("10/minute")
async def trigger_sync(request: Request) -> dict:
    """Trigger an immediate sync."""
    if google_client is None:
        raise HTTPException(status_code=503, detail="Google client not initialized")
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _do_sync)
    return {"status": "sync_triggered"}


# ═══════════════════════════════════════════════════════════════════════════════
# Config API (SUPER only — gated at dashboard proxy)
# ═══════════════════════════════════════════════════════════════════════════════
class CalendarConfig(BaseModel):
    id: str
    label: str
    person_id: str | None = None
    enabled: bool = True


class RuleConfig(BaseModel):
    scope: str = "global"
    scope_id: str | None = None
    offset_s: int


class ConfigResponse(BaseModel):
    calendars: list[dict]
    rules: list[dict]
    default_offsets: list[int]
    sync_interval_s: int
    reminder_tick_s: int


class ConfigUpdate(BaseModel):
    calendars: list[CalendarConfig] | None = None
    add_rule: RuleConfig | None = None
    delete_rule_id: int | None = None


@app.get(
    "/api/calendar/config",
    response_model=ConfigResponse,
    dependencies=[Depends(require_api_key)],
)
async def get_config() -> ConfigResponse:
    """Get current configuration."""
    calendars = [c.to_dict() for c in store.get_all_calendars()]
    rules = [r.to_dict() for r in store.get_all_rules()]
    return ConfigResponse(
        calendars=calendars,
        rules=rules,
        default_offsets=DEFAULT_OFFSETS,
        sync_interval_s=SYNC_INTERVAL_S,
        reminder_tick_s=REMINDER_TICK_S,
    )


@app.post("/api/calendar/config", dependencies=[Depends(require_api_key)])
async def update_config(update: ConfigUpdate) -> dict:
    """Update configuration."""
    changes = []
    if update.calendars is not None:
        for cal in update.calendars:
            store.upsert_calendar(
                id=cal.id,
                label=cal.label,
                person_id=cal.person_id,
                enabled=cal.enabled,
            )
            changes.append(f"upserted calendar {cal.id}")
    if update.add_rule is not None:
        store.add_rule(
            scope=update.add_rule.scope,
            scope_id=update.add_rule.scope_id,
            offset_s=update.add_rule.offset_s,
        )
        changes.append(f"added rule {update.add_rule.offset_s}s")
    if update.delete_rule_id is not None:
        store.delete_rule(update.delete_rule_id)
        changes.append(f"deleted rule {update.delete_rule_id}")
    return {"status": "ok", "changes": changes}


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)  # noqa: S104  # nosec B104
