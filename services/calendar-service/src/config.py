"""Configuration for calendar-service, read from environment variables.

All tunables live here so the sync loop, reminder tick, store and API import a
single source of truth. Defaults match the design document
(``docs/designs/calendar-service-design.md`` §6).

Calendars / people / reminder rules are **data** in SQLite (editable via the
config API), not env vars — only the service-level knobs live here.
"""

from __future__ import annotations

import os

# ── Logging ──────────────────────────────────────────────────────────────────
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

# ── Service ──────────────────────────────────────────────────────────────────
SERVICE_NAME = "calendar-service"
# 8014 is the next free port (8001-8004, 8010, 8011 taken; 8013 reserved for the
# proposed presence-service) — design §10.
PORT = int(os.environ.get("CALENDAR_PORT", "8014"))

# ── Storage (tier 2 — SQLite) ────────────────────────────────────────────────
DB_PATH = os.environ.get("CALENDAR_DB_PATH", "/app/data/calendar.db")
# OAuth refresh token lives here (secret, mode 600, never logged/returned).
TOKEN_PATH = os.environ.get("CALENDAR_TOKEN_PATH", "/app/data/token.json")

# ── Google OAuth client credentials (secrets, loaded by name from .env) ──────
GOOGLE_OAUTH_CLIENT_ID = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "")
GOOGLE_OAUTH_CLIENT_SECRET = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "")
# Least-privilege read-only scope (design §2.1).
GOOGLE_SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

# ── Sync loop ────────────────────────────────────────────────────────────────
# One sync every CALENDAR_SYNC_INTERVAL_S seconds. Design default 600 s (10 min),
# tunable within the requested 5-15 min (300-900 s) range.
SYNC_INTERVAL_S = int(os.environ.get("CALENDAR_SYNC_INTERVAL_S", "600"))
# How far ahead to cache events (design default 30 days).
SYNC_HORIZON_DAYS = int(os.environ.get("CALENDAR_SYNC_HORIZON_DAYS", "30"))

# ── Reminder loop ────────────────────────────────────────────────────────────
# Reminder tick cadence (design default 60 s).
REMINDER_TICK_S = int(os.environ.get("CALENDAR_REMINDER_TICK_S", "60"))
# Default reminder offsets seeded as global rules on first run: 30 min, 1 h, 1 day.
_DEFAULT_OFFSETS_RAW = os.environ.get("CALENDAR_DEFAULT_OFFSETS", "1800,3600,86400")
DEFAULT_OFFSETS = [int(o.strip()) for o in _DEFAULT_OFFSETS_RAW.split(",") if o.strip()]
# Master switch for sending Telegram reminders.
NOTIFY_ENABLED = os.environ.get("CALENDAR_NOTIFY_ENABLED", "true").lower() == "true"

# ── Retention (design §3.3) ──────────────────────────────────────────────────
# Drop events whose end_ts is older than this (short tail for "today so far").
EVENT_RETENTION_DAYS = int(os.environ.get("CALENDAR_EVENT_RETENTION_DAYS", "7"))
# Keep the reminders_sent dedup ledger / audit trail this long.
REMINDER_RETENTION_DAYS = int(os.environ.get("CALENDAR_REMINDER_RETENTION_DAYS", "90"))
# Prune cadence (daily).
PRUNE_INTERVAL_S = int(os.environ.get("CALENDAR_PRUNE_INTERVAL_S", str(24 * 3600)))

# ── Timezone ─────────────────────────────────────────────────────────────────
# Local timezone for "today" windows and all-day event boundaries (design §7.1).
TZ = os.environ.get("CALENDAR_TZ", "Europe/Madrid")

# ── Optional seed of calendars on first run (JSON, empty → manage via API) ───
CALENDAR_SEED = os.environ.get("CALENDAR_SEED", "")

# ── HTTP timeouts ────────────────────────────────────────────────────────────
HTTP_TIMEOUT_S = float(os.environ.get("CALENDAR_HTTP_TIMEOUT_S", "10.0"))

# Telegram delivery is driven by smart_home_common.telegram.TelegramNotifier
# .from_env(), which reads TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_IDS. If unset, the
# notifier is a no-op (reminders still recorded, nothing sent) — design §5.3.
