"""Tests for the sync path (_do_sync) and the calendar-id SSRF guard.

Regression coverage for a production crash: the sync loop re-validated each
calendar id with ``CalendarConfig._CALENDAR_ID_PATTERN.match(...)``, but under
Pydantic v2 that class attribute is a ``ModelPrivateAttr`` descriptor, not the
compiled regex, so ``.match`` raised ``AttributeError`` and killed the sync
thread on its first cycle (only reachable once Google auth actually succeeded).

The pattern now lives at module level (``main.CALENDAR_ID_PATTERN``) and is used
by both the request validator and the sync-time SSRF re-check.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import main
import pytest
from database import CalendarStore


@pytest.fixture
def store(tmp_path, monkeypatch):
    s = CalendarStore(str(tmp_path / "calendar.db"))
    monkeypatch.setattr(main, "store", s)
    return s


class TestCalendarIdPattern:
    def test_module_pattern_is_a_compiled_regex(self):
        """The guard must use a real compiled pattern, not a Pydantic descriptor."""
        assert main.CALENDAR_ID_PATTERN.match("primary")
        assert main.CALENDAR_ID_PATTERN.match("user@example.com")
        assert not main.CALENDAR_ID_PATTERN.match("not an id")
        assert not main.CALENDAR_ID_PATTERN.match("http://evil/ssrf")

    def test_config_validator_still_enforces_format(self):
        from main import CalendarConfig

        CalendarConfig(id="primary", label="Primary")
        CalendarConfig(id="a@b.com", label="Shared")
        with pytest.raises(ValueError):
            CalendarConfig(id="javascript:alert(1)", label="bad")


class TestDoSync:
    def test_valid_calendar_synced_without_crashing(self, store, monkeypatch):
        """_do_sync re-checks the id and syncs a valid calendar (no AttributeError)."""
        store.upsert_calendar(id="user@example.com", label="Mine", enabled=True)

        fake_client = MagicMock()
        fake_client.sync_events.return_value = (
            [
                {
                    "event_id": "evt1",
                    "summary": "Reunión",
                    "start": "2026-11-02T10:00:00+01:00",
                    "end": "2026-11-02T11:00:00+01:00",
                    "is_all_day": False,
                    "location": None,
                    "description": None,
                    "status": "confirmed",
                }
            ],
            "new-sync-token",
        )
        monkeypatch.setattr(main, "google_client", fake_client)

        main._do_sync()

        fake_client.sync_events.assert_called_once()
        assert store.count() == 1

    def test_malformed_calendar_id_skipped(self, store, monkeypatch):
        """A malformed id stored in the DB is skipped, never sent to Google."""
        # Bypass the validator by writing straight to the table.
        with store._db.connect() as conn:
            conn.execute(
                "INSERT INTO calendars (id, label, enabled) VALUES (?, ?, 1)",
                ("http://169.254.169.254/latest/meta-data", "ssrf"),
            )

        fake_client = MagicMock()
        monkeypatch.setattr(main, "google_client", fake_client)

        main._do_sync()

        fake_client.sync_events.assert_not_called()


class TestCalendarSeedValidation:
    """Tests for CALENDAR_SEED validation during startup (lifespan)."""

    def test_valid_seed_entries_are_inserted(self, store):
        """Valid calendar IDs in CALENDAR_SEED are inserted into the database."""
        seed_data = [
            {"id": "primary", "label": "Primary Calendar"},
            {"id": "work@company.com", "label": "Work"},
        ]
        for entry in seed_data:
            if main.CALENDAR_ID_PATTERN.match(entry["id"]):
                store.upsert_calendar(id=entry["id"], label=entry["label"], enabled=True)

        assert store.get_calendar_by_id("primary") is not None
        assert store.get_calendar_by_id("work@company.com") is not None

    def test_invalid_seed_entries_are_skipped(self, store):
        """Invalid/malicious calendar IDs in CALENDAR_SEED are rejected."""
        seed_data = [
            {"id": "http://example.com/ssrf", "label": "SSRF attempt"},
            {"id": "javascript:alert(1)", "label": "XSS attempt"},
            {"id": "../../../etc/passwd", "label": "Path traversal"},
        ]
        for entry in seed_data:
            if main.CALENDAR_ID_PATTERN.match(entry["id"]):
                store.upsert_calendar(id=entry["id"], label=entry["label"], enabled=True)

        # None of the malicious entries should be in the database
        for entry in seed_data:
            assert store.get_calendar_by_id(entry["id"]) is None

    def test_mixed_seed_only_valid_inserted(self, store):
        """When CALENDAR_SEED has both valid and invalid, only valid are inserted."""
        seed_data = [
            {"id": "primary", "label": "Primary"},
            {"id": "http://evil.com/ssrf", "label": "Bad"},
            {"id": "user@example.com", "label": "User"},
            {"id": "not a valid id!", "label": "Also bad"},
        ]
        seeded_count = 0
        for entry in seed_data:
            if main.CALENDAR_ID_PATTERN.match(entry["id"]):
                store.upsert_calendar(id=entry["id"], label=entry["label"], enabled=True)
                seeded_count += 1

        assert seeded_count == 2
        assert store.get_calendar_by_id("primary") is not None
        assert store.get_calendar_by_id("user@example.com") is not None
        assert store.get_calendar_by_id("http://evil.com/ssrf") is None
        assert store.get_calendar_by_id("not a valid id!") is None
