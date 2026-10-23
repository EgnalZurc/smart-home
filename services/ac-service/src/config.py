"""AC Service configuration constants.

This module centralizes all configurable constants and magic numbers used
throughout the AC service. Constants are grouped by category for clarity.

Categories:
    - Temperature limits (MELCloud API constraints)
    - Fan speed settings
    - Operation modes
    - Timeout and interval defaults
    - State machine parameters
    - Energy tracking defaults
"""

from __future__ import annotations

from enum import IntEnum, StrEnum

# ══════════════════════════════════════════════════════════════════════════════
# Temperature Limits (MELCloud API constraints)
# ══════════════════════════════════════════════════════════════════════════════

MELCLOUD_TEMP_MIN: float = 16.0
"""Minimum temperature supported by MELCloud API (°C)."""

MELCLOUD_TEMP_MAX: float = 31.0
"""Maximum temperature supported by MELCloud API (°C)."""

DEFAULT_TARGET_TEMP: float = 26.0
"""Default target temperature for automatic control (°C)."""

DEFAULT_SETPOINT: float = 24.0
"""Default setpoint when no specific value is set (°C)."""

DEFAULT_MANUAL_TEMP: float = 23.0
"""Default temperature for manual mode (°C)."""

DEFAULT_MIN_SETPOINT: float = 19.0
"""Default minimum setpoint for proportional control (°C)."""

DEFAULT_MAX_SETPOINT: float = 30.0
"""Default maximum setpoint for proportional control (°C)."""


# ══════════════════════════════════════════════════════════════════════════════
# Fan Speed Settings
# ══════════════════════════════════════════════════════════════════════════════


class FanSpeed(IntEnum):
    """Fan speed levels supported by MELCloud."""

    AUTO = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3


FAN_SPEED_MIN: int = FanSpeed.AUTO
"""Minimum fan speed value (auto)."""

FAN_SPEED_MAX: int = FanSpeed.HIGH
"""Maximum fan speed value (high)."""

DEFAULT_FAN_SPEED: int = FanSpeed.AUTO
"""Default fan speed (auto)."""

DEFAULT_FAN_SPEED_MAX: int = FanSpeed.HIGH
"""Default maximum fan speed for cooling_max state."""


# ══════════════════════════════════════════════════════════════════════════════
# Operation Modes
# ══════════════════════════════════════════════════════════════════════════════


class ACMode(StrEnum):
    """AC operation modes."""

    COOL = "cool"
    HEAT = "heat"
    DRY = "dry"
    FAN = "fan"
    AUTO = "auto"


class MelCloudOperationMode(IntEnum):
    """MELCloud API operation mode values."""

    HEAT = 1
    DRY = 2
    COOL = 3
    FAN = 7
    AUTO = 8


# Mapping from MELCloud API values to human-readable names
MELCLOUD_MODE_NAMES: dict[int, str] = {
    MelCloudOperationMode.HEAT: "HOT",
    MelCloudOperationMode.DRY: "DRY",
    MelCloudOperationMode.COOL: "COLD",
    MelCloudOperationMode.FAN: "FAN",
    MelCloudOperationMode.AUTO: "AUTO",
}

# Mapping from MELCloud API fan values to human-readable names (Spanish)
MELCLOUD_FAN_NAMES: dict[int, str] = {
    FanSpeed.AUTO: "Auto",
    FanSpeed.LOW: "Bajo",
    FanSpeed.MEDIUM: "Medio",
    FanSpeed.HIGH: "Alto",
}

DEFAULT_AC_MODE: str = ACMode.COOL
"""Default AC operation mode."""


# ══════════════════════════════════════════════════════════════════════════════
# Timeout and Interval Defaults
# ══════════════════════════════════════════════════════════════════════════════

DEFAULT_COOLDOWN_SECONDS: int = 180
"""Default compressor protection cooldown period (seconds)."""

DEFAULT_LOOP_INTERVAL: int = 45
"""Default control loop interval (seconds)."""

DEFAULT_SENSOR_TIMEOUT: int = 600
"""Default sensor data staleness threshold (seconds)."""

DEFAULT_SENSOR_ALERT_SECONDS: int = 3600
"""Default threshold for sensor alert (seconds without data)."""

DEFAULT_AC_STATE_UPDATE_INTERVAL: int = 30
"""Interval between real AC state updates from MELCloud (seconds)."""

DEFAULT_MELCLOUD_TIMEOUT: float = 30.0
"""Default timeout for MELCloud API requests (seconds)."""

DEFAULT_MELCLOUD_MAX_FAILURES: int = 100
"""Consecutive MELCloud failures before entering ERROR state."""

DEFAULT_Z2M_DISCOVERY_TIMEOUT: float = 10.0
"""Timeout for Zigbee2MQTT sensor discovery (seconds)."""

DEFAULT_MAX_HISTORY_PER_SENSOR: int = 200
"""Maximum history entries to keep per sensor."""

DEFAULT_MELCLOUD_UPDATE_INTERVAL: int = 30
"""Default interval for MELCloud subscription updates (seconds)."""

DEFAULT_OUTDOOR_UPDATE_INTERVAL: int = 600
"""Default interval for outdoor temperature updates (seconds)."""

DEFAULT_OUTDOOR_CACHE_TTL: int = 600
"""Default TTL for outdoor temperature cache (seconds)."""

DEFAULT_CLEANUP_INTERVAL_SECONDS: int = 86400
"""Default interval for cleanup tasks (seconds) - 24 hours."""


# ══════════════════════════════════════════════════════════════════════════════
# State Machine Parameters
# ══════════════════════════════════════════════════════════════════════════════

DEFAULT_HYSTERESIS_ON: float = 0.5
"""Default hysteresis for turning cooling on (°C above target)."""

DEFAULT_HYSTERESIS_OFF: float = 0.3
"""Default hysteresis for turning cooling off (°C below target)."""

SECONDS_SINCE_OFF_INITIAL: float = 99999.0
"""Initial value for seconds_since_off when no prior shutdown recorded."""


# ══════════════════════════════════════════════════════════════════════════════
# Energy Tracking Defaults
# ══════════════════════════════════════════════════════════════════════════════

DEFAULT_AC_POWER_COOLING_MAX: float = 2.5
"""Default power consumption in cooling_max state (kW)."""

DEFAULT_AC_POWER_COOLING_MID: float = 1.75
"""Default power consumption in cooling_mid state (kW)."""

DEFAULT_AC_POWER_MODULATING: float = 1.25
"""Default power consumption in modulating state (kW)."""

DEFAULT_AC_POWER_FORCED_ON: float = 2.5
"""Default power consumption in forced_on/manual state (kW)."""


# ══════════════════════════════════════════════════════════════════════════════
# History and Limits
# ══════════════════════════════════════════════════════════════════════════════

HISTORY_MAX_SIZE: int = 1000
"""Maximum number of history records to keep before trimming."""

HISTORY_TRIM_SIZE: int = 500
"""Number of history records to keep after trimming."""

EVENT_LOG_MAX_HOURS: int = 720
"""Maximum hours of event log history to return (30 days)."""

HISTORY_LIMIT_MAX: int = 1000
"""Maximum limit for history queries."""

HISTORY_LIMIT_MIN: int = 1
"""Minimum limit for history queries."""

SENSOR_HISTORY_LIMIT_MAX: int = 10000
"""Maximum number of records per sensor for history queries."""


# ══════════════════════════════════════════════════════════════════════════════
# MQTT Configuration Defaults
# ══════════════════════════════════════════════════════════════════════════════

DEFAULT_MQTT_BROKER: str = "mosquitto"
"""Default MQTT broker hostname."""

DEFAULT_MQTT_PORT: int = 1883
"""Default MQTT broker port (1883 for plain, 8883 for TLS)."""

DEFAULT_MQTT_TLS_ENABLED: bool = False
"""Default TLS setting - disabled for backward compatibility."""

DEFAULT_MQTT_TLS_CA_CERTS: str | None = None
"""Default path to CA certificate file. None uses system CA bundle when TLS enabled."""

DEFAULT_MQTT_CONNECT_RETRIES: int = 30
"""Default number of MQTT connection retries."""

DEFAULT_MQTT_RETRY_DELAY: int = 2
"""Default delay between MQTT connection retries (seconds)."""

DEFAULT_MQTT_KEEPALIVE: int = 60
"""Default MQTT keepalive interval (seconds)."""


# ══════════════════════════════════════════════════════════════════════════════
# Location Defaults
# ══════════════════════════════════════════════════════════════════════════════

DEFAULT_LOCATION_LATITUDE: float = 40.396644
"""Default latitude (Madrid, Spain)."""

DEFAULT_LOCATION_LONGITUDE: float = -3.622511
"""Default longitude (Madrid, Spain)."""
