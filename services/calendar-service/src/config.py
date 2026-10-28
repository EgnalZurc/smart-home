"""Configuration for calendar-service, read from environment variables.

All tunables live here so the sync loop, reminder tick, store and API import a
single source of truth. Defaults match the design document
(``docs/designs/calendar-service-design.md`` Â§6).

Calendars / people / reminder rules are **data** in SQLite (editable via the
config API), not env vars â€” only the service-level knobs live here.
"""

from __future__ import annotations

import os

__all__ = [
    "LOG_LEVEL",
    "SERVICE_NAME",
    "PORT",
    "DB_PATH",
    "TOKEN_PATH",
    "GOOGLE_OAUTH_CLIENT_ID",
    "GOOGLE_OAUTH_CLIENT_SECRET",
    "GOOGLE_SCOPES",
    "SYNC_INTERVAL_S",
    "SYNC_HORIZON_DAYS",
    "REMINDER_TICK_S",
    "DEFAULT_OFFSETS",
    "NOTIFY_ENABLED",
    "EVENT_RETENTION_DAYS",
    "REMINDER_RETENTION_DAYS",
    "PRUNE_INTERVAL_S",
    "TZ",
    "LOCAL_TZ",
    "UTC_TZ",
    "CALENDAR_SEED",
    "HTTP_TIMEOUT_S",
    "CALENDAR_API_KEY",
    "CALENDAR_AUTH_DISABLED",
    "CALENDAR_TOKEN_SECRET",
]

# â”€â”€ Logging â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

# â”€â”€ Service â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
SERVICE_NAME = "calendar-service"
# 8014 is the next free port (8001-8004, 8010, 8011 taken; 8013 reserved for the
# proposed presence-service) â€” design Â§10.
PORT = int(os.environ.get("CALENDAR_PORT", "8014"))

# â”€â”€ Storage (tier 2 â€” SQLite) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
DB_PATH = os.environ.get("CALENDAR_DB_PATH", "/app/data/calendar.db")
# OAuth refresh token lives here (secret, mode 600, never logged/returned).
TOKEN_PATH = os.environ.get("CALENDAR_TOKEN_PATH", "/app/data/token.json")

# â”€â”€ Google OAuth client credentials (secrets, loaded by name from .env) â”€â”€â”€â”€â”€â”€
GOOGLE_OAUTH_CLIENT_ID = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "")
GOOGLE_OAUTH_CLIENT_SECRET = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "")
# Least-privilege read-only scope (design Â§2.1).
GOOGLE_SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

# â”€â”€ Sync loop â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# One sync every CALENDAR_SYNC_INTERVAL_S seconds. Design default 600 s (10 min),
# tunable within the requested 5-15 min (300-900 s) range.
SYNC_INTERVAL_S = int(os.environ.get("CALENDAR_SYNC_INTERVAL_S", "600"))
# How far ahead to cache events (design default 30 days).
SYNC_HORIZON_DAYS = int(os.environ.get("CALENDAR_SYNC_HORIZON_DAYS", "30"))

# â”€â”€ Reminder loop â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Reminder tick cadence (design default 60 s).
REMINDER_TICK_S = int(os.environ.get("CALENDAR_REMINDER_TICK_S", "60"))
# Default reminder offsets seeded as global rules on first run: 30 min, 1 h, 1 day.
_DEFAULT_OFFSETS_RAW = os.environ.get("CALENDAR_DEFAULT_OFFSETS", "1800,3600,86400")
DEFAULT_OFFSETS = [int(o.strip()) for o in _DEFAULT_OFFSETS_RAW.split(",") if o.strip()]
# Master switch for sending Telegram reminders.
NOTIFY_ENABLED = os.environ.get("CALENDAR_NOTIFY_ENABLED", "true").lower() == "true"

# â”€â”€ Retention (design Â§3.3) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Drop events whose end_ts is older than this (short tail for "today so far").
EVENT_RETENTION_DAYS = int(os.environ.get("CALENDAR_EVENT_RETENTION_DAYS", "7"))
# Keep the reminders_sent dedup ledger / audit trail this long.
REMINDER_RETENTION_DAYS = int(os.environ.get("CALENDAR_REMINDER_RETENTION_DAYS", "90"))
# Prune cadence (daily).
PRUNE_INTERVAL_S = int(os.environ.get("CALENDAR_PRUNE_INTERVAL_S", str(24 * 3600)))

# â”€â”€ Timezone â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Local timezone for "today" windows and all-day event boundaries (design Â§7.1).
TZ = os.environ.get("CALENDAR_TZ", "Europe/Madrid")
# Pre-built ZoneInfo for local and UTC to avoid repeated instantiation.
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo(TZ)
UTC_TZ = ZoneInfo("UTC")

# â”€â”€ Optional seed of calendars on first run (JSON, empty â†’ manage via API) â”€â”€â”€
CALENDAR_SEED = os.environ.get("CALENDAR_SEED", "")

# â”€â”€ HTTP timeouts â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
HTTP_TIMEOUT_S = float(os.environ.get("CALENDAR_HTTP_TIMEOUT_S", "10.0"))

# â”€â”€ API authentication â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Bearer token for protecting sensitive config endpoints.
CALENDAR_API_KEY = os.environ.get("CALENDAR_API_KEY", "")
# Explicit opt-out flag for auth (must be set to 'true' to disable).
# Auth is ENABLED by default â€” if enabled but no key configured, the service
# returns HTTP 500 on protected endpoints (fail-secure).
CALENDAR_AUTH_DISABLED = (
    os.environ.get("CALENDAR_AUTH_DISABLED", "false").lower() == "true"
)

# â”€â”€ Token encryption â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Fernet key for encrypting OAuth tokens at rest. If empty, tokens are stored
# in plaintext (legacy mode for migration). Generate with:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
CALENDAR_TOKEN_SECRET = os.environ.get("CALENDAR_TOKEN_SECRET", "")

# Telegram delivery is driven by smart_home_common.telegram.TelegramNotifier
# .from_env(), which reads TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_IDS. If unset, the
# notifier is a no-op (reminders still recorded, nothing sent) â€” design Â§5.3.
