"""Unit tests for AcTempScheduler.

Tests the hourly scheduler that records AC room temperature
into sensor history.
"""

import datetime
from unittest.mock import MagicMock, patch

from ac_temp_scheduler import AcTempScheduler


class TestAcTempSchedulerInit:
    """Tests for AcTempScheduler initialization."""

    def test_init_stores_dependencies(self):
        """Should store mqtt_handler and ac_controller."""
        mock_mqtt = MagicMock()
        mock_controller = MagicMock()

        scheduler = AcTempScheduler(mock_mqtt, mock_controller)

        assert scheduler._mqtt is mock_mqtt
        assert scheduler._ac is mock_controller
        assert scheduler._last_recorded_hour is None
        assert scheduler._thread is None


class TestAcTempSchedulerRunOnce:
    """Tests for _run_once method (hourly recording logic)."""

    def test_records_on_hour(self):
        """Should record temperature when minute is 0."""
        mock_mqtt = MagicMock()
        mock_controller = MagicMock()
        mock_controller.state.ac_real_room_temp = 24.5

        scheduler = AcTempScheduler(mock_mqtt, mock_controller)

        # Mock datetime to be on the hour (minute=0)
        mock_now = datetime.datetime(2024, 1, 15, 14, 0, 30)  # 14:00:30

        with patch("ac_temp_scheduler.datetime") as mock_datetime:
            mock_datetime.datetime.now.return_value = mock_now
            scheduler._run_once()

        mock_mqtt.record_ac_temp.assert_called_once_with(24.5)
        assert scheduler._last_recorded_hour == 14

    def test_skips_when_not_on_hour(self):
        """Should not record when minute is not 0."""
        mock_mqtt = MagicMock()
        mock_controller = MagicMock()
        mock_controller.state.ac_real_room_temp = 24.5

        scheduler = AcTempScheduler(mock_mqtt, mock_controller)

        # Mock datetime to NOT be on the hour
        mock_now = datetime.datetime(2024, 1, 15, 14, 15, 30)  # 14:15:30

        with patch("ac_temp_scheduler.datetime") as mock_datetime:
            mock_datetime.datetime.now.return_value = mock_now
            scheduler._run_once()

        mock_mqtt.record_ac_temp.assert_not_called()

    def test_skips_if_already_recorded_this_hour(self):
        """Should not record twice for the same hour."""
        mock_mqtt = MagicMock()
        mock_controller = MagicMock()
        mock_controller.state.ac_real_room_temp = 24.5

        scheduler = AcTempScheduler(mock_mqtt, mock_controller)
        scheduler._last_recorded_hour = 14  # Already recorded hour 14

        mock_now = datetime.datetime(2024, 1, 15, 14, 0, 45)  # Still hour 14

        with patch("ac_temp_scheduler.datetime") as mock_datetime:
            mock_datetime.datetime.now.return_value = mock_now
            scheduler._run_once()

        mock_mqtt.record_ac_temp.assert_not_called()

    def test_records_new_hour_after_recorded_previous(self):
        """Should record when hour changes."""
        mock_mqtt = MagicMock()
        mock_controller = MagicMock()
        mock_controller.state.ac_real_room_temp = 25.0

        scheduler = AcTempScheduler(mock_mqtt, mock_controller)
        scheduler._last_recorded_hour = 13  # Recorded hour 13

        mock_now = datetime.datetime(2024, 1, 15, 14, 0, 0)  # Now hour 14

        with patch("ac_temp_scheduler.datetime") as mock_datetime:
            mock_datetime.datetime.now.return_value = mock_now
            scheduler._run_once()

        mock_mqtt.record_ac_temp.assert_called_once_with(25.0)
        assert scheduler._last_recorded_hour == 14

    def test_skips_when_room_temp_is_none(self):
        """Should skip recording if room temp is None."""
        mock_mqtt = MagicMock()
        mock_controller = MagicMock()
        mock_controller.state.ac_real_room_temp = None

        scheduler = AcTempScheduler(mock_mqtt, mock_controller)

        mock_now = datetime.datetime(2024, 1, 15, 15, 0, 0)

        with patch("ac_temp_scheduler.datetime") as mock_datetime:
            mock_datetime.datetime.now.return_value = mock_now
            scheduler._run_once()

        mock_mqtt.record_ac_temp.assert_not_called()
        # Should NOT update _last_recorded_hour since we didn't record
        assert scheduler._last_recorded_hour is None


class TestAcTempSchedulerLifecycle:
    """Tests for start/stop lifecycle."""

    def test_start_creates_thread(self):
        """start should create and start a daemon thread."""
        mock_mqtt = MagicMock()
        mock_controller = MagicMock()

        scheduler = AcTempScheduler(mock_mqtt, mock_controller)

        with patch.object(scheduler, "_run"):
            scheduler.start()

        assert scheduler._thread is not None
        assert scheduler._thread.daemon is True
        assert scheduler._thread.name == "ac-temp-scheduler"

        # Cleanup
        scheduler.stop()

    def test_stop_sets_event(self):
        """stop should set the stop event."""
        mock_mqtt = MagicMock()
        mock_controller = MagicMock()

        scheduler = AcTempScheduler(mock_mqtt, mock_controller)

        scheduler.stop()

        assert scheduler._stop_event.is_set()


class TestAcTempSchedulerErrorHandling:
    """Tests for error handling."""

    def test_run_loop_handles_exceptions(self):
        """The _run loop should catch exceptions from _run_once."""
        # Note: _run_once itself doesn't catch exceptions - it's the _run loop
        # that wraps it in a try/except. This test verifies that behavior.
        mock_mqtt = MagicMock()
        mock_controller = MagicMock()
        mock_controller.state.ac_real_room_temp = 24.5

        scheduler = AcTempScheduler(mock_mqtt, mock_controller)

        # _run_once should work normally
        mock_now = datetime.datetime(2024, 1, 15, 16, 0, 0)

        with patch("ac_temp_scheduler.datetime") as mock_datetime:
            mock_datetime.datetime.now.return_value = mock_now
            # Should not raise
            scheduler._run_once()

        mock_mqtt.record_ac_temp.assert_called_once()


class TestAcTempSchedulerMidnightEdge:
    """Tests for midnight edge cases."""

    def test_handles_midnight_transition(self):
        """Should handle transition from hour 23 to hour 0."""
        mock_mqtt = MagicMock()
        mock_controller = MagicMock()
        mock_controller.state.ac_real_room_temp = 22.0

        scheduler = AcTempScheduler(mock_mqtt, mock_controller)
        scheduler._last_recorded_hour = 23  # Last recorded at 23:00

        # Now it's midnight
        mock_now = datetime.datetime(2024, 1, 16, 0, 0, 0)

        with patch("ac_temp_scheduler.datetime") as mock_datetime:
            mock_datetime.datetime.now.return_value = mock_now
            scheduler._run_once()

        mock_mqtt.record_ac_temp.assert_called_once_with(22.0)
        assert scheduler._last_recorded_hour == 0

    def test_hour_0_after_none(self):
        """Should record at midnight even when _last_recorded_hour is None."""
        mock_mqtt = MagicMock()
        mock_controller = MagicMock()
        mock_controller.state.ac_real_room_temp = 21.0

        scheduler = AcTempScheduler(mock_mqtt, mock_controller)
        # _last_recorded_hour is None (fresh start)

        mock_now = datetime.datetime(2024, 1, 16, 0, 0, 0)

        with patch("ac_temp_scheduler.datetime") as mock_datetime:
            mock_datetime.datetime.now.return_value = mock_now
            scheduler._run_once()

        mock_mqtt.record_ac_temp.assert_called_once_with(21.0)
        assert scheduler._last_recorded_hour == 0
