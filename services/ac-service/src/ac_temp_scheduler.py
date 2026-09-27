"""AcTempScheduler: records AC room temperature hourly into sensor history."""

import datetime
import logging
import threading

logger = logging.getLogger(__name__)


class AcTempScheduler:
    """Records the AC room temperature once per hour, on the hour (:00).

    Wakes up every 30 seconds to check whether the current minute is 0
    and we have not already recorded for this hour-slot.
    """

    def __init__(self, mqtt_handler, ac_controller):
        self._mqtt = mqtt_handler
        self._ac   = ac_controller
        self._last_recorded_hour: int | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True, name="ac-temp-scheduler")
        self._thread.start()
        logger.info("AC temperature hourly scheduler started")

    def stop(self):
        self._stop_event.set()

    def _run_once(self):
        """Check if it is on the hour and record if so. Extracted for testability."""
        now = datetime.datetime.now()
        if now.minute == 0 and now.hour != self._last_recorded_hour:
            room_temp = self._ac.state.ac_real_room_temp
            if room_temp is not None:
                self._mqtt.record_ac_temp(room_temp)
                self._last_recorded_hour = now.hour
            else:
                logger.debug("AC room temp not available yet, skipping hour %d", now.hour)

    def _run(self):
        while not self._stop_event.is_set():
            try:
                self._run_once()
            except Exception as e:
                logger.warning("AcTempScheduler error: %s", e)
            self._stop_event.wait(30)  # check every 30s
