"""Unit tests for ACController.

Tests the main controller that orchestrates the state machine,
reads sensors, and applies outputs via MELCloud.
"""

import time
from unittest.mock import MagicMock, patch

import pytest
from controllers.ac_controller import (
    ACController,
    ControlConfig,
    ControlState,
    HistoryRecord,
)
from controllers.state_machine import (
    ControllerState,
    ManualParams,
    StateMachineOutputs,
)
from mqtt_handler import SensorReading


class TestControlConfig:
    """Tests for ControlConfig dataclass."""

    def test_default_values(self):
        """Should have sensible defaults."""
        config = ControlConfig()

        assert config.target_temperature == 26.0
        assert config.hysteresis_on == 0.5
        assert config.hysteresis_off == 0.3
        assert config.min_setpoint == 19.0
        assert config.max_setpoint == 30.0
        assert config.cooldown_seconds == 180
        assert config.loop_interval == 45
        assert config.sensor_timeout == 600

    def test_custom_values(self):
        """Should accept custom values."""
        config = ControlConfig(
            target_temperature=24.0,
            hysteresis_on=0.6,
            cooldown_seconds=300,
            device_id=12345,
            building_id=67890,
        )

        assert config.target_temperature == 24.0
        assert config.hysteresis_on == 0.6
        assert config.cooldown_seconds == 300
        assert config.device_id == 12345
        assert config.building_id == 67890


class TestControlState:
    """Tests for ControlState dataclass."""

    def test_default_values(self):
        """Should have safe defaults."""
        state = ControlState()

        assert state.state == "off"
        assert state.setpoint == 24.0
        assert state.average_temp is None
        assert state.average_humidity is None
        assert state.active_sensors == 0
        assert state.control_mode == "auto"
        assert state.sensor_alert is False
        assert state.melcloud_error is False


class TestACControllerInit:
    """Tests for ACController initialization."""

    def test_init_stores_dependencies(self):
        """Should store mqtt handler, melcloud client, and config."""
        mock_mqtt = MagicMock()
        mock_melcloud = MagicMock()
        config = ControlConfig()

        controller = ACController(mock_mqtt, mock_melcloud, config)

        assert controller.mqtt is mock_mqtt
        assert controller.melcloud is mock_melcloud
        assert controller.config is config

    def test_init_sets_manual_params_defaults(self):
        """Should initialize manual_params with defaults."""
        mock_mqtt = MagicMock()
        mock_melcloud = MagicMock()
        config = ControlConfig()

        controller = ACController(mock_mqtt, mock_melcloud, config)

        assert controller.state.manual_params is not None
        assert controller.state.manual_params.temperature == 23.0
        assert controller.state.manual_params.fan_speed == 0
        assert controller.state.manual_params.mode == "cool"


class TestACControllerControlMode:
    """Tests for control mode management."""

    def test_set_control_mode_auto(self):
        """Should set control mode to auto."""
        mock_mqtt = MagicMock()
        mock_melcloud = MagicMock()
        config = ControlConfig()

        controller = ACController(mock_mqtt, mock_melcloud, config)

        with patch.object(controller, "_persist_state"):
            controller.set_control_mode("auto")

        assert controller.state.control_mode == "auto"

    def test_set_control_mode_manual(self):
        """Should set control mode to manual."""
        mock_mqtt = MagicMock()
        mock_melcloud = MagicMock()
        config = ControlConfig()

        controller = ACController(mock_mqtt, mock_melcloud, config)

        with patch.object(controller, "_persist_state"):
            controller.set_control_mode("manual")

        assert controller.state.control_mode == "manual"

    def test_set_control_mode_off(self):
        """Should set control mode to off."""
        mock_mqtt = MagicMock()
        mock_melcloud = MagicMock()
        config = ControlConfig()

        controller = ACController(mock_mqtt, mock_melcloud, config)

        with patch.object(controller, "_persist_state"):
            controller.set_control_mode("off")

        assert controller.state.control_mode == "off"


class TestACControllerManualParams:
    """Tests for manual parameters management."""

    def test_set_manual_params(self):
        """Should set all manual parameters."""
        mock_mqtt = MagicMock()
        mock_melcloud = MagicMock()
        config = ControlConfig()

        controller = ACController(mock_mqtt, mock_melcloud, config)

        with patch.object(controller, "_persist_state"):
            controller.set_manual_params(
                temperature=22.0,
                fan_speed=2,
                mode="heat",
            )

        assert controller.state.manual_params.temperature == 22.0
        assert controller.state.manual_params.fan_speed == 2
        assert controller.state.manual_params.mode == "heat"

    def test_update_manual_param_temperature(self):
        """Should update only temperature."""
        mock_mqtt = MagicMock()
        mock_melcloud = MagicMock()
        config = ControlConfig()

        controller = ACController(mock_mqtt, mock_melcloud, config)
        controller.state.manual_params = ManualParams(
            temperature=23.0, fan_speed=1, mode="cool"
        )

        with patch.object(controller, "_persist_state"):
            controller.update_manual_param("temperature", 25.0)

        assert controller.state.manual_params.temperature == 25.0
        assert controller.state.manual_params.fan_speed == 1  # Unchanged
        assert controller.state.manual_params.mode == "cool"  # Unchanged

    def test_update_manual_param_fan_speed(self):
        """Should update only fan speed."""
        mock_mqtt = MagicMock()
        mock_melcloud = MagicMock()
        config = ControlConfig()

        controller = ACController(mock_mqtt, mock_melcloud, config)
        controller.state.manual_params = ManualParams(
            temperature=23.0, fan_speed=1, mode="cool"
        )

        with patch.object(controller, "_persist_state"):
            controller.update_manual_param("fan_speed", 3)

        assert controller.state.manual_params.fan_speed == 3
        assert controller.state.manual_params.temperature == 23.0  # Unchanged

    def test_update_manual_param_mode(self):
        """Should update only mode."""
        mock_mqtt = MagicMock()
        mock_melcloud = MagicMock()
        config = ControlConfig()

        controller = ACController(mock_mqtt, mock_melcloud, config)
        controller.state.manual_params = ManualParams(
            temperature=23.0, fan_speed=1, mode="cool"
        )

        with patch.object(controller, "_persist_state"):
            controller.update_manual_param("mode", "heat")

        assert controller.state.manual_params.mode == "heat"
        assert controller.state.manual_params.temperature == 23.0  # Unchanged


class TestACControllerConfig:
    """Tests for configuration updates."""

    def test_update_config(self):
        """Should update configuration parameters."""
        mock_mqtt = MagicMock()
        mock_melcloud = MagicMock()
        config = ControlConfig(target_temperature=26.0)

        controller = ACController(mock_mqtt, mock_melcloud, config)

        with patch.object(controller, "_persist_state"):
            controller.update_config(target_temperature=24.0, hysteresis_on=0.6)

        assert controller.config.target_temperature == 24.0
        assert controller.config.hysteresis_on == 0.6


class TestACControllerHistory:
    """Tests for history management."""

    def test_get_history_returns_records(self):
        """Should return history records as dicts."""
        mock_mqtt = MagicMock()
        mock_melcloud = MagicMock()
        config = ControlConfig()

        controller = ACController(mock_mqtt, mock_melcloud, config)
        controller.history = [
            HistoryRecord(
                timestamp=1000.0,
                average_temp=25.0,
                state="cooling_max",
                setpoint=19.0,
                active_sensors=3,
            ),
            HistoryRecord(
                timestamp=2000.0,
                average_temp=24.5,
                state="modulating",
                setpoint=22.0,
                active_sensors=3,
            ),
        ]

        history = controller.get_history(limit=10)

        assert len(history) == 2
        assert history[0]["timestamp"] == 1000.0
        assert history[1]["state"] == "modulating"

    def test_get_history_respects_limit(self):
        """Should respect limit parameter."""
        mock_mqtt = MagicMock()
        mock_melcloud = MagicMock()
        config = ControlConfig()

        controller = ACController(mock_mqtt, mock_melcloud, config)
        controller.history = [
            HistoryRecord(i, 25.0, "off", 24.0, 3) for i in range(100)
        ]

        history = controller.get_history(limit=5)

        assert len(history) == 5


class TestACControllerAcRealCache:
    """Tests for AC real state cache."""

    def test_update_ac_real_cache(self):
        """Should update AC real state from MELCloud data."""
        mock_mqtt = MagicMock()
        mock_melcloud = MagicMock()
        config = ControlConfig()

        controller = ACController(mock_mqtt, mock_melcloud, config)

        melcloud_data = {
            "Power": True,
            "OperationMode": 3,  # COOL
            "SetFanSpeed": 2,
            "SetTemperature": 23.0,
            "RoomTemperature": 25.5,
        }

        controller.update_ac_real_cache(melcloud_data)

        assert controller.state.ac_real_power is True
        assert controller.state.ac_real_mode == "cool"
        assert controller.state.ac_real_fan_speed == 2
        assert controller.state.ac_real_setpoint == 23.0
        assert controller.state.ac_real_room_temp == 25.5

    def test_update_ac_real_cache_handles_none(self):
        """Should handle None data gracefully."""
        mock_mqtt = MagicMock()
        mock_melcloud = MagicMock()
        config = ControlConfig()

        controller = ACController(mock_mqtt, mock_melcloud, config)

        # Should not raise
        controller.update_ac_real_cache(None)

    def test_update_ac_real_cache_maps_modes(self):
        """Should map MELCloud mode codes to strings."""
        mock_mqtt = MagicMock()
        mock_melcloud = MagicMock()
        config = ControlConfig()

        controller = ACController(mock_mqtt, mock_melcloud, config)

        # Test heat mode (1)
        controller.update_ac_real_cache({"OperationMode": 1})
        assert controller.state.ac_real_mode == "heat"

        # Test dry mode (2)
        controller.update_ac_real_cache({"OperationMode": 2})
        assert controller.state.ac_real_mode == "dry"

        # Test auto mode (8)
        controller.update_ac_real_cache({"OperationMode": 8})
        assert controller.state.ac_real_mode == "auto"


class TestACControllerEnergy:
    """Tests for energy tracking."""

    def test_get_session_kwh_initial(self):
        """Should return 0 initially."""
        mock_mqtt = MagicMock()
        mock_melcloud = MagicMock()
        config = ControlConfig()

        controller = ACController(mock_mqtt, mock_melcloud, config)

        kwh = controller.get_session_kwh()

        assert kwh == 0.0

    def test_get_power_for_state(self):
        """Should return correct power for each state."""
        mock_mqtt = MagicMock()
        mock_melcloud = MagicMock()
        config = ControlConfig(
            ac_power_cooling_max=2.5,
            ac_power_modulating=1.25,
        )

        controller = ACController(mock_mqtt, mock_melcloud, config)

        assert controller._get_power_for_state("cooling_max") == 2.5
        assert controller._get_power_for_state("modulating") == 1.25
        assert controller._get_power_for_state("off") == 0.0
        assert controller._get_power_for_state("unknown") == 0.0

    def test_reset_session_kwh(self):
        """Should reset accumulated energy."""
        mock_mqtt = MagicMock()
        mock_melcloud = MagicMock()
        config = ControlConfig()

        controller = ACController(mock_mqtt, mock_melcloud, config)
        controller._energy_state["kwh_session"] = 5.0

        controller.reset_session_kwh()

        assert controller._energy_state["kwh_session"] == 0.0


class TestACControllerNeedsMelcloudUpdate:
    """Tests for _needs_melcloud_update logic."""

    def test_needs_update_when_no_previous(self):
        """Should need update when no previous outputs."""
        mock_mqtt = MagicMock()
        mock_melcloud = MagicMock()
        config = ControlConfig()

        controller = ACController(mock_mqtt, mock_melcloud, config)
        controller._last_outputs = None

        outputs = StateMachineOutputs(
            state=ControllerState.COOLING_MAX,
            power=True,
            mode="cool",
            setpoint=19.0,
            fan_speed=3,
            sensor_alert=False,
            melcloud_error=False,
        )

        assert controller._needs_melcloud_update(outputs) is True

    def test_needs_update_when_power_changes(self):
        """Should need update when power changes."""
        mock_mqtt = MagicMock()
        mock_melcloud = MagicMock()
        config = ControlConfig()

        controller = ACController(mock_mqtt, mock_melcloud, config)
        controller._last_outputs = StateMachineOutputs(
            state=ControllerState.OFF,
            power=False,
            mode="cool",
            setpoint=24.0,
            fan_speed=0,
            sensor_alert=False,
            melcloud_error=False,
        )

        outputs = StateMachineOutputs(
            state=ControllerState.COOLING_MAX,
            power=True,  # Changed
            mode="cool",
            setpoint=24.0,
            fan_speed=0,
            sensor_alert=False,
            melcloud_error=False,
        )

        assert controller._needs_melcloud_update(outputs) is True

    def test_needs_update_when_setpoint_changes(self):
        """Should need update when setpoint changes."""
        mock_mqtt = MagicMock()
        mock_melcloud = MagicMock()
        config = ControlConfig()

        controller = ACController(mock_mqtt, mock_melcloud, config)
        controller._last_outputs = StateMachineOutputs(
            state=ControllerState.MODULATING,
            power=True,
            mode="cool",
            setpoint=22.0,
            fan_speed=0,
            sensor_alert=False,
            melcloud_error=False,
        )

        outputs = StateMachineOutputs(
            state=ControllerState.MODULATING,
            power=True,
            mode="cool",
            setpoint=23.0,  # Changed
            fan_speed=0,
            sensor_alert=False,
            melcloud_error=False,
        )

        assert controller._needs_melcloud_update(outputs) is True

    def test_no_update_when_same(self):
        """Should not need update when outputs are same."""
        mock_mqtt = MagicMock()
        mock_melcloud = MagicMock()
        config = ControlConfig()

        controller = ACController(mock_mqtt, mock_melcloud, config)
        outputs = StateMachineOutputs(
            state=ControllerState.MODULATING,
            power=True,
            mode="cool",
            setpoint=22.0,
            fan_speed=0,
            sensor_alert=False,
            melcloud_error=False,
        )
        controller._last_outputs = outputs

        assert controller._needs_melcloud_update(outputs) is False


class TestACControllerCurrentState:
    """Tests for current_state property."""

    def test_current_state_returns_state(self):
        """Should return current state with thread safety."""
        mock_mqtt = MagicMock()
        mock_melcloud = MagicMock()
        config = ControlConfig()

        controller = ACController(mock_mqtt, mock_melcloud, config)
        controller.state.average_temp = 25.5
        controller.state.state = "cooling_max"

        state = controller.current_state

        assert state.average_temp == 25.5
        assert state.state == "cooling_max"


class TestACControllerReadSensors:
    """Tests for _read_sensors method."""

    def test_read_sensors_calculates_averages(self):
        """Should calculate average temperature and humidity."""
        mock_mqtt = MagicMock()
        mock_melcloud = MagicMock()
        config = ControlConfig(sensor_timeout=600)

        controller = ACController(mock_mqtt, mock_melcloud, config)

        # Mock sensor readings

        now = time.time()
        mock_mqtt.get_active_readings.return_value = {
            "S1": SensorReading(24.0, 50.0, 90, now),
            "S2": SensorReading(26.0, 60.0, 80, now),
        }

        avg_temp, avg_hum, active_count, last_time = controller._read_sensors()

        assert avg_temp == 25.0  # (24 + 26) / 2
        assert avg_hum == 55.0  # (50 + 60) / 2
        assert active_count == 2

    def test_read_sensors_excludes_ac_virtual_sensor(self):
        """Should exclude AC virtual sensor from averages."""
        mock_mqtt = MagicMock()
        mock_melcloud = MagicMock()
        config = ControlConfig(sensor_timeout=600)

        controller = ACController(mock_mqtt, mock_melcloud, config)

        now = time.time()
        mock_mqtt.get_active_readings.return_value = {
            "S1": SensorReading(24.0, 50.0, 90, now),
            "AC": SensorReading(28.0, None, None, now),  # Should be excluded
        }

        avg_temp, avg_hum, active_count, last_time = controller._read_sensors()

        assert avg_temp == 24.0  # Only S1
        assert active_count == 1  # AC excluded

    def test_read_sensors_empty_returns_none(self):
        """Should return None when no sensors available."""
        mock_mqtt = MagicMock()
        mock_melcloud = MagicMock()
        config = ControlConfig()

        controller = ACController(mock_mqtt, mock_melcloud, config)
        mock_mqtt.get_active_readings.return_value = {}

        avg_temp, avg_hum, active_count, last_time = controller._read_sensors()

        assert avg_temp is None
        assert avg_hum is None
        assert active_count == 0


class TestACControllerBuildInputs:
    """Tests for _build_inputs method."""

    def test_build_inputs_auto_mode(self):
        """Should build inputs for auto mode."""
        mock_mqtt = MagicMock()
        mock_melcloud = MagicMock()
        config = ControlConfig(target_temperature=25.0)

        controller = ACController(mock_mqtt, mock_melcloud, config)
        controller.state.control_mode = "auto"
        controller._last_sensor_update_time = 100.0

        with patch("time.time", return_value=200.0):
            inputs = controller._build_inputs(25.0, 150.0)

        assert inputs.average_temp == 25.0
        assert inputs.target_temp == 25.0
        assert inputs.manual_mode.value == "auto"

    def test_build_inputs_manual_mode(self):
        """Should build inputs for manual mode."""
        mock_mqtt = MagicMock()
        mock_melcloud = MagicMock()
        config = ControlConfig()

        controller = ACController(mock_mqtt, mock_melcloud, config)
        controller.state.control_mode = "manual"
        controller.state.manual_params = ManualParams(
            temperature=22.0, fan_speed=2, mode="cool"
        )

        inputs = controller._build_inputs(25.0, 100.0)

        assert inputs.manual_mode.value == "manual"
        assert inputs.manual_params.temperature == 22.0

    def test_build_inputs_off_mode(self):
        """Should build inputs for off mode."""
        mock_mqtt = MagicMock()
        mock_melcloud = MagicMock()
        config = ControlConfig()

        controller = ACController(mock_mqtt, mock_melcloud, config)
        controller.state.control_mode = "off"

        inputs = controller._build_inputs(25.0, 100.0)

        assert inputs.manual_mode.value == "off"


class TestACControllerBuildSmConfig:
    """Tests for _build_sm_config method."""

    def test_build_sm_config(self):
        """Should create StateMachineConfig from ControlConfig."""
        mock_mqtt = MagicMock()
        mock_melcloud = MagicMock()
        config = ControlConfig(
            hysteresis_on=0.6,
            hysteresis_off=0.4,
            min_setpoint=18.0,
            max_setpoint=31.0,
            cooldown_seconds=200,
            sensor_timeout=1800,
            melcloud_max_failures=50,
        )

        controller = ACController(mock_mqtt, mock_melcloud, config)
        sm_config = controller._build_sm_config()

        assert sm_config.hysteresis_on == 0.6
        assert sm_config.hysteresis_off == 0.4
        assert sm_config.min_setpoint == 18.0
        assert sm_config.max_setpoint == 31.0
        assert sm_config.cooldown_seconds == 200
        assert sm_config.sensor_alert_seconds == 1800
        assert sm_config.melcloud_max_failures == 50


class TestACControllerApplyOutputs:
    """Tests for _apply_outputs method."""

    def test_apply_outputs_sends_to_melcloud(self):
        """Should send command to MELCloud when outputs change."""
        mock_mqtt = MagicMock()
        mock_melcloud = MagicMock()
        mock_melcloud.set_temperature.return_value = True
        config = ControlConfig(device_id=123)

        controller = ACController(mock_mqtt, mock_melcloud, config)
        controller._last_outputs = None

        outputs = StateMachineOutputs(
            state=ControllerState.COOLING_MAX,
            power=True,
            mode="cool",
            setpoint=19.0,
            fan_speed=3,
            sensor_alert=False,
            melcloud_error=False,
        )

        controller._apply_outputs(outputs)

        mock_melcloud.set_temperature.assert_called_once_with(
            123, 19.0, power=True, mode="cool", fan_speed=3
        )
        assert controller._consecutive_melcloud_failures == 0

    def test_apply_outputs_increments_failures_on_error(self):
        """Should increment failure count on MELCloud error."""
        mock_mqtt = MagicMock()
        mock_melcloud = MagicMock()
        mock_melcloud.set_temperature.return_value = False
        config = ControlConfig()

        controller = ACController(mock_mqtt, mock_melcloud, config)
        controller._last_outputs = None
        controller._consecutive_melcloud_failures = 0

        outputs = StateMachineOutputs(
            state=ControllerState.COOLING_MAX,
            power=True,
            mode="cool",
            setpoint=19.0,
            fan_speed=3,
            sensor_alert=False,
            melcloud_error=False,
        )

        controller._apply_outputs(outputs)

        assert controller._consecutive_melcloud_failures == 1

    def test_apply_outputs_skips_error_state(self):
        """Should not send command when in ERROR state."""
        mock_mqtt = MagicMock()
        mock_melcloud = MagicMock()
        config = ControlConfig()

        controller = ACController(mock_mqtt, mock_melcloud, config)

        outputs = StateMachineOutputs(
            state=ControllerState.ERROR,
            power=False,
            mode="cool",
            setpoint=24.0,
            fan_speed=0,
            sensor_alert=False,
            melcloud_error=True,
        )

        controller._apply_outputs(outputs)

        mock_melcloud.set_temperature.assert_not_called()
        assert controller._current_sm_state == ControllerState.ERROR

    def test_apply_outputs_records_off_time(self):
        """Should record off timestamp when AC turns off."""
        mock_mqtt = MagicMock()
        mock_melcloud = MagicMock()
        mock_melcloud.set_temperature.return_value = True
        config = ControlConfig(cooldown_seconds=180)

        controller = ACController(mock_mqtt, mock_melcloud, config)
        controller._current_sm_state = ControllerState.COOLING_MAX
        controller._last_outputs = None

        outputs = StateMachineOutputs(
            state=ControllerState.COOLDOWN,
            power=False,
            mode="cool",
            setpoint=24.0,
            fan_speed=0,
            sensor_alert=False,
            melcloud_error=False,
        )

        with patch("time.time", return_value=1234567890.0):
            controller._apply_outputs(outputs)

        assert controller._last_off_time == 1234567890.0


class TestACControllerUpdateState:
    """Tests for _update_state method."""

    def test_update_state_updates_visible_state(self):
        """Should update all visible state fields."""
        mock_mqtt = MagicMock()
        mock_melcloud = MagicMock()
        config = ControlConfig()

        controller = ACController(mock_mqtt, mock_melcloud, config)

        outputs = StateMachineOutputs(
            state=ControllerState.MODULATING,
            power=True,
            mode="cool",
            setpoint=22.0,
            fan_speed=0,
            sensor_alert=False,
            melcloud_error=False,
        )

        controller._update_state(outputs, 25.0, 55.0, 3)

        assert controller.state.state == "modulating"
        assert controller.state.setpoint == 22.0
        assert controller.state.average_temp == 25.0
        assert controller.state.average_humidity == 55.0
        assert controller.state.active_sensors == 3

    def test_update_state_registers_errors(self):
        """Should register errors in error tracker."""
        mock_mqtt = MagicMock()
        mock_melcloud = MagicMock()
        config = ControlConfig()

        controller = ACController(mock_mqtt, mock_melcloud, config)
        mock_tracker = MagicMock()
        controller._error_tracker = mock_tracker

        outputs = StateMachineOutputs(
            state=ControllerState.OFF,
            power=False,
            mode="cool",
            setpoint=24.0,
            fan_speed=0,
            sensor_alert=True,
            melcloud_error=True,
        )

        controller._update_state(outputs, 25.0, 55.0, 0)

        # Should register both errors
        assert mock_tracker.register.call_count == 2

    def test_update_state_clears_errors(self):
        """Should clear errors when resolved."""
        mock_mqtt = MagicMock()
        mock_melcloud = MagicMock()
        config = ControlConfig()

        controller = ACController(mock_mqtt, mock_melcloud, config)
        mock_tracker = MagicMock()
        controller._error_tracker = mock_tracker

        outputs = StateMachineOutputs(
            state=ControllerState.OFF,
            power=False,
            mode="cool",
            setpoint=24.0,
            fan_speed=0,
            sensor_alert=False,
            melcloud_error=False,
        )

        controller._update_state(outputs, 25.0, 55.0, 3)

        # Should clear both errors
        assert mock_tracker.clear.call_count == 2

    def test_update_state_limits_history(self):
        """Should limit history size."""
        mock_mqtt = MagicMock()
        mock_melcloud = MagicMock()
        config = ControlConfig()

        controller = ACController(mock_mqtt, mock_melcloud, config)
        # Fill history to limit
        controller.history = [
            HistoryRecord(i, 25.0, "off", 24.0, 3) for i in range(1001)
        ]

        outputs = StateMachineOutputs(
            state=ControllerState.OFF,
            power=False,
            mode="cool",
            setpoint=24.0,
            fan_speed=0,
            sensor_alert=False,
            melcloud_error=False,
        )

        controller._update_state(outputs, 25.0, 55.0, 3)

        # Code trims to 500 when > 1000, then adds 1 = 501, but then
        # the slice already brings to 500. Let's check it's bounded.
        assert len(controller.history) <= 501


class TestACControllerTrackEnergy:
    """Tests for energy tracking methods."""

    def test_track_energy_transition(self):
        """Should track energy on state transitions."""
        mock_mqtt = MagicMock()
        mock_melcloud = MagicMock()
        config = ControlConfig(ac_power_cooling_max=2.5)

        controller = ACController(mock_mqtt, mock_melcloud, config)
        controller._energy_state = {
            "last_state": "cooling_max",
            "last_transition": 1000.0,
            "kwh_session": 0.0,
        }

        # Simulate 1 hour of cooling_max (2.5 kW)
        with patch("time.time", return_value=4600.0):  # 1 hour later
            controller._track_energy_transition("off")

        # 2.5 kW * 1 hour = 2.5 kWh
        assert controller._energy_state["kwh_session"] == pytest.approx(2.5, rel=0.01)
        assert controller._energy_state["last_state"] == "off"
