"""MQTT handler for Zigbee sensors.

Subscribes to sensor topics, maintains a registry
of the last reading from each one, and persists data to disk
so they survive restarts.
"""

import json
import logging
import os
import threading
import time
from pathlib import Path

import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)

# Persistence file (inside container, mounted as volume in production)
PERSIST_FILE = os.environ.get("SENSOR_PERSIST_FILE", "/app/data/sensor_readings.json")


class SensorReading:
    """Reading from a sensor."""

    def __init__(self, temperature: float, humidity: float | None, battery: int | None, timestamp: float):
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


class MqttHandler:
    """Manages MQTT connection and sensor readings."""

    def __init__(
        self, 
        broker: str, 
        port: int, 
        sensor_names: list[str],
        connect_retries: int = 30,
        retry_delay: int = 2,
        keepalive: int = 60,
        max_history: int = 200
    ):
        self.broker = broker
        self.port = port
        self.sensor_names = sensor_names
        self.connect_retries = connect_retries
        self.retry_delay = retry_delay
        self.keepalive = keepalive
        self.max_history = max_history
        self.readings: dict[str, SensorReading] = {}  # Last reading per sensor
        self.history: dict[str, list[SensorReading]] = {}  # FIFO history per sensor
        self._lock = threading.Lock()
        self._client: mqtt.Client | None = None
        self._connected = False

        # Load persisted data from disk
        self._load_from_disk()

    def _load_from_disk(self):
        """Loads reading history for each sensor from disk."""
        try:
            path = Path(PERSIST_FILE)
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                for name, sensor_data in data.items():
                    # 'AC' is a virtual sensor (MELCloud room temp) - always load it
                    if name not in self.sensor_names and name != "AC":
                        continue
                    # New format: list of readings
                    if isinstance(sensor_data, list):
                        readings_list = [SensorReading.from_dict(d) for d in sensor_data]
                        self.history[name] = readings_list[-self.max_history:]
                        if readings_list:
                            self.readings[name] = readings_list[-1]
                    else:
                        # Old format: single dict → migrate
                        reading = SensorReading.from_dict(sensor_data)
                        self.readings[name] = reading
                        self.history[name] = [reading]
                logger.info("Loaded %d sensors from disk (%s)", len(self.readings), PERSIST_FILE)
            else:
                logger.info("No persisted data at %s (first boot)", PERSIST_FILE)
        except Exception as e:
            logger.warning("Error loading data from disk: %s", e)

    def _save_to_disk(self):
        """Saves reading history for each sensor to disk.
        
        IMPORTANT: Must be called WITH active lock or with data copy.
        """
        try:
            path = Path(PERSIST_FILE)
            path.parent.mkdir(parents=True, exist_ok=True)
            # Make copy inside lock to avoid race conditions
            data = {}
            for name, readings_list in self.history.items():
                data[name] = [r.to_dict() for r in readings_list]
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.warning("Error saving data to disk: %s", e)

    def start(self):
        """Starts MQTT connection and subscribes to topics."""
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self._error_tracker = None  # F0.30 - injected via set_error_tracker()
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.on_disconnect = self._on_disconnect

        logger.info("Connecting to MQTT %s:%d", self.broker, self.port)

        # Retry connection
        for attempt in range(self.connect_retries):
            try:
                self._client.connect(self.broker, self.port, self.keepalive)
                self._client.loop_start()
                return
            except Exception as e:
                logger.warning("MQTT connection attempt %d: %s", attempt + 1, e)
                time.sleep(self.retry_delay)

        raise ConnectionError(f"Could not connect to MQTT {self.broker}:{self.port}")

    def stop(self):
        """Stops MQTT connection and saves data to disk."""
        self._save_to_disk()
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()

    def set_error_tracker(self, tracker) -> None:
        """Inject error tracker (F0.30)."""
        self._error_tracker = tracker

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        logger.info("Connected to MQTT (rc=%s)", reason_code)
        self._connected = True
        if self._error_tracker:
            self._error_tracker.clear("mqtt_disconnected")
        client.subscribe("zigbee2mqtt/+")
        logger.info("Subscribed to zigbee2mqtt/+ (sensors: %s)", self.sensor_names)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        logger.warning("Disconnected from MQTT (rc=%s)", reason_code)
        self._connected = False
        if self._error_tracker:
            self._error_tracker.register("mqtt_disconnected", "error", "Disconnected from MQTT broker", "mqtt")

    def _on_message(self, client, userdata, msg):
        """Processes an MQTT message from a sensor."""
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

            # Do ALL manipulation inside the lock (fix race condition)
            with self._lock:
                self.readings[sensor_name] = reading
                # Save each reading as a point in history (FIFO)
                if sensor_name not in self.history:
                    self.history[sensor_name] = []
                self.history[sensor_name].append(reading)
                if len(self.history[sensor_name]) > self.max_history:
                    self.history[sensor_name] = self.history[sensor_name][-self.max_history:]
                
                # Make copy of data to persist
                data_to_save = {}
                for name, readings_list in self.history.items():
                    data_to_save[name] = [r.to_dict() for r in readings_list]
            
            # Persist to disk OUTSIDE lock to not block
            try:
                path = Path(PERSIST_FILE)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(data_to_save, ensure_ascii=False), encoding="utf-8")
            except Exception as e:
                logger.warning("Error saving data to disk: %s", e)

        except (json.JSONDecodeError, ValueError, KeyError) as e:
            logger.warning("Error processing message from %s: %s", msg.topic, e)

    def record_ac_temp(self, room_temp: float) -> None:
        """Record A/C room temperature as an hourly sample in history.

        Stored under the key 'AC' so it appears in /api/sensors/history
        alongside Zigbee sensor data.
        """
        reading = SensorReading(
            temperature=room_temp,
            humidity=None,
            battery=None,
            timestamp=time.time(),
        )
        with self._lock:
            if "AC" not in self.history:
                self.history["AC"] = []
            self.history["AC"].append(reading)
            if len(self.history["AC"]) > self.max_history:
                self.history["AC"] = self.history["AC"][-self.max_history:]
            data_to_save = {}
            for name, readings_list in self.history.items():
                data_to_save[name] = [r.to_dict() for r in readings_list]

        try:
            path = Path(PERSIST_FILE)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data_to_save, ensure_ascii=False), encoding="utf-8")
            logger.info("AC room temp recorded: %.1f°C", room_temp)
        except Exception as e:
            logger.warning("Error saving AC temp to disk: %s", e)

    def get_active_readings(self, max_age_seconds: int = 600) -> dict[str, SensorReading]:
        """Returns sensors with recent data (< max_age)."""
        now = time.time()
        active = {}
        with self._lock:
            for name, reading in self.readings.items():
                if (now - reading.timestamp) < max_age_seconds:
                    active[name] = reading
        return active

    def get_average_temperature(self, max_age_seconds: int = 600) -> float | None:
        """Calculates average temperature from active sensors."""
        active = self.get_active_readings(max_age_seconds)
        if not active:
            return None
        temps = [r.temperature for r in active.values()]
        return sum(temps) / len(temps)

    def get_average_humidity(self, max_age_seconds: int = 600) -> float | None:
        """Calculates average humidity from active sensors."""
        active = self.get_active_readings(max_age_seconds)
        if not active:
            return None
        hums = [r.humidity for r in active.values()]
        return sum(hums) / len(hums)

    @property
    def is_connected(self) -> bool:
        return self._connected
