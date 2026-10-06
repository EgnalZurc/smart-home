"""Unit tests for AC controller state machine."""

from controllers.state_machine import (
    ControllerState,
    ManualMode,
    ManualParams,
    StateMachineConfig,
    StateMachineInputs,
    _calculate_proportional_setpoint,
    evaluate,
)


class TestStateMachineConfig:
    """Tests for StateMachineConfig defaults."""

    def test_default_values(self):
        """Config should have sensible defaults."""
        config = StateMachineConfig()

        assert config.hysteresis_on == 0.5
        assert config.hysteresis_off == 0.3
        assert config.min_setpoint == 19.0
        assert config.max_setpoint == 30.0
        assert config.cooldown_seconds == 180
        assert config.sensor_alert_seconds == 3600


class TestProportionalSetpoint:
    """Tests for proportional setpoint calculation."""

    def test_hot_edge_returns_min_setpoint(self):
        """At hot threshold, setpoint should be minimum (max cooling)."""
        config = StateMachineConfig()
        target = 25.0
        hot_edge = target + config.hysteresis_on  # 25.5

        setpoint = _calculate_proportional_setpoint(hot_edge, target, config)

        assert setpoint == config.min_setpoint

    def test_cold_edge_returns_max_setpoint(self):
        """At cold threshold, setpoint should be maximum (min cooling)."""
        config = StateMachineConfig()
        target = 25.0
        cold_edge = target - config.hysteresis_off  # 24.7

        setpoint = _calculate_proportional_setpoint(cold_edge, target, config)

        assert setpoint == config.max_setpoint

    def test_middle_returns_intermediate(self):
        """At target temp, setpoint should be intermediate."""
        config = StateMachineConfig()
        target = 25.0

        setpoint = _calculate_proportional_setpoint(target, target, config)

        assert config.min_setpoint < setpoint < config.max_setpoint


class TestEvaluateOffState:
    """Tests for OFF state transitions."""

    def test_off_stays_off_when_cool(self):
        """Should stay OFF when temperature is below threshold."""
        config = StateMachineConfig()
        inputs = StateMachineInputs(
            average_temp=24.0,  # Below target + hysteresis
            target_temp=25.0,
            manual_mode=ManualMode.AUTO,
            manual_params=ManualParams(),
            seconds_since_last_off=1000,
            seconds_since_last_sensor_update=0,
            consecutive_melcloud_failures=0,
        )

        result = evaluate(ControllerState.OFF, inputs, config)

        assert result.state == ControllerState.OFF
        assert result.power is False

    def test_off_transitions_to_cooling_when_hot(self):
        """Should transition to COOLING_MAX when temp exceeds threshold."""
        config = StateMachineConfig()
        inputs = StateMachineInputs(
            average_temp=26.0,  # Above target + hysteresis (25.5)
            target_temp=25.0,
            manual_mode=ManualMode.AUTO,
            manual_params=ManualParams(),
            seconds_since_last_off=1000,
            seconds_since_last_sensor_update=0,
            consecutive_melcloud_failures=0,
        )

        result = evaluate(ControllerState.OFF, inputs, config)

        assert result.state == ControllerState.COOLING_MAX
        assert result.power is True
        assert result.fan_speed == 3

    def test_off_stays_off_when_no_sensor_data(self):
        """Should stay OFF when no sensor data available."""
        config = StateMachineConfig()
        inputs = StateMachineInputs(
            average_temp=None,
            target_temp=25.0,
            manual_mode=ManualMode.AUTO,
            manual_params=ManualParams(),
            seconds_since_last_off=1000,
            seconds_since_last_sensor_update=0,
            consecutive_melcloud_failures=0,
        )

        result = evaluate(ControllerState.OFF, inputs, config)

        assert result.state == ControllerState.OFF


class TestEvaluateCoolingMaxState:
    """Tests for COOLING_MAX state transitions."""

    def test_cooling_max_transitions_to_cooldown_when_cold(self):
        """Should transition to COOLDOWN when temp drops below cold threshold."""
        config = StateMachineConfig()
        inputs = StateMachineInputs(
            average_temp=24.0,  # Below target - hysteresis (24.7)
            target_temp=25.0,
            manual_mode=ManualMode.AUTO,
            manual_params=ManualParams(),
            seconds_since_last_off=1000,
            seconds_since_last_sensor_update=0,
            consecutive_melcloud_failures=0,
        )

        result = evaluate(ControllerState.COOLING_MAX, inputs, config)

        assert result.state == ControllerState.COOLDOWN
        assert result.power is False

    def test_cooling_max_transitions_to_modulating(self):
        """Should transition to MODULATING in intermediate zone."""
        config = StateMachineConfig()
        inputs = StateMachineInputs(
            average_temp=25.0,  # Between cold (24.7) and hot (25.5)
            target_temp=25.0,
            manual_mode=ManualMode.AUTO,
            manual_params=ManualParams(),
            seconds_since_last_off=1000,
            seconds_since_last_sensor_update=0,
            consecutive_melcloud_failures=0,
        )

        result = evaluate(ControllerState.COOLING_MAX, inputs, config)

        assert result.state == ControllerState.MODULATING
        assert result.power is True
        assert result.fan_speed == 0  # Auto fan in modulating

    def test_cooling_max_stays_when_still_hot(self):
        """Should stay COOLING_MAX when still above hot threshold."""
        config = StateMachineConfig()
        inputs = StateMachineInputs(
            average_temp=27.0,  # Still above threshold
            target_temp=25.0,
            manual_mode=ManualMode.AUTO,
            manual_params=ManualParams(),
            seconds_since_last_off=1000,
            seconds_since_last_sensor_update=0,
            consecutive_melcloud_failures=0,
        )

        result = evaluate(ControllerState.COOLING_MAX, inputs, config)

        assert result.state == ControllerState.COOLING_MAX


class TestEvaluateCooldownState:
    """Tests for COOLDOWN state transitions."""

    def test_cooldown_stays_during_cooldown_period(self):
        """Should stay in COOLDOWN during cooldown period."""
        config = StateMachineConfig(cooldown_seconds=180)
        inputs = StateMachineInputs(
            average_temp=26.0,
            target_temp=25.0,
            manual_mode=ManualMode.AUTO,
            manual_params=ManualParams(),
            seconds_since_last_off=100,  # Still in cooldown
            seconds_since_last_sensor_update=0,
            consecutive_melcloud_failures=0,
        )

        result = evaluate(ControllerState.COOLDOWN, inputs, config)

        assert result.state == ControllerState.COOLDOWN

    def test_cooldown_transitions_after_period(self):
        """Should transition out of COOLDOWN after period ends."""
        config = StateMachineConfig(cooldown_seconds=180)
        inputs = StateMachineInputs(
            average_temp=26.0,  # Hot
            target_temp=25.0,
            manual_mode=ManualMode.AUTO,
            manual_params=ManualParams(),
            seconds_since_last_off=200,  # Past cooldown
            seconds_since_last_sensor_update=0,
            consecutive_melcloud_failures=0,
        )

        result = evaluate(ControllerState.COOLDOWN, inputs, config)

        assert result.state == ControllerState.COOLING_MAX


class TestManualMode:
    """Tests for manual mode overrides."""

    def test_manual_off_forces_system_off(self):
        """Manual OFF mode should force SYSTEM_OFF state."""
        config = StateMachineConfig()
        inputs = StateMachineInputs(
            average_temp=30.0,  # Very hot
            target_temp=25.0,
            manual_mode=ManualMode.OFF,
            manual_params=ManualParams(),
            seconds_since_last_off=1000,
            seconds_since_last_sensor_update=0,
            consecutive_melcloud_failures=0,
        )

        result = evaluate(ControllerState.COOLING_MAX, inputs, config)

        assert result.state == ControllerState.SYSTEM_OFF
        assert result.power is False

    def test_manual_mode_uses_params(self):
        """Manual mode should use specified parameters."""
        config = StateMachineConfig()
        manual_params = ManualParams(temperature=22.0, fan_speed=2, mode="cool")
        inputs = StateMachineInputs(
            average_temp=25.0,
            target_temp=25.0,
            manual_mode=ManualMode.MANUAL,
            manual_params=manual_params,
            seconds_since_last_off=1000,
            seconds_since_last_sensor_update=0,
            consecutive_melcloud_failures=0,
        )

        result = evaluate(ControllerState.OFF, inputs, config)

        assert result.state == ControllerState.MANUAL
        assert result.power is True
        assert result.setpoint == 22.0
        assert result.fan_speed == 2
        assert result.mode == "cool"


class TestErrorConditions:
    """Tests for error conditions."""

    def test_melcloud_error_after_max_failures(self):
        """Should enter ERROR state after max MELCloud failures."""
        config = StateMachineConfig(melcloud_max_failures=100)
        inputs = StateMachineInputs(
            average_temp=26.0,
            target_temp=25.0,
            manual_mode=ManualMode.AUTO,
            manual_params=ManualParams(),
            seconds_since_last_off=1000,
            seconds_since_last_sensor_update=0,
            consecutive_melcloud_failures=100,  # At max
        )

        result = evaluate(ControllerState.COOLING_MAX, inputs, config)

        assert result.state == ControllerState.ERROR
        assert result.power is False
        assert result.melcloud_error is True

    def test_sensor_alert_flag_set(self):
        """Should set sensor_alert when sensor data is old."""
        config = StateMachineConfig(sensor_alert_seconds=3600)
        inputs = StateMachineInputs(
            average_temp=25.0,
            target_temp=25.0,
            manual_mode=ManualMode.AUTO,
            manual_params=ManualParams(),
            seconds_since_last_off=1000,
            seconds_since_last_sensor_update=4000,  # Exceeds threshold
            consecutive_melcloud_failures=0,
        )

        result = evaluate(ControllerState.OFF, inputs, config)

        assert result.sensor_alert is True


class TestModulatingState:
    """Tests for MODULATING state."""

    def test_modulating_adjusts_setpoint(self):
        """Should adjust setpoint based on temperature."""
        config = StateMachineConfig()
        inputs = StateMachineInputs(
            average_temp=25.2,  # In modulating range
            target_temp=25.0,
            manual_mode=ManualMode.AUTO,
            manual_params=ManualParams(),
            seconds_since_last_off=1000,
            seconds_since_last_sensor_update=0,
            consecutive_melcloud_failures=0,
        )

        result = evaluate(ControllerState.MODULATING, inputs, config)

        assert result.state == ControllerState.MODULATING
        assert config.min_setpoint < result.setpoint < config.max_setpoint

    def test_modulating_transitions_to_cooling_max_when_hot(self):
        """Should transition to COOLING_MAX when temp exceeds threshold."""
        config = StateMachineConfig()
        inputs = StateMachineInputs(
            average_temp=26.0,  # Above hot threshold
            target_temp=25.0,
            manual_mode=ManualMode.AUTO,
            manual_params=ManualParams(),
            seconds_since_last_off=1000,
            seconds_since_last_sensor_update=0,
            consecutive_melcloud_failures=0,
        )

        result = evaluate(ControllerState.MODULATING, inputs, config)

        assert result.state == ControllerState.COOLING_MAX
