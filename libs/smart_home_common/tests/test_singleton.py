"""Tests for smart_home_common.singleton — process lock management."""

import os
import sys
from unittest.mock import MagicMock

import pytest

from smart_home_common import singleton
from smart_home_common.singleton import (
    _cleanup_lock_windows,
    _ensure_singleton_unix,
    _ensure_singleton_windows,
    _hold_lock_ref,
    _pid_alive,
    ensure_singleton,
)


class TestEnsureSingleton:
    """Tests for the public ensure_singleton entry point."""

    def test_creates_lock_directory(self, tmp_path):
        """The lock directory is created if it does not exist."""
        lock_path = tmp_path / "subdir" / "test.lock"
        assert not lock_path.parent.exists()

        try:
            ensure_singleton(str(lock_path))
        except SystemExit:
            # Another instance may hold the lock; the directory must still exist.
            pass
        assert lock_path.parent.exists()

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific test")
    def test_windows_lock_mechanism(self, tmp_path):
        """On Windows the lock file is created and contains the PID."""
        lock_path = tmp_path / "test.lock"
        _ensure_singleton_windows(str(lock_path))
        assert lock_path.exists()
        assert lock_path.read_text().strip().isdigit()

    @pytest.mark.skipif(sys.platform == "win32", reason="Unix-specific test")
    def test_unix_lock_mechanism(self, tmp_path):
        """On Unix the lock file is created."""
        lock_path = tmp_path / "test.lock"
        _ensure_singleton_unix(str(lock_path))
        assert lock_path.exists()

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific test")
    def test_windows_second_instance_exits(self, tmp_path):
        """A second live instance exits with code 1 on Windows."""
        lock_path = tmp_path / "test.lock"
        _ensure_singleton_windows(str(lock_path))
        # The current PID is written and alive, so a retry must exit.
        with pytest.raises(SystemExit) as exc:
            _ensure_singleton_windows(str(lock_path))
        assert exc.value.code == 1

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific test")
    def test_windows_orphan_lock_is_reclaimed(self, tmp_path):
        """A lock left by a dead PID is reclaimed on Windows."""
        lock_path = tmp_path / "test.lock"
        lock_path.write_text("999999999")  # PID unlikely to be alive
        _ensure_singleton_windows(str(lock_path))
        # Reclaimed: the file now holds the current PID.
        assert lock_path.read_text().strip() == str(os.getpid())


class TestPidAlive:
    """Tests for _pid_alive."""

    def test_current_pid_is_alive(self):
        assert _pid_alive(os.getpid()) is True

    def test_nonexistent_pid(self):
        assert _pid_alive(999999999) is False


class TestHoldLockRef:
    """Tests for _hold_lock_ref."""

    def test_stores_reference(self):
        mock_file = MagicMock()
        _hold_lock_ref(mock_file)
        assert singleton._lock_file_handle is mock_file


class TestCleanupLockWindows:
    """Tests for _cleanup_lock_windows."""

    def test_removes_lock_file(self, tmp_path):
        lock_path = tmp_path / "test.lock"
        lock_path.write_text("12345")
        _cleanup_lock_windows(str(lock_path))
        assert not lock_path.exists()

    def test_handles_missing_file(self, tmp_path):
        lock_path = tmp_path / "nonexistent.lock"
        # Must not raise.
        _cleanup_lock_windows(str(lock_path))
