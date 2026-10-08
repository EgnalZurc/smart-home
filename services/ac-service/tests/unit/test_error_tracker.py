"""Unit tests for ErrorTracker."""

import time


class TestErrorTracker:
    """Tests for ErrorTracker class."""

    def test_register_adds_error(self):
        """register should add an error to tracker."""
        from smart_home_common.utils.error_tracker import ErrorTracker

        tracker = ErrorTracker()
        tracker.register("test_error", "error", "Test message", "test_source")

        active = tracker.get_active()
        assert len(active) == 1
        assert active[0]["id"] == "test_error"
        assert active[0]["severity"] == "error"
        assert active[0]["message"] == "Test message"
        assert active[0]["source"] == "test_source"

    def test_register_is_idempotent(self):
        """register should not duplicate if error already exists."""
        from smart_home_common.utils.error_tracker import ErrorTracker

        tracker = ErrorTracker()
        tracker.register("dup_error", "error", "First message", "source")
        tracker.register("dup_error", "error", "Second message", "source")

        active = tracker.get_active()
        assert len(active) == 1
        assert active[0]["message"] == "First message"  # Original preserved

    def test_register_preserves_original_timestamp(self):
        """register should preserve original timestamp on duplicate."""
        from smart_home_common.utils.error_tracker import ErrorTracker

        tracker = ErrorTracker()
        tracker.register("time_error", "error", "Message", "source")
        time.sleep(0.1)
        original_time = tracker.get_active()[0]["timestamp"]

        tracker.register("time_error", "error", "Updated", "source")
        new_time = tracker.get_active()[0]["timestamp"]

        assert new_time == original_time

    def test_clear_removes_error(self):
        """clear should remove a specific error."""
        from smart_home_common.utils.error_tracker import ErrorTracker

        tracker = ErrorTracker()
        tracker.register("to_clear", "error", "Will be cleared", "source")
        tracker.clear("to_clear")

        active = tracker.get_active()
        assert len(active) == 0

    def test_clear_nonexistent_is_safe(self):
        """clear should not error for non-existent error."""
        from smart_home_common.utils.error_tracker import ErrorTracker

        tracker = ErrorTracker()
        tracker.clear("nonexistent")  # Should not raise

        assert tracker.get_active() == []

    def test_get_active_returns_newest_first(self):
        """get_active should return errors sorted newest first."""
        from smart_home_common.utils.error_tracker import ErrorTracker

        tracker = ErrorTracker()
        tracker.register("old", "error", "Old error", "source")
        time.sleep(0.05)
        tracker.register("new", "error", "New error", "source")

        active = tracker.get_active()
        assert active[0]["id"] == "new"
        assert active[1]["id"] == "old"

    def test_has_active_true_when_errors(self):
        """has_active should return True when errors exist."""
        from smart_home_common.utils.error_tracker import ErrorTracker

        tracker = ErrorTracker()
        tracker.register("error", "error", "Message", "source")

        assert tracker.has_active() is True

    def test_has_active_false_when_empty(self):
        """has_active should return False when no errors."""
        from smart_home_common.utils.error_tracker import ErrorTracker

        tracker = ErrorTracker()

        assert tracker.has_active() is False

    def test_multiple_errors_tracked(self):
        """Should track multiple different errors."""
        from smart_home_common.utils.error_tracker import ErrorTracker

        tracker = ErrorTracker()
        tracker.register("error1", "error", "Error 1", "source1")
        tracker.register("error2", "warning", "Error 2", "source2")
        tracker.register("error3", "error", "Error 3", "source3")

        active = tracker.get_active()
        assert len(active) == 3

    def test_clear_one_keeps_others(self):
        """Clearing one error should keep others."""
        from smart_home_common.utils.error_tracker import ErrorTracker

        tracker = ErrorTracker()
        tracker.register("keep", "error", "Keep this", "source")
        tracker.register("remove", "error", "Remove this", "source")
        tracker.clear("remove")

        active = tracker.get_active()
        assert len(active) == 1
        assert active[0]["id"] == "keep"

    def test_severity_types(self):
        """Should support both error and warning severities."""
        from smart_home_common.utils.error_tracker import ErrorTracker

        tracker = ErrorTracker()
        tracker.register("err", "error", "Error msg", "source")
        tracker.register("warn", "warning", "Warning msg", "source")

        active = tracker.get_active()
        severities = {e["severity"] for e in active}

        assert "error" in severities
        assert "warning" in severities
