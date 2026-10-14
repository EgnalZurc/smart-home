"""AC controller state machine.

This module defines all states, transitions and outputs deterministically.
Each tick receives inputs and produces outputs without side effects.
It's pure logic — does not do I/O, does not call MELCloud, does not read MQTT.

The state machine implements a hysteresis-based temperature controller with
the following states:

    - OFF: AC is off, waiting for temperature to exceed threshold
    - COOLDOWN: Compressor protection period after shutdown
    - COOLING_MAX: Maximum cooling power (high fan, minimum setpoint)
    - MODULATING: Proportional control within hysteresis band
    - MANUAL: User-controlled settings override automatic control
    - SYSTEM_OFF: System disabled by user
    - ERROR: Unrecoverable error state (MELCloud failures)

State Transitions:
    OFF → COOLING_MAX: When avg_temp > target + hysteresis_on
    COOLING_MAX → MODULATING: When avg_temp enters hysteresis band
    COOLING_MAX → COOLDOWN: When avg_temp < target - hysteresis_off
    MODULATING → COOLING_MAX: When avg_temp > target + hysteresis_on
    MODULATING → COOLDOWN: When avg_temp < target - hysteresis_off
    COOLDOWN → OFF/MODULATING/COOLING_MAX: After cooldown period
    Any → MANUAL/SYSTEM_OFF: On manual override
    Any → ERROR: On excessive MELCloud failures
"""

from dataclasses import dataclass
from enum import Enum

from config import (
    DEFAULT_AC_MODE,
    DEFAULT_FAN_SPEED,
    DEFAULT_HYSTERESIS_OFF,
    DEFAULT_HYSTERESIS_ON,
    DEFAULT_MANUAL_TEMP,
    DEFAULT_MAX_SETPOINT,
    DEFAULT_MELCLOUD_MAX_FAILURES,
    DEFAULT_MIN_SETPOINT,
    DEFAULT_SETPOINT,
    FAN_SPEED_MAX,
    FanSpeed,
)


class ControllerState(str, Enum):
    """Possible controller states.

    Each state represents a distinct operating mode of the AC controller,
    determining power state, fan speed, and setpoint behavior.

    Attributes:
        OFF: AC is powered off, monitoring temperature.
        COOLDOWN: Compressor protection period after shutdown.
        COOLING_MAX: Maximum cooling with high fan and minimum setpoint.
        MODULATING: Proportional control adjusting setpoint within band.
        MANUAL: User-specified settings override automatic control.
        SYSTEM_OFF: System disabled by user request.
        ERROR: Unrecoverable error state requiring intervention.
    """

    OFF = "off"
    COOLDOWN = "cooldown"
    COOLING_MAX = "cooling_max"
    MODULATING = "modulating"
    MANUAL = "manual"
    SYSTEM_OFF = "system_off"
    ERROR = "error"


class ManualMode(str, Enum):
    """Control modes selectable by the user.

    Attributes:
        AUTO: Automatic temperature-based control using hysteresis.
        MANUAL: Manual control with user-specified temperature/fan/mode.
        OFF: System completely off (AC disabled regardless of temperature).
    """

    AUTO = "auto"
    MANUAL = "manual"
    OFF = "off"


@dataclass(frozen=True)
class ManualParams:
    """Manual mode parameters set by the user.

    These parameters are applied when the controller is in MANUAL mode,
    bypassing automatic temperature control.

    Attributes:
        temperature: Target setpoint temperature in Celsius.
        fan_speed: Fan speed level (0=auto, 1=low, 2=mid, 3=high).
        mode: AC operation mode ("cool" or "heat").
    """

    temperature: float = DEFAULT_MANUAL_TEMP
    fan_speed: int = DEFAULT_FAN_SPEED
    mode: str = DEFAULT_AC_MODE


@dataclass(frozen=True)
class StateMachineInputs:
    """Inputs for a single state machine tick.

    All inputs are read-only and represent the current system state
    as observed by the controller.

    Attributes:
        average_temp: Current average temperature from sensors (°C),
            or None if no valid sensor data is available.
        target_temp: Desired target temperature (°C).
        manual_mode: Current user-selected control mode.
        manual_params: User-specified parameters for manual mode.
        seconds_since_last_off: Time elapsed since last AC shutdown (s).
        seconds_since_last_sensor_update: Time since last sensor reading (s).
        consecutive_melcloud_failures: Count of consecutive MELCloud API failures.
    """

    average_temp: float | None
    target_temp: float
    manual_mode: ManualMode
    manual_params: ManualParams
    seconds_since_last_off: float
    seconds_since_last_sensor_update: float
    consecutive_melcloud_failures: int


@dataclass(frozen=True)
class StateMachineOutputs:
    """Outputs produced by the state machine for one tick.

    These outputs are used by the controller to send commands to MELCloud
    and update the visible system state.

    Attributes:
        state: New controller state after this tick.
        power: Whether the AC should be powered on.
        mode: AC operation mode ("cool" or "heat").
        setpoint: Target temperature to send to AC (°C).
        fan_speed: Fan speed setting (0=auto, 1-3=manual levels).
        sensor_alert: True if sensor data is stale/missing.
        melcloud_error: True if MELCloud communication has failed.
    """

    state: ControllerState
    power: bool
    mode: str
    setpoint: float
    fan_speed: int
    sensor_alert: bool
    melcloud_error: bool


@dataclass(frozen=True)
class StateMachineConfig:
    """Configurable state machine parameters.

    These parameters tune the behavior of the state machine and can be
    adjusted at runtime through the API.

    Attributes:
        hysteresis_on: Temperature offset above target to start cooling (°C).
        hysteresis_off: Temperature offset below target to stop cooling (°C).
        min_setpoint: Minimum setpoint for proportional control (°C).
        max_setpoint: Maximum setpoint for proportional control (°C).
        cooldown_seconds: Compressor protection period after shutdown (s).
        sensor_alert_seconds: Threshold for sensor staleness alert (s).
        melcloud_max_failures: Consecutive failures before ERROR state.
    """

    hysteresis_on: float = DEFAULT_HYSTERESIS_ON
    hysteresis_off: float = DEFAULT_HYSTERESIS_OFF
    min_setpoint: float = DEFAULT_MIN_SETPOINT
    max_setpoint: float = DEFAULT_MAX_SETPOINT
    cooldown_seconds: int = 180
    sensor_alert_seconds: int = 3600
    melcloud_max_failures: int = DEFAULT_MELCLOUD_MAX_FAILURES


def _calculate_proportional_setpoint(
    average_temp: float,
    target_temp: float,
    config: StateMachineConfig,
) -> float:
    """Calculate proportional setpoint for MODULATING state.

    Maps the current temperature within the hysteresis band to a setpoint
    using linear interpolation. When temperature is at the hot edge of
    the band, returns minimum setpoint (maximum cooling power). When at
    the cold edge, returns maximum setpoint (minimum cooling power).

    Args:
        average_temp: Current average temperature from sensors (°C).
        target_temp: Desired target temperature (°C).
        config: State machine configuration with setpoint limits.

    Returns:
        Calculated setpoint rounded to 0.1°C, clamped to configured limits.

    Example:
        >>> config = StateMachineConfig(hysteresis_on=0.5, hysteresis_off=0.3)
        >>> _calculate_proportional_setpoint(26.5, 26.0, config)  # Hot edge
        19.0  # Minimum setpoint (max cooling)
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
    """Generate standard outputs for OFF state.

    Args:
        sensor_alert: Whether sensor data is stale.
        melcloud_error: Whether MELCloud communication has failed.

    Returns:
        StateMachineOutputs with AC powered off at default setpoint.
    """
    return StateMachineOutputs(
        state=ControllerState.OFF,
        power=False,
        mode=DEFAULT_AC_MODE,
        setpoint=DEFAULT_SETPOINT,
        fan_speed=DEFAULT_FAN_SPEED,
        sensor_alert=sensor_alert,
        melcloud_error=melcloud_error,
    )


def _cooldown_outputs(sensor_alert: bool, melcloud_error: bool) -> StateMachineOutputs:
    """Generate standard outputs for COOLDOWN state.

    Args:
        sensor_alert: Whether sensor data is stale.
        melcloud_error: Whether MELCloud communication has failed.

    Returns:
        StateMachineOutputs with AC powered off during cooldown.
    """
    return StateMachineOutputs(
        state=ControllerState.COOLDOWN,
        power=False,
        mode=DEFAULT_AC_MODE,
        setpoint=DEFAULT_SETPOINT,
        fan_speed=DEFAULT_FAN_SPEED,
        sensor_alert=sensor_alert,
        melcloud_error=melcloud_error,
    )


def _cooling_max_outputs(
    sensor_alert: bool, melcloud_error: bool, config: StateMachineConfig
) -> StateMachineOutputs:
    """Generate standard outputs for COOLING_MAX state.

    Args:
        sensor_alert: Whether sensor data is stale.
        melcloud_error: Whether MELCloud communication has failed.
        config: State machine configuration for minimum setpoint.

    Returns:
        StateMachineOutputs with maximum cooling power (min setpoint, high fan).
    """
    return StateMachineOutputs(
        state=ControllerState.COOLING_MAX,
        power=True,
        mode=DEFAULT_AC_MODE,
        setpoint=config.min_setpoint,
        fan_speed=FAN_SPEED_MAX,
        sensor_alert=sensor_alert,
        melcloud_error=melcloud_error,
    )


def _modulating_outputs(
    setpoint: float, sensor_alert: bool, melcloud_error: bool
) -> StateMachineOutputs:
    """Generate standard outputs for MODULATING state.

    Args:
        setpoint: Calculated proportional setpoint temperature (°C).
        sensor_alert: Whether sensor data is stale.
        melcloud_error: Whether MELCloud communication has failed.

    Returns:
        StateMachineOutputs with proportional control (auto fan, variable setpoint).
    """
    return StateMachineOutputs(
        state=ControllerState.MODULATING,
        power=True,
        mode=DEFAULT_AC_MODE,
        setpoint=setpoint,
        fan_speed=FanSpeed.AUTO,
        sensor_alert=sensor_alert,
        melcloud_error=melcloud_error,
    )


def evaluate(
    current_state: ControllerState,
    inputs: StateMachineInputs,
    config: StateMachineConfig,
    last_modulating_setpoint: float = DEFAULT_SETPOINT,
) -> StateMachineOutputs:
    """Evaluate one state machine tick and produce outputs.

    This is the main entry point for the state machine. It takes the current
    state and inputs, applies the transition logic, and returns the new
    outputs. This function is pure and has no side effects.

    Priority order:
        1. MELCloud error (100+ consecutive failures) → ERROR state
        2. Manual override (OFF/MANUAL mode) → SYSTEM_OFF/MANUAL state
        3. Automatic control based on temperature and current state

    Args:
        current_state: Current controller state before this tick.
        inputs: Current sensor readings and system state.
        config: Configurable state machine parameters.
        last_modulating_setpoint: Last setpoint used in MODULATING state,
            used to maintain stable output when sensor data is temporarily missing.

    Returns:
        StateMachineOutputs with new state and AC control parameters.

    Example:
        >>> state = ControllerState.OFF
        >>> inputs = StateMachineInputs(
        ...     average_temp=27.0, target_temp=26.0,
        ...     manual_mode=ManualMode.AUTO, manual_params=ManualParams(),
        ...     seconds_since_last_off=300, seconds_since_last_sensor_update=10,
        ...     consecutive_melcloud_failures=0
        ... )
        >>> config = StateMachineConfig()
        >>> outputs = evaluate(state, inputs, config)
        >>> outputs.state
        ControllerState.COOLING_MAX
    """
    # Cross-cutting flags
    sensor_alert = (
        inputs.seconds_since_last_sensor_update >= config.sensor_alert_seconds
    )
    melcloud_error = (
        inputs.consecutive_melcloud_failures >= config.melcloud_max_failures
    )

    # --- Priority 1: MELCloud error (100 consecutive failures) ---
    if melcloud_error:
        return StateMachineOutputs(
            state=ControllerState.ERROR,
            power=False,
            mode=DEFAULT_AC_MODE,
            setpoint=DEFAULT_SETPOINT,
            fan_speed=DEFAULT_FAN_SPEED,
            sensor_alert=sensor_alert,
            melcloud_error=True,
        )

    # --- Priority 2: Manual override ---
    if inputs.manual_mode == ManualMode.OFF:
        return StateMachineOutputs(
            state=ControllerState.SYSTEM_OFF,
            power=False,
            mode=DEFAULT_AC_MODE,
            setpoint=DEFAULT_SETPOINT,
            fan_speed=DEFAULT_FAN_SPEED,
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

    def _auto_decision() -> StateMachineOutputs:
        """Evaluate automatic control decision based on current state."""
        match current_state:
            case ControllerState.OFF:
                return _evaluate_off(avg, hot_threshold, sensor_alert, config)

            case ControllerState.COOLDOWN:
                return _evaluate_cooldown(
                    avg,
                    hot_threshold,
                    cold_threshold,
                    cooldown_done,
                    target,
                    config,
                    sensor_alert,
                )

            case ControllerState.COOLING_MAX:
                return _evaluate_cooling_max(
                    avg,
                    hot_threshold,
                    cold_threshold,
                    target,
                    config,
                    sensor_alert,
                )

            case ControllerState.MODULATING:
                return _evaluate_modulating(
                    avg,
                    hot_threshold,
                    cold_threshold,
                    target,
                    config,
                    sensor_alert,
                    last_modulating_setpoint,
                )

            case ControllerState.SYSTEM_OFF | ControllerState.MANUAL:
                # Returning to auto from override: re-evaluate without cooldown
                return _evaluate_from_override(
                    avg,
                    hot_threshold,
                    cold_threshold,
                    target,
                    config,
                    sensor_alert,
                )

            case ControllerState.ERROR:
                # Recovered from error: re-evaluate
                return _evaluate_from_override(
                    avg,
                    hot_threshold,
                    cold_threshold,
                    target,
                    config,
                    sensor_alert,
                )

            case _:
                # Safe fallback
                return _off_outputs(sensor_alert, False)

    return _auto_decision()


def _evaluate_off(
    avg: float | None,
    hot_threshold: float,
    sensor_alert: bool,
    config: StateMachineConfig,
) -> StateMachineOutputs:
    """Evaluate transitions from OFF state.

    The AC remains off until the average temperature exceeds the hot
    threshold (target + hysteresis_on), at which point it transitions
    to COOLING_MAX.

    Args:
        avg: Current average temperature (°C), or None if unavailable.
        hot_threshold: Temperature threshold to start cooling (°C).
        sensor_alert: Whether sensor data is stale.
        config: State machine configuration.

    Returns:
        StateMachineOutputs for OFF or COOLING_MAX state.
    """
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
    """Evaluate transitions from COOLDOWN state.

    During cooldown, the AC remains off to protect the compressor.
    Once cooldown is complete, the state machine re-evaluates based
    on current temperature.

    Args:
        avg: Current average temperature (°C), or None if unavailable.
        hot_threshold: Temperature threshold to start cooling (°C).
        cold_threshold: Temperature threshold below target (°C).
        cooldown_done: Whether the cooldown period has elapsed.
        target: Target temperature for setpoint calculation (°C).
        config: State machine configuration.
        sensor_alert: Whether sensor data is stale.

    Returns:
        StateMachineOutputs for COOLDOWN, OFF, MODULATING, or COOLING_MAX.
    """
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
    """Evaluate transitions from COOLING_MAX state.

    In COOLING_MAX, the AC runs at maximum power (minimum setpoint,
    high fan) until temperature drops into the control band or below
    the cold threshold.

    Args:
        avg: Current average temperature (°C), or None if unavailable.
        hot_threshold: Temperature threshold above target (°C).
        cold_threshold: Temperature threshold below target (°C).
        target: Target temperature for setpoint calculation (°C).
        config: State machine configuration.
        sensor_alert: Whether sensor data is stale.

    Returns:
        StateMachineOutputs for COOLING_MAX, MODULATING, or COOLDOWN.
    """
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
    """Evaluate transitions from MODULATING state.

    In MODULATING, the setpoint is adjusted proportionally based on
    the current temperature within the hysteresis band. If temperature
    moves outside the band, transitions to COOLING_MAX or COOLDOWN.

    Args:
        avg: Current average temperature (°C), or None if unavailable.
        hot_threshold: Temperature threshold above target (°C).
        cold_threshold: Temperature threshold below target (°C).
        target: Target temperature for setpoint calculation (°C).
        config: State machine configuration.
        sensor_alert: Whether sensor data is stale.
        last_setpoint: Previous setpoint to maintain if no sensor data.

    Returns:
        StateMachineOutputs for MODULATING, COOLING_MAX, or COOLDOWN.
    """
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
    """Re-evaluate when returning to auto from override or error.

    When transitioning from MANUAL, SYSTEM_OFF, or ERROR states back to
    automatic control, this function determines the appropriate state
    without requiring a cooldown period.

    Args:
        avg: Current average temperature (°C), or None if unavailable.
        hot_threshold: Temperature threshold above target (°C).
        cold_threshold: Temperature threshold below target (°C).
        target: Target temperature for setpoint calculation (°C).
        config: State machine configuration.
        sensor_alert: Whether sensor data is stale.

    Returns:
        StateMachineOutputs for OFF, MODULATING, or COOLING_MAX state.
    """
    if avg is None:
        return _off_outputs(sensor_alert, False)

    if avg > hot_threshold:
        return _cooling_max_outputs(sensor_alert, False, config)

    if avg >= cold_threshold:
        setpoint = _calculate_proportional_setpoint(avg, target, config)
        return _modulating_outputs(setpoint, sensor_alert, False)

    return _off_outputs(sensor_alert, False)
