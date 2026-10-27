"""Reminder engine for calendar-service.

Evaluates which reminders are due based on configured rules, formats human-friendly
Telegram messages with emojis, and sends them via TelegramNotifier with deduplication.

Priority order for reminder rules (most specific wins):
  1. person rules (scope="person", scope_id=person_id)
  2. calendar rules (scope="calendar", scope_id=calendar_id)
  3. global rules (scope="global")

If a more specific scope defines rules, those override the more general ones entirely
(not merged). This lets you silence reminders for one person while keeping defaults
for others.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import TYPE_CHECKING, TypedDict
from zoneinfo import ZoneInfo

from config import TZ

try:
    from smart_home_common.telegram import TelegramNotifier
except ImportError:  # pragma: no cover - import fallback outside the container
    import sys
    from pathlib import Path

    _repo_root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(_repo_root / "libs" / "smart_home_common" / "src"))
    from smart_home_common.telegram import TelegramNotifier

from database import CalendarStore

if TYPE_CHECKING:
    from database import EventRow


class ReminderStats(TypedDict):
    """Statistics from a reminder check run."""

    checked: int
    sent: int
    skipped: int
    failed: int


logger = logging.getLogger(__name__)

# Default offsets (seconds before event start): 1 day, 2 hours, 30 minutes
OFFSETS_DEFAULT = [86400, 7200, 1800]

# ── Localized strings (Spanish) ──────────────────────────────────────────────
# These could be moved to a config file or i18n system for multi-language support
MSG_TODAY = "Hoy"
MSG_TOMORROW = "Mañana"
MSG_IN_MINUTES = "en {minutes} min"
MSG_IN_HOURS = "en {hours}h"
MSG_NO_TITLE = "Evento sin título"
MONTH_NAMES = [
    "",
    "ene",
    "feb",
    "mar",
    "abr",
    "may",
    "jun",
    "jul",
    "ago",
    "sep",
    "oct",
    "nov",
    "dic",
]


def get_applicable_rules(
    event: EventRow,
    store: CalendarStore,
) -> list[int]:
    """Return the list of offset_s values applicable to this event.

    Priority: person > calendar > global. If a more specific scope has rules,
    only those rules apply (no merging with less specific scopes).

    Args:
        event: Event dict with at least calendar_id and optionally person_id.
        store: CalendarStore instance to query rules.

    Returns:
        List of offset_s integers (e.g. [86400, 7200, 1800]).
    """
    # Use the store's built-in priority logic
    rules = store.get_rules_for_event(event)
    if rules:
        return [r.offset_s for r in rules]

    # No rules configured → use defaults
    return OFFSETS_DEFAULT


def _format_relative_time(event_start: int, now: int, tz: ZoneInfo) -> str:
    """Format the event time as a human-readable string with relative context.

    Examples:
        - "Hoy 14:00 (en 30 min)"
        - "Mañana 10:00"
        - "15 oct 09:30"
    """
    now_dt = datetime.fromtimestamp(now, tz=tz)
    event_dt = datetime.fromtimestamp(event_start, tz=tz)

    time_str = event_dt.strftime("%H:%M")
    delta_s = event_start - now

    # Same calendar day
    if event_dt.date() == now_dt.date():
        if delta_s < 3600:
            minutes = max(1, delta_s // 60)
            return f"{MSG_TODAY} {time_str} ({MSG_IN_MINUTES.format(minutes=minutes)})"
        else:
            hours = delta_s // 3600
            return f"{MSG_TODAY} {time_str} ({MSG_IN_HOURS.format(hours=hours)})"

    # Tomorrow
    tomorrow = now_dt.date().toordinal() + 1
    if event_dt.date().toordinal() == tomorrow:
        return f"{MSG_TOMORROW} {time_str}"

    # Further out: "15 oct 09:30"
    day = event_dt.day
    month = MONTH_NAMES[event_dt.month]
    return f"{day} {month} {time_str}"


def format_reminder_message(
    event: EventRow,
    offset_s: int,
    store: CalendarStore | None = None,
    now: int | None = None,
) -> str:
    """Format a reminder message for Telegram with emojis.

    Args:
        event: Event dict with title, start_ts, location, person_id, calendar_id.
            Note: Uses .get() for safe access since the event may come from
            different query results with varying columns populated.
        offset_s: The offset (seconds before start) that triggered this reminder.
        store: Optional CalendarStore to look up calendar label and person name.
        now: Current timestamp (defaults to time.time()).

    Returns:
        Formatted string with emojis ready for Telegram.
    """
    now = int(time.time()) if now is None else now
    tz = ZoneInfo(TZ)

    lines = []

    # 🔔 Title
    title = event.get("title") or MSG_NO_TITLE
    lines.append(f"🔔 {title}")

    # 📅 Date/time with relative context
    start_ts = event.get("start_ts", now)
    time_str = _format_relative_time(start_ts, now, tz)
    lines.append(f"📅 {time_str}")

    # 📍 Location (if present)
    location = event.get("location")
    if location:
        lines.append(f"📍 {location}")

    # 👤 Person (if calendar has person_id and we can look up the name)
    person_id = event.get("person_id")
    if person_id:
        # For now just show the person_id; a future task can add people lookup
        lines.append(f"👤 {person_id}")

    # 📆 Calendar name (if >1 enabled calendar)
    if store:
        enabled_calendars = store.get_enabled_calendars()
        if len(enabled_calendars) > 1:
            calendar_id = event.get("calendar_id")
            if calendar_id:
                cal = store.get_calendar_by_id(calendar_id)
                if cal:
                    lines.append(f"📆 {cal.label}")

    return "\n".join(lines)


def check_and_send_reminders(
    store: CalendarStore,
    telegram_notifier: TelegramNotifier,
    now: int | None = None,
) -> ReminderStats:
    """Check for due reminders and send them.

    For each event in the reminder window:
      1. Get applicable rules (offsets)
      2. For each offset, calculate fire_at = start_ts - offset_s
      3. If fire_at <= now and not already sent, send and record

    Args:
        store: CalendarStore instance.
        telegram_notifier: TelegramNotifier instance for sending.
        now: Current timestamp (defaults to time.time()).

    Returns:
        Dict with counts: {"checked": N, "sent": M, "skipped": K, "failed": F}
    """
    now = int(time.time()) if now is None else now

    # Get all enabled rules to find the max offset (determines the window)
    all_rules = store.get_all_rules()
    if all_rules:
        max_offset = max(r.offset_s for r in all_rules)
    else:
        max_offset = max(OFFSETS_DEFAULT)

    # Get events in the reminder window
    events = store.get_events_in_reminder_window(now=now, max_offset_s=max_offset)

    stats = {"checked": 0, "sent": 0, "skipped": 0, "failed": 0}

    for event in events:
        offsets = get_applicable_rules(event, store)
        start_ts = event["start_ts"]
        event_uid = event["uid"]

        for offset_s in offsets:
            stats["checked"] += 1
            fire_at = start_ts - offset_s

            # Is it time to fire this reminder?
            if fire_at > now:
                # Not yet due
                stats["skipped"] += 1
                continue

            # Try to record in dedup ledger FIRST (atomic check-and-insert)
            # This also handles the case where another tick already sent it
            recorded = store.try_record_reminder(
                event_uid=event_uid,
                offset_s=offset_s,
                event_start=start_ts,
            )

            if not recorded:
                # Already sent (by this or previous tick)
                stats["skipped"] += 1
                continue

            # Format and send
            message = format_reminder_message(event, offset_s, store, now)
            result = telegram_notifier.send(message)

            if result.success:
                logger.info(
                    "Sent reminder for %s (offset=%ds): %s",
                    event_uid,
                    offset_s,
                    event.get("title", ""),
                )
                stats["sent"] += 1
            else:
                logger.warning(
                    "Failed to send reminder for %s: %s",
                    event_uid,
                    result.message,
                )
                stats["failed"] += 1

    if stats["sent"] or stats["failed"]:
        logger.info(
            "Reminder tick: checked=%d sent=%d skipped=%d failed=%d",
            stats["checked"],
            stats["sent"],
            stats["skipped"],
            stats["failed"],
        )

    return stats
