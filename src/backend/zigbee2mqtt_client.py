"""Cliente para obtener información de Zigbee2MQTT.

Permite descubrir automáticamente dispositivos conectados mediante MQTT.
"""

import json
import logging
from typing import Any

import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)


class Zigbee2MQTTClient:
    """Cliente para interactuar con Zigbee2MQTT vía MQTT."""

    def __init__(self, mqtt_broker: str, mqtt_port: int = 1883, timeout: float = 10.0):
        """Inicializa el cliente.

        Args:
            mqtt_broker: Host del broker MQTT (ej: mosquitto)
            mqtt_port: Puerto del broker MQTT (default: 1883)
            timeout: Timeout en segundos para obtener respuestas
        """
        self.mqtt_broker = mqtt_broker
        self.mqtt_port = mqtt_port
        self.timeout = timeout
        self.devices: list[dict[str, Any]] = []
        self.response_received = False

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        """Callback al conectar."""
        if rc == 0:
            logger.debug("Conectado a MQTT %s:%d", self.mqtt_broker, self.mqtt_port)
            # Suscribirse al topic de dispositivos
            client.subscribe("zigbee2mqtt/bridge/devices")
        else:
            logger.error("Error al conectar a MQTT: rc=%d", rc)

    def _on_message(self, client, userdata, msg):
        """Callback al recibir mensaje."""
        if msg.topic == "zigbee2mqtt/bridge/devices":
            try:
                self.devices = json.loads(msg.payload.decode())
                self.response_received = True
                logger.debug("Recibidos %d dispositivos", len(self.devices))
            except json.JSONDecodeError as e:
                logger.error("Error al decodificar JSON de dispositivos: %s", e)

    def get_devices(self) -> list[dict[str, Any]]:
        """Obtiene la lista de dispositivos conectados a Zigbee2MQTT vía MQTT.

        Returns:
            Lista de dispositivos. Cada dispositivo es un dict con:
            - friendly_name: Nombre del dispositivo
            - ieee_address: Dirección IEEE
            - type: Tipo (Coordinator, Router, EndDevice)
            - model_id: ID del modelo
            - manufacturer: Fabricante
            - definition: Definición del dispositivo (contiene 'supported', 'exposes', etc.)

        Raises:
            Exception: Si no se puede conectar o no se recibe respuesta
        """
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        client.on_connect = self._on_connect
        client.on_message = self._on_message

        try:
            logger.info("Conectando a MQTT %s:%d para obtener dispositivos...", self.mqtt_broker, self.mqtt_port)
            client.connect(self.mqtt_broker, self.mqtt_port, 60)
            
            # Iniciar loop en background
            client.loop_start()

            # Solicitar lista de dispositivos
            client.publish("zigbee2mqtt/bridge/request/devices", "")

            # Esperar respuesta con timeout
            import time
            elapsed = 0.0
            poll_interval = 0.1
            while not self.response_received and elapsed < self.timeout:
                time.sleep(poll_interval)
                elapsed += poll_interval

            if not self.response_received:
                raise Exception(f"Timeout esperando respuesta de Zigbee2MQTT después de {self.timeout}s")

            logger.info("Obtenidos %d dispositivos de Zigbee2MQTT", len(self.devices))
            return self.devices

        except Exception as e:
            logger.error("Error al obtener dispositivos: %s", e)
            raise
        finally:
            client.loop_stop()
            client.disconnect()

    def discover_temperature_sensors(self) -> list[str]:
        """Descubre automáticamente sensores de temperatura/humedad.

        Filtra dispositivos que:
        - No sean Coordinador
        - Tengan capacidad de medir temperatura (exposes temperature)

        Returns:
            Lista de friendly_names de sensores descubiertos
        """
        try:
            devices = self.get_devices()
            sensors = []

            for device in devices:
                # Ignorar coordinador
                if device.get("type") == "Coordinator":
                    continue

                # Verificar si tiene sensor de temperatura en 'exposes'
                definition = device.get("definition")
                if not definition:
                    continue

                exposes = definition.get("exposes", [])
                has_temperature = any(
                    expose.get("property") == "temperature" or 
                    (expose.get("type") == "climate" and any(
                        f.get("property") == "temperature" 
                        for f in expose.get("features", [])
                    ))
                    for expose in exposes
                )

                if has_temperature:
                    friendly_name = device.get("friendly_name")
                    if friendly_name:
                        sensors.append(friendly_name)
                        logger.info(
                            "Sensor descubierto: %s (%s - %s)",
                            friendly_name,
                            device.get("manufacturer", "Unknown"),
                            device.get("model_id", "Unknown"),
                        )

            logger.info("Total sensores de temperatura descubiertos: %d", len(sensors))
            return sensors

        except Exception as e:
            logger.error("Error al descubrir sensores: %s", e)
            # Devolver lista vacía en lugar de fallar - el sistema puede funcionar
            # con configuración manual si Zigbee2MQTT no está disponible
            return []
