"""Handler MQTT para sensores Zigbee.

Se suscribe a los topics de los sensores, mantiene un registro
de la última lectura de cada uno, y persiste los datos en disco
para que sobrevivan reinicios.
"""

import json
import logging
import os
import threading
import time
from pathlib import Path

import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)

# Fichero de persistencia (dentro del contenedor, montado como volumen en producción)
PERSIST_FILE = os.environ.get("SENSOR_PERSIST_FILE", "/app/data/sensor_readings.json")


class SensorReading:
    """Lectura de un sensor."""

    def __init__(self, temperature: float, humidity: float, battery: int, timestamp: float):
        self.temperature = temperature
        self.humidity = humidity
        self.battery = battery
        self.timestamp = timestamp

    def to_dict(self) -> dict:
        return {
            "temperature": self.temperature,
            "humidity": self.humidity,
            "battery": self.battery,
            "timestamp": self.timestamp,
        }

    @staticmethod
    def from_dict(d: dict) -> "SensorReading":
        return SensorReading(
            temperature=d["temperature"],
            humidity=d["humidity"],
            battery=d["battery"],
            timestamp=d["timestamp"],
        )


MAX_HISTORY_PER_SENSOR = 200


class MqttHandler:
    """Gestiona la conexión MQTT y las lecturas de sensores."""

    def __init__(self, broker: str, port: int, sensor_names: list[str]):
        self.broker = broker
        self.port = port
        self.sensor_names = sensor_names
        self.readings: dict[str, SensorReading] = {}  # Última lectura por sensor
        self.history: dict[str, list[SensorReading]] = {}  # Historial FIFO (max 200) por sensor
        self._lock = threading.Lock()
        self._client: mqtt.Client | None = None
        self._connected = False

        # Cargar datos persistidos del disco
        self._load_from_disk()

    def _load_from_disk(self):
        """Carga el historial de lecturas de cada sensor desde disco."""
        try:
            path = Path(PERSIST_FILE)
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                for name, sensor_data in data.items():
                    if name not in self.sensor_names:
                        continue
                    # Formato nuevo: lista de lecturas
                    if isinstance(sensor_data, list):
                        readings_list = [SensorReading.from_dict(d) for d in sensor_data]
                        self.history[name] = readings_list[-MAX_HISTORY_PER_SENSOR:]
                        if readings_list:
                            self.readings[name] = readings_list[-1]
                    else:
                        # Formato antiguo: un solo dict → migrar
                        reading = SensorReading.from_dict(sensor_data)
                        self.readings[name] = reading
                        self.history[name] = [reading]
                logger.info("Cargados %d sensores desde disco (%s)", len(self.readings), PERSIST_FILE)
            else:
                logger.info("No hay datos persistidos en %s (primer arranque)", PERSIST_FILE)
        except Exception as e:
            logger.warning("Error cargando datos de disco: %s", e)

    def _save_to_disk(self):
        """Guarda el historial de lecturas de cada sensor a disco."""
        try:
            path = Path(PERSIST_FILE)
            path.parent.mkdir(parents=True, exist_ok=True)
            data = {}
            with self._lock:
                for name, readings_list in self.history.items():
                    data[name] = [r.to_dict() for r in readings_list]
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.warning("Error guardando datos a disco: %s", e)

    def start(self):
        """Inicia la conexión MQTT y se suscribe a los topics."""
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.on_disconnect = self._on_disconnect

        logger.info("Conectando a MQTT %s:%d", self.broker, self.port)

        # Reintentar conexión
        for attempt in range(30):
            try:
                self._client.connect(self.broker, self.port, 60)
                self._client.loop_start()
                return
            except Exception as e:
                logger.warning("Intento %d conexión MQTT: %s", attempt + 1, e)
                time.sleep(2)

        raise ConnectionError(f"No se pudo conectar a MQTT {self.broker}:{self.port}")

    def stop(self):
        """Detiene la conexión MQTT y guarda datos a disco."""
        self._save_to_disk()
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        logger.info("Conectado a MQTT (rc=%s)", reason_code)
        self._connected = True
        client.subscribe("zigbee2mqtt/+")
        logger.info("Suscrito a zigbee2mqtt/+ (sensores: %s)", self.sensor_names)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        logger.warning("Desconectado de MQTT (rc=%s)", reason_code)
        self._connected = False

    def _on_message(self, client, userdata, msg):
        """Procesa un mensaje MQTT de un sensor."""
        try:
            parts = msg.topic.split("/")
            if len(parts) < 2:
                return

            sensor_name = "/".join(parts[1:])
            if sensor_name not in self.sensor_names:
                return

            payload = json.loads(msg.payload.decode())
            temperature = payload.get("temperature")
            humidity = payload.get("humidity", 0)
            battery = payload.get("battery", 0)

            if temperature is None:
                return

            reading = SensorReading(
                temperature=float(temperature),
                humidity=float(humidity),
                battery=int(battery),
                timestamp=time.time(),
            )

            with self._lock:
                self.readings[sensor_name] = reading
                # Guardar cada lectura como un punto en el historial (FIFO, max 200)
                if sensor_name not in self.history:
                    self.history[sensor_name] = []
                self.history[sensor_name].append(reading)
                if len(self.history[sensor_name]) > MAX_HISTORY_PER_SENSOR:
                    self.history[sensor_name] = self.history[sensor_name][-MAX_HISTORY_PER_SENSOR:]

            # Persistir a disco
            self._save_to_disk()

        except (json.JSONDecodeError, ValueError, KeyError) as e:
            logger.warning("Error procesando mensaje de %s: %s", msg.topic, e)

    def get_active_readings(self, max_age_seconds: int = 600) -> dict[str, SensorReading]:
        """Devuelve sensores con dato reciente (< max_age)."""
        now = time.time()
        active = {}
        with self._lock:
            for name, reading in self.readings.items():
                if (now - reading.timestamp) < max_age_seconds:
                    active[name] = reading
        return active

    def get_average_temperature(self, max_age_seconds: int = 600) -> float | None:
        """Calcula la media de temperatura de sensores activos."""
        active = self.get_active_readings(max_age_seconds)
        if not active:
            return None
        temps = [r.temperature for r in active.values()]
        return sum(temps) / len(temps)

    def get_average_humidity(self, max_age_seconds: int = 600) -> float | None:
        """Calcula la media de humedad de sensores activos."""
        active = self.get_active_readings(max_age_seconds)
        if not active:
            return None
        hums = [r.humidity for r in active.values()]
        return sum(hums) / len(hums)

    @property
    def is_connected(self) -> bool:
        return self._connected
