"""Client to get information from Zigbee2MQTT.

Allows automatic discovery of connected devices via MQTT.
"""

import json
import logging
from typing import Any

import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)


class Zigbee2MQTTClient:
    """Client to interact with Zigbee2MQTT via MQTT."""

    def __init__(self, mqtt_broker: str, mqtt_port: int = 1883, timeout: float = 10.0):
        """Initializes the client.

        Args:
            mqtt_broker: MQTT broker host (e.g., mosquitto)
            mqtt_port: MQTT broker port (default: 1883)
            timeout: Timeout in seconds to get responses
        """
        self.mqtt_broker = mqtt_broker
        self.mqtt_port = mqtt_port
        self.timeout = timeout
        self.devices: list[dict[str, Any]] = []
        self.response_received = False

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        """Callback on connect."""
        if rc == 0:
            logger.debug("Connected to MQTT %s:%d", self.mqtt_broker, self.mqtt_port)
            # Subscribe to devices topic
            client.subscribe("zigbee2mqtt/bridge/devices")
        else:
            logger.error("Error connecting to MQTT: rc=%d", rc)

    def _on_message(self, client, userdata, msg):
        """Callback on message received."""
        if msg.topic == "zigbee2mqtt/bridge/devices":
            try:
                self.devices = json.loads(msg.payload.decode())
                self.response_received = True
                logger.debug("Received %d devices", len(self.devices))
            except json.JSONDecodeError as e:
                logger.error("Error decoding devices JSON: %s", e)

    def get_devices(self) -> list[dict[str, Any]]:
        """Gets the list of devices connected to Zigbee2MQTT via MQTT.

        Returns:
            List of devices. Each device is a dict with:
            - friendly_name: Device name
            - ieee_address: IEEE address
            - type: Type (Coordinator, Router, EndDevice)
            - model_id: Model ID
            - manufacturer: Manufacturer
            - definition: Device definition (contains 'supported', 'exposes', etc.)

        Raises:
            Exception: If cannot connect or no response received
        """
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        client.on_connect = self._on_connect
        client.on_message = self._on_message

        try:
            logger.info("Connecting to MQTT %s:%d to get devices...", self.mqtt_broker, self.mqtt_port)
            client.connect(self.mqtt_broker, self.mqtt_port, 60)
            
            # Start loop in background
            client.loop_start()

            # Request device list
            client.publish("zigbee2mqtt/bridge/request/devices", "")

            # Wait for response with timeout
            import time
            elapsed = 0.0
            poll_interval = 0.1
            while not self.response_received and elapsed < self.timeout:
                time.sleep(poll_interval)
                elapsed += poll_interval

            if not self.response_received:
                raise Exception(f"Timeout waiting for Zigbee2MQTT response after {self.timeout}s")

            logger.info("Got %d devices from Zigbee2MQTT", len(self.devices))
            return self.devices

        except Exception as e:
            logger.error("Error getting devices: %s", e)
            raise
        finally:
            client.loop_stop()
            client.disconnect()

    def discover_temperature_sensors(self) -> list[str]:
        """Automatically discovers temperature/humidity sensors.

        Filters devices that:
        - Are not Coordinator
        - Have temperature measurement capability (exposes temperature)

        Returns:
            List of friendly_names of discovered sensors
        """
        try:
            devices = self.get_devices()
            sensors = []

            for device in devices:
                # Ignore coordinator
                if device.get("type") == "Coordinator":
                    continue

                # Check if it has temperature sensor in 'exposes'
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
                            "Sensor discovered: %s (%s - %s)",
                            friendly_name,
                            device.get("manufacturer", "Unknown"),
                            device.get("model_id", "Unknown"),
                        )

            logger.info("Total temperature sensors discovered: %d", len(sensors))
            return sensors

        except Exception as e:
            logger.error("Error discovering sensors: %s", e)
            # Return empty list instead of failing - system can work
            # with manual configuration if Zigbee2MQTT is not available
            return []
