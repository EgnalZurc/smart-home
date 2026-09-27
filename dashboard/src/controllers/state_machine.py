"""AC controller state machine.

Defines all states, transitions and outputs deterministically.
Each tick receives inputs and produces outputs without side effects.
It's pure logic — does not do I/O, does not call MELCloud, does not read MQTT.
"""

from dataclasses import dataclass
from enum import Enum


class ControllerState(str, Enum):
    """Possible controller states."""
    OFF = "off"
    COOLDOWN = "cooldown"
    COOLING_MAX = "cooling_max"
    MODULATING = "modulating"
    MANUAL = "manual"
    SYSTEM_OFF = "system_off"
    ERROR = "error"


class ManualMode(str, Enum):
    """Control modes."""
    AUTO = "auto"      # Automatic temperature-based control
    MANUAL = "manual"  # Manual control with user-specified settings
    OFF = "off"        # System off (AC disabled)


@dataclass(frozen=True)
class ManualParams:
    """Manual mode parameters."""
    temperature: float = 23.0
    fan_speed: int = 0  # 0=auto, 1=low, 2=mid, 3=high
    mode: str = "cool"  # "cool" or "heat"


@dataclass(frozen=True)
class StateMachineInputs:
    """Inputs of a state machine tick."""
    average_temp: float | None
    target_temp: float
    manual_mode: ManualMode
    manual_params: ManualParams
    seconds_since_last_off: float
    seconds_since_last_sensor_update: float
    consecutive_melcloud_failures: int


@dataclass(frozen=True)
class StateMachineOutputs:
    """Outputs produced by the state machine."""
    state: ControllerState
    power: bool
    mode: str  # Siempre "cool"
    setpoint: float
    fan_speed: int
    sensor_alert: bool
    melcloud_error: bool


# --- Technical constants (not directly configurable) ---
# Cooldown and sensor_alert come from configuration
MELCLOUD_MAX_FAILURES_DEFAULT = 100

# --- Default constants (configurable) ---
DEFAULT_HYSTERESIS_ON = 0.5
DEFAULT_HYSTERESIS_OFF = 0.3
DEFAULT_MIN_SETPOINT = 19.0
DEFAULT_MAX_SETPOINT = 30.0


@dataclass(frozen=True)
class StateMachineConfig:
    """Configurable state machine parameters."""
    hysteresis_on: float = DEFAULT_HYSTERESIS_ON
    hysteresis_off: float = DEFAULT_HYSTERESIS_OFF
    min_setpoint: float = DEFAULT_MIN_SETPOINT
    max_setpoint: float = DEFAULT_MAX_SETPOINT
    cooldown_seconds: int = 180
    sensor_alert_seconds: int = 3600
    melcloud_max_failures: int = MELCLOUD_MAX_FAILURES_DEFAULT


def _calculate_proportional_setpoint(
    average_temp: float,
    target_temp: float,
    config: StateMachineConfig,
) -> float:
    """Calculates proportional setpoint for MODULATING.

    position=1 (hot edge) → minimum setpoint (19°C, maximum power)
    position=0 (cold edge) → maximum setpoint (30°C, minimum power)
    """
    range_size = config.hysteresis_on + config.hysteresis_off
    if range_size == 0:
        return config.min_setpoint

    cold_edge = target_temp - config.hysteresis_off
    position = (average_temp - cold_edge) / range_size
    position = max(0.0, min(1.0, position))

    setpoint_range = config.max_setpoint - config.min_setpoint
    setpoint = config.max_setpoint - (position * setpoint_range)
    return round(max(config.min_setpoint, min(config.max_setpoint, setpoint)), 1)


def _off_outputs(sensor_alert: bool, melcloud_error: bool) -> StateMachineOutputs:
    """Standard outputs for off states."""
    return StateMachineOutputs(
        state=ControllerState.OFF,
        power=False,
        mode="cool",
        setpoint=24.0,
        fan_speed=0,
        sensor_alert=sensor_alert,
        melcloud_error=melcloud_error,
    )


def _cooldown_outputs(sensor_alert: bool, melcloud_error: bool) -> StateMachineOutputs:
    """Standard outputs for COOLDOWN."""
    return StateMachineOutputs(
        state=ControllerState.COOLDOWN,
        power=False,
        mode="cool",
        setpoint=24.0,
        fan_speed=0,
        sensor_alert=sensor_alert,
        melcloud_error=melcloud_error,
    )


def _cooling_max_outputs(sensor_alert: bool, melcloud_error: bool, config: StateMachineConfig) -> StateMachineOutputs:
    """Standard outputs for COOLING_MAX."""
    return StateMachineOutputs(
        state=ControllerState.COOLING_MAX,
        power=True,
        mode="cool",
        setpoint=config.min_setpoint,
        fan_speed=3,
        sensor_alert=sensor_alert,
        melcloud_error=melcloud_error,
    )


def _modulating_outputs(
    setpoint: float, sensor_alert: bool, melcloud_error: bool
) -> StateMachineOutputs:
    """Standard outputs for MODULATING."""
    return StateMachineOutputs(
        state=ControllerState.MODULATING,
        power=True,
        mode="cool",
        setpoint=setpoint,
        fan_speed=0,
        sensor_alert=sensor_alert,
        melcloud_error=melcloud_error,
    )


def evaluate(
    current_state: ControllerState,
    inputs: StateMachineInputs,
    config: StateMachineConfig,
    last_modulating_setpoint: float = 24.0,
) -> StateMachineOutputs:
    """Evaluates one state machine tick.

    Pure function: given current state + inputs + config, returns outputs.
    Has no side effects.

    Args:
        current_state: Current controller state.
        inputs: Current tick inputs.
        config: Configurable parameters.
        last_modulating_setpoint: Last setpoint used in MODULATING (to maintain if no data).

    Returns:
        StateMachineOutputs with new state and outputs for MELCloud.
    """
    # Cross-cutting flags
    sensor_alert = inputs.seconds_since_last_sensor_update >= config.sensor_alert_seconds
    melcloud_error = inputs.consecutive_melcloud_failures >= config.melcloud_max_failures

    # --- Priority 1: MELCloud error (100 consecutive failures) ---
    if melcloud_error:
        return StateMachineOutputs(
            state=ControllerState.ERROR,
            power=False,
            mode="cool",
            setpoint=24.0,
            fan_speed=0,
            sensor_alert=sensor_alert,
            melcloud_error=True,
        )

    # --- Priority 2: Manual override ---
    if inputs.manual_mode == ManualMode.OFF:
        return StateMachineOutputs(
            state=ControllerState.SYSTEM_OFF,
            power=False,
            mode="cool",
            setpoint=24.0,
            fan_speed=0,
            sensor_alert=sensor_alert,
            melcloud_error=False,
        )

    if inputs.manual_mode == ManualMode.MANUAL:
        return StateMachineOutputs(
            state=ControllerState.MANUAL,
            power=True,
            mode=inputs.manual_params.mode,
            setpoint=inputs.manual_params.temperature,
            fan_speed=inputs.manual_params.fan_speed,
            sensor_alert=sensor_alert,
            melcloud_error=False,
        )

    # --- Priority 3: Automatic mode ---
    avg = inputs.average_temp
    target = inputs.target_temp
    hot_threshold = target + config.hysteresis_on
    cold_threshold = target - config.hysteresis_off
    cooldown_done = inputs.seconds_since_last_off >= config.cooldown_seconds

    # Sub-function to evaluate automatic decision
    def _auto_decision() -> StateMachineOutputs:
        match current_state:
            case ControllerState.OFF:
                return _evaluate_off(avg, hot_threshold, sensor_alert, config)

            case ControllerState.COOLDOWN:
                return _evaluate_cooldown(
                    avg, hot_threshold, cold_threshold, cooldown_done,
                    target, config, sensor_alert,
                )

            case ControllerState.COOLING_MAX:
                return _evaluate_cooling_max(
                    avg, hot_threshold, cold_threshold,
                    target, config, sensor_alert,
                )

            case ControllerState.MODULATING:
                return _evaluate_modulating(
                    avg, hot_threshold, cold_threshold,
                    target, config, sensor_alert, last_modulating_setpoint,
                )

            case ControllerState.SYSTEM_OFF | ControllerState.MANUAL:
                # Returning to auto from override: re-evaluate without cooldown
                return _evaluate_from_override(
                    avg, hot_threshold, cold_threshold,
                    target, config, sensor_alert,
                )

            case ControllerState.ERROR:
                # Recovered from error: re-evaluate
                return _evaluate_from_override(
                    avg, hot_threshold, cold_threshold,
                    target, config, sensor_alert,
                )

            case _:
                # Safe fallback
                return _off_outputs(sensor_alert, False)

    return _auto_decision()


def _evaluate_off(
    avg: float | None, hot_threshold: float, sensor_alert: bool, config: StateMachineConfig
) -> StateMachineOutputs:
    """Transitions from OFF."""
    if avg is None:
        return _off_outputs(sensor_alert, False)

    if avg > hot_threshold:
        return _cooling_max_outputs(sensor_alert, False, config)

    return _off_outputs(sensor_alert, False)


def _evaluate_cooldown(
    avg: float | None,
    hot_threshold: float,
    cold_threshold: float,
    cooldown_done: bool,
    target: float,
    config: StateMachineConfig,
    sensor_alert: bool,
) -> StateMachineOutputs:
    """Transitions from COOLDOWN."""
    if not cooldown_done:
        return _cooldown_outputs(sensor_alert, False)

    # Cooldown finished: re-evaluate
    if avg is None:
        return _off_outputs(sensor_alert, False)

    if avg > hot_threshold:
        return _cooling_max_outputs(sensor_alert, False, config)

    if avg >= cold_threshold:
        setpoint = _calculate_proportional_setpoint(avg, target, config)
        return _modulating_outputs(setpoint, sensor_alert, False)

    return _off_outputs(sensor_alert, False)


def _evaluate_cooling_max(
    avg: float | None,
    hot_threshold: float,
    cold_threshold: float,
    target: float,
    config: StateMachineConfig,
    sensor_alert: bool,
) -> StateMachineOutputs:
    """Transitions from COOLING_MAX."""
    if avg is None:
        # No data: keep cooling
        return _cooling_max_outputs(sensor_alert, False, config)

    if avg < cold_threshold:
        # Target reached → turn off → cooldown
        return _cooldown_outputs(sensor_alert, False)

    if avg <= hot_threshold:
        # Intermediate zone → modulate
        setpoint = _calculate_proportional_setpoint(avg, target, config)
        return _modulating_outputs(setpoint, sensor_alert, False)

    # Still hot → keep cooling max
    return _cooling_max_outputs(sensor_alert, False, config)


def _evaluate_modulating(
    avg: float | None,
    hot_threshold: float,
    cold_threshold: float,
    target: float,
    config: StateMachineConfig,
    sensor_alert: bool,
    last_setpoint: float,
) -> StateMachineOutputs:
    """Transitions from MODULATING."""
    if avg is None:
        # No data: keep last setpoint
        return _modulating_outputs(last_setpoint, sensor_alert, False)

    if avg > hot_threshold:
        return _cooling_max_outputs(sensor_alert, False, config)

    if avg < cold_threshold:
        # Target reached → turn off → cooldown
        return _cooldown_outputs(sensor_alert, False)

    # Still in intermediate zone → recalculate setpoint
    setpoint = _calculate_proportional_setpoint(avg, target, config)
    return _modulating_outputs(setpoint, sensor_alert, False)


def _evaluate_from_override(
    avg: float | None,
    hot_threshold: float,
    cold_threshold: float,
    target: float,
    config: StateMachineConfig,
    sensor_alert: bool,
) -> StateMachineOutputs:
    """Re-evaluation when returning to auto from override or error. No cooldown."""
    if avg is None:
        return _off_outputs(sensor_alert, False)

    if avg > hot_threshold:
        return _cooling_max_outputs(sensor_alert, False, config)

    if avg >= cold_threshold:
        setpoint = _calculate_proportional_setpoint(avg, target, config)
        return _modulating_outputs(setpoint, sensor_alert, False)

    return _off_outputs(sensor_alert, False)
