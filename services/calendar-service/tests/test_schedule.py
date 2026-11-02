"""Tests for the daily-summary scheduling helper and sync-interval config.

Regression coverage for a latent crash: _seconds_until_next_summary used
``target.replace(day=target.day + 1)`` to roll to "tomorrow". On the last day
of a month that raises ``ValueError: day is out of range for month``, and the
daily-summary thread only catches DB/OS errors, so the summary loop would die
permanently. It now adds a ``timedelta(days=1)`` instead.
"""

from __future__ import annotations

import importlib
from datetime import datetime

import main
from config import LOCAL_TZ


class _FrozenDatetime(datetime):
    """datetime subclass whose now() returns a fixed instant (for freezing)."""

    _frozen: datetime

    @classmethod
    def now(cls, tz=None):  # type: ignore[override]
        return cls._frozen if tz is None else cls._frozen.astimezone(tz)


def _freeze(monkeypatch, instant: datetime) -> None:
    _FrozenDatetime._frozen = instant
    monkeypatch.setattr(main, "datetime", _FrozenDatetime)


class TestSecondsUntilNextSummary:
    def test_month_end_evening_does_not_crash(self, monkeypatch):
        """Oct 31 23:00, summary hour 03:00 already passed → tomorrow, no crash."""
        monkeypatch.setattr(main, "DAILY_SUMMARY_HOUR", 3)
        now = datetime(2026, 10, 31, 23, 0, 0, tzinfo=LOCAL_TZ)
        _freeze(monkeypatch, now)

        secs = main._seconds_until_next_summary()

        # Next summary is Nov 1 at 03:00 → 4 hours away.
        assert secs == 4 * 3600

    def test_day_before_target_schedules_today(self, monkeypatch):
        """Before the summary hour → scheduled for later the same day."""
        monkeypatch.setattr(main, "DAILY_SUMMARY_HOUR", 3)
        now = datetime(2026, 11, 2, 1, 0, 0, tzinfo=LOCAL_TZ)
        _freeze(monkeypatch, now)

        secs = main._seconds_until_next_summary()

        # 02:00 → 03:00 today = 2 hours.
        assert secs == 2 * 3600

    def test_year_end_rolls_over(self, monkeypatch):
        """Dec 31 23:00 rolls into the next year without error."""
        monkeypatch.setattr(main, "DAILY_SUMMARY_HOUR", 3)
        now = datetime(2026, 12, 31, 23, 0, 0, tzinfo=LOCAL_TZ)
        _freeze(monkeypatch, now)

        secs = main._seconds_until_next_summary()

        assert secs == 4 * 3600


class TestSyncIntervalConfig:
    def test_s_suffixed_name_takes_precedence(self, monkeypatch):
        monkeypatch.setenv("CALENDAR_SYNC_INTERVAL_S", "450")
        monkeypatch.setenv("CALENDAR_SYNC_INTERVAL", "300")
        import config

        importlib.reload(config)
        try:
            assert config.SYNC_INTERVAL_S == 450
        finally:
            monkeypatch.delenv("CALENDAR_SYNC_INTERVAL_S", raising=False)
            monkeypatch.delenv("CALENDAR_SYNC_INTERVAL", raising=False)
            importlib.reload(config)

    def test_legacy_unsuffixed_name_honoured(self, monkeypatch):
        """The legacy CALENDAR_SYNC_INTERVAL (compose) is no longer ignored."""
        monkeypatch.delenv("CALENDAR_SYNC_INTERVAL_S", raising=False)
        monkeypatch.setenv("CALENDAR_SYNC_INTERVAL", "300")
        import config

        importlib.reload(config)
        try:
            assert config.SYNC_INTERVAL_S == 300
        finally:
            monkeypatch.delenv("CALENDAR_SYNC_INTERVAL", raising=False)
            importlib.reload(config)

    def test_default_when_neither_set(self, monkeypatch):
        monkeypatch.delenv("CALENDAR_SYNC_INTERVAL_S", raising=False)
        monkeypatch.delenv("CALENDAR_SYNC_INTERVAL", raising=False)
        import config

        importlib.reload(config)
        assert config.SYNC_INTERVAL_S == 600
