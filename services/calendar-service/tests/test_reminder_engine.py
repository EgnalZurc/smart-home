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
