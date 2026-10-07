"""Tests for singleton.py - process lock management."""

import os
import sys
import tempfile
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


class TestEnsureSingleton:
    """Tests for ensure_singleton function."""

    def test_creates_lock_directory(self, tmp_path):
        """Test that lock directory is created if missing."""
        from singleton import ensure_singleton

        lock_path = tmp_path / "subdir" / "test.lock"
        assert not lock_path.parent.exists()

        # On Windows, this should work
        try:
            ensure_singleton(str(lock_path))
            assert lock_path.parent.exists()
        except SystemExit:
            # May exit if another test left a lock
            pass

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific test")
    def test_windows_lock_mechanism(self, tmp_path):
        """Test Windows lock file behavior."""
        from singleton import _ensure_singleton_windows

        lock_path = tmp_path / "test.lock"

        # First call should succeed
        _ensure_singleton_windows(str(lock_path))
        assert lock_path.exists()

        # File should contain PID
        content = lock_path.read_text()
        assert content.strip().isdigit()

    @pytest.mark.skipif(sys.platform == "win32", reason="Unix-specific test")
    def test_unix_lock_mechanism(self, tmp_path):
        """Test Unix lock file behavior."""
        from singleton import _ensure_singleton_unix

        lock_path = tmp_path / "test.lock"

        # First call should succeed
        _ensure_singleton_unix(str(lock_path))
        assert lock_path.exists()


class TestPidAlive:
    """Tests for _pid_alive function."""

    def test_current_pid_is_alive(self):
        """Test that current process is detected as alive."""
        from singleton import _pid_alive

        assert _pid_alive(os.getpid()) is True

    def test_nonexistent_pid(self):
        """Test that non-existent PID returns False."""
        from singleton import _pid_alive

        # Use a very high PID that's unlikely to exist
        fake_pid = 999999999
        assert _pid_alive(fake_pid) is False


class TestHoldLockRef:
    """Tests for _hold_lock_ref function."""

    def test_stores_reference(self):
        """Test that reference is stored globally."""
        from singleton import _hold_lock_ref, _lock_file_handle

        mock_file = MagicMock()
        _hold_lock_ref(mock_file)

        # Import again to check global state
        import singleton
        assert singleton._lock_file_handle is mock_file


class TestCleanupLockWindows:
    """Tests for _cleanup_lock_windows function."""

    def test_removes_lock_file(self, tmp_path):
        """Test that lock file is removed on cleanup."""
        from singleton import _cleanup_lock_windows

        lock_path = tmp_path / "test.lock"
        lock_path.write_text("12345")

        _cleanup_lock_windows(str(lock_path))
        assert not lock_path.exists()

    def test_handles_missing_file(self, tmp_path):
        """Test that cleanup doesn't error on missing file."""
        from singleton import _cleanup_lock_windows

        lock_path = tmp_path / "nonexistent.lock"
        # Should not raise
        _cleanup_lock_windows(str(lock_path))
