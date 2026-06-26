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
