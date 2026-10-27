"""Pydantic models for calendar-service.

These describe the API contract (request/response shapes) and the domain
objects the sync loop and reminder engine pass around. Storage-neutral so a
second calendar provider could be added later.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# ── Event status ─────────────────────────────────────────────────────────────
# Mirrors the ``status`` column on the events table:
#   confirmed → a live event instance
#   cancelled → Google tombstone (status == "cancelled")
#   deleted   → soft-deleted locally (suppresses in-flight reminders)
EventStatus = str  # one of: "confirmed" | "cancelled" | "deleted"

# Reminder-rule scope: most specific enabled rule wins (person > calendar > global).
ReminderScope = str  # one of: "global" | "calendar" | "person"


class Calendar(BaseModel):
    """A Google calendar the service tracks."""

    id: str = Field(
        ..., description="Google calendarId, e.g. 'x@group.calendar.google.com'"
    )
    label: str = Field(..., description="Display name, e.g. 'Familia'")
    person_id: str | None = Field(
        None, description="Optional owner slug (reminder routing)"
    )
    colour: str | None = Field(None, description="Hex colour for the dashboard dot")
    enabled: bool = Field(
        True, description="Only enabled calendars are synced/surfaced"
    )


class CalendarEvent(BaseModel):
    """A cached calendar event instance.

    Recurring events are already expanded into concrete instances by Google
    (``singleEvents=true``), so every instance has a distinct ``start_ts`` and
    its own stable ``uid``. Timestamps are unix epoch (UTC); the frontend
    formats to the local timezone. All-day events use local-midnight boundaries.
    """

    uid: str = Field(..., description="Stable key '<calendar_id>:<event_id>:<start>'")
    calendar_id: str = Field(..., description="Owning calendar id")
    google_id: str = Field(..., description="Google event id (shared across instances)")
    title: str = Field(..., description="Event summary/title")
    description: str | None = Field(None, description="Event description")
    location: str | None = Field(None, description="Event location")
    start_ts: int = Field(
        ..., description="Start, unix epoch (UTC); all-day → local midnight"
    )
    end_ts: int = Field(..., description="End, unix epoch (UTC)")
    all_day: bool = Field(False, description="True for all-day events")
    person_id: str | None = Field(None, description="Resolved person association")
    status: EventStatus = Field(
        "confirmed", description="confirmed | cancelled | deleted"
    )


class ReminderRule(BaseModel):
    """A reminder offset rule.

    Offsets are data, not code: ``offset_s`` is seconds before an event's start
    at which to remind (1800 = 30 min, 3600 = 1 h, 86400 = 1 day). ``scope``
    narrows the rule to a calendar or person; ``global`` applies to every event.
    """

    id: int | None = Field(None, description="Autoincrement id (None before insert)")
    scope: ReminderScope = Field("global", description="global | calendar | person")
    scope_id: str | None = Field(
        None, description="calendar_id or person_id (null for global)"
    )
    offset_s: int = Field(..., description="Seconds before start to remind")
    enabled: bool = Field(True, description="Whether the rule is active")


class Reminder(BaseModel):
    """A reminder that is due (or was sent) for a specific event occurrence.

    The ``(event_uid, offset_s, event_start)`` triple is the deduplication key:
    a reminder fires exactly once per event occurrence per offset, even across
    restarts or overlapping ticks. ``sent_ts`` / ``ok`` are set once the Telegram
    send is attempted; before that they are ``None``.
    """

    event_uid: str = Field(..., description="Event this reminder is for")
    offset_s: int = Field(
        ..., description="Offset that triggered it (seconds before start)"
    )
    event_start: int = Field(
        ..., description="The event start the reminder is for (dedup key)"
    )
    sent_ts: int | None = Field(
        None, description="When the send was attempted (unix epoch)"
    )
    ok: bool | None = Field(None, description="Whether Telegram delivery succeeded")


class HealthResponse(BaseModel):
    """Health payload for the /health endpoint.

    Surfaces the real failure signals so a silently-broken deployment is visible:
    a revoked OAuth token, a stalled sync loop, an unwritable DB or a dead
    reminder tick each turn the dashboard health step red.
    """

    online: bool = Field(True, description="Service is running")
    service: str = Field(..., description="Service name")
    db_ok: bool = Field(..., description="SQLite store answers a trivial query")
    google_auth_ok: bool = Field(
        False, description="OAuth refresh token present/valid (false until configured)"
    )
    last_sync_ok: bool | None = Field(None, description="Last Google sync succeeded")
    last_sync_age_s: float | None = Field(
        None, description="Seconds since last successful sync"
    )
    reminder_tick_age_s: float | None = Field(
        None, description="Seconds since last reminder tick"
    )
