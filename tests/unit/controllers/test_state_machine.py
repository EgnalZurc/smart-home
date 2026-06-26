"""Unit tests for controllers/state_machine.py ? pure function, no mocking needed."""
import pytest
from controllers.state_machine import (
    ControllerState, ManualMode, ManualParams,
    StateMachineConfig, StateMachineInputs, evaluate,
)


@pytest.fixture
def cfg():
    return StateMachineConfig(
        hysteresis_on=0.5, hysteresis_off=0.3,
        min_setpoint=19.0, max_setpoint=30.0,
        cooldown_seconds=180, sensor_alert_seconds=3600,
        melcloud_max_failures=100,
    )


def make_inputs(avg_temp=25.0, state=ControllerState.OFF,
                seconds_since_off=9999, manual_mode=ManualMode.AUTO,
                manual_params=None, melcloud_failures=0,
                seconds_since_sensor=0):
    # StateMachineInputs does NOT include current_state (passed separately to evaluate())
    return StateMachineInputs(
        average_temp=avg_temp,
        target_temp=26.0,
        seconds_since_last_off=seconds_since_off,
        manual_mode=manual_mode,
        manual_params=manual_params,
        consecutive_melcloud_failures=melcloud_failures,
        seconds_since_last_sensor_update=seconds_since_sensor,
    )


class TestTransitionsFromOff:
    def test_stays_off_when_cool(self, cfg):
        inputs = make_inputs(avg_temp=25.5, state=ControllerState.OFF)  # below hot_threshold 26.5
        out = evaluate(ControllerState.OFF, inputs, cfg, 24.0)
        assert out.state == ControllerState.OFF

    def test_goes_cooling_max_when_hot(self, cfg):
        inputs = make_inputs(avg_temp=27.0, state=ControllerState.OFF)  # above 26.5
        out = evaluate(ControllerState.OFF, inputs, cfg, 24.0)
        assert out.state == ControllerState.COOLING_MAX

    def test_stays_off_with_no_sensor_data(self, cfg):
        inputs = make_inputs(avg_temp=None, state=ControllerState.OFF)
        out = evaluate(ControllerState.OFF, inputs, cfg, 24.0)
        assert out.state == ControllerState.OFF


class TestTransitionsFromCoolingMax:
    def test_goes_cooldown_when_cold(self, cfg):
        inputs = make_inputs(avg_temp=25.5, state=ControllerState.COOLING_MAX)  # below cold 25.7
        out = evaluate(ControllerState.COOLING_MAX, inputs, cfg, 24.0)
        assert out.state == ControllerState.COOLDOWN

    def test_goes_modulating_when_in_range(self, cfg):
        inputs = make_inputs(avg_temp=26.0, state=ControllerState.COOLING_MAX)  # 25.7 < 26 < 26.5
        out = evaluate(ControllerState.COOLING_MAX, inputs, cfg, 24.0)
        assert out.state == ControllerState.MODULATING

    def test_stays_cooling_max_when_still_hot(self, cfg):
        inputs = make_inputs(avg_temp=27.5, state=ControllerState.COOLING_MAX)
        out = evaluate(ControllerState.COOLING_MAX, inputs, cfg, 24.0)
        assert out.state == ControllerState.COOLING_MAX

    def test_stays_cooling_max_with_no_sensor(self, cfg):
        inputs = make_inputs(avg_temp=None, state=ControllerState.COOLING_MAX)
        out = evaluate(ControllerState.COOLING_MAX, inputs, cfg, 24.0)
        assert out.state == ControllerState.COOLING_MAX
        assert out.power is True


class TestTransitionsFromModulating:
    def test_goes_cooling_max_when_hot(self, cfg):
        inputs = make_inputs(avg_temp=27.0, state=ControllerState.MODULATING)
        out = evaluate(ControllerState.MODULATING, inputs, cfg, 24.0)
        assert out.state == ControllerState.COOLING_MAX

    def test_goes_cooldown_when_cold(self, cfg):
        inputs = make_inputs(avg_temp=25.5, state=ControllerState.MODULATING)
        out = evaluate(ControllerState.MODULATING, inputs, cfg, 24.0)
        assert out.state == ControllerState.COOLDOWN

    def test_stays_modulating_in_range(self, cfg):
        inputs = make_inputs(avg_temp=26.0, state=ControllerState.MODULATING)
        out = evaluate(ControllerState.MODULATING, inputs, cfg, 24.0)
        assert out.state == ControllerState.MODULATING
        assert out.power is True

    def test_setpoint_proportional_near_hot_edge(self, cfg):
        # Near hot_threshold (26.5) ? low setpoint (max cooling)
        inputs = make_inputs(avg_temp=26.4, state=ControllerState.MODULATING)
        out = evaluate(ControllerState.MODULATING, inputs, cfg, 24.0)
        assert out.setpoint <= 22.0  # proportional, near max cooling

    def test_setpoint_proportional_near_cold_edge(self, cfg):
        # Near cold_threshold (25.7) ? high setpoint (min cooling)
        inputs = make_inputs(avg_temp=25.8, state=ControllerState.MODULATING)
        out = evaluate(ControllerState.MODULATING, inputs, cfg, 24.0)
        assert out.setpoint >= 26.0  # proportional, near min cooling


class TestTransitionsFromCooldown:
    def test_stays_cooldown_before_time(self, cfg):
        inputs = make_inputs(avg_temp=25.0, state=ControllerState.COOLDOWN,
                             seconds_since_off=60)  # 180s not done
        out = evaluate(ControllerState.COOLDOWN, inputs, cfg, 24.0)
        assert out.state == ControllerState.COOLDOWN
        assert out.power is False

    def test_goes_cooling_max_after_cooldown_if_hot(self, cfg):
        inputs = make_inputs(avg_temp=27.0, state=ControllerState.COOLDOWN,
                             seconds_since_off=200)  # cooldown done
        out = evaluate(ControllerState.COOLDOWN, inputs, cfg, 24.0)
        assert out.state == ControllerState.COOLING_MAX

    def test_goes_off_after_cooldown_if_cool(self, cfg):
        inputs = make_inputs(avg_temp=25.0, state=ControllerState.COOLDOWN,
                             seconds_since_off=200)
        out = evaluate(ControllerState.COOLDOWN, inputs, cfg, 24.0)
        assert out.state == ControllerState.OFF


class TestManualMode:
    def test_manual_mode_forces_manual_state(self, cfg):
        params = ManualParams(temperature=22.0, fan_speed=2, mode="cool")
        inputs = make_inputs(manual_mode=ManualMode.MANUAL, manual_params=params)
        out = evaluate(ControllerState.OFF, inputs, cfg, 24.0)
        assert out.state == ControllerState.MANUAL
        assert out.power is True
        assert out.setpoint == 22.0
        assert out.fan_speed == 2

    def test_off_mode_forces_system_off(self, cfg):
        inputs = make_inputs(manual_mode=ManualMode.OFF)
        out = evaluate(ControllerState.COOLING_MAX, inputs, cfg, 24.0)
        assert out.state == ControllerState.SYSTEM_OFF
        assert out.power is False


class TestErrorState:
    def test_melcloud_errors_trigger_error_state(self, cfg):
        inputs = make_inputs(melcloud_failures=100)
        out = evaluate(ControllerState.COOLING_MAX, inputs, cfg, 24.0)
        assert out.state == ControllerState.ERROR
        assert out.power is False
        assert out.melcloud_error is True

    def test_below_threshold_no_error(self, cfg):
        inputs = make_inputs(melcloud_failures=99)
        out = evaluate(ControllerState.OFF, inputs, cfg, 24.0)
        assert out.state != ControllerState.ERROR


class TestSensorAlert:
    def test_sensor_alert_set_when_stale(self, cfg):
        inputs = make_inputs(seconds_since_sensor=3601)
        out = evaluate(ControllerState.OFF, inputs, cfg, 24.0)
        assert out.sensor_alert is True

    def test_no_sensor_alert_when_fresh(self, cfg):
        inputs = make_inputs(seconds_since_sensor=100)
        out = evaluate(ControllerState.OFF, inputs, cfg, 24.0)
        assert out.sensor_alert is False

    def test_sensor_alert_does_not_change_state(self, cfg):
        # Sensor alert is informational only ? state transitions still work normally
        inputs = make_inputs(avg_temp=27.0, state=ControllerState.OFF, seconds_since_sensor=9999)
        out = evaluate(ControllerState.OFF, inputs, cfg, 24.0)
        assert out.state == ControllerState.COOLING_MAX
        assert out.sensor_alert is True


class TestOutputShape:
    def test_all_outputs_present(self, cfg):
        inputs = make_inputs()
        out = evaluate(ControllerState.OFF, inputs, cfg, 24.0)
        assert hasattr(out, "state")
        assert hasattr(out, "power")
        assert hasattr(out, "setpoint")
        assert hasattr(out, "fan_speed")
        # ac_mode not in outputs, field is "mode"
        assert hasattr(out, "mode")
        assert hasattr(out, "sensor_alert")
        assert hasattr(out, "melcloud_error")
