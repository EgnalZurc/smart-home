"""Unit tests for the event_log module (ACEventLog).

Tests the SQLite-backed command event logging: persisting commands and
reading back the history window.
"""

import time

from event_log import ACEventLog


def _make_log(tmp_path):
    """Create an ACEventLog backed by a temp-dir database."""
    return ACEventLog(db_path=tmp_path / "ac_event_log.db")


class TestLogCommand:
    """Tests for ACEventLog.log_command."""

    def test_log_command_persists_entry(self, tmp_path):
        """A logged command appears in the history."""
        log = _make_log(tmp_path)

        assert log.log_command("control", {"mode": "auto"}, True) is True

        history = log.get_history(hours=24)
        assert len(history) == 1
        entry = history[0]
        assert entry["command_type"] == "control"
        assert entry["params"] == {"mode": "auto"}
        assert entry["success"] is True
        assert entry["error_msg"] is None
        assert isinstance(entry["timestamp"], float)

    def test_log_command_records_failure(self, tmp_path):
        """A failed command stores success=False and the error message."""
        log = _make_log(tmp_path)

        log.log_command("manual", {"mode": "cold"}, False, "invalid mode")

        entry = log.get_history()[0]
        assert entry["success"] is False
        assert entry["error_msg"] == "invalid mode"

    def test_log_command_none_params_stored_as_empty(self, tmp_path):
        """None params are stored as an empty object."""
        log = _make_log(tmp_path)

        log.log_command("control", None, True)

        assert log.get_history()[0]["params"] == {}

    def test_log_command_serialises_non_json_values(self, tmp_path):
        """Non-JSON-native values are coerced via str rather than raising."""
        log = _make_log(tmp_path)

        # A set is not JSON-serialisable; default=str must handle it.
        assert log.log_command("config", {"obj": {1, 2}}, True) is True
        assert len(log.get_history()) == 1

    def test_log_command_creates_db_file(self, tmp_path):
        """The database file is created on first write."""
        db_path = tmp_path / "nested" / "ac_event_log.db"
        log = ACEventLog(db_path=db_path)

        log.log_command("control", {"mode": "off"}, True)

        assert db_path.exists()

    def test_log_command_returns_false_on_error(self, tmp_path, monkeypatch):
        """A persistence error returns False without raising."""
        log = _make_log(tmp_path)

        def boom(*_args, **_kwargs):
            raise RuntimeError("db down")

        monkeypatch.setattr(log._db, "connect", boom)

        assert log.log_command("control", {"mode": "auto"}, True) is False


class TestGetHistory:
    """Tests for ACEventLog.get_history."""

    def test_get_history_empty_when_no_events(self, tmp_path):
        """An empty database yields an empty history."""
        log = _make_log(tmp_path)
        assert log.get_history() == []

    def test_get_history_newest_first(self, tmp_path):
        """Events are returned newest-first."""
        log = _make_log(tmp_path)

        log.log_command("control", {"n": 1}, True)
        time.sleep(0.01)
        log.log_command("control", {"n": 2}, True)

        history = log.get_history()
        assert [e["params"]["n"] for e in history] == [2, 1]

    def test_get_history_filters_by_window(self, tmp_path):
        """Events older than the window are excluded."""
        log = _make_log(tmp_path)

        # Insert an event with a timestamp 48h in the past directly.
        old_ts = time.time() - 48 * 3600
        with log._db.connect() as conn:
            conn.execute(
                """
                INSERT INTO command_events
                    (timestamp, command_type, params_json, success, error_msg)
                VALUES (?, ?, ?, ?, ?)
                """,
                (old_ts, "control", "{}", 1, None),
            )
        # And a recent one.
        log.log_command("control", {"recent": True}, True)

        history = log.get_history(hours=24)
        assert len(history) == 1
        assert history[0]["params"] == {"recent": True}

    def test_get_history_clamps_non_positive_hours(self, tmp_path):
        """hours <= 0 is clamped to a 1-hour window (no crash)."""
        log = _make_log(tmp_path)
        log.log_command("control", {"mode": "auto"}, True)

        # Should not raise and should still return the recent event.
        assert len(log.get_history(hours=0)) == 1
        assert len(log.get_history(hours=-5)) == 1

    def test_get_history_returns_empty_on_error(self, tmp_path, monkeypatch):
        """A read error returns an empty list instead of raising."""
        log = _make_log(tmp_path)
        log.log_command("control", {"mode": "auto"}, True)

        def boom(*_args, **_kwargs):
            raise RuntimeError("db down")

        monkeypatch.setattr(log._db, "connect", boom)

        assert log.get_history() == []

    def test_get_history_handles_corrupt_params_json(self, tmp_path):
        """A row with invalid params_json degrades to an empty params dict."""
        log = _make_log(tmp_path)
        with log._db.connect() as conn:
            conn.execute(
                """
                INSERT INTO command_events
                    (timestamp, command_type, params_json, success, error_msg)
                VALUES (?, ?, ?, ?, ?)
                """,
                (time.time(), "control", "not-json {{", 1, None),
            )

        entry = log.get_history()[0]
        assert entry["params"] == {}
