"""Configuration for presence-service, read from environment variables.

All tunables live here so the engine, sources, storage and MQTT handler import
a single source of truth. Defaults match the design document
(``docs/designs/presence-service-design.md`` §6).
"""

from __future__ import annotations

import os

# ── Logging ──────────────────────────────────────────────────────────────────
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

# ── Service ──────────────────────────────────────────────────────────────────
SERVICE_NAME = "presence-service"
PORT = int(os.environ.get("PRESENCE_PORT", "8013"))

# ── SQLite (tier 2) ──────────────────────────────────────────────────────────
DB_PATH = os.environ.get("PRESENCE_DB_PATH", "/app/data/presence.db")

# ── Loops ────────────────────────────────────────────────────────────────────
# Router poll cadence (design: 30 s) and the engine recompute tick (design: 5 s).
ROUTER_POLL_INTERVAL_S = int(os.environ.get("PRESENCE_ROUTER_POLL_INTERVAL_S", "30"))
ENGINE_TICK_S = int(os.environ.get("PRESENCE_ENGINE_TICK_S", "5"))

# ── Source TTLs (evidence freshness, seconds) ────────────────────────────────
ROUTER_TTL_S = int(os.environ.get("PRESENCE_ROUTER_TTL_S", "180"))
BLE_TTL_S = int(os.environ.get("PRESENCE_BLE_TTL_S", "60"))
MOTION_OCCUPANCY_TTL_S = int(os.environ.get("PRESENCE_MOTION_OCCUPANCY_TTL_S", "600"))

# ── Fusion weights & threshold ───────────────────────────────────────────────
WEIGHT_ROUTER = float(os.environ.get("PRESENCE_WEIGHT_ROUTER", "0.6"))
WEIGHT_BLE = float(os.environ.get("PRESENCE_WEIGHT_BLE", "0.5"))
WEIGHT_MOTION = float(os.environ.get("PRESENCE_WEIGHT_MOTION", "0.2"))
PRESENT_THRESHOLD = float(os.environ.get("PRESENCE_PRESENT_THRESHOLD", "0.5"))

# ── Debounce / state timeouts (seconds) ──────────────────────────────────────
ARRIVAL_DEBOUNCE_S = int(os.environ.get("PRESENCE_ARRIVAL_DEBOUNCE_S", "30"))
DEPARTURE_GRACE_S = int(os.environ.get("PRESENCE_DEPARTURE_GRACE_S", "300"))
SLEEP_INACTIVITY_S = int(os.environ.get("PRESENCE_SLEEP_INACTIVITY_S", "2700"))
NIGHT_WINDOW = os.environ.get("PRESENCE_NIGHT_WINDOW", "23:00-08:00")
SLEEP_ZONE = os.environ.get("PRESENCE_SLEEP_ZONE", "bedroom")

# ── Router access (one mode) ─────────────────────────────────────────────────
# arpsweep | openwrt_ssh | fritzbox | mikrotik
ROUTER_MODE = os.environ.get("PRESENCE_ROUTER_MODE", "arpsweep")
ROUTER_HOST = os.environ.get("PRESENCE_ROUTER_HOST", "192.168.1.1")
ROUTER_USER = os.environ.get("PRESENCE_ROUTER_USER", "")
# ROUTER_PASSWORD / key supplied via .env, never logged.
ARP_SUBNET = os.environ.get("PRESENCE_ARP_SUBNET", "192.168.1.0/24")

# ── MQTT (shared broker) ─────────────────────────────────────────────────────
MQTT_BROKER = os.environ.get("PRESENCE_MQTT_BROKER", "mosquitto")
MQTT_PORT = int(os.environ.get("PRESENCE_MQTT_PORT", "1883"))
BLE_TOPIC = os.environ.get("PRESENCE_BLE_TOPIC", "presence/ble/#")
MOTION_TOPIC = os.environ.get("PRESENCE_MOTION_TOPIC", "zigbee2mqtt/+")
MQTT_PUBLISH_PREFIX = os.environ.get("PRESENCE_MQTT_PUBLISH_PREFIX", "presence")

# ── Notifications ────────────────────────────────────────────────────────────
# Delivery is driven by libs/notifications.TelegramNotifier.from_env(), which
# reads TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_IDS. If unset, the notifier is a
# no-op (transitions still persist + publish, just no message is sent).
NOTIFY_ENABLED = os.environ.get("PRESENCE_NOTIFY_ENABLED", "true").lower() == "true"
# Subset of arrival|departure|empty|occupied.
NOTIFY_EVENTS = [
    e.strip()
    for e in os.environ.get("PRESENCE_NOTIFY_EVENTS", "arrival,departure").split(",")
    if e.strip()
]

# ── Seed people on first run (empty → manage via API) ────────────────────────
# JSON array of {id, name, devices:[{mac,label}], beacons:[{ble_id,label}]}.
PEOPLE_SEED = os.environ.get("PRESENCE_PEOPLE_SEED", "")

# ── Retention ────────────────────────────────────────────────────────────────
# Transition audit trail retention (design §7.3: 1 year).
RETENTION_DAYS = int(os.environ.get("PRESENCE_RETENTION_DAYS", "365"))
PRUNE_INTERVAL_S = int(os.environ.get("PRESENCE_PRUNE_INTERVAL_S", str(24 * 3600)))
