"""AC controller.

Orchestrates the state machine, reads sensors, applies outputs via MELCloud.
Decision logic is 100% in state_machine.py (pure function).
This module only does I/O and maintains temporal state.
"""

import logging
import threading
import time
from dataclasses import dataclass

from controllers.state_machine import (
    ControllerState,
    ForceOnParams,
    ManualMode,
    StateMachineConfig,
    StateMachineInputs,
    StateMachineOutputs,
    evaluate,
)
from melcloud_client import MelCloudClient
from mqtt_handler import MqttHandler
from state_persistence import PersistedState, load_state, save_state

logger = logging.getLogger(__name__)


@dataclass
class ControlConfig:
    """Control parameters."""

    target_temperature: float = 26.0
    hysteresis_on: float = 0.5
    hysteresis_off: float = 0.3
    min_setpoint: float = 19.0
    max_setpoint: float = 30.0
    cooldown_seconds: int = 180
    loop_interval: int = 45
    sensor_timeout: int = 600
    ac_mode: str = "cool"
    fan_speed_max: int = 3
    fan_speed_modulate: int = 0
    device_id: int = 0
    building_id: int = 0
    melcloud_max_failures: int = 100
    # Power for energy calculation (kW)
    ac_power_cooling_max: float = 2.5
    ac_power_cooling_mid: float = 1.75
    ac_power_modulating: float = 1.25
    ac_power_forced_on: float = 2.5


@dataclass
class ControlState:
    """Observable controller state (for API/UI)."""

    state: str = "off"
    setpoint: float = 24.0
    average_temp: float | None = None
    average_humidity: float | None = None  # Added to avoid recalculating in API
    active_sensors: int = 0
    total_sensors: int = 5
    last_update: float = 0.0
    override: str | None = "off"  # None=auto, "on", "off" - STARTS IN FORCE OFF
    sensor_alert: bool = False
    melcloud_error: bool = False
    force_on_params: ForceOnParams | None = None


@dataclass
class HistoryRecord:
    """History record."""

    timestamp: float
    average_temp: float | None
    state: str
    setpoint: float
    active_sensors: int


class ACController:
    """Virtual thermostat controller. Uses state machine to decide."""

    def __init__(
        self,
        mqtt_handler: MqttHandler,
        melcloud: MelCloudClient,
        config: ControlConfig,
    ):
        self.mqtt = mqtt_handler
        self.melcloud = melcloud
        self.config = config
        self.state = ControlState()
        self.history: list[HistoryRecord] = []
        self._running = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

        # Internal state machine variables
        self._current_sm_state: ControllerState = ControllerState.FORCED_OFF
        self._last_off_time: float = 0.0
        self._last_sensor_update_time: float = time.time()
        self._consecutive_melcloud_failures: int = 0
        self._last_outputs: StateMachineOutputs | None = None
        self._last_modulating_setpoint: float = 24.0

        # Energy tracking
        self._energy_state = {
            'last_state': 'off',
            'last_transition': time.time(),
            'kwh_session': 0.0  # kWh accumulated in current session
        }

    @property
    def current_state(self) -> ControlState:
        with self._lock:
            return self.state

    def get_history(self, limit: int = 100) -> list[dict]:
        """Returns the last N history entries."""
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

    def update_config(self, **kwargs):
        """Updates configuration parameters on the fly."""
        with self._lock:
            for key, value in kwargs.items():
                if hasattr(self.config, key):
                    setattr(self.config, key, value)
                    logger.info("Config updated: %s = %s", key, value)
        # Persist state after user change
        self._persist_state()

    def set_override(self, mode: str | None):
        """Sets manual override: None=auto, 'on'=force AC, 'off'=force off."""
        with self._lock:
            self.state.override = mode
        logger.info("Override set: %s", mode)
        # Persist state after user change
        self._persist_state()

    def set_force_on_params(self, temperature: float, fan_speed: int):
        """Saves force on parameters."""
        with self._lock:
            self.state.force_on_params = ForceOnParams(temperature=temperature, fan_speed=fan_speed)
        # Persist state after user change
        self._persist_state()

    def start(self):
        """Starts the control loop in a thread."""
        self._running = True
        self._thread = threading.Thread(target=self._control_loop, daemon=True)
        self._thread.start()
        logger.info("AC controller started (interval=%ds)", self.config.loop_interval)

    def stop(self):
        """Stops the control loop and persists final state."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=10)
        # Save state before shutdown
        self._persist_state()
        logger.info("AC controller stopped")

    def restore_state(self) -> bool:
        """Restores controller state from disk.
        
        Must be called BEFORE start() to restore previous session.
        
        Returns:
            True if state was restored, False if no state found
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
            self.state.override = persisted.override
            if persisted.force_on_temperature is not None:
                self.state.force_on_params = ForceOnParams(
                    temperature=persisted.force_on_temperature,
                    fan_speed=persisted.force_on_fan_speed or 0
                )
        
        # Restore internal state machine state
        try:
            self._current_sm_state = ControllerState(persisted.current_sm_state)
        except ValueError:
            logger.warning("Invalid state '%s', defaulting to FORCED_OFF", persisted.current_sm_state)
            self._current_sm_state = ControllerState.FORCED_OFF
        
        self._last_off_time = persisted.last_off_timestamp
        self._last_modulating_setpoint = persisted.last_modulating_setpoint
        
        logger.info("Controller state restored successfully")
        return True

    def _persist_state(self):
        """Saves current controller state to disk."""
        with self._lock:
            force_temp = self.state.force_on_params.temperature if self.state.force_on_params else None
            force_fan = self.state.force_on_params.fan_speed if self.state.force_on_params else None
            
            state = PersistedState(
                target_temperature=self.config.target_temperature,
                hysteresis_on=self.config.hysteresis_on,
                hysteresis_off=self.config.hysteresis_off,
                min_setpoint=self.config.min_setpoint,
                max_setpoint=self.config.max_setpoint,
                cooldown_seconds=self.config.cooldown_seconds,
                sensor_timeout=self.config.sensor_timeout,
                override=self.state.override,
                force_on_temperature=force_temp,
                force_on_fan_speed=force_fan,
                current_sm_state=self._current_sm_state.value,
                last_off_timestamp=self._last_off_time,
                last_modulating_setpoint=self._last_modulating_setpoint,
            )
        
        save_state(state)

    def _control_loop(self):
        """Main control loop."""
        while self._running:
            try:
                self._tick()
            except Exception as e:
                logger.error("Error en loop de control: %s", e, exc_info=True)

            time.sleep(self.config.loop_interval)

    def _tick(self):
        """One control cycle: read → evaluate → apply → record."""
        # 1. READ: Get inputs (calculate avg_temp and avg_hum ONCE)
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

        # 4. RECORD: Update visible state and history (includes avg_temp and avg_hum)
        self._update_state(outputs, avg_temp, avg_hum, active_count)

        # 5. LOG
        if avg_temp is not None:
            logger.info(
                "Tick: avg=%.1f°C, target=%.1f°C, state=%s, setpoint=%.1f°C, sensors=%d/%d%s%s",
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
        """Reads sensors and returns (avg_temp, avg_hum, active_count, most recent timestamp)."""
        avg_temp = None
        avg_hum = None
        last_sensor_time = self._last_sensor_update_time

        with self.mqtt._lock:
            readings = self.mqtt.readings
            if readings:
                # Calculate average temperature
                temps = [r.temperature for r in readings.values() if r.temperature is not None]
                if temps:
                    avg_temp = sum(temps) / len(temps)
                
                # Calculate average humidity
                hums = [r.humidity for r in readings.values() if r.humidity is not None]
                if hums:
                    avg_hum = sum(hums) / len(hums)
                
                # Find most recent timestamp
                timestamps = [r.timestamp for r in readings.values()]
                if timestamps:
                    most_recent = max(timestamps)
                    if most_recent > self._last_sensor_update_time:
                        self._last_sensor_update_time = most_recent
                        last_sensor_time = most_recent

        active_count = len(self.mqtt.get_active_readings(self.config.sensor_timeout))
        return avg_temp, avg_hum, active_count, last_sensor_time

    def _build_inputs(self, avg_temp: float | None, last_sensor_time: float) -> StateMachineInputs:
        """Builds inputs for state machine."""
        with self._lock:
            override = self.state.override
            force_params = self.state.force_on_params or ForceOnParams()

        # Map override string to ManualMode enum
        if override == "off":
            manual_mode = ManualMode.FORCE_OFF
        elif override == "on":
            manual_mode = ManualMode.FORCE_ON
        else:
            manual_mode = ManualMode.AUTO

        # Time since last off
        if self._last_off_time == 0.0:
            seconds_since_off = 99999.0
        else:
            seconds_since_off = time.time() - self._last_off_time

        # Time since last sensor update
        seconds_since_sensor = time.time() - last_sensor_time

        return StateMachineInputs(
            average_temp=avg_temp,
            target_temp=self.config.target_temperature,
            manual_mode=manual_mode,
            force_on_params=force_params,
            seconds_since_last_off=seconds_since_off,
            seconds_since_last_sensor_update=seconds_since_sensor,
            consecutive_melcloud_failures=self._consecutive_melcloud_failures,
        )

    def _build_sm_config(self) -> StateMachineConfig:
        """Builds config for state machine."""
        return StateMachineConfig(
            hysteresis_on=self.config.hysteresis_on,
            hysteresis_off=self.config.hysteresis_off,
            min_setpoint=self.config.min_setpoint,
            max_setpoint=self.config.max_setpoint,
            cooldown_seconds=self.config.cooldown_seconds,
            sensor_alert_seconds=self.config.sensor_timeout,
            melcloud_max_failures=self.config.melcloud_max_failures,
        )

    def _apply_outputs(self, outputs: StateMachineOutputs):
        """Aplica los outputs al AC vía MELCloud si es necesario."""
        # No actuar si estamos en ERROR
        if outputs.state == ControllerState.ERROR:
            self._current_sm_state = outputs.state
            return

        # Detectar si los outputs cambiaron respecto al último envío
        needs_send = self._needs_melcloud_update(outputs)

        if needs_send:
            success = self.melcloud.set_temperature(
                self.config.device_id,
                outputs.setpoint,
                power=outputs.power,
                mode=outputs.mode,
                fan_speed=outputs.fan_speed,
            )

            if success:
                self._consecutive_melcloud_failures = 0
                # Registrar apagado para cooldown
                if not outputs.power and self._current_sm_state not in (
                    ControllerState.OFF, ControllerState.COOLDOWN, ControllerState.FORCED_OFF
                ):
                    self._last_off_time = time.time()
                    logger.info("AC apagado. Cooldown de %ds iniciado.", COOLDOWN_SECONDS)
                elif outputs.power:
                    logger.info(
                        "AC encendido: consigna=%.1f°C, fan=%d",
                        outputs.setpoint, outputs.fan_speed,
                    )
            else:
                self._consecutive_melcloud_failures += 1
                logger.warning(
                    "Fallo MELCloud (%d consecutivos). Estado deseado: %s",
                    self._consecutive_melcloud_failures, outputs.state.value,
                )

        # Update internal state machine state
        old_sm_state = self._current_sm_state
        self._current_sm_state = outputs.state
        
        # Track energy transition si cambió el estado
        if old_sm_state != outputs.state:
            self._track_energy_transition(outputs.state.value)

        # Guardar última consigna de modulación
        if outputs.state == ControllerState.MODULATING:
            self._last_modulating_setpoint = outputs.setpoint

        # Guardar outputs para comparación en el próximo tick
        self._last_outputs = outputs

    def _needs_melcloud_update(self, outputs: StateMachineOutputs) -> bool:
        """Determina si hay que enviar un comando a MELCloud."""
        if self._last_outputs is None:
            return True

        last = self._last_outputs

        # Si cambió power, modo, consigna o fan → enviar
        if outputs.power != last.power:
            return True
        if outputs.mode != last.mode:
            return True
        if outputs.setpoint != last.setpoint:
            return True
        if outputs.fan_speed != last.fan_speed:
            return True

        return False

    def _update_state(self, outputs: StateMachineOutputs, avg_temp: float | None, avg_hum: float | None, active_count: int):
        """Updates visible state (for API/UI) and history."""
        with self._lock:
            self.state.state = outputs.state.value
            self.state.setpoint = outputs.setpoint
            self.state.average_temp = round(avg_temp, 2) if avg_temp else None
            self.state.average_humidity = round(avg_hum, 1) if avg_hum else None  # Guardamos para la API
            self.state.active_sensors = active_count
            self.state.last_update = time.time()
            self.state.sensor_alert = outputs.sensor_alert
            self.state.melcloud_error = outputs.melcloud_error

            # Histórico
            self.history.append(HistoryRecord(
                timestamp=time.time(),
                average_temp=round(avg_temp, 2) if avg_temp else None,
                state=outputs.state.value,
                setpoint=outputs.setpoint,
                active_sensors=active_count,
            ))

            # Limitar histórico
            if len(self.history) > 1000:
                self.history = self.history[-500:]

    # ===== Métodos de tracking de energía =====

    def _track_energy_transition(self, new_state: str):
        """Registra transición de estado para cálculo de energía."""
        now = time.time()
        elapsed_hours = (now - self._energy_state['last_transition']) / 3600
        
        # Calcular consumo del estado anterior
        power_kw = self._get_power_for_state(self._energy_state['last_state'])
        kwh_consumed = power_kw * elapsed_hours
        self._energy_state['kwh_session'] += kwh_consumed
        
        # Update state
        self._energy_state['last_state'] = new_state
        self._energy_state['last_transition'] = now
        
        if kwh_consumed > 0:
            logger.debug(
                "Energía: estado %s durante %.2fh consumió %.4f kWh (total sesión: %.4f kWh)",
                self._energy_state['last_state'],
                elapsed_hours,
                kwh_consumed,
                self._energy_state['kwh_session']
            )
    
    def _get_power_for_state(self, state: str) -> float:
        """Devuelve potencia en kW para un estado.
        
        Args:
            state: Estado del controlador
            
        Returns:
            Potencia en kW
        """
        power_map = {
            'cooling_max': self.config.ac_power_cooling_max,
            'cooling_mid': self.config.ac_power_cooling_mid,
            'modulating': self.config.ac_power_modulating,
            'forced_on': self.config.ac_power_forced_on,
        }
        return power_map.get(state, 0.0)
    
    def get_session_kwh(self) -> float:
        """Devuelve kWh consumidos en la sesión actual (desde último registro).
        
        Returns:
            kWh acumulados en la sesión
        """
        # Añadir consumo del estado actual hasta ahora
        now = time.time()
        elapsed_hours = (now - self._energy_state['last_transition']) / 3600
        power_kw = self._get_power_for_state(self._energy_state['last_state'])
        current_kwh = power_kw * elapsed_hours
        total = self._energy_state['kwh_session'] + current_kwh
        return total
    
    def reset_session_kwh(self):
        """Resetea contador de sesión (llamado tras registro horario)."""
        logger.info("Reseteando sesión de energía (acumulado: %.4f kWh)", self._energy_state['kwh_session'])
        self._energy_state['kwh_session'] = 0.0
        self._energy_state['last_transition'] = time.time()
