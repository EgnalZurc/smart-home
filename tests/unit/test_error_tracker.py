"""Unit tests for error_tracker.py"""
import time
from error_tracker import ErrorTracker


class TestRegister:
    def test_creates_entry(self):
        t = ErrorTracker()
        t.register("e1", "error", "Something broke", "service")
        assert t.has_active()

    def test_idempotent_preserves_timestamp(self):
        t = ErrorTracker()
        t.register("e1", "error", "msg", "src")
        ts = t.get_active()[0]["timestamp"]
        time.sleep(0.05)
        t.register("e1", "error", "msg changed", "src")
        assert t.get_active()[0]["timestamp"] == ts
        assert t.get_active()[0]["message"] == "msg"

    def test_multiple_different_ids(self):
        t = ErrorTracker()
        t.register("e1", "error", "A", "s1")
        t.register("e2", "warning", "B", "s2")
        assert len(t.get_active()) == 2


class TestClear:
    def test_removes_entry(self):
        t = ErrorTracker()
        t.register("e1", "error", "msg", "src")
        t.clear("e1")
        assert not t.has_active()

    def test_nonexistent_is_noop(self):
        t = ErrorTracker()
        t.clear("nonexistent")  # must not raise
        assert not t.has_active()

    def test_only_clears_specified(self):
        t = ErrorTracker()
        t.register("e1", "error", "A", "s")
        t.register("e2", "error", "B", "s")
        t.clear("e1")
        active = t.get_active()
        assert len(active) == 1
        assert active[0]["id"] == "e2"


class TestGetActive:
    def test_correct_shape(self):
        t = ErrorTracker()
        t.register("e1", "warning", "Watch out", "mqtt")
        e = t.get_active()[0]
        assert e["id"] == "e1"
        assert e["severity"] == "warning"
        assert e["message"] == "Watch out"
        assert e["source"] == "mqtt"
        assert isinstance(e["timestamp"], float)

    def test_sorted_newest_first(self):
        t = ErrorTracker()
        t.register("old", "error", "A", "s")
        time.sleep(0.05)
        t.register("new", "error", "B", "s")
        ids = [e["id"] for e in t.get_active()]
        assert ids == ["new", "old"]

    def test_empty_when_no_errors(self):
        assert ErrorTracker().get_active() == []


class TestHasActive:
    def test_false_when_empty(self):
        assert not ErrorTracker().has_active()

    def test_true_with_errors(self):
        t = ErrorTracker()
        t.register("x", "error", "m", "s")
        assert t.has_active()

    def test_false_after_all_cleared(self):
        t = ErrorTracker()
        t.register("x", "error", "m", "s")
        t.clear("x")
        assert not t.has_active()
