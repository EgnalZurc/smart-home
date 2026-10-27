"""Configuration for energy-monitor, read from environment variables.

All tunables live here so the collector, storage and (future) Shelly client
import a single source of truth. Defaults match the design document
(``docs/designs/energy-monitor-design.md`` §6).

This is the *scaffold* of the service: the collector, Shelly client and alert
engine arrive in later tasks. The config surface, however, is laid out in full
now so those tasks only add behaviour, not new knobs.
"""

from __future__ import annotations

import logging
import os

_logger = logging.getLogger(__name__)

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

# ── Shelly authentication (global defaults) ──────────────────────────────────
# SECURITY: Default credentials for Shelly devices. Individual devices can
# override these by specifying "username"/"password" in their ENERGY_DEVICES
# entry. Never hardcode credentials in source code.
#
# Environment variables:
#   SHELLY_USER     - Default username for all Shelly devices
#   SHELLY_PASSWORD - Default password for all Shelly devices
#
# Per-device override in ENERGY_DEVICES JSON:
#   [{"id": "em1", "ip": "192.168.1.50", "username": "admin", "password": "..."}]
SHELLY_USER = os.environ.get("SHELLY_USER", "")
SHELLY_PASSWORD = os.environ.get("SHELLY_PASSWORD", "")

# ── Tariff / cost estimation (design §6) ─────────────────────────────────────
TARIFF_MODE = os.environ.get("ENERGY_TARIFF_MODE", "flat")
PRICE_EUR_KWH = float(os.environ.get("ENERGY_PRICE_EUR_KWH", "0.15"))

# ── Alerting (design §8) ─────────────────────────────────────────────────────
# Master switch for the (future) alert engine. Telegram delivery is driven by
# libs/notifications.TelegramNotifier.from_env() (TELEGRAM_BOT_TOKEN /
# TELEGRAM_CHAT_IDS); if unset, alerts still fire + persist, just send nothing.
ALERTS_ENABLED = os.environ.get("ENERGY_ALERTS_ENABLED", "true").lower() == "true"

# Consumption thresholds. A value <= 0 disables that rule. Checked by the alert
# engine (Task 6.4) against the whole-home total; crossing a threshold fires an
# alert, dropping back below it resolves it.
#   * instantaneous power spike (W), evaluated on the latest 1-min max sample.
#   * daily energy budget (kWh), evaluated on the running day-to-date total.
#   * monthly energy budget (kWh), evaluated on the month-to-date total.
POWER_ALERT_W = float(os.environ.get("ENERGY_POWER_ALERT_W", "3500"))
DAILY_KWH_ALERT = float(os.environ.get("ENERGY_DAILY_KWH_ALERT", "20"))
MONTHLY_KWH_ALERT = float(os.environ.get("ENERGY_MONTHLY_KWH_ALERT", "400"))

# ── Warn on negative thresholds (likely config typo) ──────────────────────────
# Negative values are treated as disabled (same as 0), but this is rarely
# intentional. Log a warning to help catch configuration mistakes early.
for _name, _val in [
    ("ENERGY_POWER_ALERT_W", POWER_ALERT_W),
    ("ENERGY_DAILY_KWH_ALERT", DAILY_KWH_ALERT),
    ("ENERGY_MONTHLY_KWH_ALERT", MONTHLY_KWH_ALERT),
]:
    if _val < 0:
        _logger.warning(
            "%s is negative (%.2f); treating as disabled (0). "
            "Set to 0 explicitly or a positive value.",
            _name,
            _val,
        )

# ── Public exports ────────────────────────────────────────────────────────────
__all__ = [
    "ALERT_RETENTION_DAYS",
    "ALERTS_ENABLED",
    "DAILY_KWH_ALERT",
    "DB_PATH",
    "DEVICES_JSON",
    "ENERGY_RETENTION_DAYS",
    "ENERGY_SNAPSHOT_INTERVAL_S",
    "HTTP_TIMEOUT_S",
    "LOG_LEVEL",
    "MONTHLY_KWH_ALERT",
    "POLL_INTERVAL_S",
    "PORT",
    "POWER_ALERT_W",
    "POWER_RETENTION_DAYS",
    "PRICE_EUR_KWH",
    "PRUNE_INTERVAL_S",
    "RING_BUFFER_MAXLEN",
    "ROLLUP_INTERVAL_S",
    "SERVICE_NAME",
    "SHELLY_PASSWORD",
    "SHELLY_USER",
    "TARIFF_MODE",
]
