"""Tests unitarios de la máquina de estados del controlador AC.

Cubren todas las transiciones, corner cases y reglas transversales.
"""

import sys
from pathlib import Path

# Añadir el directorio del backend al path
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "controllers"))

from controllers.state_machine import (
    ControllerState,
    ForceOnParams,
    ManualMode,
    StateMachineConfig,
    StateMachineInputs,
    StateMachineOutputs,
    evaluate,
    _calculate_proportional_setpoint,
    COOLDOWN_SECONDS,
    SENSOR_ALERT_SECONDS,
    MELCLOUD_MAX_FAILURES,
)


# --- Helpers ---

def make_inputs(
    average_temp: float | None = 26.0,
    target_temp: float = 23.0,
    manual_mode: ManualMode = ManualMode.AUTO,
    force_on_params: ForceOnParams = ForceOnParams(),
    seconds_since_last_off: float = 9999.0,
    seconds_since_last_sensor_update: float = 0.0,
    consecutive_melcloud_failures: int = 0,
) -> StateMachineInputs:
    return StateMachineInputs(
        average_temp=average_temp,
        target_temp=target_temp,
        manual_mode=manual_mode,
        force_on_params=force_on_params,
        seconds_since_last_off=seconds_since_last_off,
        seconds_since_last_sensor_update=seconds_since_last_sensor_update,
        consecutive_melcloud_failures=consecutive_melcloud_failures,
    )


DEFAULT_CONFIG = StateMachineConfig()


# =============================================================================
# TESTS: Outputs completos
# =============================================================================

class TestOutputsAlwaysComplete:
    """Verifica que todos los outputs tengan valores definidos en cualquier estado."""

    def _assert_outputs_complete(self, outputs: StateMachineOutputs):
        assert outputs.state is not None
        assert isinstance(outputs.power, bool)
        assert outputs.mode == "cool"
        assert 19.0 <= outputs.setpoint <= 30.0 or outputs.setpoint == 24.0
        assert outputs.fan_speed in (0, 1, 2, 3)
        assert isinstance(outputs.sensor_alert, bool)
        assert isinstance(outputs.melcloud_error, bool)

    def test_off_state_complete(self):
        result = evaluate(ControllerState.OFF, make_inputs(average_temp=22.0), DEFAULT_CONFIG)
        self._assert_outputs_complete(result)

    def test_cooling_max_complete(self):
        result = evaluate(ControllerState.OFF, make_inputs(average_temp=26.0), DEFAULT_CONFIG)
        self._assert_outputs_complete(result)

    def test_modulating_complete(self):
        result = evaluate(ControllerState.COOLING_MAX, make_inputs(average_temp=23.2), DEFAULT_CONFIG)
        self._assert_outputs_complete(result)

    def test_cooldown_complete(self):
        result = evaluate(ControllerState.COOLDOWN, make_inputs(seconds_since_last_off=10.0), DEFAULT_CONFIG)
        self._assert_outputs_complete(result)

    def test_forced_on_complete(self):
        result = evaluate(
            ControllerState.OFF,
            make_inputs(manual_mode=ManualMode.FORCE_ON, force_on_params=ForceOnParams(temperature=25.0, fan_speed=2)),
            DEFAULT_CONFIG,
        )
        self._assert_outputs_complete(result)

    def test_forced_off_complete(self):
        result = evaluate(ControllerState.COOLING_MAX, make_inputs(manual_mode=ManualMode.FORCE_OFF), DEFAULT_CONFIG)
        self._assert_outputs_complete(result)

    def test_error_complete(self):
        result = evaluate(ControllerState.OFF, make_inputs(consecutive_melcloud_failures=100), DEFAULT_CONFIG)
        self._assert_outputs_complete(result)

    def test_none_temp_complete(self):
        result = evaluate(ControllerState.COOLING_MAX, make_inputs(average_temp=None), DEFAULT_CONFIG)
        self._assert_outputs_complete(result)


# =============================================================================
# TESTS: Estado OFF
# =============================================================================

class TestStateOff:
    """Transiciones desde OFF."""

    def test_stays_off_when_below_target(self):
        result = evaluate(ControllerState.OFF, make_inputs(average_temp=22.0), DEFAULT_CONFIG)
        assert result.state == ControllerState.OFF
        assert result.power is False

    def test_stays_off_when_in_dead_zone(self):
        # 23.3 está entre obj-0.3 (22.7) y obj+0.5 (23.5)
        result = evaluate(ControllerState.OFF, make_inputs(average_temp=23.3), DEFAULT_CONFIG)
        assert result.state == ControllerState.OFF
        assert result.power is False

    def test_stays_off_at_hot_threshold_exactly(self):
        # 23.5 = obj + 0.5, no supera
        result = evaluate(ControllerState.OFF, make_inputs(average_temp=23.5), DEFAULT_CONFIG)
        assert result.state == ControllerState.OFF
        assert result.power is False

    def test_transitions_to_cooling_max_above_threshold(self):
        # 23.6 > obj + 0.5
        result = evaluate(ControllerState.OFF, make_inputs(average_temp=23.6), DEFAULT_CONFIG)
        assert result.state == ControllerState.COOLING_MAX
        assert result.power is True
        assert result.setpoint == 19.0
        assert result.fan_speed == 3

    def test_stays_off_with_no_sensor_data(self):
        result = evaluate(ControllerState.OFF, make_inputs(average_temp=None), DEFAULT_CONFIG)
        assert result.state == ControllerState.OFF
        assert result.power is False


# =============================================================================
# TESTS: Estado COOLING_MAX
# =============================================================================

class TestStateCoolingMax:
    """Transiciones desde COOLING_MAX."""

    def test_stays_cooling_max_when_hot(self):
        result = evaluate(ControllerState.COOLING_MAX, make_inputs(average_temp=26.0), DEFAULT_CONFIG)
        assert result.state == ControllerState.COOLING_MAX
        assert result.power is True
        assert result.setpoint == 19.0
        assert result.fan_speed == 3

    def test_transitions_to_modulating_in_dead_zone(self):
        # 23.0 está entre 22.7 y 23.5
        result = evaluate(ControllerState.COOLING_MAX, make_inputs(average_temp=23.0), DEFAULT_CONFIG)
        assert result.state == ControllerState.MODULATING
        assert result.power is True
        assert result.fan_speed == 0

    def test_transitions_to_cooldown_below_cold_threshold(self):
        # 22.6 < 22.7 (obj - 0.3)
        result = evaluate(ControllerState.COOLING_MAX, make_inputs(average_temp=22.6), DEFAULT_CONFIG)
        assert result.state == ControllerState.COOLDOWN
        assert result.power is False

    def test_maintains_cooling_with_no_sensor_data(self):
        result = evaluate(ControllerState.COOLING_MAX, make_inputs(average_temp=None), DEFAULT_CONFIG)
        assert result.state == ControllerState.COOLING_MAX
        assert result.power is True
        assert result.setpoint == 19.0


# =============================================================================
# TESTS: Estado MODULATING
# =============================================================================

class TestStateModulating:
    """Transiciones desde MODULATING."""

    def test_stays_modulating_in_dead_zone(self):
        result = evaluate(ControllerState.MODULATING, make_inputs(average_temp=23.2), DEFAULT_CONFIG)
        assert result.state == ControllerState.MODULATING
        assert result.power is True
        assert 19.0 <= result.setpoint <= 30.0

    def test_transitions_to_cooling_max_when_hot(self):
        result = evaluate(ControllerState.MODULATING, make_inputs(average_temp=23.6), DEFAULT_CONFIG)
        assert result.state == ControllerState.COOLING_MAX
        assert result.setpoint == 19.0
        assert result.fan_speed == 3

    def test_transitions_to_cooldown_when_cold(self):
        result = evaluate(ControllerState.MODULATING, make_inputs(average_temp=22.6), DEFAULT_CONFIG)
        assert result.state == ControllerState.COOLDOWN
        assert result.power is False

    def test_maintains_last_setpoint_with_no_data(self):
        result = evaluate(
            ControllerState.MODULATING,
            make_inputs(average_temp=None),
            DEFAULT_CONFIG,
            last_modulating_setpoint=25.5,
        )
        assert result.state == ControllerState.MODULATING
        assert result.power is True
        assert result.setpoint == 25.5

    def test_setpoint_proportional_near_hot_edge(self):
        # 23.4 muy cerca de hot (23.5) → consigna baja (más potencia)
        result = evaluate(ControllerState.MODULATING, make_inputs(average_temp=23.4), DEFAULT_CONFIG)
        assert result.setpoint < 22.0  # Cerca del mínimo

    def test_setpoint_proportional_near_cold_edge(self):
        # 22.8 muy cerca de cold (22.7) → consigna alta (menos potencia)
        result = evaluate(ControllerState.MODULATING, make_inputs(average_temp=22.8), DEFAULT_CONFIG)
        assert result.setpoint > 27.0  # Cerca del máximo


# =============================================================================
# TESTS: Estado COOLDOWN
# =============================================================================

class TestStateCooldown:
    """Transiciones desde COOLDOWN."""

    def test_stays_in_cooldown_when_time_not_elapsed(self):
        result = evaluate(
            ControllerState.COOLDOWN,
            make_inputs(average_temp=26.0, seconds_since_last_off=100.0),
            DEFAULT_CONFIG,
        )
        assert result.state == ControllerState.COOLDOWN
        assert result.power is False

    def test_stays_in_cooldown_at_299_seconds(self):
        result = evaluate(
            ControllerState.COOLDOWN,
            make_inputs(average_temp=26.0, seconds_since_last_off=299.0),
            DEFAULT_CONFIG,
        )
        assert result.state == ControllerState.COOLDOWN

    def test_transitions_to_cooling_max_after_cooldown_when_hot(self):
        result = evaluate(
            ControllerState.COOLDOWN,
            make_inputs(average_temp=26.0, seconds_since_last_off=300.0),
            DEFAULT_CONFIG,
        )
        assert result.state == ControllerState.COOLING_MAX
        assert result.power is True

    def test_transitions_to_modulating_after_cooldown_in_zone(self):
        result = evaluate(
            ControllerState.COOLDOWN,
            make_inputs(average_temp=23.2, seconds_since_last_off=300.0),
            DEFAULT_CONFIG,
        )
        assert result.state == ControllerState.MODULATING
        assert result.power is True

    def test_transitions_to_off_after_cooldown_when_cold(self):
        result = evaluate(
            ControllerState.COOLDOWN,
            make_inputs(average_temp=22.0, seconds_since_last_off=300.0),
            DEFAULT_CONFIG,
        )
        assert result.state == ControllerState.OFF
        assert result.power is False

    def test_transitions_to_off_after_cooldown_no_data(self):
        result = evaluate(
            ControllerState.COOLDOWN,
            make_inputs(average_temp=None, seconds_since_last_off=300.0),
            DEFAULT_CONFIG,
        )
        assert result.state == ControllerState.OFF
        assert result.power is False


# =============================================================================
# TESTS: Override manual
# =============================================================================

class TestManualOverride:
    """Force ON / Force OFF desde cualquier estado."""

    def test_force_off_from_cooling_max(self):
        result = evaluate(
            ControllerState.COOLING_MAX,
            make_inputs(manual_mode=ManualMode.FORCE_OFF),
            DEFAULT_CONFIG,
        )
        assert result.state == ControllerState.FORCED_OFF
        assert result.power is False

    def test_force_off_from_off(self):
        result = evaluate(
            ControllerState.OFF,
            make_inputs(manual_mode=ManualMode.FORCE_OFF),
            DEFAULT_CONFIG,
        )
        assert result.state == ControllerState.FORCED_OFF
        assert result.power is False

    def test_force_on_from_off(self):
        params = ForceOnParams(temperature=25.0, fan_speed=2)
        result = evaluate(
            ControllerState.OFF,
            make_inputs(manual_mode=ManualMode.FORCE_ON, force_on_params=params),
            DEFAULT_CONFIG,
        )
        assert result.state == ControllerState.FORCED_ON
        assert result.power is True
        assert result.setpoint == 25.0
        assert result.fan_speed == 2

    def test_force_on_from_cooldown(self):
        params = ForceOnParams(temperature=21.0, fan_speed=3)
        result = evaluate(
            ControllerState.COOLDOWN,
            make_inputs(manual_mode=ManualMode.FORCE_ON, force_on_params=params, seconds_since_last_off=10.0),
            DEFAULT_CONFIG,
        )
        assert result.state == ControllerState.FORCED_ON
        assert result.power is True
        assert result.setpoint == 21.0
        # Ignora cooldown cuando es manual

    def test_return_to_auto_from_forced_off_no_cooldown(self):
        """Al volver a auto desde FORCED_OFF, no se aplica cooldown."""
        result = evaluate(
            ControllerState.FORCED_OFF,
            make_inputs(average_temp=26.0, seconds_since_last_off=0.0),  # 0s desde apagado
            DEFAULT_CONFIG,
        )
        # Debería ir a COOLING_MAX directamente, sin cooldown
        assert result.state == ControllerState.COOLING_MAX
        assert result.power is True

    def test_return_to_auto_from_forced_on_cold(self):
        """Al volver a auto desde FORCED_ON con casa fría, va a OFF."""
        result = evaluate(
            ControllerState.FORCED_ON,
            make_inputs(average_temp=22.0),
            DEFAULT_CONFIG,
        )
        assert result.state == ControllerState.OFF
        assert result.power is False


# =============================================================================
# TESTS: Error MELCloud
# =============================================================================

class TestMelCloudError:
    """Estado ERROR tras 100 fallos consecutivos."""

    def test_enters_error_at_100_failures(self):
        result = evaluate(
            ControllerState.COOLING_MAX,
            make_inputs(consecutive_melcloud_failures=100),
            DEFAULT_CONFIG,
        )
        assert result.state == ControllerState.ERROR
        assert result.power is False
        assert result.melcloud_error is True

    def test_no_error_at_99_failures(self):
        result = evaluate(
            ControllerState.COOLING_MAX,
            make_inputs(average_temp=26.0, consecutive_melcloud_failures=99),
            DEFAULT_CONFIG,
        )
        assert result.state == ControllerState.COOLING_MAX
        assert result.melcloud_error is False

    def test_recovers_from_error_when_failures_drop(self):
        result = evaluate(
            ControllerState.ERROR,
            make_inputs(average_temp=26.0, consecutive_melcloud_failures=0),
            DEFAULT_CONFIG,
        )
        assert result.state == ControllerState.COOLING_MAX
        assert result.melcloud_error is False

    def test_error_overrides_force_on(self):
        """Error tiene prioridad sobre force_on."""
        result = evaluate(
            ControllerState.FORCED_ON,
            make_inputs(manual_mode=ManualMode.FORCE_ON, consecutive_melcloud_failures=100),
            DEFAULT_CONFIG,
        )
        assert result.state == ControllerState.ERROR
        assert result.power is False


# =============================================================================
# TESTS: Alerta sensores
# =============================================================================

class TestSensorAlert:
    """Alerta cuando no hay actualización en 60 minutos."""

    def test_no_alert_when_recent(self):
        result = evaluate(
            ControllerState.COOLING_MAX,
            make_inputs(seconds_since_last_sensor_update=1800.0),  # 30 min
            DEFAULT_CONFIG,
        )
        assert result.sensor_alert is False

    def test_alert_at_60_minutes(self):
        result = evaluate(
            ControllerState.COOLING_MAX,
            make_inputs(seconds_since_last_sensor_update=3600.0),  # 60 min
            DEFAULT_CONFIG,
        )
        assert result.sensor_alert is True

    def test_alert_does_not_change_state(self):
        """La alerta no cambia el estado, solo informa."""
        result = evaluate(
            ControllerState.COOLING_MAX,
            make_inputs(average_temp=26.0, seconds_since_last_sensor_update=7200.0),
            DEFAULT_CONFIG,
        )
        assert result.state == ControllerState.COOLING_MAX
        assert result.sensor_alert is True
        assert result.power is True


# =============================================================================
# TESTS: Consigna proporcional
# =============================================================================

class TestProportionalSetpoint:
    """Cálculo de la consigna proporcional."""

    def test_at_cold_edge_returns_max_setpoint(self):
        # avg = obj - 0.3 = 22.7 → position=0 → setpoint=30
        setpoint = _calculate_proportional_setpoint(22.7, 23.0, DEFAULT_CONFIG)
        assert setpoint == 30.0

    def test_at_hot_edge_returns_min_setpoint(self):
        # avg = obj + 0.5 = 23.5 → position=1 → setpoint=19
        setpoint = _calculate_proportional_setpoint(23.5, 23.0, DEFAULT_CONFIG)
        assert setpoint == 19.0

    def test_at_midpoint(self):
        # avg = 23.1 → position = (23.1 - 22.7) / 0.8 = 0.5 → setpoint = 30 - 0.5*11 = 24.5
        setpoint = _calculate_proportional_setpoint(23.1, 23.0, DEFAULT_CONFIG)
        assert setpoint == 24.5

    def test_clamped_below_min(self):
        # Si somehow avg está fuera del rango, debe clampear
        setpoint = _calculate_proportional_setpoint(24.0, 23.0, DEFAULT_CONFIG)
        assert setpoint >= 19.0

    def test_clamped_above_max(self):
        setpoint = _calculate_proportional_setpoint(20.0, 23.0, DEFAULT_CONFIG)
        assert setpoint <= 30.0


# =============================================================================
# TESTS: Modo siempre cool
# =============================================================================

class TestAlwaysCool:
    """El modo es siempre 'cool'."""

    def test_mode_cool_in_off(self):
        result = evaluate(ControllerState.OFF, make_inputs(average_temp=22.0), DEFAULT_CONFIG)
        assert result.mode == "cool"

    def test_mode_cool_in_cooling_max(self):
        result = evaluate(ControllerState.OFF, make_inputs(average_temp=26.0), DEFAULT_CONFIG)
        assert result.mode == "cool"

    def test_mode_cool_in_forced_on(self):
        result = evaluate(
            ControllerState.OFF,
            make_inputs(manual_mode=ManualMode.FORCE_ON),
            DEFAULT_CONFIG,
        )
        assert result.mode == "cool"

    def test_mode_cool_in_error(self):
        result = evaluate(
            ControllerState.OFF,
            make_inputs(consecutive_melcloud_failures=100),
            DEFAULT_CONFIG,
        )
        assert result.mode == "cool"


# =============================================================================
# TESTS: Determinismo (mismos inputs → mismos outputs)
# =============================================================================

class TestDeterminism:
    """La máquina de estados es determinista."""

    def test_same_inputs_same_outputs(self):
        inputs = make_inputs(average_temp=25.0)
        r1 = evaluate(ControllerState.OFF, inputs, DEFAULT_CONFIG)
        r2 = evaluate(ControllerState.OFF, inputs, DEFAULT_CONFIG)
        assert r1 == r2

    def test_different_states_different_outputs(self):
        inputs = make_inputs(average_temp=23.2)
        r_off = evaluate(ControllerState.OFF, inputs, DEFAULT_CONFIG)
        r_cooling = evaluate(ControllerState.COOLING_MAX, inputs, DEFAULT_CONFIG)
        assert r_off.state != r_cooling.state
