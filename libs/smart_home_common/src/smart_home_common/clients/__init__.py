"""External service clients."""

from smart_home_common.clients.melcloud import MelCloudClient
from smart_home_common.clients.zigbee import Zigbee2MQTTClient

__all__ = ["MelCloudClient", "Zigbee2MQTTClient"]
