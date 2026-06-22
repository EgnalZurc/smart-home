"""Controlador del AC.

Orquesta la máquina de estados, lee sensores, aplica outputs vía MELCloud.
La lógica de decisión está 100% en state_machine.py (función pura).
Este módulo solo hace I/O y mantiene el estado temporal.
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
    COOLDOWN_SECONDS,
)
from melcloud_client import MelCloudClient
from mqtt_handler import MqttHandler

logger = logging.getLogger(__name__)


@dataclass
class ControlConfig:
    """Parámetros de control."""

    target_temperature: float = 23.0
    hysteresis_on: float = 0.5
    hysteresis_off: float = 0.3
    min_setpoint: float = 19.0
    max_setpoint: float = 30.0
    cooldown_seconds: int = COOLDOWN_SECONDS
    loop_interval: int = 45
    sensor_timeout: int = 600
    ac_mode: str = "cool"
    fan_speed_max: int = 3
    fan_speed_modulate: int = 0
    device_id: int = 12345
    building_id: int = 67890


@dataclass
class ControlState:
    """Estado observable del controlador (para API/UI)."""

    state: str = "off"
    setpoint: float = 24.0
    average_temp: float | None = None
    average_humidity: float | None = None  # Añadido para evitar recalcular en API
    active_sensors: int = 0
    total_sensors: int = 5
    last_update: float = 0.0
    override: str | None = None  # None=auto, "on", "off"
    sensor_alert: bool = False
    melcloud_error: bool = False
    force_on_params: ForceOnParams | None = None


@dataclass
class HistoryRecord:
    """Registro del histórico."""

    timestamp: float
    average_temp: float | None
    state: str
    setpoint: float
    active_sensors: int


class ACController:
    """Controlador del termostato virtual. Usa la máquina de estados para decidir."""

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

        # Variables internas de la máquina de estados
        self._current_sm_state: ControllerState = ControllerState.OFF
        self._last_off_time: float = 0.0
        self._last_sensor_update_time: float = time.time()
        self._consecutive_melcloud_failures: int = 0
        self._last_outputs: StateMachineOutputs | None = None
        self._last_modulating_setpoint: float = 24.0

        # Tracking de energía
        self._energy_state = {
            'last_state': 'off',
            'last_transition': time.time(),
            'kwh_session': 0.0  # kWh acumulados en la sesión actual
        }

    @property
    def current_state(self) -> ControlState:
        with self._lock:
            return self.state

    def get_history(self, limit: int = 100) -> list[dict]:
        """Devuelve las últimas N entradas del histórico."""
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
        """Actualiza parámetros de configuración en caliente."""
        with self._lock:
            for key, value in kwargs.items():
                if hasattr(self.config, key):
                    setattr(self.config, key, value)
                    logger.info("Config actualizada: %s = %s", key, value)

    def set_override(self, mode: str | None):
        """Establece override manual: None=auto, 'on'=forzar AC, 'off'=forzar apagado."""
        with self._lock:
            self.state.override = mode
        logger.info("Override establecido: %s", mode)

    def set_force_on_params(self, temperature: float, fan_speed: int):
        """Guarda los parámetros de forzar encendido."""
        with self._lock:
            self.state.force_on_params = ForceOnParams(temperature=temperature, fan_speed=fan_speed)

    def start(self):
        """Inicia el loop de control en un thread."""
        self._running = True
        self._thread = threading.Thread(target=self._control_loop, daemon=True)
        self._thread.start()
        logger.info("Controlador AC iniciado (intervalo=%ds)", self.config.loop_interval)

    def stop(self):
        """Detiene el loop de control."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=10)
        logger.info("Controlador AC detenido")

    def _control_loop(self):
        """Loop principal de control."""
        while self._running:
            try:
                self._tick()
            except Exception as e:
                logger.error("Error en loop de control: %s", e, exc_info=True)

            time.sleep(self.config.loop_interval)

    def _tick(self):
        """Un ciclo de control: leer → evaluar → aplicar → registrar."""
        # 1. LEER: Obtener inputs (calcula temp_media y hum_media UNA SOLA VEZ)
        avg_temp, avg_hum, active_count, last_sensor_time = self._read_sensors()
        inputs = self._build_inputs(avg_temp, last_sensor_time)
        sm_config = self._build_sm_config()

        # 2. EVALUAR: Llamar a la máquina de estados
        outputs = evaluate(
            current_state=self._current_sm_state,
            inputs=inputs,
            config=sm_config,
            last_modulating_setpoint=self._last_modulating_setpoint,
        )

        # 3. APLICAR: Enviar a MELCloud si cambió
        self._apply_outputs(outputs)

        # 4. REGISTRAR: Actualizar estado visible y histórico (incluye avg_temp y avg_hum)
        self._update_state(outputs, avg_temp, avg_hum, active_count)

        # 5. LOG
        if avg_temp is not None:
            logger.info(
                "Tick: media=%.1f°C, objetivo=%.1f°C, estado=%s, consigna=%.1f°C, sensores=%d/%d%s%s",
                avg_temp,
                self.config.target_temperature,
                outputs.state.value,
                outputs.setpoint,
                active_count,
                self.state.total_sensors,
                " [ALERTA SENSORES]" if outputs.sensor_alert else "",
                " [ERROR MELCLOUD]" if outputs.melcloud_error else "",
            )

    def _read_sensors(self) -> tuple[float | None, float | None, int, float]:
        """Lee sensores y devuelve (temp_media, hum_media, activos, timestamp más reciente)."""
        avg_temp = None
        avg_hum = None
        last_sensor_time = self._last_sensor_update_time

        with self.mqtt._lock:
            readings = self.mqtt.readings
            if readings:
                # Calcular temperatura media
                temps = [r.temperature for r in readings.values() if r.temperature is not None]
                if temps:
                    avg_temp = sum(temps) / len(temps)
                
                # Calcular humedad media
                hums = [r.humidity for r in readings.values() if r.humidity is not None]
                if hums:
                    avg_hum = sum(hums) / len(hums)
                
                # Encontrar el timestamp más reciente
                timestamps = [r.timestamp for r in readings.values()]
                if timestamps:
                    most_recent = max(timestamps)
                    if most_recent > self._last_sensor_update_time:
                        self._last_sensor_update_time = most_recent
                        last_sensor_time = most_recent

        active_count = len(self.mqtt.get_active_readings(self.config.sensor_timeout))
        return avg_temp, avg_hum, active_count, last_sensor_time

    def _build_inputs(self, avg_temp: float | None, last_sensor_time: float) -> StateMachineInputs:
        """Construye los inputs para la máquina de estados."""
        with self._lock:
            override = self.state.override
            force_params = self.state.force_on_params or ForceOnParams()

        # Mapear override string a ManualMode enum
        if override == "off":
            manual_mode = ManualMode.FORCE_OFF
        elif override == "on":
            manual_mode = ManualMode.FORCE_ON
        else:
            manual_mode = ManualMode.AUTO

        # Tiempo desde último apagado
        if self._last_off_time == 0.0:
            seconds_since_off = 99999.0
        else:
            seconds_since_off = time.time() - self._last_off_time

        # Tiempo desde última actualización de sensores
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
        """Construye la config para la máquina de estados."""
        return StateMachineConfig(
            hysteresis_on=self.config.hysteresis_on,
            hysteresis_off=self.config.hysteresis_off,
            min_setpoint=self.config.min_setpoint,
            max_setpoint=self.config.max_setpoint,
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

        # Actualizar estado interno de la máquina
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
        """Actualiza el estado visible (para API/UI) y el histórico."""
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
        
        # Actualizar estado
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
            'cooling_max': 2.5,
            'cooling_mid': 1.75,
            'modulating': 1.25,
            'forced_on': 2.5,  # Asumimos máximo
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
