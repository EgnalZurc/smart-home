"""Integration tests for automatic AC control requirements."""
import time, pytest
from unittest.mock import MagicMock
from controllers.ac_controller import ACController, ControlConfig
from controllers.state_machine import ControllerState
from mqtt_handler import SensorReading


@pytest.fixture
def ctrl_with_sensors(mock_melcloud, error_tracker):
    import threading
    mqtt = MagicMock()
    mqtt.sensor_names = ["s1", "s2", "s3"]
    now = time.time()
    mqtt.readings = {
        "s1": SensorReading(25.0, 40, 100, now),
        "s2": SensorReading(26.0, 42, 100, now),
        "s3": SensorReading(24.0, 38, 100, now),
    }
    mqtt.history = {"s1": [], "s2": [], "s3": []}
    mqtt.is_connected = True
    mqtt._lock = threading.Lock()

    def get_active(max_age=3600):
        return {k: v for k, v in mqtt.readings.items()
                if time.time() - v.timestamp < max_age}
    mqtt.get_active_readings.side_effect = get_active

    config = ControlConfig(
        target_temperature=26.0,
        hysteresis_on=0.5, hysteresis_off=0.3,
        loop_interval=10, device_id=123, building_id=456,
    )
    ctrl = ACController(mqtt, mock_melcloud, config)
    ctrl.set_error_tracker(error_tracker)
    return ctrl


class TestF0AutoCoolingDecision:
    def test_ac_activates_when_temp_exceeds_threshold(self, ctrl_with_sensors, mock_melcloud):
        ctrl = ctrl_with_sensors
        now = time.time()
        ctrl.mqtt.readings = {
            "s1": SensorReading(27.5, 40, 100, now),
            "s2": SensorReading(27.5, 40, 100, now),
            "s3": SensorReading(27.5, 40, 100, now),
        }
        ctrl.set_control_mode("auto")
        ctrl._tick()
        assert mock_melcloud.set_temperature.called

    def test_ac_stays_off_when_temp_in_range(self, ctrl_with_sensors, mock_melcloud):
        ctrl = ctrl_with_sensors
        now = time.time()
        ctrl.mqtt.readings = {
            "s1": SensorReading(25.0, 40, 100, now),
            "s2": SensorReading(25.5, 40, 100, now),
            "s3": SensorReading(25.0, 40, 100, now),
        }
        mock_melcloud.set_temperature.reset_mock()
        ctrl.set_control_mode("auto")
        ctrl._tick()
        state = ctrl.state.state
        assert state in ("off", "system_off", "cooldown")

    def test_stale_sensor_data_does_not_crash(self, ctrl_with_sensors, error_tracker):
        ctrl = ctrl_with_sensors
        old_time = time.time() - 7200
        ctrl.mqtt.readings = {
            "s1": SensorReading(25.0, 40, 100, old_time),
        }
        ctrl.set_control_mode("auto")
        ctrl._tick()  # must not raise


class TestF0MelCloudErrorHandling:
    def test_melcloud_failure_increments_counter(
            self, ctrl_with_sensors, mock_melcloud, error_tracker):
        """MELCloud failures increment counter; error registered once threshold exceeded.
        _needs_melcloud_update only calls set_temperature on state changes,
        so we use threshold=1 to test with the first failure."""
        ctrl = ctrl_with_sensors
        ctrl.config.melcloud_max_failures = 1
        mock_melcloud.set_temperature.return_value = False
        now = time.time()
        ctrl.mqtt.readings = {"s1": SensorReading(27.5, 40, 100, now)}
        ctrl.mqtt.get_active_readings.return_value = {"s1": SensorReading(27.5, 40, 100, now)}
        ctrl.set_control_mode("auto")
        ctrl._tick()
        assert ctrl._consecutive_melcloud_failures >= 1, "Failure counter did not increment"
        # Run one more tick so the failure counter is fed back through the state machine
        # and melcloud_error is registered via _update_state
        now = time.time()
        ctrl.mqtt.readings = {"s1": SensorReading(26.9, 40, 100, now)}  # still hot
        ctrl.mqtt.get_active_readings.return_value = {"s1": SensorReading(26.9, 40, 100, now)}
        ctrl._tick()
        active_ids = [e["id"] for e in error_tracker.get_active()]
        assert "melcloud_error" in active_ids, f"Expected melcloud_error, got: {active_ids}"
    def test_melcloud_error_cleared_on_success(
            self, ctrl_with_sensors, mock_melcloud, error_tracker):
        ctrl = ctrl_with_sensors
        error_tracker.register("melcloud_error", "error", "test", "melcloud")
        mock_melcloud.set_temperature.return_value = True
        ctrl._consecutive_melcloud_failures = 0
        now = time.time()
        ctrl.mqtt.readings = {"s1": SensorReading(27.5, 40, 100, now)}
        ctrl.set_control_mode("auto")
        ctrl._tick()
        active_ids = [e["id"] for e in error_tracker.get_active()]
        assert "melcloud_error" not in active_ids
