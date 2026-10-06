"""Unit tests for cleanup.py - automatic log cleanup."""

import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from cleanup import CleanupScheduler, cleanup_old_logs, run_cleanup


class TestCleanupOldLogs:
    def test_returns_zero_for_nonexistent_dir(self):
        result = cleanup_old_logs("/nonexistent/path/xyz", 3)
        assert result == 0

    def test_returns_zero_for_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = cleanup_old_logs(tmpdir, 3)
            assert result == 0

    def test_keeps_recent_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a recent file
            recent_file = Path(tmpdir) / "recent.log"
            recent_file.write_text("recent log content")

            result = cleanup_old_logs(tmpdir, 3)
            assert result == 0
            assert recent_file.exists()

    def test_deletes_old_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create an old file
            old_file = Path(tmpdir) / "old.log"
            old_file.write_text("old log content")

            # Set mtime to 5 days ago
            old_time = time.time() - (5 * 86400)
            os.utime(old_file, (old_time, old_time))

            result = cleanup_old_logs(tmpdir, 3)
            assert result == 1
            assert not old_file.exists()

    def test_deletes_old_directories(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create an old directory with a log file (z2m format)
            old_dir = Path(tmpdir) / "2024-01-01.10-30-00"
            old_dir.mkdir()
            log_file = old_dir / "log.log"
            log_file.write_text("old log")

            # Set mtime to 5 days ago
            old_time = time.time() - (5 * 86400)
            os.utime(log_file, (old_time, old_time))
            os.utime(old_dir, (old_time, old_time))

            result = cleanup_old_logs(tmpdir, 3)
            assert result == 1
            assert not old_dir.exists()

    def test_handles_permission_error_gracefully(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            old_file = Path(tmpdir) / "protected.log"
            old_file.write_text("protected")
            old_time = time.time() - (5 * 86400)
            os.utime(old_file, (old_time, old_time))

            # Mock unlink to raise an error
            with patch.object(
                Path, "unlink", side_effect=PermissionError("Access denied")
            ):
                result = cleanup_old_logs(tmpdir, 3)
                # Should continue without crashing
                assert result == 0


class TestRunCleanup:
    @patch("cleanup.cleanup_old_logs")
    def test_calls_cleanup_old_logs(self, mock_cleanup):
        mock_cleanup.return_value = 5
        run_cleanup()
        mock_cleanup.assert_called_once()

    @patch("cleanup.cleanup_old_logs")
    def test_logs_results(self, mock_cleanup):
        mock_cleanup.return_value = 3
        with patch("cleanup.logger") as mock_logger:
            run_cleanup()
            # Should log start, cleanup result, and end
            assert mock_logger.info.call_count >= 2


class TestCleanupScheduler:
    def test_init_defaults(self):
        scheduler = CleanupScheduler()
        assert scheduler._interval == 86400  # 24h
        assert scheduler._grace_period == 60
        assert scheduler._running is False

    def test_init_custom_values(self):
        scheduler = CleanupScheduler(interval=3600, grace_period=10)
        assert scheduler._interval == 3600
        assert scheduler._grace_period == 10

    def test_start_sets_running(self):
        scheduler = CleanupScheduler(interval=3600, grace_period=0)
        with patch("cleanup.run_cleanup"):
            scheduler.start()
            assert scheduler._running is True
            scheduler.stop()

    def test_stop_clears_running(self):
        scheduler = CleanupScheduler(interval=3600, grace_period=0)
        with patch("cleanup.run_cleanup"):
            scheduler.start()
            scheduler.stop()
            assert scheduler._running is False

    def test_start_twice_is_noop(self):
        scheduler = CleanupScheduler(interval=3600, grace_period=0)
        with patch("cleanup.run_cleanup"):
            scheduler.start()
            # Second call returns early without starting another thread
            scheduler.start()
            # Should still only have one thread
            assert scheduler._running is True
            scheduler.stop()

    @patch("cleanup.run_cleanup")
    @patch("cleanup.time.sleep", side_effect=InterruptedError)
    def test_loop_runs_cleanup_after_grace_period(self, mock_sleep, mock_run):
        scheduler = CleanupScheduler(interval=3600, grace_period=1)
        # The loop will exit on first sleep due to InterruptedError
        try:
            scheduler._running = True
            scheduler._loop()
        except InterruptedError:
            pass
        # Sleep is called for grace period
        mock_sleep.assert_called()
