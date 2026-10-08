"""Tests for smart_home_common.utils.error_tracker — error tracking system."""

import threading
import time
from unittest.mock import patch

import pytest

from smart_home_common.utils.error_tracker import ErrorTracker, _TrackedError


class TestTrackedError:
    """Tests for _TrackedError dataclass."""

    def test_creation(self):
        """_TrackedError stores all fields correctly."""
        now = time.time()
        error = _TrackedError(
            id="test_error",
            timestamp=now,
            severity="error",
            message="Test message",
            source="test_source",
        )
        assert error.id == "test_error"
        assert error.timestamp == now
        assert error.severity == "error"
        assert error.message == "Test message"
        assert error.source == "test_source"

    def test_warning_severity(self):
        """_TrackedError accepts warning severity."""
        error = _TrackedError(
            id="warn_id",
            timestamp=time.time(),
            severity="warning",
            message="Warning message",
            source="source",
        )
        assert error.severity == "warning"


class TestErrorTracker:
    """Tests for ErrorTracker class."""

    @pytest.fixture
    def tracker(self):
        """Fresh ErrorTracker instance for each test."""
        return ErrorTracker()

    def test_initialization(self, tracker):
        """ErrorTracker initializes with empty errors."""
        assert tracker._errors == {}
        assert tracker.get_active() == []
        assert tracker.has_active() is False

    def test_register_new_error(self, tracker):
        """register() adds new error to tracker."""
        tracker.register(
            error_id="err_001",
            severity="error",
            message="Connection failed",
            source="melcloud",
        )
        assert tracker.has_active() is True
        errors = tracker.get_active()
        assert len(errors) == 1
        assert errors[0]["id"] == "err_001"
        assert errors[0]["severity"] == "error"
        assert errors[0]["message"] == "Connection failed"
        assert errors[0]["source"] == "melcloud"

    def test_register_duplicate_is_noop(self, tracker):
        """register() with existing id does not overwrite."""
        # Register first error
        tracker.register("dup_err", "error", "First message", "source1")
        first_errors = tracker.get_active()
        first_timestamp = first_errors[0]["timestamp"]

        # Wait a bit and try to register again
        time.sleep(0.01)
        tracker.register("dup_err", "warning", "Second message", "source2")

        # Should still have original error
        errors = tracker.get_active()
        assert len(errors) == 1
        assert errors[0]["message"] == "First message"
        assert errors[0]["timestamp"] == first_timestamp
        assert errors[0]["severity"] == "error"
        assert errors[0]["source"] == "source1"

    def test_register_multiple_distinct_errors(self, tracker):
        """register() allows multiple distinct errors."""
        tracker.register("err_1", "error", "Error 1", "source_a")
        tracker.register("err_2", "warning", "Warning 2", "source_b")
        tracker.register("err_3", "error", "Error 3", "source_c")

        errors = tracker.get_active()
        assert len(errors) == 3
        error_ids = {e["id"] for e in errors}
        assert error_ids == {"err_1", "err_2", "err_3"}

    def test_clear_existing_error(self, tracker):
        """clear() removes specified error."""
        tracker.register("to_clear", "error", "Will be cleared", "source")
        assert tracker.has_active() is True

        tracker.clear("to_clear")

        assert tracker.has_active() is False
        assert tracker.get_active() == []

    def test_clear_nonexistent_is_safe(self, tracker):
        """clear() with nonexistent id does not raise."""
        # Should not raise
        tracker.clear("nonexistent_error")
        assert tracker.get_active() == []

    def test_clear_specific_error_leaves_others(self, tracker):
        """clear() removes only specified error."""
        tracker.register("err_1", "error", "Error 1", "source")
        tracker.register("err_2", "error", "Error 2", "source")
        tracker.register("err_3", "error", "Error 3", "source")

        tracker.clear("err_2")

        errors = tracker.get_active()
        assert len(errors) == 2
        error_ids = {e["id"] for e in errors}
        assert error_ids == {"err_1", "err_3"}

    def test_get_active_returns_newest_first(self, tracker):
        """get_active() returns errors sorted by timestamp, newest first."""
        # Register errors with distinct timestamps
        with patch("time.time", return_value=1000.0):
            tracker.register("old", "error", "Old error", "source")

        with patch("time.time", return_value=2000.0):
            tracker.register("middle", "error", "Middle error", "source")

        with patch("time.time", return_value=3000.0):
            tracker.register("newest", "error", "Newest error", "source")

        errors = tracker.get_active()

        assert errors[0]["id"] == "newest"
        assert errors[1]["id"] == "middle"
        assert errors[2]["id"] == "old"

    def test_get_active_returns_copy(self, tracker):
        """get_active() returns dict copies, not internal references."""
        tracker.register("test_err", "error", "Test", "source")
        errors1 = tracker.get_active()
        errors2 = tracker.get_active()

        # Modifying returned dict should not affect tracker
        errors1[0]["message"] = "Modified"

        errors3 = tracker.get_active()
        assert errors3[0]["message"] == "Test"
        assert errors1 is not errors2

    def test_has_active_false_when_empty(self, tracker):
        """has_active() returns False when no errors."""
        assert tracker.has_active() is False

    def test_has_active_true_when_errors(self, tracker):
        """has_active() returns True when errors exist."""
        tracker.register("err", "error", "Error", "source")
        assert tracker.has_active() is True

    def test_has_active_false_after_clear_all(self, tracker):
        """has_active() returns False after all errors cleared."""
        tracker.register("err_1", "error", "Error 1", "source")
        tracker.register("err_2", "error", "Error 2", "source")

        tracker.clear("err_1")
        assert tracker.has_active() is True

        tracker.clear("err_2")
        assert tracker.has_active() is False

    def test_thread_safety_register(self, tracker):
        """register() is thread-safe with concurrent calls."""
        errors_registered = []

        def register_errors(start_id):
            for i in range(50):
                error_id = f"err_{start_id}_{i}"
                tracker.register(error_id, "error", f"Error {error_id}", "source")
                errors_registered.append(error_id)

        threads = [threading.Thread(target=register_errors, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All unique errors should be registered
        active = tracker.get_active()
        assert len(active) == 250  # 5 threads * 50 errors each

    def test_thread_safety_clear(self, tracker):
        """clear() is thread-safe with concurrent calls."""
        # Pre-register errors
        for i in range(100):
            tracker.register(f"err_{i}", "error", f"Error {i}", "source")

        def clear_errors(start, end):
            for i in range(start, end):
                tracker.clear(f"err_{i}")

        threads = [
            threading.Thread(target=clear_errors, args=(0, 25)),
            threading.Thread(target=clear_errors, args=(25, 50)),
            threading.Thread(target=clear_errors, args=(50, 75)),
            threading.Thread(target=clear_errors, args=(75, 100)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert tracker.has_active() is False

    def test_thread_safety_mixed_operations(self, tracker):
        """Concurrent register, clear, and get_active are thread-safe."""
        results = {"active_counts": []}

        def writer():
            for i in range(50):
                tracker.register(f"write_err_{i}", "error", f"Error {i}", "writer")
                time.sleep(0.001)

        def clearer():
            for i in range(50):
                tracker.clear(f"write_err_{i}")
                time.sleep(0.001)

        def reader():
            for _ in range(100):
                active = tracker.get_active()
                results["active_counts"].append(len(active))
                time.sleep(0.001)

        threads = [
            threading.Thread(target=writer),
            threading.Thread(target=clearer),
            threading.Thread(target=reader),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Reader should have gotten results without errors
        assert len(results["active_counts"]) == 100

    def test_error_message_preserved(self, tracker):
        """Error message with special characters is preserved."""
        message = "Error: connection to 'server' failed (timeout=30s) <critical>"
        tracker.register("special_err", "error", message, "source")

        errors = tracker.get_active()
        assert errors[0]["message"] == message

    def test_source_field_preserved(self, tracker):
        """Source field is correctly stored and returned."""
        tracker.register("err_1", "error", "Error", "melcloud_api")
        tracker.register("err_2", "warning", "Warning", "outdoor_sensor")

        errors = tracker.get_active()
        sources = {e["source"] for e in errors}
        assert sources == {"melcloud_api", "outdoor_sensor"}

    def test_timestamp_is_set_automatically(self, tracker):
        """Timestamp is set when error is registered."""
        before = time.time()
        tracker.register("err", "error", "Error", "source")
        after = time.time()

        errors = tracker.get_active()
        assert before <= errors[0]["timestamp"] <= after

    def test_reregister_after_clear(self, tracker):
        """Error can be registered again after being cleared."""
        tracker.register("recyclable", "error", "First occurrence", "source")
        first_timestamp = tracker.get_active()[0]["timestamp"]

        tracker.clear("recyclable")
        assert tracker.has_active() is False

        time.sleep(0.01)
        tracker.register("recyclable", "error", "Second occurrence", "source")

        errors = tracker.get_active()
        assert len(errors) == 1
        assert errors[0]["message"] == "Second occurrence"
        assert errors[0]["timestamp"] > first_timestamp
