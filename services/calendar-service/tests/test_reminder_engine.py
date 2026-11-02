"""Tests for the reminder_engine module.

These test the rule priority logic, message formatting, and deduplication
without actually sending Telegram messages (using a mock notifier).
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest
from database import CalendarStore
from reminder_engine import (
    OFFSETS_DEFAULT,
    check_and_send_reminders,
    format_daily_summary,
    format_reminder_message,
    get_applicable_rules,
)


@pytest.fixture
def store(tmp_path):
    """Fresh CalendarStore on a temp DB."""
    return CalendarStore(str(tmp_path / "calendar.db"))


@pytest.fixture
def mock_notifier():
    """Mock TelegramNotifier that always succeeds."""
    notifier = MagicMock()
    result = MagicMock()
    result.success = True
    result.message = "Sent to 1 chat(s)"
    notifier.send.return_value = result
    notifier.enabled = True
    return notifier


class TestGetApplicableRules:
    def test_returns_defaults_when_no_rules(self, store):
        """No rules configured → use OFFSETS_DEFAULT."""
        event = {"calendar_id": "cal1", "person_id": None}
        offsets = get_applicable_rules(event, store)
        assert offsets == OFFSETS_DEFAULT

    def test_global_rules_override_defaults(self, store):
        """Global rules in DB override defaults."""
        store.add_rule("global", None, 3600)
        event = {"calendar_id": "cal1", "person_id": None}
        offsets = get_applicable_rules(event, store)
        assert offsets == [3600]

    def test_calendar_rules_override_global(self, store):
        """Calendar-specific rules take precedence over global."""
        store.add_rule("global", None, 3600)
        store.add_rule("calendar", "cal1", 1800)
        event = {"calendar_id": "cal1", "person_id": None}
        offsets = get_applicable_rules(event, store)
        assert offsets == [1800]  # Not [3600]

    def test_person_rules_override_calendar(self, store):
        """Person-specific rules take precedence over calendar and global."""
        store.add_rule("global", None, 3600)
        store.add_rule("calendar", "cal1", 1800)
        store.add_rule("person", "alice", 900)
        event = {"calendar_id": "cal1", "person_id": "alice"}
        offsets = get_applicable_rules(event, store)
        assert offsets == [900]  # Not [1800] or [3600]

    def test_disabled_rules_ignored(self, store):
        """Disabled rules are not returned."""
        # Add a rule, then disable it directly via SQL
        rule_id = store.add_rule("global", None, 3600)
        with store._db.connect() as conn:
            conn.execute(
                "UPDATE reminder_rules SET enabled = 0 WHERE id = ?", (rule_id,)
            )
        event = {"calendar_id": "cal1", "person_id": None}
        offsets = get_applicable_rules(event, store)
        assert offsets == OFFSETS_DEFAULT  # Falls back to defaults


class TestFormatReminderMessage:
    def test_basic_format(self):
        """Message includes emoji-prefixed title and time."""
        now = int(time.time())
        event = {
            "title": "Team standup",
            "start_ts": now + 1800,  # 30 min from now
            "location": None,
            "person_id": None,
            "calendar_id": "cal1",
        }
        msg = format_reminder_message(event, 1800, store=None, now=now)
        assert "🔔 Team standup" in msg
        assert "📅" in msg
        assert "Hoy" in msg

    def test_includes_location(self):
        """Location appears when present."""
        now = int(time.time())
        event = {
            "title": "Meeting",
            "start_ts": now + 3600,
            "location": "Sala A",
            "person_id": None,
            "calendar_id": "cal1",
        }
        msg = format_reminder_message(event, 3600, store=None, now=now)
        assert "📍 Sala A" in msg

    def test_includes_person(self):
        """Person ID appears when present."""
        now = int(time.time())
        event = {
            "title": "1:1",
            "start_ts": now + 3600,
            "location": None,
            "person_id": "alice",
            "calendar_id": "cal1",
        }
        msg = format_reminder_message(event, 3600, store=None, now=now)
        assert "👤 alice" in msg


class TestCheckAndSendReminders:
    def test_sends_due_reminder(self, store, mock_notifier):
        """A reminder is sent when fire_at <= now."""
        now = int(time.time())
        event_start = now + 1800  # 30 min from now
        # Add a global rule for 30-min reminder
        store.add_rule("global", None, 1800)
        # Add an event
        store.upsert_event(
            {
                "uid": "cal1:evt1:123",
                "calendar_id": "cal1",
                "google_id": "evt1",
                "title": "Test event",
                "start_ts": event_start,
                "end_ts": event_start + 3600,
            }
        )
        # fire_at = event_start - 1800 = now → should fire
        stats = check_and_send_reminders(store, mock_notifier, now=now)
        assert stats["sent"] == 1
        assert mock_notifier.send.called

    def test_skips_already_sent(self, store, mock_notifier):
        """Does not re-send a reminder that's already recorded."""
        now = int(time.time())
        event_start = now + 1800
        store.add_rule("global", None, 1800)
        store.upsert_event(
            {
                "uid": "cal1:evt1:123",
                "calendar_id": "cal1",
                "google_id": "evt1",
                "title": "Test event",
                "start_ts": event_start,
                "end_ts": event_start + 3600,
            }
        )
        # Pre-record the reminder as sent
        store.try_record_reminder("cal1:evt1:123", 1800, event_start)

        stats = check_and_send_reminders(store, mock_notifier, now=now)
        assert stats["sent"] == 0
        assert stats["skipped"] == 1
        assert not mock_notifier.send.called

    def test_skips_not_yet_due(self, store, mock_notifier):
        """Some offsets are not yet due while others fire immediately.

        With two rules (3600s and 900s) and an event 2000s from now:
        - 3600s offset: fire_at = now-1600 → past, fires immediately
        - 900s offset: fire_at = now+1100 → future, skipped
        """
        now = int(time.time())
        event_start = now + 2000
        store.add_rule("global", None, 3600)  # 1h offset → defines window
        store.add_rule("global", None, 900)  # 15 min offset → not due for this event
        store.upsert_event(
            {
                "uid": "cal1:evt1:123",
                "calendar_id": "cal1",
                "google_id": "evt1",
                "title": "Test event",
                "start_ts": event_start,
                "end_ts": event_start + 3600,
            }
        )
        stats = check_and_send_reminders(store, mock_notifier, now=now)
        # One offset is due (3600), one is not (900)
        assert stats["sent"] == 1
        assert stats["skipped"] == 1
        assert mock_notifier.send.call_count == 1


class TestFormatDailySummary:
    def test_empty_day(self):
        """No events produces the 'no events' message."""
        msg = format_daily_summary([], "30/10/2026", store=None)
        assert "📅 Eventos de hoy 30/10/2026:" in msg
        assert "No hay eventos programados para hoy" in msg

    def test_single_timed_event(self):
        """Single timed event is listed with time and title."""
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from config import TZ

        tz = ZoneInfo(TZ)
        event_dt = datetime(2026, 10, 30, 9, 0, 0, tzinfo=tz)
        events = [
            {
                "uid": "cal1:evt1",
                "calendar_id": "cal1",
                "google_id": "evt1",
                "title": "Morning standup",
                "start_ts": int(event_dt.timestamp()),
                "end_ts": int(event_dt.timestamp()) + 1800,
                "location": None,
                "all_day": False,
            }
        ]
        msg = format_daily_summary(events, "30/10/2026", store=None)
        assert "📅 Eventos de hoy 30/10/2026:" in msg
        assert "- 09:00 Morning standup" in msg
        assert "No hay eventos" not in msg

    def test_event_with_location(self):
        """Event with location shows the location line."""
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from config import TZ

        tz = ZoneInfo(TZ)
        event_dt = datetime(2026, 10, 30, 14, 30, 0, tzinfo=tz)
        events = [
            {
                "uid": "cal1:evt1",
                "calendar_id": "cal1",
                "google_id": "evt1",
                "title": "Team meeting",
                "start_ts": int(event_dt.timestamp()),
                "end_ts": int(event_dt.timestamp()) + 3600,
                "location": "Sala A",
                "all_day": False,
            }
        ]
        msg = format_daily_summary(events, "30/10/2026", store=None)
        assert "- 14:30 Team meeting" in msg
        assert "📍 Sala A" in msg

    def test_multiple_timed_events(self):
        """Multiple timed events are listed in order."""
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from config import TZ

        tz = ZoneInfo(TZ)
        events = [
            {
                "uid": "cal1:evt1",
                "calendar_id": "cal1",
                "google_id": "evt1",
                "title": "Morning coffee",
                "start_ts": int(datetime(2026, 10, 30, 8, 0, tzinfo=tz).timestamp()),
                "end_ts": int(datetime(2026, 10, 30, 8, 30, tzinfo=tz).timestamp()),
                "location": None,
                "all_day": False,
            },
            {
                "uid": "cal1:evt2",
                "calendar_id": "cal1",
                "google_id": "evt2",
                "title": "Lunch with team",
                "start_ts": int(datetime(2026, 10, 30, 13, 0, tzinfo=tz).timestamp()),
                "end_ts": int(datetime(2026, 10, 30, 14, 0, tzinfo=tz).timestamp()),
                "location": "Cafeteria",
                "all_day": False,
            },
        ]
        msg = format_daily_summary(events, "30/10/2026", store=None)
        assert "- 08:00 Morning coffee" in msg
        assert "- 13:00 Lunch with team" in msg
        assert "📍 Cafeteria" in msg
        # Check order (Morning before Lunch)
        assert msg.index("Morning coffee") < msg.index("Lunch with team")

    def test_all_day_event(self):
        """All-day event is shown with 🌅 emoji and no time."""
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from config import TZ

        tz = ZoneInfo(TZ)
        # All-day events have start_ts at midnight
        midnight = datetime(2026, 10, 30, 0, 0, 0, tzinfo=tz)
        events = [
            {
                "uid": "cal1:evt1",
                "calendar_id": "cal1",
                "google_id": "evt1",
                "title": "Cumpleaños de Juan",
                "start_ts": int(midnight.timestamp()),
                "end_ts": int(midnight.timestamp()) + 86400,
                "location": "Casa de Juan",
                "all_day": True,
            }
        ]
        msg = format_daily_summary(events, "30/10/2026", store=None)
        assert "🌅 Cumpleaños de Juan" in msg
        assert "📍 Casa de Juan" in msg
        # Should NOT have time format
        assert "00:00" not in msg
        assert "- " not in msg.split("🌅")[1].split("\n")[0]  # No bullet before title

    def test_all_day_events_shown_first(self):
        """All-day events appear before timed events."""
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from config import TZ

        tz = ZoneInfo(TZ)
        midnight = datetime(2026, 10, 30, 0, 0, 0, tzinfo=tz)
        events = [
            {
                "uid": "cal1:evt1",
                "calendar_id": "cal1",
                "google_id": "evt1",
                "title": "Reunión 9am",
                "start_ts": int(datetime(2026, 10, 30, 9, 0, tzinfo=tz).timestamp()),
                "end_ts": int(datetime(2026, 10, 30, 10, 0, tzinfo=tz).timestamp()),
                "location": None,
                "all_day": False,
            },
            {
                "uid": "cal1:evt2",
                "calendar_id": "cal1",
                "google_id": "evt2",
                "title": "Festivo Nacional",
                "start_ts": int(midnight.timestamp()),
                "end_ts": int(midnight.timestamp()) + 86400,
                "location": None,
                "all_day": True,
            },
        ]
        msg = format_daily_summary(events, "30/10/2026", store=None)
        # All-day event should come before timed event
        assert msg.index("Festivo Nacional") < msg.index("Reunión 9am")
        # Check format
        assert "🌅 Festivo Nacional" in msg
        assert "- 09:00 Reunión 9am" in msg

    def test_mixed_events_with_locations(self):
        """Mixed all-day and timed events with locations format correctly."""
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from config import TZ

        tz = ZoneInfo(TZ)
        midnight = datetime(2026, 10, 30, 0, 0, 0, tzinfo=tz)
        events = [
            {
                "uid": "cal1:evt1",
                "calendar_id": "cal1",
                "google_id": "evt1",
                "title": "Cumpleaños de Juan",
                "start_ts": int(midnight.timestamp()),
                "end_ts": int(midnight.timestamp()) + 86400,
                "location": "Casa de Juan",
                "all_day": True,
            },
            {
                "uid": "cal1:evt2",
                "calendar_id": "cal1",
                "google_id": "evt2",
                "title": "Reunión de equipo",
                "start_ts": int(datetime(2026, 10, 30, 9, 0, tzinfo=tz).timestamp()),
                "end_ts": int(datetime(2026, 10, 30, 10, 0, tzinfo=tz).timestamp()),
                "location": "Oficina",
                "all_day": False,
            },
            {
                "uid": "cal1:evt3",
                "calendar_id": "cal1",
                "google_id": "evt3",
                "title": "Dentista",
                "start_ts": int(datetime(2026, 10, 30, 14, 30, tzinfo=tz).timestamp()),
                "end_ts": int(datetime(2026, 10, 30, 15, 30, tzinfo=tz).timestamp()),
                "location": None,
                "all_day": False,
            },
        ]
        msg = format_daily_summary(events, "30/10/2026", store=None)

        # Verify structure matches the spec
        assert "🌅 Cumpleaños de Juan" in msg
        assert "📍 Casa de Juan" in msg
        assert "- 09:00 Reunión de equipo" in msg
        assert "📍 Oficina" in msg
        assert "- 14:30 Dentista" in msg

        # Order: all-day first, then timed by time
        assert msg.index("Cumpleaños") < msg.index("Reunión")
        assert msg.index("Reunión") < msg.index("Dentista")


class TestReportedBugScenarios:
    """Regression tests for the four reported calendar-service bugs.

    Scenario 1 & 4: events notified twice / "en 59 min" + "en 29 min" because
      more than one global offset was active (1800 and 3600). With a single
      [3600] offset exactly one reminder fires.
    Scenario 2: all-day birthdays fired a "before" reminder on the PREVIOUS day
      (offset before midnight lands the day before) — they must be skipped and
      appear only in the daily summary.
    Scenario 3: a single timed event rendered directly under an all-day event,
      reading as its sub-line — a blank line must separate the two groups.
    """

    def test_single_offset_fires_once(self, store, mock_notifier):
        """Scenario 1 & 4: with only the 1h rule, a timed event fires once."""
        now = int(time.time())
        event_start = now + 3600  # exactly 1h away
        store.add_rule("global", None, 3600)
        store.upsert_event(
            {
                "uid": "cal1:evt1",
                "calendar_id": "cal1",
                "google_id": "evt1",
                "title": "curso",
                "start_ts": event_start,
                "end_ts": event_start + 3600,
                "all_day": False,
            }
        )
        stats = check_and_send_reminders(store, mock_notifier, now=now)
        assert stats["sent"] == 1
        assert mock_notifier.send.call_count == 1

    def test_two_offsets_fire_twice_without_fix(self, store, mock_notifier):
        """Scenario 4 root cause: two active offsets => two notifications.

        Documents the behaviour the reconcile fix prevents: when both 3600 and
        1800 are active, a timed event is announced twice (at 1h and 30min).
        """
        now = int(time.time())
        event_start = now + 3600
        store.add_rule("global", None, 3600)
        store.add_rule("global", None, 1800)
        store.upsert_event(
            {
                "uid": "cal1:evt1",
                "calendar_id": "cal1",
                "google_id": "evt1",
                "title": "curso",
                "start_ts": event_start,
                "end_ts": event_start + 3600,
                "all_day": False,
            }
        )
        stats = check_and_send_reminders(store, mock_notifier, now=now)
        # 3600 fires now; 1800 is 30 min away, not yet due
        assert stats["sent"] == 1
        # Advance to 30 min before start: the second offset also fires
        stats2 = check_and_send_reminders(store, mock_notifier, now=event_start - 1800)
        assert stats2["sent"] == 1
        # Same event announced twice in total — the duplicate the user reported
        assert mock_notifier.send.call_count == 2

    def test_all_day_event_never_fires_before_reminder(self, store, mock_notifier):
        """Scenario 2: an all-day birthday must not fire a timed reminder.

        The birthday starts at local midnight; a 1h offset would land at 23:00
        the previous day. The engine must skip all-day events entirely.
        """
        now = int(time.time())
        midnight = now + 3600  # pretend "midnight" is 1h away
        store.add_rule("global", None, 3600)
        store.upsert_event(
            {
                "uid": "cal1:bday",
                "calendar_id": "cal1",
                "google_id": "bday",
                "title": "🎂 Eva Ariza",
                "start_ts": midnight,
                "end_ts": midnight + 86400,
                "all_day": True,
            }
        )
        stats = check_and_send_reminders(store, mock_notifier, now=now)
        assert stats["sent"] == 0
        assert not mock_notifier.send.called

    def test_timed_event_still_fires_when_all_day_present(self, store, mock_notifier):
        """A timed event is unaffected by the all-day skip on the same tick."""
        now = int(time.time())
        start = now + 3600
        store.add_rule("global", None, 3600)
        store.upsert_event(
            {
                "uid": "cal1:bday",
                "calendar_id": "cal1",
                "google_id": "bday",
                "title": "🎂 Eva Ariza",
                "start_ts": start,
                "end_ts": start + 86400,
                "all_day": True,
            }
        )
        store.upsert_event(
            {
                "uid": "cal1:curso",
                "calendar_id": "cal1",
                "google_id": "curso",
                "title": "curso",
                "start_ts": start,
                "end_ts": start + 3600,
                "all_day": False,
            }
        )
        stats = check_and_send_reminders(store, mock_notifier, now=now)
        assert stats["sent"] == 1
        assert mock_notifier.send.call_count == 1

    def test_summary_separates_all_day_from_timed(self):
        """Scenario 3: a blank line separates the all-day and timed blocks."""
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from config import TZ

        tz = ZoneInfo(TZ)
        midnight = datetime(2026, 10, 31, 0, 0, 0, tzinfo=tz)
        events = [
            {
                "uid": "cal1:bday",
                "calendar_id": "cal1",
                "google_id": "bday",
                "title": "🎂 Eva Ariza",
                "start_ts": int(midnight.timestamp()),
                "end_ts": int(midnight.timestamp()) + 86400,
                "location": None,
                "all_day": True,
            },
            {
                "uid": "cal1:curso",
                "calendar_id": "cal1",
                "google_id": "curso",
                "title": "curso",
                "start_ts": int(datetime(2026, 10, 31, 8, 0, tzinfo=tz).timestamp()),
                "end_ts": int(datetime(2026, 10, 31, 9, 0, tzinfo=tz).timestamp()),
                "location": None,
                "all_day": False,
            },
        ]
        msg = format_daily_summary(events, "31/10/2026", store=None)
        # The timed event line must not be glued to the all-day line.
        assert "🌅 🎂 Eva Ariza\n\n- 08:00 curso" in msg
        # Both events still present and distinct
        assert "🌅 🎂 Eva Ariza" in msg
        assert "- 08:00 curso" in msg
