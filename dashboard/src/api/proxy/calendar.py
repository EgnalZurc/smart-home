"""Calendar service proxy routes.

Proxies requests to the calendar-service for Google Calendar sync
and reminder configuration. SUPER-only access.
"""

from fastapi import APIRouter, Request

from api.auth_helpers import require_super

from .base import ServiceProxy

router = APIRouter(prefix="/api/settings/calendar", tags=["Calendar Settings"])

_proxy = ServiceProxy("http://calendar-service:8014")


@router.get("/config")
async def get_calendar_config(request: Request):
    """Returns calendar configuration (sync interval, offsets, calendars, rules)."""
    require_super(request)
    return await _proxy.get("/api/calendar/config")


@router.post("/config")
async def post_calendar_config(request: Request):
    """Save calendar configuration."""
    require_super(request)
    body = await request.json()
    return await _proxy.post("/api/calendar/config", json=body)


@router.post("/sync")
async def trigger_calendar_sync(request: Request):
    """Trigger an immediate calendar sync."""
    require_super(request)
    return await _proxy.post("/api/calendar/sync")


@router.get("/today")
async def get_today_events(request: Request):
    """Get today's events."""
    require_super(request)
    return await _proxy.get("/api/calendar/today")
