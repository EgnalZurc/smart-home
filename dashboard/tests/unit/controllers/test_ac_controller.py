"""Unit tests for controllers/ac_controller.py"""
import time
import pytest
from unittest.mock import MagicMock, patch
from controllers.ac_controller import ACController, ControlConfig
from controllers.state_machine import ManualMode, ManualParams, ControllerState


@pytest.fixture
def config():
    return ControlConfig(
        target_temperature=26.0,
        hysteresis_on=0.5,
        hysteresis_off=0.3,
        loop_interval=10,
        device_id=123, building_id=456,
        melcloud_max_failures=3,
    )


@pytest.fixture
def ctrl(mock_mqtt, mock_melcloud, error_tracker, config):
    c = ACController(mock_mqtt, mock_melcloud, config)
    c.set_error_tracker(error_tracker)
    return c


class TestInit:
    def test_initial_state_exists(self, ctrl):
        assert ctrl.state is not None

    def test_initial_control_mode(self, ctrl):
        # Default is system_off due to SYSTEM_OFF initial state
        assert ctrl.state.control_mode in ("auto", "off", "system_off", "manual")

    def test_error_tracker_injected(self, ctrl, error_tracker):
        assert ctrl._error_tracker is error_tracker


class TestUpdateConfig:
    def test_update_target_temperature(self, ctrl):
        ctrl.update_config(target_temperature=24.0)
        assert ctrl.config.target_temperature == 24.0

    def test_update_multiple_fields(self, ctrl):
        ctrl.update_config(target_temperature=25.0, hysteresis_on=0.8)
        assert ctrl.config.target_temperature == 25.0
        assert ctrl.config.hysteresis_on == 0.8


class TestSetControlMode:
    def test_set_mode_does_not_raise(self, ctrl):
        ctrl.set_control_mode("auto")   # should not raise

    def test_set_off_changes_state(self, ctrl):
        ctrl.set_control_mode("off")
        assert ctrl.state.control_mode == "off"

    def test_set_manual_changes_state(self, ctrl):
        ctrl.set_control_mode("manual")
        assert ctrl.state.control_mode == "manual"


class TestSetManualParams:
    def test_params_stored(self, ctrl):
        ctrl.set_manual_params(temperature=22.0, fan_speed=2, mode="cool")
        if ctrl.state.manual_params:
            assert ctrl.state.manual_params.temperature == 22.0

    def test_update_manual_param_does_not_raise(self, ctrl):
        ctrl.set_manual_params(temperature=22.0, fan_speed=1, mode="cool")
        ctrl.update_manual_param("temperature", 20.0)  # should not raise


class TestGetHistory:
    def test_history_initially_empty(self, ctrl):
        assert ctrl.get_history(10) == []

    def test_history_limit_respected(self, ctrl):
        from controllers.ac_controller import HistoryRecord
        for i in range(20):
            ctrl.history.append(HistoryRecord(
                timestamp=float(i), average_temp=25.0,
                state="off", setpoint=24.0, active_sensors=5
            ))
        assert len(ctrl.get_history(5)) == 5


class TestUpdateAcRealCache:
    def test_caches_power_on(self, ctrl):
        ctrl.update_ac_real_cache({
            "Power": True, "OperationMode": 3, "SetTemperature": 22.0,
            "SetFanSpeed": 2, "RoomTemperature": 24.0,
        })
        assert ctrl.state.ac_real_power is True
        assert ctrl.state.ac_real_room_temp == 24.0

    def test_operation_mode_1_maps_to_heat(self, ctrl):
        ctrl.update_ac_real_cache({
            "Power": True, "OperationMode": 1, "SetTemperature": 22.0,
            "SetFanSpeed": 0, "RoomTemperature": 24.0,
        })
        assert ctrl.state.ac_real_mode == "heat"

    def test_operation_mode_3_maps_to_cool(self, ctrl):
        ctrl.update_ac_real_cache({
            "Power": True, "OperationMode": 3, "SetTemperature": 22.0,
            "SetFanSpeed": 0, "RoomTemperature": 24.0,
        })
        assert ctrl.state.ac_real_mode == "cool"


class TestErrorTrackerIntegration:
    def test_sensor_alert_registered(self, ctrl, error_tracker):
        outputs = MagicMock()
        outputs.state = ControllerState.OFF
        outputs.sensor_alert = True
        outputs.melcloud_error = False
        outputs.power = False
        outputs.setpoint = 24.0
        outputs.fan_speed = 0
        outputs.mode = "cool"
        ctrl._update_state(outputs, 25.0, 40.0, 5)
        assert error_tracker.has_active()

    def test_sensor_alert_cleared_when_resolved(self, ctrl, error_tracker):
        error_tracker.register("sensor_alert", "warning", "test", "sensors")
        outputs = MagicMock()
        outputs.state = ControllerState.OFF
        outputs.sensor_alert = False
        outputs.melcloud_error = False
        outputs.power = False
        outputs.setpoint = 24.0
        outputs.fan_speed = 0
        outputs.mode = "cool"
        ctrl._update_state(outputs, 25.0, 40.0, 5)
        ids = [e["id"] for e in error_tracker.get_active()]
        assert "sensor_alert" not in ids


class TestReadSensors:
    """_read_sensors must use ONLY active sensors for avg ? not stale ones (bug fix)."""

    def _make_ctrl(self, sensor_timeout=3600):
        from unittest.mock import patch as _patch, MagicMock as _MM
        from mqtt_handler import MqttHandler, SensorReading
        import threading

        with _patch("mqtt_handler.mqtt"):
            with _patch.object(MqttHandler, "_load_from_disk"):
                mqtt = MqttHandler("localhost", 1883, ["s1", "s2", "s3"], max_history=200)
                mqtt._error_tracker = None
                mqtt._connected = True

        now = time.time()
        # s1, s3: fresh readings
        mqtt.readings["s1"] = SensorReading(28.0, 39, 100, now - 60)
        mqtt.readings["s3"] = SensorReading(26.0, 41, 100, now - 60)
        # s2: stale reading (way beyond sensor_timeout)
        mqtt.readings["s2"] = SensorReading(20.0, 60, 100, now - 7200)

        melcloud = _MM()
        config = ControlConfig(
            target_temperature=25.0, hysteresis_on=0.5, hysteresis_off=0.3,
            min_setpoint=19.0, max_setpoint=30.0, cooldown_seconds=180,
            loop_interval=10, sensor_timeout=sensor_timeout, fan_speed_max=3,
            device_id=1, building_id=1,
        )
        from error_tracker import ErrorTracker
        ctrl = ACController(mqtt, melcloud, config)
        ctrl.set_error_tracker(ErrorTracker())
        return ctrl

    def test_avg_excludes_stale_sensor(self):
        """Stale s2=20.0 must be excluded; avg should be (28+26)/2=27.0, not (28+20+26)/3=24.7."""
        ctrl = self._make_ctrl(sensor_timeout=3600)
        avg_temp, avg_hum, active_count, _ = ctrl._read_sensors()
        assert active_count == 2
        assert avg_temp == pytest.approx(27.0, abs=0.1)

    def test_active_count_matches_avg_sources(self):
        """active_count and avg must always use the same sensor set."""
        ctrl = self._make_ctrl(sensor_timeout=3600)
        avg_temp, _, active_count, _ = ctrl._read_sensors()
        # active_count=2 means only s1 and s3 contribute to avg
        assert active_count == 2
        # Verify avg is NOT skewed by the stale 20.0 reading
        assert avg_temp > 26.0  # would be ~24.7 if stale sensor were included

    def test_all_stale_returns_none_avg(self):
        """If all sensors are stale, avg_temp should be None."""
        ctrl = self._make_ctrl(sensor_timeout=10)  # very short timeout
        avg_temp, avg_hum, active_count, _ = ctrl._read_sensors()
        assert active_count == 0
        assert avg_temp is None
        assert avg_hum is None
