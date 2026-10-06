"""Unit tests for ac_controller.py - virtual thermostat controller."""

import time
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_mqtt():
    """Create mock MqttHandler."""
    mqtt = MagicMock()
    mqtt.get_active_readings.return_value = {}
    return mqtt


@pytest.fixture
def mock_melcloud():
    """Create mock MelCloudClient."""
    melcloud = MagicMock()
    melcloud.set_temperature.return_value = True
    return melcloud


@pytest.fixture
def controller(mock_mqtt, mock_melcloud):
    """Create ACController with mocked dependencies."""
    from controllers.ac_controller import ACController, ControlConfig

    config = ControlConfig(
        target_temperature=25.0,
        hysteresis_on=0.5,
        hysteresis_off=0.3,
        loop_interval=1,  # Fast for tests
    )

    ctrl = ACController(
        mqtt_handler=mock_mqtt,
        melcloud=mock_melcloud,
        config=config,
    )
    yield ctrl
    ctrl.stop()


class TestControlConfig:
    def test_defaults(self):
        from controllers.ac_controller import ControlConfig

        config = ControlConfig()

        assert config.target_temperature == 26.0
        assert config.hysteresis_on == 0.5
        assert config.hysteresis_off == 0.3
        assert config.min_setpoint == 19.0
        assert config.max_setpoint == 30.0


class TestControlState:
    def test_defaults(self):
        from controllers.ac_controller import ControlState

        state = ControlState()

        assert state.state == "off"
        assert state.control_mode == "auto"
        assert state.average_temp is None


class TestACControllerInit:
    def test_init_sets_attributes(self, mock_mqtt, mock_melcloud):
        from controllers.ac_controller import ACController, ControlConfig

        config = ControlConfig(target_temperature=24.0)
        ctrl = ACController(mock_mqtt, mock_melcloud, config)

        assert ctrl.mqtt is mock_mqtt
        assert ctrl.melcloud is mock_melcloud
        assert ctrl.config.target_temperature == 24.0
        assert ctrl.state.control_mode == "auto"

    def test_manual_params_initialized(self, controller):
        assert controller.state.manual_params is not None
        assert controller.state.manual_params.temperature == 23.0


class TestControlModeManagement:
    def test_set_control_mode_auto(self, controller):
        controller.set_control_mode("auto")
        assert controller.state.control_mode == "auto"

    def test_set_control_mode_manual(self, controller):
        controller.set_control_mode("manual")
        assert controller.state.control_mode == "manual"

    def test_set_control_mode_off(self, controller):
        controller.set_control_mode("off")
        assert controller.state.control_mode == "off"


class TestManualParams:
    def test_set_manual_params(self, controller):
        controller.set_manual_params(temperature=22.0, fan_speed=2, mode="heat")

        assert controller.state.manual_params.temperature == 22.0
        assert controller.state.manual_params.fan_speed == 2
        assert controller.state.manual_params.mode == "heat"

    def test_update_manual_param_temperature(self, controller):
        controller.update_manual_param("temperature", 21.0)
        assert controller.state.manual_params.temperature == 21.0

    def test_update_manual_param_fan_speed(self, controller):
        controller.update_manual_param("fan_speed", 3)
        assert controller.state.manual_params.fan_speed == 3

    def test_update_manual_param_mode(self, controller):
        controller.update_manual_param("mode", "heat")
        assert controller.state.manual_params.mode == "heat"


class TestConfigUpdate:
    def test_update_config_single_param(self, controller):
        controller.update_config(target_temperature=23.0)
        assert controller.config.target_temperature == 23.0

    def test_update_config_multiple_params(self, controller):
        controller.update_config(
            target_temperature=24.0, hysteresis_on=0.8, min_setpoint=18.0
        )

        assert controller.config.target_temperature == 24.0
        assert controller.config.hysteresis_on == 0.8
        assert controller.config.min_setpoint == 18.0

    def test_update_config_ignores_unknown(self, controller):
        # Should not raise
        controller.update_config(unknown_param=999)


class TestHistory:
    def test_get_history_empty(self, controller):
        history = controller.get_history()
        assert history == []

    def test_get_history_with_limit(self, controller):
        from controllers.ac_controller import HistoryRecord

        # Add some history
        for i in range(10):
            controller.history.append(
                HistoryRecord(
                    timestamp=time.time(),
                    average_temp=22.0 + i * 0.1,
                    state="off",
                    setpoint=24.0,
                    active_sensors=3,
                )
            )

        history = controller.get_history(limit=5)
        assert len(history) == 5


class TestReadSensors:
    def test_read_sensors_calculates_average(self, controller, mock_mqtt):
        from mqtt_handler import SensorReading

        now = time.time()
        mock_mqtt.get_active_readings.return_value = {
            "sensor1": SensorReading(20.0, 50.0, 90, now),
            "sensor2": SensorReading(24.0, 60.0, 85, now),
        }

        avg_temp, avg_hum, count, _ = controller._read_sensors()

        assert avg_temp == 22.0  # (20 + 24) / 2
        assert avg_hum == 55.0  # (50 + 60) / 2
        assert count == 2

    def test_read_sensors_excludes_ac_virtual(self, controller, mock_mqtt):
        from mqtt_handler import SensorReading

        now = time.time()
        mock_mqtt.get_active_readings.return_value = {
            "sensor1": SensorReading(20.0, 50.0, 90, now),
            "AC": SensorReading(30.0, None, None, now),  # Virtual sensor
        }

        avg_temp, _, count, _ = controller._read_sensors()

        assert avg_temp == 20.0  # Only sensor1
        assert count == 1  # AC excluded

    def test_read_sensors_empty_returns_none(self, controller, mock_mqtt):
        mock_mqtt.get_active_readings.return_value = {}

        avg_temp, avg_hum, count, _ = controller._read_sensors()

        assert avg_temp is None
        assert avg_hum is None
        assert count == 0


class TestMelCloudUpdate:
    def test_needs_update_on_power_change(self, controller):
        from controllers.state_machine import ControllerState, StateMachineOutputs

        controller._last_outputs = StateMachineOutputs(
            state=ControllerState.OFF,
            power=False,
            setpoint=24.0,
            mode="cool",
            fan_speed=0,
            sensor_alert=False,
            melcloud_error=False,
        )

        new_outputs = StateMachineOutputs(
            state=ControllerState.COOLING_MAX,
            power=True,  # Changed
            setpoint=24.0,
            mode="cool",
            fan_speed=0,
            sensor_alert=False,
            melcloud_error=False,
        )

        assert controller._needs_melcloud_update(new_outputs) is True

    def test_needs_update_on_setpoint_change(self, controller):
        from controllers.state_machine import ControllerState, StateMachineOutputs

        controller._last_outputs = StateMachineOutputs(
            state=ControllerState.COOLING_MAX,
            power=True,
            setpoint=24.0,
            mode="cool",
            fan_speed=0,
            sensor_alert=False,
            melcloud_error=False,
        )

        new_outputs = StateMachineOutputs(
            state=ControllerState.COOLING_MAX,
            power=True,
            setpoint=23.0,  # Changed
            mode="cool",
            fan_speed=0,
            sensor_alert=False,
            melcloud_error=False,
        )

        assert controller._needs_melcloud_update(new_outputs) is True

    def test_no_update_when_same(self, controller):
        from controllers.state_machine import ControllerState, StateMachineOutputs

        outputs = StateMachineOutputs(
            state=ControllerState.OFF,
            power=False,
            setpoint=24.0,
            mode="cool",
            fan_speed=0,
            sensor_alert=False,
            melcloud_error=False,
        )
        controller._last_outputs = outputs

        assert controller._needs_melcloud_update(outputs) is False


class TestAcRealCache:
    def test_update_ac_real_cache(self, controller):
        melcloud_data = {
            "Power": True,
            "OperationMode": 3,  # cool
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

    def test_update_ac_real_cache_heat_mode(self, controller):
        melcloud_data = {
            "Power": True,
            "OperationMode": 1,  # heat
            "SetFanSpeed": 1,
            "SetTemperature": 22.0,
            "RoomTemperature": 20.0,
        }

        controller.update_ac_real_cache(melcloud_data)

        assert controller.state.ac_real_mode == "heat"

    def test_update_ac_real_cache_none_data(self, controller):
        controller.update_ac_real_cache(None)
        # Should not crash


class TestEnergyTracking:
    def test_get_power_for_state(self, controller):
        assert controller._get_power_for_state("cooling_max") == 2.5
        assert controller._get_power_for_state("cooling_mid") == 1.75
        assert controller._get_power_for_state("modulating") == 1.25
        assert controller._get_power_for_state("off") == 0.0

    def test_get_session_kwh(self, controller):
        kwh = controller.get_session_kwh()
        assert kwh >= 0.0

    def test_reset_session_kwh(self, controller):
        controller._energy_state["kwh_session"] = 10.0
        controller.reset_session_kwh()

        assert controller._energy_state["kwh_session"] == 0.0


class TestErrorTracker:
    def test_set_error_tracker(self, controller):
        tracker = MagicMock()
        controller.set_error_tracker(tracker)

        assert controller._error_tracker is tracker


class TestStartStop:
    def test_start_creates_thread(self, controller):
        controller.start()

        assert controller._running is True
        assert controller._thread is not None
        assert controller._thread.is_alive()

    def test_stop_joins_thread(self, controller):
        controller.start()
        time.sleep(0.1)
        controller.stop()

        assert controller._running is False


class TestStatePersistence:
    def test_restore_state_returns_false_when_no_file(self, controller):
        with patch("controllers.ac_controller.load_state", return_value=None):
            result = controller.restore_state()
            assert result is False

    def test_restore_state_applies_settings(self, controller):
        from state_persistence import PersistedState

        persisted = PersistedState(
            target_temperature=23.0,
            hysteresis_on=0.6,
            hysteresis_off=0.4,
            min_setpoint=18.0,
            max_setpoint=28.0,
            cooldown_seconds=200,
            sensor_timeout=500,
            override="on",
            force_on_temperature=22.0,
            force_on_fan_speed=2,
            current_sm_state="manual",
            last_off_timestamp=1000.0,
            last_modulating_setpoint=24.0,
        )

        with patch("controllers.ac_controller.load_state", return_value=persisted):
            result = controller.restore_state()

            assert result is True
            assert controller.config.target_temperature == 23.0
            assert controller.state.control_mode == "manual"
            assert controller.state.manual_params.temperature == 22.0


class TestCurrentState:
    def test_current_state_property(self, controller):
        controller.state.average_temp = 24.5

        state = controller.current_state

        assert state.average_temp == 24.5
