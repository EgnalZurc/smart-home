"""AC controller.

Orchestrates the state machine, reads sensors, applies outputs via MELCloud.
Decision logic is 100% in state_machine.py (pure function).
This module only does I/O and maintains temporal state.

The controller runs a background thread that periodically:
1. Reads temperature sensors via MQTT
2. Evaluates the state machine to determine desired AC state
3. Sends commands to MELCloud when state changes
4. Updates observable state for the API/UI
5. Records history for debugging and analysis

Thread Safety:
    All public methods that access mutable state use _lock for thread safety.
    MELCloud API calls are serialized with _melcloud_lock to prevent races.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

import httpx
from config import (
    DEFAULT_AC_MODE,
    DEFAULT_FAN_SPEED,
    DEFAULT_FAN_SPEED_MAX,
    DEFAULT_MANUAL_TEMP,
    DEFAULT_SETPOINT,
    HISTORY_MAX_SIZE,
    HISTORY_TRIM_SIZE,
    SECONDS_SINCE_OFF_INITIAL,
)
from smart_home_common.clients.melcloud import MelCloudClient
from smart_home_common.mqtt.handler import MqttHandler
from state_persistence import PersistedState, load_state, save_state

from controllers.state_machine import (
    ControllerState,
    ManualMode,
    ManualParams,
    StateMachineConfig,
    StateMachineInputs,
    StateMachineOutputs,
    evaluate,
)
from controllers.thermal import (
    EnergyConfig,
    EnergyTracker,
    ThermalSampleRecorder,
)

if TYPE_CHECKING:
    from thermal_analysis import ThermalBuffer

logger = logging.getLogger(__name__)


class ErrorTrackerProtocol(Protocol):
    """Protocol for error tracking interface.

    Defines the minimal interface expected by the controller for error
    registration and clearing. Used for dependency injection typing.
    """

    def register(self, key: str, severity: str, message: str, category: str) -> None:
        """Register an error."""
        ...

    def clear(self, key: str) -> None:
        """Clear a previously registered error."""
        ...


@dataclass
class ControlConfig:
    """Control parameters for the AC controller.

    These parameters can be adjusted at runtime through the API and are
    persisted to disk to survive restarts.

    Attributes:
        target_temperature: Desired room temperature in Celsius.
        hysteresis_on: Temperature above target to start cooling (°C).
        hysteresis_off: Temperature below target to stop cooling (°C).
        min_setpoint: Minimum AC setpoint for proportional control (°C).
        max_setpoint: Maximum AC setpoint for proportional control (°C).
        cooldown_seconds: Compressor protection period after shutdown.
        loop_interval: Seconds between control loop iterations.
        sensor_timeout: Seconds before a sensor is considered offline.
        ac_state_update_interval: Seconds between MELCloud state polls.
        ac_mode: Default AC operation mode ("cool" or "heat").
        fan_speed_max: Maximum fan speed for cooling_max state.
        fan_speed_modulate: Fan speed for modulating state (0=auto).
        device_id: MELCloud device identifier.
        building_id: MELCloud building identifier.
        melcloud_max_failures: Consecutive failures before ERROR state.
        ac_power_cooling_max: Power consumption in cooling_max (kW).
        ac_power_cooling_mid: Power consumption in cooling_mid (kW).
        ac_power_modulating: Power consumption in modulating (kW).
        ac_power_forced_on: Power consumption in manual/forced_on (kW).
    """

    target_temperature: float = 26.0
    hysteresis_on: float = 0.5
    hysteresis_off: float = 0.3
    min_setpoint: float = 19.0
    max_setpoint: float = 30.0
    cooldown_seconds: int = 180
    loop_interval: int = 45
    sensor_timeout: int = 600
    ac_state_update_interval: int = 30
    ac_mode: str = DEFAULT_AC_MODE
    fan_speed_max: int = DEFAULT_FAN_SPEED_MAX
    fan_speed_modulate: int = DEFAULT_FAN_SPEED
    device_id: int = 0
    building_id: int = 0
    melcloud_max_failures: int = 100
    ac_power_cooling_max: float = 2.5
    ac_power_cooling_mid: float = 1.75
    ac_power_modulating: float = 1.25
    ac_power_forced_on: float = 2.5


@dataclass
class ControlState:
    """Observable controller state for API/UI.

    This dataclass represents the current state of the controller as seen
    by external consumers (REST API, web UI). It is updated after each
    control loop tick.

    Attributes:
        state: Current controller state name (e.g., "off", "cooling_max").
        setpoint: Current AC setpoint temperature (°C).
        average_temp: Average temperature from active sensors (°C).
        average_humidity: Average humidity from active sensors (%).
        active_sensors: Number of sensors reporting within timeout.
        total_sensors: Total number of configured sensors.
        last_update: Timestamp of last state update.
        control_mode: User-selected mode ("auto", "manual", "off").
        sensor_alert: True if sensor data is stale or missing.
        melcloud_error: True if MELCloud communication has failed.
        manual_params: User-specified parameters for manual mode.
        ac_mode: Current AC operation mode ("cool" or "heat").
        fan_speed: Current fan speed setting (0-3).
        ac_real_power: Real AC power state from MELCloud (cached).
        ac_real_mode: Real AC mode from MELCloud (cached).
        ac_real_fan_speed: Real AC fan speed from MELCloud (cached).
        ac_real_setpoint: Real AC setpoint from MELCloud (cached).
        ac_real_room_temp: Real room temp from AC sensor (cached).
        ac_real_last_update: Timestamp of last MELCloud cache update.
    """

    state: str = "off"
    setpoint: float = DEFAULT_SETPOINT
    average_temp: float | None = None
    average_humidity: float | None = None
    active_sensors: int = 0
    total_sensors: int = 5
    last_update: float = 0.0
    control_mode: str = "auto"
    sensor_alert: bool = False
    melcloud_error: bool = False
    manual_params: ManualParams | None = None
    ac_mode: str = DEFAULT_AC_MODE
    fan_speed: int = DEFAULT_FAN_SPEED

    ac_real_power: bool | None = None
    ac_real_mode: str | None = None
    ac_real_fan_speed: int | None = None
    ac_real_setpoint: float | None = None
    ac_real_room_temp: float | None = None
    ac_real_last_update: float = 0.0


@dataclass
class HistoryRecord:
    """Single history record for controller action tracking.

    Used for debugging, analysis, and the /api/ac/history endpoint.

    Attributes:
        timestamp: Unix timestamp of the record.
        average_temp: Average temperature at the time (°C).
        state: Controller state at the time.
        setpoint: AC setpoint at the time (°C).
        active_sensors: Number of active sensors.
    """

    timestamp: float
    average_temp: float | None
    state: str
    setpoint: float
    active_sensors: int


class ACController:
    """Virtual thermostat controller using a state machine for decisions.

    This class implements a smart thermostat that:
    - Reads temperature from multiple Zigbee sensors via MQTT
    - Uses a hysteresis-based state machine for control decisions
    - Sends commands to MELCloud to control a Mitsubishi AC unit
    - Provides observable state for a web UI and REST API
    - Persists configuration and state across restarts

    The control logic is fully delegated to the state_machine module,
    keeping this class focused on I/O and state management.

    Thread Safety:
        The controller runs a background thread for the control loop.
        All public state access methods are protected by _lock.
        MELCloud API calls are serialized by _melcloud_lock.

    Example:
        >>> mqtt_handler = MqttHandler(...)
        >>> melcloud = MelCloudClient(...)
        >>> config = ControlConfig(target_temperature=26.0)
        >>> controller = ACController(mqtt_handler, melcloud, config)
        >>> controller.restore_state()  # Load previous state if available
        >>> controller.start()  # Begin control loop
        >>> # ... later ...
        >>> controller.stop()  # Clean shutdown
    """

    def __init__(
        self,
        mqtt_handler: MqttHandler,
        melcloud: MelCloudClient,
        config: ControlConfig,
    ) -> None:
        """Initialize the AC controller.

        Args:
            mqtt_handler: MQTT handler for sensor data subscription.
            melcloud: MELCloud client for AC control commands.
            config: Controller configuration parameters.
        """
        self.mqtt = mqtt_handler
        self.melcloud = melcloud
        self.config = config
        self.state = ControlState()
        # Initialize manual_params with defaults
        self.state.manual_params = ManualParams(
            temperature=DEFAULT_MANUAL_TEMP,
            fan_speed=DEFAULT_FAN_SPEED,
            mode=DEFAULT_AC_MODE,
        )
        self.history: list[HistoryRecord] = []
        self._running = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._melcloud_lock = threading.Lock()

        # Internal state machine variables
        self._current_sm_state: ControllerState = ControllerState.OFF
        self._last_off_time: float = 0.0
        self._last_sensor_update_time: float = time.time()
        self._consecutive_melcloud_failures: int = 0
        self._error_tracker = None
        self._last_outputs: StateMachineOutputs | None = None
        self._last_modulating_setpoint: float = DEFAULT_SETPOINT

        # Thermal analysis (optional, injected via set_thermal_buffer())
        self._thermal_recorder = ThermalSampleRecorder()

        # Energy tracking using dedicated tracker
        energy_config = EnergyConfig(
            ac_power_cooling_max=config.ac_power_cooling_max,
            ac_power_cooling_mid=config.ac_power_cooling_mid,
            ac_power_modulating=config.ac_power_modulating,
            ac_power_forced_on=config.ac_power_forced_on,
        )
        self._energy_tracker = EnergyTracker(energy_config)

    @property
    def current_state(self) -> ControlState:
        """Get the current observable controller state (thread-safe).

        Returns:
            Copy of the current ControlState.
        """
        with self._lock:
            return self.state

    def get_history(self, limit: int = 100) -> list[dict]:
        """Return the last N history entries as dictionaries.

        Args:
            limit: Maximum number of entries to return.

        Returns:
            List of history records as dictionaries, newest last.
        """
        with self._lock:
            records = self.history[-limit:]
        return [
            {
                "timestamp": r.timestamp,
                "average_temp": r.average_temp,
                "state": r.state,
                "setpoint": r.setpoint,
                "active_sensors": r.active_sensors,
            }
            for r in records
        ]

    def update_config(self, **kwargs: Any) -> None:
        """Update configuration parameters on the fly.

        Any keyword argument that matches a ControlConfig attribute will
        be updated. Changes are persisted to disk.

        Args:
            **kwargs: Configuration parameters to update. Accepts any attribute
                name from ControlConfig (e.g., target_temperature, hysteresis_on).

        Example:
            >>> controller.update_config(target_temperature=25.0)
        """
        with self._lock:
            for key, value in kwargs.items():
                if hasattr(self.config, key):
                    setattr(self.config, key, value)
                    logger.info("Config updated: %s = %s", key, value)
        self._persist_state()

    def set_control_mode(self, mode: str) -> None:
        """Set the control mode.

        Args:
            mode: One of "auto", "manual", or "off".
                - auto: Automatic temperature-based control
                - manual: User-specified settings
                - off: AC disabled regardless of temperature
        """
        with self._lock:
            self.state.control_mode = mode
        logger.info("Control mode set: %s", mode)
        self._persist_state()

    def set_manual_params(self, temperature: float, fan_speed: int, mode: str) -> None:
        """Save manual mode parameters.

        These parameters are applied when control_mode is "manual".

        Args:
            temperature: Target setpoint temperature (°C).
            fan_speed: Fan speed (0=auto, 1=low, 2=mid, 3=high).
            mode: AC mode ("cool" or "heat").
        """
        with self._lock:
            self.state.manual_params = ManualParams(
                temperature=temperature, fan_speed=fan_speed, mode=mode
            )
        logger.info(
            "Manual params set: temp=%.1f°C, fan=%d, mode=%s",
            temperature,
            fan_speed,
            mode,
        )
        self._persist_state()

    def update_manual_param(self, param: str, value: float | int | str) -> None:
        """Update a single manual parameter for real-time UI updates.

        Args:
            param: Parameter name ("temperature", "fan_speed", or "mode").
            value: New value for the parameter (float for temperature, int for
                fan_speed, str for mode).
        """
        with self._lock:
            if self.state.manual_params is None:
                self.state.manual_params = ManualParams()

            current = self.state.manual_params
            if param == "temperature":
                self.state.manual_params = ManualParams(
                    temperature=value, fan_speed=current.fan_speed, mode=current.mode
                )
            elif param == "fan_speed":
                self.state.manual_params = ManualParams(
                    temperature=current.temperature, fan_speed=value, mode=current.mode
                )
            elif param == "mode":
                self.state.manual_params = ManualParams(
                    temperature=current.temperature,
                    fan_speed=current.fan_speed,
                    mode=value,
                )

        logger.info("Manual param updated: %s = %s", param, value)
        self._persist_state()

    def set_temperature_safe(
        self,
        temperature: float,
        *,
        power: bool = True,
        mode: str = "cool",
        fan_speed: int = 0,
    ) -> bool:
        """Thread-safe wrapper for MELCloud set_temperature.

        Acquires _melcloud_lock before calling the MELCloud client to prevent
        race conditions between API endpoints and the control loop.

        Args:
            temperature: Target setpoint temperature (°C).
            power: Whether to turn AC on (True) or off (False).
            mode: AC mode ("cool" or "heat").
            fan_speed: Fan speed (0=auto, 1=low, 2=mid, 3=high).

        Returns:
            True if command was successful, False otherwise.
        """
        with self._melcloud_lock:
            return self.melcloud.set_temperature(
                self.config.device_id,
                temperature,
                power=power,
                mode=mode,
                fan_speed=fan_speed,
            )

    def start(self) -> None:
        """Start the control loop in a background thread.

        The control loop runs periodically (every loop_interval seconds)
        until stop() is called.
        """
        self._running = True
        self._thread = threading.Thread(target=self._control_loop, daemon=True)
        self._thread.start()
        logger.info("AC controller started (interval=%ds)", self.config.loop_interval)

    def stop(self) -> None:
        """Stop the control loop and persist final state.

        Waits up to 10 seconds for the control thread to finish.
        """
        self._running = False
        if self._thread:
            self._thread.join(timeout=10)
        self._persist_state()
        logger.info("AC controller stopped")

    def set_error_tracker(self, tracker: ErrorTrackerProtocol | None) -> None:
        """Inject error tracker for centralized error reporting.

        Args:
            tracker: ErrorTracker instance for registering/clearing errors.
        """
        self._error_tracker = tracker

    def set_thermal_buffer(
        self,
        buffer: ThermalBuffer,
        outdoor_temp_provider: Callable[[], float | None] | None = None,
    ) -> None:
        """Inject thermal buffer and optional outdoor temperature provider.

        When set, the controller appends one ThermalSample per tick so the
        thermal-curves analysis can run.

        Args:
            buffer: ThermalBuffer instance for sample storage.
            outdoor_temp_provider: Zero-arg callable returning outdoor temp (°C)
                or None. Called defensively so failures don't break control.
        """
        self._thermal_recorder.set_buffer(buffer)
        if outdoor_temp_provider is not None:
            self._thermal_recorder.set_outdoor_provider(outdoor_temp_provider)

    def restore_state(self) -> bool:
        """Restore controller state from disk.

        Must be called BEFORE start() to restore previous session.

        Returns:
            True if state was restored, False if no state found.
        """
        persisted = load_state()
        if persisted is None:
            logger.info("No previous state to restore, using defaults")
            return False

        # Restore configuration
        self.config.target_temperature = persisted.target_temperature
        self.config.hysteresis_on = persisted.hysteresis_on
        self.config.hysteresis_off = persisted.hysteresis_off
        self.config.min_setpoint = persisted.min_setpoint
        self.config.max_setpoint = persisted.max_setpoint
        self.config.cooldown_seconds = persisted.cooldown_seconds
        self.config.sensor_timeout = persisted.sensor_timeout

        # Restore manual mode
        with self._lock:
            if persisted.override == "on":
                self.state.control_mode = "manual"
            elif persisted.override == "off":
                self.state.control_mode = "off"
            else:
                self.state.control_mode = "auto"

            if persisted.force_on_temperature is not None:
                self.state.manual_params = ManualParams(
                    temperature=persisted.force_on_temperature,
                    fan_speed=persisted.force_on_fan_speed or DEFAULT_FAN_SPEED,
                    mode=DEFAULT_AC_MODE,
                )
            else:
                self.state.manual_params = ManualParams(
                    temperature=DEFAULT_MANUAL_TEMP,
                    fan_speed=DEFAULT_FAN_SPEED,
                    mode=DEFAULT_AC_MODE,
                )

        # Restore internal state machine state
        try:
            state_mapping = {"forced_on": "manual", "forced_off": "system_off"}
            state_value = state_mapping.get(
                persisted.current_sm_state, persisted.current_sm_state
            )
            self._current_sm_state = ControllerState(state_value)
        except ValueError:
            logger.warning(
                "Invalid state '%s', defaulting to SYSTEM_OFF",
                persisted.current_sm_state,
            )
            self._current_sm_state = ControllerState.SYSTEM_OFF

        self._last_off_time = persisted.last_off_timestamp
        self._last_modulating_setpoint = persisted.last_modulating_setpoint

        logger.info("Controller state restored successfully")
        return True

    def _persist_state(self) -> None:
        """Save current controller state to disk."""
        with self._lock:
            manual_temp = (
                self.state.manual_params.temperature
                if self.state.manual_params
                else None
            )
            manual_fan = (
                self.state.manual_params.fan_speed if self.state.manual_params else None
            )

            override_value = None
            if self.state.control_mode == "manual":
                override_value = "on"
            elif self.state.control_mode == "off":
                override_value = "off"

            state = PersistedState(
                target_temperature=self.config.target_temperature,
                hysteresis_on=self.config.hysteresis_on,
                hysteresis_off=self.config.hysteresis_off,
                min_setpoint=self.config.min_setpoint,
                max_setpoint=self.config.max_setpoint,
                cooldown_seconds=self.config.cooldown_seconds,
                sensor_timeout=self.config.sensor_timeout,
                override=override_value,
                force_on_temperature=manual_temp,
                force_on_fan_speed=manual_fan,
                current_sm_state=self._current_sm_state.value,
                last_off_timestamp=self._last_off_time,
                last_modulating_setpoint=self._last_modulating_setpoint,
            )

        save_state(state)

    def _control_loop(self) -> None:
        """Main control loop running in background thread.

        Executes one tick per loop_interval seconds until stopped.
        Exceptions are caught and logged to prevent thread death.
        """
        while self._running:
            try:
                self._tick()
            except (
                OSError,
                ValueError,
                TypeError,
                KeyError,
                AttributeError,
                httpx.HTTPError,
                httpx.TimeoutException,
            ) as e:
                # Known recoverable errors: network issues, sensor data parsing,
                # state access errors, MELCloud API failures.
                # Log and continue to keep the control loop alive.
                # Log message in Spanish for consistency with existing logs and
                # to match the dashboard UI language (user-facing service).
                logger.exception("Error en loop de control: %s", e)

            time.sleep(self.config.loop_interval)

    def _tick(self) -> None:
        """Execute one control cycle: read → evaluate → apply → record.

        This is the core of the control loop, called once per interval.
        """
        # 1. READ: Get inputs
        avg_temp, avg_hum, active_count, last_sensor_time = self._read_sensors()
        inputs = self._build_inputs(avg_temp, last_sensor_time)
        sm_config = self._build_sm_config()

        # 2. EVALUATE: Call state machine
        outputs = evaluate(
            current_state=self._current_sm_state,
            inputs=inputs,
            config=sm_config,
            last_modulating_setpoint=self._last_modulating_setpoint,
        )

        # 3. APPLY: Send to MELCloud if changed
        self._apply_outputs(outputs)

        # 4. RECORD: Update visible state and history
        self._update_state(outputs, avg_temp, avg_hum, active_count)

        # 5. LOG
        if avg_temp is not None:
            logger.info(
                "Tick: avg=%.1f°C, target=%.1f°C, state=%s, setpoint=%.1f°C, "
                "sensors=%d/%d%s%s",
                avg_temp,
                self.config.target_temperature,
                outputs.state.value,
                outputs.setpoint,
                active_count,
                self.state.total_sensors,
                " [SENSOR ALERT]" if outputs.sensor_alert else "",
                " [MELCLOUD ERROR]" if outputs.melcloud_error else "",
            )

    def _read_sensors(self) -> tuple[float | None, float | None, int, float]:
        """Read sensors and calculate averages.

        Returns:
            Tuple of (avg_temp, avg_hum, active_count, most_recent_timestamp).
            avg_temp and avg_hum are None if no valid readings available.
        """
        avg_temp = None
        avg_hum = None
        last_sensor_time = self._last_sensor_update_time

        try:
            # Exclude virtual 'AC' sensor from averages
            active_readings = {
                name: r
                for name, r in self.mqtt.get_active_readings(
                    self.config.sensor_timeout
                ).items()
                if name != "AC"
            }

            if active_readings:
                temps = [
                    r.temperature
                    for r in active_readings.values()
                    if r.temperature is not None
                ]
                if temps:
                    avg_temp = sum(temps) / len(temps)

                hums = [
                    r.humidity
                    for r in active_readings.values()
                    if r.humidity is not None
                ]
                if hums:
                    avg_hum = sum(hums) / len(hums)

                timestamps = [r.timestamp for r in active_readings.values()]
                if timestamps:
                    most_recent = max(timestamps)
                    if most_recent > self._last_sensor_update_time:
                        self._last_sensor_update_time = most_recent
                        last_sensor_time = most_recent

            active_count = len(active_readings)
        except (KeyError, AttributeError, TypeError) as e:
            # Sensor data structure errors during iteration - return safe defaults
            logger.warning("Error reading sensor data: %s", e)
            active_count = 0

        return avg_temp, avg_hum, active_count, last_sensor_time

    def _build_inputs(
        self, avg_temp: float | None, last_sensor_time: float
    ) -> StateMachineInputs:
        """Build inputs dataclass for state machine evaluation.

        Args:
            avg_temp: Current average temperature from sensors (°C).
            last_sensor_time: Timestamp of most recent sensor reading.

        Returns:
            StateMachineInputs populated with current system state.
        """
        with self._lock:
            control_mode = self.state.control_mode
            manual_params = self.state.manual_params or ManualParams()

        # Map control_mode string to ManualMode enum
        if control_mode == "off":
            manual_mode = ManualMode.OFF
        elif control_mode == "manual":
            manual_mode = ManualMode.MANUAL
        else:
            manual_mode = ManualMode.AUTO

        # Time since last off
        if self._last_off_time == 0.0:
            seconds_since_off = SECONDS_SINCE_OFF_INITIAL
        else:
            seconds_since_off = time.time() - self._last_off_time

        # Time since last sensor update
        seconds_since_sensor = time.time() - last_sensor_time

        return StateMachineInputs(
            average_temp=avg_temp,
            target_temp=self.config.target_temperature,
            manual_mode=manual_mode,
            manual_params=manual_params,
            seconds_since_last_off=seconds_since_off,
            seconds_since_last_sensor_update=seconds_since_sensor,
            consecutive_melcloud_failures=self._consecutive_melcloud_failures,
        )

    def _build_sm_config(self) -> StateMachineConfig:
        """Build configuration dataclass for state machine.

        Returns:
            StateMachineConfig populated from current ControlConfig.
        """
        return StateMachineConfig(
            hysteresis_on=self.config.hysteresis_on,
            hysteresis_off=self.config.hysteresis_off,
            min_setpoint=self.config.min_setpoint,
            max_setpoint=self.config.max_setpoint,
            cooldown_seconds=self.config.cooldown_seconds,
            sensor_alert_seconds=self.config.sensor_timeout,
            melcloud_max_failures=self.config.melcloud_max_failures,
        )

    def _apply_outputs(self, outputs: StateMachineOutputs) -> None:
        """Apply state machine outputs to AC via MELCloud.

        Only sends commands when outputs have changed from the previous tick.

        Args:
            outputs: State machine outputs to apply.
        """
        # Don't act if we're in ERROR state
        if outputs.state == ControllerState.ERROR:
            self._current_sm_state = outputs.state
            return

        needs_send = self._needs_melcloud_update(outputs)

        if needs_send:
            with self._melcloud_lock:
                success = self.melcloud.set_temperature(
                    self.config.device_id,
                    outputs.setpoint,
                    power=outputs.power,
                    mode=outputs.mode,
                    fan_speed=outputs.fan_speed,
                )

            if success:
                self._consecutive_melcloud_failures = 0
                if not outputs.power and self._current_sm_state not in (
                    ControllerState.OFF,
                    ControllerState.COOLDOWN,
                    ControllerState.SYSTEM_OFF,
                ):
                    self._last_off_time = time.time()
                    logger.info(
                        "AC apagado. Cooldown de %ds iniciado.",
                        self.config.cooldown_seconds,
                    )
                elif outputs.power:
                    logger.info(
                        "AC encendido: consigna=%.1f°C, fan=%d",
                        outputs.setpoint,
                        outputs.fan_speed,
                    )
            else:
                self._consecutive_melcloud_failures += 1
                logger.warning(
                    "Fallo MELCloud (%d consecutivos). Estado deseado: %s",
                    self._consecutive_melcloud_failures,
                    outputs.state.value,
                )

        old_sm_state = self._current_sm_state
        self._current_sm_state = outputs.state

        if old_sm_state != outputs.state:
            self._track_energy_transition(outputs.state.value)

        if outputs.state == ControllerState.MODULATING:
            self._last_modulating_setpoint = outputs.setpoint

        self._last_outputs = outputs

    def _needs_melcloud_update(self, outputs: StateMachineOutputs) -> bool:
        """Determine if MELCloud command is needed.

        Args:
            outputs: New state machine outputs.

        Returns:
            True if any controllable parameter has changed.
        """
        with self._lock:
            if self._last_outputs is None:
                return True
            last = self._last_outputs

        if outputs.power != last.power:
            return True
        if outputs.mode != last.mode:
            return True
        if outputs.setpoint != last.setpoint:
            return True
        return outputs.fan_speed != last.fan_speed

    def _update_state(
        self,
        outputs: StateMachineOutputs,
        avg_temp: float | None,
        avg_hum: float | None,
        active_count: int,
    ) -> None:
        """Update visible state and history after a tick.

        Args:
            outputs: State machine outputs from this tick.
            avg_temp: Average temperature from sensors (°C).
            avg_hum: Average humidity from sensors (%).
            active_count: Number of active sensors.
        """
        with self._lock:
            self.state.state = outputs.state.value
            self.state.setpoint = outputs.setpoint
            self.state.ac_mode = outputs.mode
            self.state.fan_speed = outputs.fan_speed
            self.state.average_temp = round(avg_temp, 2) if avg_temp else None
            self.state.average_humidity = round(avg_hum, 1) if avg_hum else None
            self.state.active_sensors = active_count
            self.state.last_update = time.time()
            self.state.sensor_alert = outputs.sensor_alert
            self.state.melcloud_error = outputs.melcloud_error

            # Register/clear errors in error tracker
            if self._error_tracker:
                if outputs.sensor_alert:
                    self._error_tracker.register(
                        "sensor_alert",
                        "warning",
                        "One or more sensors are offline or not reporting",
                        "sensors",
                    )
                else:
                    self._error_tracker.clear("sensor_alert")

                if outputs.melcloud_error:
                    self._error_tracker.register(
                        "melcloud_error",
                        "error",
                        f"MELCloud unreachable ({self._consecutive_melcloud_failures} "
                        "consecutive failures)",
                        "melcloud",
                    )
                else:
                    self._error_tracker.clear("melcloud_error")

            # Record history
            self.history.append(
                HistoryRecord(
                    timestamp=time.time(),
                    average_temp=round(avg_temp, 2) if avg_temp else None,
                    state=outputs.state.value,
                    setpoint=outputs.setpoint,
                    active_sensors=active_count,
                )
            )

            # Trim history if needed
            if len(self.history) > HISTORY_MAX_SIZE:
                self.history = self.history[-HISTORY_TRIM_SIZE:]

        self._record_thermal_sample(outputs, avg_temp)

    def _record_thermal_sample(
        self, outputs: StateMachineOutputs, avg_temp: float | None
    ) -> None:
        """Append one ThermalSample to the injected buffer if configured.

        Args:
            outputs: State machine outputs from this tick.
            avg_temp: Average temperature from sensors (°C).
        """
        self._thermal_recorder.record(
            timestamp=time.time(),
            average_temp=avg_temp,
            setpoint=outputs.setpoint,
            state=outputs.state.value,
            mode=outputs.mode,
        )

    def update_ac_real_cache(self, melcloud_data: dict) -> None:
        """Update AC real state cache from MELCloud subscription data.

        Called by SubscriptionManager after fetching from MELCloud.

        Args:
            melcloud_data: Raw data dictionary from MELCloud API.
        """
        if melcloud_data is None:
            return

        mode_map = {1: "heat", 2: "dry", 3: "cool", 7: "fan", 8: "auto"}

        with self._lock:
            self.state.ac_real_power = melcloud_data.get("Power", False)
            self.state.ac_real_mode = mode_map.get(
                melcloud_data.get("OperationMode"), "cool"
            )
            self.state.ac_real_fan_speed = melcloud_data.get("SetFanSpeed", 0)
            self.state.ac_real_setpoint = melcloud_data.get("SetTemperature")
            self.state.ac_real_room_temp = melcloud_data.get("RoomTemperature")
            self.state.ac_real_last_update = time.time()

    def _track_energy_transition(self, new_state: str) -> None:
        """Record state transition for energy calculation.

        Args:
            new_state: New controller state name.
        """
        self._energy_tracker.record_transition(new_state)

    def _get_power_for_state(self, state: str) -> float:
        """Return power consumption in kW for a given state.

        Args:
            state: Controller state name.

        Returns:
            Power consumption in kW, or 0.0 for off states.
        """
        return self._energy_tracker.get_power_for_state(state)

    def get_session_kwh(self) -> float:
        """Return kWh consumed in current session since last reset.

        Includes energy consumed in the current state up to now.

        Returns:
            Total kWh consumed in the current session.
        """
        return self._energy_tracker.get_session_kwh()

    def reset_session_kwh(self) -> None:
        """Reset session energy counter (called after hourly log)."""
        self._energy_tracker.reset_session()
