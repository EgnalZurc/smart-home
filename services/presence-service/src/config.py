"""Configuration for presence-service, read from environment variables.

All tunables live here so the engine, sources, storage and MQTT handler import
a single source of truth. Defaults match the design document
(``docs/designs/presence-service-design.md`` §6).
"""

from __future__ import annotations

import ipaddress
import logging
import os
import re
from re import Pattern

# ── Validation helpers ───────────────────────────────────────────────────────

_NIGHT_WINDOW_RE: Pattern[str] = re.compile(r"^\d{2}:\d{2}-\d{2}:\d{2}$")
_HOSTNAME_RE: Pattern[str] = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?$")
# MQTT topic validation: alphanumeric, slashes, underscores, hyphens only.
# Rejects wildcards (#, +) and special characters to prevent topic injection.
_MQTT_TOPIC_RE: Pattern[str] = re.compile(r"^[a-zA-Z0-9/_-]+$")

__all__ = [
    # Rate Limiting
    "MAX_REQUESTS_PER_MINUTE",
    "RATE_LIMIT_WINDOW_S",
    "MAX_RATE_LIMIT_ENTRIES",
    # Logging
    "LOG_LEVEL",
    # Service
    "SERVICE_NAME",
    "PORT",
    # SQLite
    "DB_PATH",
    # Loops
    "ROUTER_POLL_INTERVAL_S",
    "ENGINE_TICK_S",
    # Source TTLs
    "ROUTER_TTL_S",
    "BLE_TTL_S",
    "MOTION_OCCUPANCY_TTL_S",
    # Fusion weights & threshold
    "WEIGHT_ROUTER",
    "WEIGHT_BLE",
    "WEIGHT_MOTION",
    "PRESENT_THRESHOLD",
    # Debounce / state timeouts
    "ARRIVAL_DEBOUNCE_S",
    "DEPARTURE_GRACE_S",
    "SLEEP_INACTIVITY_S",
    "NIGHT_WINDOW",
    "SLEEP_ZONE",
    # Router access
    "ROUTER_MODE",
    "VALID_ROUTER_MODES",
    "ROUTER_HOST",
    "ROUTER_USER",
    "ROUTER_PASSWORD",
    "ARP_SUBNET",
    # MQTT
    "MQTT_BROKER",
    "MQTT_PORT",
    "BLE_TOPIC",
    "MOTION_TOPIC",
    "MQTT_PUBLISH_PREFIX",
    # Notifications
    "NOTIFY_ENABLED",
    "NOTIFY_EVENTS",
    # Seed
    "PEOPLE_SEED",
    # Retention
    "RETENTION_DAYS",
    "PRUNE_INTERVAL_S",
    # Validators
    "validate_mqtt_topic",
]


def _validate_subnet(value: str) -> str:
    """Validate CIDR notation (e.g. 192.168.1.0/24)."""
    try:
        ipaddress.ip_network(value, strict=False)
    except ValueError as exc:
        raise ValueError(f"ARP_SUBNET invalid CIDR: {value!r}") from exc
    return value


def _validate_router_host(value: str) -> str:
    """Validate IP address or alphanumeric hostname."""
    # Try IP first
    try:
        ipaddress.ip_address(value)
        return value
    except ValueError:
        pass
    # Must be a valid hostname (alphanumeric + hyphens, not starting/ending with hyphen)
    if not _HOSTNAME_RE.match(value):
        raise ValueError(
            f"ROUTER_HOST must be valid IP or alphanumeric hostname: {value!r}"
        )
    return value


def _validate_night_window(value: str) -> str:
    """Validate HH:MM-HH:MM format with valid time ranges."""
    if not _NIGHT_WINDOW_RE.match(value):
        raise ValueError(f"NIGHT_WINDOW must match HH:MM-HH:MM format: {value!r}")
    start: str
    end: str
    start, end = value.split("-")
    for time_str in (start, end):
        hh: int
        mm: int
        hh, mm = map(int, time_str.split(":"))
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            raise ValueError(
                f"NIGHT_WINDOW contains invalid time {time_str!r}: {value!r}"
            )
    return value


def validate_mqtt_topic(value: str, *, allow_wildcards: bool = False) -> str:
    """Validate MQTT topic to prevent topic injection attacks.

    Args:
        value: The topic string to validate.
        allow_wildcards: If True, allow # and + wildcards for subscriptions.
                         If False, reject all wildcards (for publish topics).

    Returns:
        The validated topic string.

    Raises:
        ValueError: If the topic contains invalid characters.
    """
    if not value:
        raise ValueError("MQTT topic cannot be empty")

    # For subscription topics, temporarily strip trailing # wildcard for validation
    check_value: str = value
    if allow_wildcards:
        # Allow trailing /# or standalone # for multi-level wildcard subscriptions
        if check_value.endswith("/#"):
            check_value = check_value[:-2]
        elif check_value == "#":
            return value
        # Allow + as single-level wildcard in path segments
        check_value = check_value.replace("/+", "/X").replace("+/", "X/")
        if check_value == "+":
            check_value = "X"

    if not _MQTT_TOPIC_RE.match(check_value):
        if not allow_wildcards and ("#" in value or "+" in value):
            raise ValueError(
                f"MQTT topic contains wildcards (not allowed for publish): {value!r}"
            )
        raise ValueError(
            f"MQTT topic contains invalid characters (allowed: a-zA-Z0-9/_-): {value!r}"
        )
    return value


# ── Rate Limiting ────────────────────────────────────────────────────────────
# Health endpoints execute DB queries, so rate limiting prevents DoS via spam.
MAX_REQUESTS_PER_MINUTE: int = int(
    os.environ.get("PRESENCE_MAX_REQUESTS_PER_MINUTE", "30")
)
RATE_LIMIT_WINDOW_S: int = int(os.environ.get("PRESENCE_RATE_LIMIT_WINDOW_S", "60"))
MAX_RATE_LIMIT_ENTRIES: int = int(
    os.environ.get("PRESENCE_MAX_RATE_LIMIT_ENTRIES", "1000")
)

# ── Logging ──────────────────────────────────────────────────────────────────
LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO").upper()

# ── Service ──────────────────────────────────────────────────────────────────
SERVICE_NAME: str = "presence-service"
PORT: int = int(os.environ.get("PRESENCE_PORT", "8013"))

# ── SQLite (tier 2) ──────────────────────────────────────────────────────────
DB_PATH: str = os.environ.get("PRESENCE_DB_PATH", "/app/data/presence.db")

# ── Loops ────────────────────────────────────────────────────────────────────
# Router poll cadence (design: 30 s) and the engine recompute tick (design: 5 s).
ROUTER_POLL_INTERVAL_S: int = int(
    os.environ.get("PRESENCE_ROUTER_POLL_INTERVAL_S", "30")
)
ENGINE_TICK_S: int = int(os.environ.get("PRESENCE_ENGINE_TICK_S", "5"))

# ── Source TTLs (evidence freshness, seconds) ────────────────────────────────
ROUTER_TTL_S: int = int(os.environ.get("PRESENCE_ROUTER_TTL_S", "180"))
BLE_TTL_S: int = int(os.environ.get("PRESENCE_BLE_TTL_S", "60"))
MOTION_OCCUPANCY_TTL_S: int = int(
    os.environ.get("PRESENCE_MOTION_OCCUPANCY_TTL_S", "600")
)

# ── Fusion weights & threshold ───────────────────────────────────────────────
WEIGHT_ROUTER: float = float(os.environ.get("PRESENCE_WEIGHT_ROUTER", "0.6"))
WEIGHT_BLE: float = float(os.environ.get("PRESENCE_WEIGHT_BLE", "0.5"))
WEIGHT_MOTION: float = float(os.environ.get("PRESENCE_WEIGHT_MOTION", "0.2"))
PRESENT_THRESHOLD: float = float(os.environ.get("PRESENCE_PRESENT_THRESHOLD", "0.5"))

# ── Debounce / state timeouts (seconds) ──────────────────────────────────────
ARRIVAL_DEBOUNCE_S: int = int(os.environ.get("PRESENCE_ARRIVAL_DEBOUNCE_S", "30"))
DEPARTURE_GRACE_S: int = int(os.environ.get("PRESENCE_DEPARTURE_GRACE_S", "300"))
SLEEP_INACTIVITY_S: int = int(os.environ.get("PRESENCE_SLEEP_INACTIVITY_S", "2700"))
NIGHT_WINDOW: str = _validate_night_window(
    os.environ.get("PRESENCE_NIGHT_WINDOW", "23:00-08:00")
)
SLEEP_ZONE: str = os.environ.get("PRESENCE_SLEEP_ZONE", "bedroom")

# ── Router access (one mode) ─────────────────────────────────────────────────
# SECURITY NOTE: arpsweep mode requires NET_RAW capability (see docs/SECURITY_FIXES.md).
# This is an accepted risk - the container is isolated and only accessible via Tailscale.
# Prefer SSH-based modes (openwrt_ssh, fritzbox, mikrotik) when available, as they
# don't require elevated network privileges.
VALID_ROUTER_MODES: frozenset[str] = frozenset(
    {"arpsweep", "openwrt_ssh", "fritzbox", "mikrotik"}
)


def _validate_router_mode(value: str) -> str:
    """Validate ROUTER_MODE is one of the supported router polling strategies."""
    if value not in VALID_ROUTER_MODES:
        raise ValueError(
            f"ROUTER_MODE must be one of {sorted(VALID_ROUTER_MODES)}: got {value!r}"
        )
    return value


ROUTER_MODE: str = _validate_router_mode(
    os.environ.get("PRESENCE_ROUTER_MODE", "arpsweep")
)
ROUTER_HOST: str = _validate_router_host(
    os.environ.get("PRESENCE_ROUTER_HOST", "192.168.1.1")
)
ROUTER_USER: str = os.environ.get("PRESENCE_ROUTER_USER", "")
# ROUTER_PASSWORD / key supplied via .env, never logged.
ARP_SUBNET: str = _validate_subnet(
    os.environ.get("PRESENCE_ARP_SUBNET", "192.168.1.0/24")
)

# ── MQTT (shared broker) ─────────────────────────────────────────────────────
# SECURITY: MQTT credentials rotation policy
#   - MQTT_USER / MQTT_PASSWORD are injected via environment variables from .env.
#   - Rotate credentials at least every 90 days or immediately after a suspected
#     compromise.
#   - Use strong, randomly generated passwords (>=32 chars, mixed case + digits).
#   - Update Mosquitto ACLs and all subscriber services simultaneously during
#     rotation to avoid service disruption.
#   - Keep a rotation log in infrastructure/mosquitto/docs/credential-rotation.md.
MQTT_BROKER: str = os.environ.get("PRESENCE_MQTT_BROKER", "mosquitto")
MQTT_PORT: int = int(os.environ.get("PRESENCE_MQTT_PORT", "1883"))
# Subscription topics allow wildcards (#, +) for pattern matching.
BLE_TOPIC: str = validate_mqtt_topic(
    os.environ.get("PRESENCE_BLE_TOPIC", "presence/ble/#"), allow_wildcards=True
)
MOTION_TOPIC: str = validate_mqtt_topic(
    os.environ.get("PRESENCE_MOTION_TOPIC", "zigbee2mqtt/+"), allow_wildcards=True
)
# Publish prefix must NOT contain wildcards (injection risk).
MQTT_PUBLISH_PREFIX: str = validate_mqtt_topic(
    os.environ.get("PRESENCE_MQTT_PUBLISH_PREFIX", "presence"), allow_wildcards=False
)

# ── Notifications ────────────────────────────────────────────────────────────
# Delivery is driven by libs/notifications.TelegramNotifier.from_env(), which
# reads TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_IDS. If unset, the notifier is a
# no-op (transitions still persist + publish, just no message is sent).
NOTIFY_ENABLED: bool = (
    os.environ.get("PRESENCE_NOTIFY_ENABLED", "true").lower() == "true"
)
# Subset of arrival|departure|empty|occupied.
NOTIFY_EVENTS: list[str] = [
    e.strip()
    for e in os.environ.get("PRESENCE_NOTIFY_EVENTS", "arrival,departure").split(",")
    if e.strip()
]

# ── Seed people on first run (empty → manage via API) ────────────────────────
# JSON array of {id, name, devices:[{mac,label}], beacons:[{ble_id,label}]}.
PEOPLE_SEED: str = os.environ.get("PRESENCE_PEOPLE_SEED", "")

# ── Retention ────────────────────────────────────────────────────────────────
# Transition audit trail retention (design §7.3: 1 year).
RETENTION_DAYS: int = int(os.environ.get("PRESENCE_RETENTION_DAYS", "365"))
PRUNE_INTERVAL_S: int = int(os.environ.get("PRESENCE_PRUNE_INTERVAL_S", str(24 * 3600)))

# ── MQTT Credential Rotation Warning ─────────────────────────────────────────
# Log a warning if MQTT credentials appear to be using defaults or are missing.
_config_logger: logging.Logger = logging.getLogger(__name__)
_mqtt_user = os.environ.get("MQTT_USER", "")
_mqtt_pass = os.environ.get("MQTT_PASSWORD", "")
if not _mqtt_user or not _mqtt_pass:
    _config_logger.warning(
        "MQTT_USER and/or MQTT_PASSWORD not set. "
        "MQTT authentication may be disabled. See security policy at "
        "infrastructure/mosquitto/docs/credential-rotation.md"
    )

# ── Router Password Validation Warning ───────────────────────────────────────
# Log warnings if ROUTER_PASSWORD is empty or too short for security.
ROUTER_PASSWORD: str = os.environ.get("ROUTER_PASSWORD", "")
if ROUTER_PASSWORD and len(ROUTER_PASSWORD) < 8:
    _config_logger.warning(
        "ROUTER_PASSWORD is short (<%d chars) - consider a stronger password", 8
    )
if not ROUTER_PASSWORD:
    _config_logger.warning(
        "ROUTER_PASSWORD is empty - router integration will not work"
    )
