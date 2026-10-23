"""AC temperature scheduler.

Records the AC unit's room temperature reading once per hour into the sensor
history topic. This provides a periodic snapshot of the indoor temperature
as reported by the AC's internal thermometer, separate from the external
Zigbee sensors.

The scheduler wakes up every 30 seconds to check whether it's on the hour
(:00 minute) and publishes the temperature to MQTT if not already recorded
for that hour-slot. This data is useful for long-term analysis and for
cross-referencing with the external sensor readings.
"""

from __future__ import annotations

import datetime
import logging
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from controllers.ac_controller import ACController
    from smart_home_common.mqtt.handler import MqttHandler

logger = logging.getLogger(__name__)


class AcTempScheduler:
    """Records the AC room temperature once per hour, on the hour (:00).

    Wakes up every 30 seconds to check whether the current minute is 0
    and we have not already recorded for this hour-slot.
    """

    _mqtt: MqttHandler
    _ac: ACController
    _last_recorded_hour: int | None
    _thread: threading.Thread | None
    _stop_event: threading.Event

    def __init__(self, mqtt_handler: MqttHandler, ac_controller: ACController) -> None:
        self._mqtt = mqtt_handler
        self._ac = ac_controller
        self._last_recorded_hour = None
        self._thread = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="ac-temp-scheduler"
        )
        self._thread.start()
        logger.info("AC temperature hourly scheduler started")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _run_once(self) -> None:
        """Check if it is on the hour and record if so. Extracted for testability."""
        now = datetime.datetime.now()
        if now.minute == 0 and now.hour != self._last_recorded_hour:
            room_temp = self._ac.state.ac_real_room_temp
            if room_temp is not None:
                self._mqtt.record_ac_temp(room_temp)
                self._last_recorded_hour = now.hour
            else:
                logger.debug(
                    "AC room temp not available yet, skipping hour %d", now.hour
                )

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._run_once()
            except (AttributeError, TypeError, ValueError) as e:
                # Sensor state access or MQTT errors - log and continue
                logger.warning("AcTempScheduler error: %s", e)
            self._stop_event.wait(30)  # check every 30s
