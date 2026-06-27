"""Unit tests for AcTempScheduler (AC-CHART.10)."""
import datetime
from unittest.mock import MagicMock, patch
import pytest
from ac_temp_scheduler import AcTempScheduler


class TestAcTempScheduler:
    """AcTempScheduler records AC room temp into mqtt_handler.history at :00."""

    def _make_scheduler(self, mqtt=None, ac=None):
        mqtt = mqtt or MagicMock()
        ac   = ac   or MagicMock()
        ac.state.ac_real_room_temp = 23.5
        return AcTempScheduler(mqtt, ac)

    def _at_minute(self, hour, minute):
        return datetime.datetime(2026, 6, 27, hour, minute, 0)

    def test_records_when_minute_zero(self):
        mqtt = MagicMock()
        ac   = MagicMock()
        ac.state.ac_real_room_temp = 23.5
        sched = AcTempScheduler(mqtt, ac)

        with patch("ac_temp_scheduler.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = self._at_minute(15, 0)
            sched._run_once()

        mqtt.record_ac_temp.assert_called_once_with(23.5)

    def test_skips_when_minute_not_zero(self):
        mqtt = MagicMock()
        ac   = MagicMock()
        ac.state.ac_real_room_temp = 23.5
        sched = AcTempScheduler(mqtt, ac)

        with patch("ac_temp_scheduler.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = self._at_minute(15, 30)
            sched._run_once()

        mqtt.record_ac_temp.assert_not_called()

    def test_skips_same_hour_twice(self):
        mqtt = MagicMock()
        ac   = MagicMock()
        ac.state.ac_real_room_temp = 22.0
        sched = AcTempScheduler(mqtt, ac)

        with patch("ac_temp_scheduler.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = self._at_minute(15, 0)
            sched._run_once()
            sched._run_once()  # same hour, should not record again

        assert mqtt.record_ac_temp.call_count == 1

    def test_records_next_hour(self):
        mqtt = MagicMock()
        ac   = MagicMock()
        ac.state.ac_real_room_temp = 22.0
        sched = AcTempScheduler(mqtt, ac)

        with patch("ac_temp_scheduler.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = self._at_minute(15, 0)
            sched._run_once()
            mock_dt.datetime.now.return_value = self._at_minute(16, 0)
            sched._run_once()

        assert mqtt.record_ac_temp.call_count == 2

    def test_skips_when_room_temp_none(self):
        mqtt = MagicMock()
        ac   = MagicMock()
        ac.state.ac_real_room_temp = None
        sched = AcTempScheduler(mqtt, ac)

        with patch("ac_temp_scheduler.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = self._at_minute(15, 0)
            sched._run_once()

        mqtt.record_ac_temp.assert_not_called()
