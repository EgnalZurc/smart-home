"""Configuration for energy-monitor, read from environment variables.

All tunables live here so the collector, storage and (future) Shelly client
import a single source of truth. Defaults match the design document
(``docs/designs/energy-monitor-design.md`` §6).

This is the *scaffold* of the service: the collector, Shelly client and alert
engine arrive in later tasks. The config surface, however, is laid out in full
now so those tasks only add behaviour, not new knobs.
"""

from __future__ import annotations

import os

# ── Logging ──────────────────────────────────────────────────────────────────
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

# ── Service ──────────────────────────────────────────────────────────────────
SERVICE_NAME = "energy-monitor"
PORT = int(os.environ.get("ENERGY_PORT", "8012"))

# ── Collector cadence (design §3.3) ──────────────────────────────────────────
# Instantaneous power is volatile, so we poll faster than metrics-service (30 s).
POLL_INTERVAL_S = int(os.environ.get("ENERGY_POLL_INTERVAL_S", "10"))
# 1-min power rollup to SQLite.
ROLLUP_INTERVAL_S = int(os.environ.get("ENERGY_ROLLUP_INTERVAL_S", "60"))
# Hourly snapshot of the monotonic kWh counter.
ENERGY_SNAPSHOT_INTERVAL_S = int(
    os.environ.get("ENERGY_ENERGY_SNAPSHOT_INTERVAL_S", str(3600))
)

# ── Ring buffer (tier 1, design §4.1) ────────────────────────────────────────
# 360 points * 10 s = 1 h of hi-resolution power per channel.
RING_BUFFER_MAXLEN = int(os.environ.get("ENERGY_RING_BUFFER_MAXLEN", "360"))

# ── SQLite (tier 2, design §4.2 / §4.4) ──────────────────────────────────────
DB_PATH = os.environ.get("ENERGY_DB_PATH", "/app/data/energy.db")
# Fine-grained 1-min power history retention.
POWER_RETENTION_DAYS = int(os.environ.get("ENERGY_POWER_RETENTION_DAYS", "90"))
# Hourly energy counter retention (3 years for year-over-year comparison).
ENERGY_RETENTION_DAYS = int(os.environ.get("ENERGY_ENERGY_RETENTION_DAYS", "1095"))
# Alert audit-trail retention.
ALERT_RETENTION_DAYS = int(os.environ.get("ENERGY_ALERT_RETENTION_DAYS", "365"))
# Prune cadence in seconds (daily).
PRUNE_INTERVAL_S = int(os.environ.get("ENERGY_PRUNE_INTERVAL_S", str(24 * 3600)))

# ── Shelly device I/O (design §3) ────────────────────────────────────────────
HTTP_TIMEOUT_S = float(os.environ.get("ENERGY_HTTP_TIMEOUT_S", "4.0"))
# Device inventory as JSON: [{"id","ip","gen","channels":{"ch0":"label",...}}].
# Empty by default so the scaffold starts cleanly without hardware present.
DEVICES_JSON = os.environ.get("ENERGY_DEVICES", "[]")

# ── Tariff / cost estimation (design §6) ─────────────────────────────────────
TARIFF_MODE = os.environ.get("ENERGY_TARIFF_MODE", "flat")
PRICE_EUR_KWH = float(os.environ.get("ENERGY_PRICE_EUR_KWH", "0.15"))

# ── Alerting (design §8) ─────────────────────────────────────────────────────
# Master switch for the (future) alert engine. Telegram delivery is driven by
# libs/notifications.TelegramNotifier.from_env() (TELEGRAM_BOT_TOKEN /
# TELEGRAM_CHAT_IDS); if unset, alerts still fire + persist, just send nothing.
ALERTS_ENABLED = os.environ.get("ENERGY_ALERTS_ENABLED", "true").lower() == "true"
