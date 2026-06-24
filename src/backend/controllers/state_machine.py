"""Máquina de estados del controlador AC.

Define de forma determinista todos los estados, transiciones y outputs.
Cada tick recibe inputs y produce outputs sin efectos secundarios.
Es pura lógica — no hace I/O, no llama a MELCloud, no lee MQTT.
"""

from dataclasses import dataclass
from enum import Enum


class ControllerState(str, Enum):
    """Estados posibles del controlador."""
    OFF = "off"
    COOLDOWN = "cooldown"
    COOLING_MAX = "cooling_max"
    MODULATING = "modulating"
    FORCED_ON = "forced_on"
    FORCED_OFF = "forced_off"
    ERROR = "error"


class ManualMode(str, Enum):
    """Modos de control manual."""
    AUTO = "auto"
    FORCE_ON = "force_on"
    FORCE_OFF = "force_off"


@dataclass(frozen=True)
class ForceOnParams:
    """Parámetros del encendido manual."""
    temperature: float = 23.0
    fan_speed: int = 0


@dataclass(frozen=True)
class StateMachineInputs:
    """Inputs de un tick de la máquina de estados."""
    average_temp: float | None
    target_temp: float
    manual_mode: ManualMode
    force_on_params: ForceOnParams
    seconds_since_last_off: float
    seconds_since_last_sensor_update: float
    consecutive_melcloud_failures: int


@dataclass(frozen=True)
class StateMachineOutputs:
    """Outputs producidos por la máquina de estados."""
    state: ControllerState
    power: bool
    mode: str  # Siempre "cool"
    setpoint: float
    fan_speed: int
    sensor_alert: bool
    melcloud_error: bool


# --- Constantes técnicas (no configurables directamente) ---
# El cooldown y sensor_alert vienen de la configuración
MELCLOUD_MAX_FAILURES_DEFAULT = 100

# --- Constantes por defecto (configurables) ---
DEFAULT_HYSTERESIS_ON = 0.5
DEFAULT_HYSTERESIS_OFF = 0.3
DEFAULT_MIN_SETPOINT = 19.0
DEFAULT_MAX_SETPOINT = 30.0


@dataclass(frozen=True)
class StateMachineConfig:
    """Parámetros configurables de la máquina de estados."""
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
    """Calcula la consigna proporcional para MODULATING.

    position=1 (borde caliente) → consigna mínima (19°C, máxima potencia)
    position=0 (borde frío) → consigna máxima (30°C, mínima potencia)
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
    """Outputs estándar para estados apagados."""
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
    """Outputs estándar para COOLDOWN."""
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
    """Outputs estándar para COOLING_MAX."""
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
    """Outputs estándar para MODULATING."""
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
    """Evalúa un tick de la máquina de estados.

    Función pura: dados un estado actual + inputs + config, devuelve outputs.
    No tiene efectos secundarios.

    Args:
        current_state: Estado actual del controlador.
        inputs: Inputs del tick actual.
        config: Parámetros configurables.
        last_modulating_setpoint: Última consigna usada en MODULATING (para mantener si no hay datos).

    Returns:
        StateMachineOutputs con el nuevo estado y los outputs para MELCloud.
    """
    # Flags transversales
    sensor_alert = inputs.seconds_since_last_sensor_update >= config.sensor_alert_seconds
    melcloud_error = inputs.consecutive_melcloud_failures >= config.melcloud_max_failures

    # --- Prioridad 1: Error MELCloud (100 fallos consecutivos) ---
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

    # --- Prioridad 2: Override manual ---
    if inputs.manual_mode == ManualMode.FORCE_OFF:
        return StateMachineOutputs(
            state=ControllerState.FORCED_OFF,
            power=False,
            mode="cool",
            setpoint=24.0,
            fan_speed=0,
            sensor_alert=sensor_alert,
            melcloud_error=False,
        )

    if inputs.manual_mode == ManualMode.FORCE_ON:
        return StateMachineOutputs(
            state=ControllerState.FORCED_ON,
            power=True,
            mode="cool",
            setpoint=inputs.force_on_params.temperature,
            fan_speed=inputs.force_on_params.fan_speed,
            sensor_alert=sensor_alert,
            melcloud_error=False,
        )

    # --- Prioridad 3: Modo automático ---
    avg = inputs.average_temp
    target = inputs.target_temp
    hot_threshold = target + config.hysteresis_on
    cold_threshold = target - config.hysteresis_off
    cooldown_done = inputs.seconds_since_last_off >= config.cooldown_seconds

    # Sub-función para evaluar la decisión automática
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

            case ControllerState.FORCED_OFF | ControllerState.FORCED_ON:
                # Volviendo a auto desde override: re-evalúa sin cooldown
                return _evaluate_from_override(
                    avg, hot_threshold, cold_threshold,
                    target, config, sensor_alert,
                )

            case ControllerState.ERROR:
                # Recuperado de error: re-evalúa
                return _evaluate_from_override(
                    avg, hot_threshold, cold_threshold,
                    target, config, sensor_alert,
                )

            case _:
                # Fallback seguro
                return _off_outputs(sensor_alert, False)

    return _auto_decision()


def _evaluate_off(
    avg: float | None, hot_threshold: float, sensor_alert: bool, config: StateMachineConfig
) -> StateMachineOutputs:
    """Transiciones desde OFF."""
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
    """Transiciones desde COOLDOWN."""
    if not cooldown_done:
        return _cooldown_outputs(sensor_alert, False)

    # Cooldown terminado: re-evalúa
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
    """Transiciones desde COOLING_MAX."""
    if avg is None:
        # Sin datos: mantener enfriando
        return _cooling_max_outputs(sensor_alert, False, config)

    if avg < cold_threshold:
        # Objetivo alcanzado → apagar → cooldown
        return _cooldown_outputs(sensor_alert, False)

    if avg <= hot_threshold:
        # Zona intermedia → modular
        setpoint = _calculate_proportional_setpoint(avg, target, config)
        return _modulating_outputs(setpoint, sensor_alert, False)

    # Sigue caliente → mantener cooling max
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
    """Transiciones desde MODULATING."""
    if avg is None:
        # Sin datos: mantener última consigna
        return _modulating_outputs(last_setpoint, sensor_alert, False)

    if avg > hot_threshold:
        return _cooling_max_outputs(sensor_alert, False, config)

    if avg < cold_threshold:
        # Objetivo alcanzado → apagar → cooldown
        return _cooldown_outputs(sensor_alert, False)

    # Sigue en zona intermedia → recalcular consigna
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
    """Re-evaluación al volver a auto desde override o error. Sin cooldown."""
    if avg is None:
        return _off_outputs(sensor_alert, False)

    if avg > hot_threshold:
        return _cooling_max_outputs(sensor_alert, False, config)

    if avg >= cold_threshold:
        setpoint = _calculate_proportional_setpoint(avg, target, config)
        return _modulating_outputs(setpoint, sensor_alert, False)

    return _off_outputs(sensor_alert, False)
