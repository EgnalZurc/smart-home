"""Tests for database.py CalendarStore methods.

Covers the methods that had TODO comments requesting tests:
- prune_old_reminders: retention-based cleanup of reminder records
- get_events_in_window: time-window event queries with boundary conditions
- clear_calendar_events: per-calendar event deletion
"""

from __future__ import annotations

import time

import pytest
from database import CalendarStore


@pytest.fixture
def store(tmp_path):
    """Create a fresh CalendarStore on a temp DB for each test."""
    return CalendarStore(str(tmp_path / "test.db"))


# ══════════════════════════════════════════════════════════════════════════════
# prune_old_reminders tests
# ══════════════════════════════════════════════════════════════════════════════
class TestPruneOldReminders:
    """Tests for prune_old_reminders method."""

    def test_deletes_records_older_than_retention(self, store):
        """Records older than retention_days are deleted."""
        now = int(time.time())
        retention_days = 30
        cutoff = now - retention_days * 24 * 3600

        # Insert a record older than retention (should be deleted)
        old_ts = cutoff - 86400  # 1 day before cutoff
        store.try_record_reminder("event:old", 1800, now)
        # Manually update sent_ts to make it old
        with store._db.connect() as conn:
            conn.execute(
                "UPDATE reminders_sent SET sent_ts = ? WHERE event_uid = ?",
                (old_ts, "event:old"),
            )

        # Insert a recent record (should be preserved)
        store.try_record_reminder("event:new", 1800, now + 3600)

        deleted = store.prune_old_reminders(retention_days=retention_days)
        assert deleted == 1

        # Verify old record is gone, new record remains
        with store._db.connect() as conn:
            rows = conn.execute("SELECT event_uid FROM reminders_sent").fetchall()
        uids = [r["event_uid"] for r in rows]
        assert "event:old" not in uids
        assert "event:new" in uids

    def test_preserves_records_within_retention(self, store):
        """Records within retention_days are preserved."""
        now = int(time.time())
        retention_days = 30

        # Insert records within retention window
        store.try_record_reminder("event:a", 1800, now)
        store.try_record_reminder("event:b", 3600, now + 100)

        deleted = store.prune_old_reminders(retention_days=retention_days)
        assert deleted == 0

        # Both should still exist
        with store._db.connect() as conn:
            count = conn.execute("SELECT COUNT(*) AS n FROM reminders_sent").fetchone()[
                "n"
            ]
        assert count == 2

    def test_empty_table_returns_zero(self, store):
        """Empty reminders_sent table returns 0."""
        deleted = store.prune_old_reminders(retention_days=30)
        assert deleted == 0


# ══════════════════════════════════════════════════════════════════════════════
# get_events_in_window tests
# ══════════════════════════════════════════════════════════════════════════════
class TestGetEventsInWindow:
    """Tests for get_events_in_window method."""

    def _make_event(self, store, uid, start_ts, end_ts, status="confirmed"):
        """Helper to insert an event."""
        store.upsert_event(
            {
                "uid": uid,
                "calendar_id": "test@cal",
                "google_id": uid.split(":")[1] if ":" in uid else uid,
                "title": f"Event {uid}",
                "start_ts": start_ts,
                "end_ts": end_ts,
                "status": status,
                "updated_ts": int(time.time()),
            }
        )

    def test_event_exactly_at_window_start(self, store):
        """Event starting exactly at window start is included."""
        window_start = 1000
        window_end = 2000
        self._make_event(store, "test:exact_start", start_ts=1000, end_ts=1500)

        events = store.get_events_in_window(window_start, window_end)
        uids = [e["uid"] for e in events]
        assert "test:exact_start" in uids

    def test_event_exactly_at_window_end(self, store):
        """Event ending exactly at window end is included."""
        window_start = 1000
        window_end = 2000
        self._make_event(store, "test:exact_end", start_ts=1500, end_ts=2000)

        events = store.get_events_in_window(window_start, window_end)
        uids = [e["uid"] for e in events]
        assert "test:exact_end" in uids

    def test_event_spanning_entire_window(self, store):
        """Event that spans the entire window is included."""
        window_start = 1000
        window_end = 2000
        self._make_event(store, "test:spanning", start_ts=500, end_ts=2500)

        events = store.get_events_in_window(window_start, window_end)
        uids = [e["uid"] for e in events]
        assert "test:spanning" in uids

    def test_event_partially_overlapping_starts_before(self, store):
        """Event that starts before window and ends during is included."""
        window_start = 1000
        window_end = 2000
        self._make_event(store, "test:starts_before", start_ts=500, end_ts=1500)

        events = store.get_events_in_window(window_start, window_end)
        uids = [e["uid"] for e in events]
        assert "test:starts_before" in uids

    def test_event_partially_overlapping_ends_after(self, store):
        """Event that starts during window and ends after is included."""
        window_start = 1000
        window_end = 2000
        self._make_event(store, "test:ends_after", start_ts=1500, end_ts=2500)

        events = store.get_events_in_window(window_start, window_end)
        uids = [e["uid"] for e in events]
        assert "test:ends_after" in uids

    def test_event_entirely_before_window_excluded(self, store):
        """Event that ends before window start is excluded."""
        window_start = 1000
        window_end = 2000
        self._make_event(store, "test:before", start_ts=100, end_ts=500)

        events = store.get_events_in_window(window_start, window_end)
        uids = [e["uid"] for e in events]
        assert "test:before" not in uids

    def test_event_entirely_after_window_excluded(self, store):
        """Event that starts after window end is excluded."""
        window_start = 1000
        window_end = 2000
        self._make_event(store, "test:after", start_ts=2500, end_ts=3000)

        events = store.get_events_in_window(window_start, window_end)
        uids = [e["uid"] for e in events]
        assert "test:after" not in uids

    def test_cancelled_events_excluded(self, store):
        """Cancelled events are not returned."""
        window_start = 1000
        window_end = 2000
        self._make_event(
            store, "test:cancelled", start_ts=1200, end_ts=1800, status="cancelled"
        )
        self._make_event(
            store, "test:confirmed", start_ts=1200, end_ts=1800, status="confirmed"
        )

        events = store.get_events_in_window(window_start, window_end)
        uids = [e["uid"] for e in events]
        assert "test:cancelled" not in uids
        assert "test:confirmed" in uids

    def test_tentative_events_included(self, store):
        """Tentative events from shared calendars are included."""
        window_start = 1000
        window_end = 2000
        self._make_event(
            store, "test:tentative", start_ts=1200, end_ts=1800, status="tentative"
        )

        events = store.get_events_in_window(window_start, window_end)
        uids = [e["uid"] for e in events]
        assert "test:tentative" in uids

    def test_empty_window_returns_empty_list(self, store):
        """No events in window returns empty list."""
        events = store.get_events_in_window(1000, 2000)
        assert events == []

    def test_event_ending_at_window_start_excluded(self, store):
        """An event whose exclusive end equals window start does not overlap.

        Reproduces the all-day duplicate bug: a Google all-day event's end is
        the exclusive start of the next day; that boundary must not make the
        event appear in the following day's window.
        """
        window_start = 1000
        window_end = 2000
        self._make_event(store, "test:ends_at_start", start_ts=500, end_ts=1000)

        events = store.get_events_in_window(window_start, window_end)
        uids = [e["uid"] for e in events]
        assert "test:ends_at_start" not in uids

    def test_all_day_event_not_duplicated_on_next_day(self, store):
        """All-day event defined on day D appears on D only, not D+1.

        Realistic case (reported bug): birthday on 2026-11-08 stored as an
        all-day event with exclusive end 2026-11-09 00:00:00 local time.
        """
        from datetime import datetime
        from zoneinfo import ZoneInfo

        tz = ZoneInfo("Europe/Madrid")
        day8_start = int(datetime(2026, 11, 8, 0, 0, 0, tzinfo=tz).timestamp())
        day8_end = int(datetime(2026, 11, 8, 23, 59, 59, tzinfo=tz).timestamp())
        day9_start = int(datetime(2026, 11, 9, 0, 0, 0, tzinfo=tz).timestamp())
        day9_end = int(datetime(2026, 11, 9, 23, 59, 59, tzinfo=tz).timestamp())

        # Google all-day: start = day date, end = next day (exclusive).
        store.upsert_event(
            {
                "uid": "bday:raul",
                "calendar_id": "birthdays@cal",
                "google_id": "raul",
                "title": "Cumpleaños Raúl García",
                "start_ts": day8_start,
                "end_ts": day9_start,  # exclusive boundary
                "all_day": True,
                "status": "confirmed",
                "updated_ts": int(time.time()),
            }
        )

        day8 = [e["uid"] for e in store.get_events_in_window(day8_start, day8_end)]
        day9 = [e["uid"] for e in store.get_events_in_window(day9_start, day9_end)]
        assert day8 == ["bday:raul"]
        assert day9 == []


# ══════════════════════════════════════════════════════════════════════════════
# clear_calendar_events tests
# ══════════════════════════════════════════════════════════════════════════════
class TestClearCalendarEvents:
    """Tests for clear_calendar_events method."""

    def _make_event(self, store, uid, calendar_id):
        """Helper to insert an event for a specific calendar."""
        store.upsert_event(
            {
                "uid": uid,
                "calendar_id": calendar_id,
                "google_id": uid.split(":")[1] if ":" in uid else uid,
                "title": f"Event {uid}",
                "start_ts": int(time.time()) + 3600,
                "end_ts": int(time.time()) + 7200,
                "status": "confirmed",
                "updated_ts": int(time.time()),
            }
        )

    def test_deletes_events_for_specified_calendar(self, store):
        """Events for the specified calendar_id are deleted."""
        self._make_event(store, "cal1:a", "calendar-1")
        self._make_event(store, "cal1:b", "calendar-1")

        deleted = store.clear_calendar_events("calendar-1")
        assert deleted == 2
        assert store.count() == 0

    def test_preserves_events_for_other_calendars(self, store):
        """Events for other calendars are preserved."""
        self._make_event(store, "cal1:a", "calendar-1")
        self._make_event(store, "cal2:b", "calendar-2")
        self._make_event(store, "cal2:c", "calendar-2")

        deleted = store.clear_calendar_events("calendar-1")
        assert deleted == 1
        assert store.count() == 2

        # Verify the right events remain
        with store._db.connect() as conn:
            rows = conn.execute("SELECT calendar_id FROM events").fetchall()
        cal_ids = [r["calendar_id"] for r in rows]
        assert all(c == "calendar-2" for c in cal_ids)

    def test_empty_calendar_returns_zero(self, store):
        """Calendar with no events returns 0."""
        deleted = store.clear_calendar_events("nonexistent-calendar")
        assert deleted == 0

    def test_clears_correct_calendar_among_many(self, store):
        """Correctly targets one calendar among several."""
        self._make_event(store, "cal1:a", "calendar-1")
        self._make_event(store, "cal2:b", "calendar-2")
        self._make_event(store, "cal3:c", "calendar-3")

        deleted = store.clear_calendar_events("calendar-2")
        assert deleted == 1
        assert store.count() == 2

        # Verify calendar-2 events are gone
        with store._db.connect() as conn:
            rows = conn.execute("SELECT calendar_id FROM events").fetchall()
        cal_ids = [r["calendar_id"] for r in rows]
        assert "calendar-2" not in cal_ids
        assert "calendar-1" in cal_ids
        assert "calendar-3" in cal_ids


# ══════════════════════════════════════════════════════════════════════════════
# reconcile_global_rules tests (Scenario 1 root cause)
# ══════════════════════════════════════════════════════════════════════════════
class TestReconcileGlobalRules:
    """reconcile_global_rules makes enabled global rules match the config set."""

    def _global_offsets(self, store):
        with store._db.connect() as conn:
            rows = conn.execute(
                "SELECT offset_s FROM reminder_rules "
                "WHERE scope = 'global' AND enabled = 1"
            ).fetchall()
        return sorted(r["offset_s"] for r in rows)

    def test_narrows_stale_seed_to_single_offset(self, store):
        """A DB seeded with [86400, 7200, 1800] is reduced to [3600]."""
        store.seed_default_rules(offsets=[86400, 7200, 1800])
        assert self._global_offsets(store) == [1800, 7200, 86400]

        changed = store.reconcile_global_rules([3600])
        assert changed is True
        assert self._global_offsets(store) == [3600]

    def test_noop_when_already_matching(self, store):
        """Reconcile is a no-op (returns False) when rules already match."""
        store.seed_default_rules(offsets=[3600])
        changed = store.reconcile_global_rules([3600])
        assert changed is False
        assert self._global_offsets(store) == [3600]

    def test_creates_rules_on_empty_db(self, store):
        """With no rules yet, reconcile installs the configured offsets."""
        changed = store.reconcile_global_rules([3600])
        assert changed is True
        assert self._global_offsets(store) == [3600]

    def test_leaves_scoped_rules_untouched(self, store):
        """Calendar/person-scoped overrides survive reconciliation."""
        store.seed_default_rules(offsets=[86400, 1800])
        store.add_rule("calendar", "cal1", 900)
        store.add_rule("person", "alice", 600)

        store.reconcile_global_rules([3600])

        assert self._global_offsets(store) == [3600]
        with store._db.connect() as conn:
            scoped = conn.execute(
                "SELECT scope, scope_id, offset_s FROM reminder_rules "
                "WHERE scope != 'global' ORDER BY scope"
            ).fetchall()
        rows = [(r["scope"], r["scope_id"], r["offset_s"]) for r in scoped]
        assert ("calendar", "cal1", 900) in rows
        assert ("person", "alice", 600) in rows

    def test_removes_stale_disabled_global_rows(self, store):
        """Disabled stale global rows are cleared, not left to resurface."""
        store.seed_default_rules(offsets=[86400, 3600])
        # Disable one rule directly
        with store._db.connect() as conn:
            conn.execute(
                "UPDATE reminder_rules SET enabled = 0 "
                "WHERE scope = 'global' AND offset_s = 86400"
            )
        store.reconcile_global_rules([3600])
        with store._db.connect() as conn:
            total = conn.execute(
                "SELECT COUNT(*) AS n FROM reminder_rules WHERE scope = 'global'"
            ).fetchone()["n"]
        # Exactly one global row (the configured 3600), no lingering disabled row
        assert total == 1
        assert self._global_offsets(store) == [3600]
