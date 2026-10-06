"""Unit tests for ac_temp_scheduler.py - hourly temperature recording."""

import time
from unittest.mock import MagicMock, patch

import pytest


class TestAcTempScheduler:
    @pytest.fixture
    def mock_dependencies(self):
        """Create mock mqtt_handler and ac_controller."""
        mqtt = MagicMock()
        ac = MagicMock()
        ac.state = MagicMock()
        ac.state.ac_real_room_temp = 23.5
        return mqtt, ac

    @pytest.fixture
    def scheduler(self, mock_dependencies):
        """Create scheduler with mocked dependencies."""
        from ac_temp_scheduler import AcTempScheduler

        mqtt, ac = mock_dependencies
        sched = AcTempScheduler(mqtt, ac)
        yield sched
        sched.stop()

    def test_init_sets_attributes(self, mock_dependencies):
        from ac_temp_scheduler import AcTempScheduler

        mqtt, ac = mock_dependencies
        sched = AcTempScheduler(mqtt, ac)

        assert sched._mqtt is mqtt
        assert sched._ac is ac
        assert sched._last_recorded_hour is None
        assert sched._thread is None

    def test_start_creates_thread(self, scheduler):
        scheduler.start()

        assert scheduler._thread is not None
        assert scheduler._thread.is_alive()
        assert scheduler._thread.daemon is True

    def test_stop_sets_event(self, scheduler):
        scheduler.start()
        scheduler.stop()

        assert scheduler._stop_event.is_set()

    def test_run_once_records_at_hour_zero(self, scheduler, mock_dependencies):
        mqtt, ac = mock_dependencies

        # Mock time to be exactly on the hour
        with patch("ac_temp_scheduler.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.minute = 0
            mock_now.hour = 10
            mock_dt.datetime.now.return_value = mock_now

            scheduler._run_once()

            mqtt.record_ac_temp.assert_called_once_with(23.5)
            assert scheduler._last_recorded_hour == 10

    def test_run_once_skips_non_zero_minute(self, scheduler, mock_dependencies):
        mqtt, ac = mock_dependencies

        with patch("ac_temp_scheduler.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.minute = 15  # Not on the hour
            mock_now.hour = 10
            mock_dt.datetime.now.return_value = mock_now

            scheduler._run_once()

            mqtt.record_ac_temp.assert_not_called()

    def test_run_once_skips_same_hour(self, scheduler, mock_dependencies):
        mqtt, ac = mock_dependencies
        scheduler._last_recorded_hour = 10  # Already recorded

        with patch("ac_temp_scheduler.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.minute = 0
            mock_now.hour = 10  # Same hour
            mock_dt.datetime.now.return_value = mock_now

            scheduler._run_once()

            mqtt.record_ac_temp.assert_not_called()

    def test_run_once_records_new_hour(self, scheduler, mock_dependencies):
        mqtt, ac = mock_dependencies
        scheduler._last_recorded_hour = 9  # Previous hour

        with patch("ac_temp_scheduler.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.minute = 0
            mock_now.hour = 10  # New hour
            mock_dt.datetime.now.return_value = mock_now

            scheduler._run_once()

            mqtt.record_ac_temp.assert_called_once()
            assert scheduler._last_recorded_hour == 10

    def test_run_once_skips_when_temp_none(self, scheduler, mock_dependencies):
        mqtt, ac = mock_dependencies
        ac.state.ac_real_room_temp = None

        with patch("ac_temp_scheduler.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.minute = 0
            mock_now.hour = 10
            mock_dt.datetime.now.return_value = mock_now

            scheduler._run_once()

            mqtt.record_ac_temp.assert_not_called()

    def test_run_handles_exception(self, mock_dependencies):
        """Test that exceptions in record_ac_temp don't crash the scheduler."""
        from ac_temp_scheduler import AcTempScheduler

        mqtt, ac = mock_dependencies

        # Setup: ac has room temp
        ac.state.ac_real_room_temp = 25.0

        # Create scheduler
        sched = AcTempScheduler(mqtt, ac)

        with patch("ac_temp_scheduler.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.minute = 0
            mock_now.hour = 10
            mock_dt.datetime.now.return_value = mock_now

            # Make record_ac_temp raise
            mqtt.record_ac_temp.side_effect = Exception("Fail!")

            # The _run method catches exceptions, not _run_once
            # So we test that _run doesn't crash when exception occurs
            sched._stop_event.set()  # Prevent infinite loop
            sched._run()  # Should complete without raising

    def test_scheduler_loop_stops_on_event(self, mock_dependencies):
        """Test that the scheduler loop respects the stop event."""
        from ac_temp_scheduler import AcTempScheduler

        mqtt, ac = mock_dependencies
        sched = AcTempScheduler(mqtt, ac)

        # Start and immediately stop
        sched.start()
        time.sleep(0.1)  # Let thread start
        sched.stop()

        # Thread should stop within reasonable time
        sched._thread.join(timeout=1.0)
        assert not sched._thread.is_alive()
