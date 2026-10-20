"""Baby Gifts Service — Configuration.

Centralizes all configuration from environment variables with sensible defaults.
All settings can be overridden via environment variables for deployment flexibility.
"""

import os
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
# DATA_DIR: Directory for persistent data (gifts.json, SQLite database).
# Default: /app/data (Docker container path).
DATA_DIR: Path = Path(os.environ.get("DATA_DIR", "/app/data"))

# GIFTS_FILE: JSON file storing the gift registry.
GIFTS_FILE: Path = DATA_DIR / "gifts.json"

# DB_FILE: SQLite database for invitations and rate limiting.
DB_FILE: Path = DATA_DIR / "baby_gifts.db"

# ── Invitations ───────────────────────────────────────────────────────────────
# INVITATION_EXPIRY_DAYS: Number of days until an invitation link expires.
# Default: 180 days (6 months).
INVITATION_EXPIRY_DAYS: int = int(os.environ.get("INVITATION_EXPIRY_DAYS", "180"))

# ── User permissions ──────────────────────────────────────────────────────────
# FAMILIA_USERS: Comma-separated list of usernames with elevated privileges.
# These users can see hidden gifts and toggle gift visibility.
# Default: "egnal,virchu" (the parents).
_familia_raw: str = os.environ.get("FAMILIA_USERS", "egnal,virchu") or ""
FAMILIA_USERS: set[str] = {
    u.strip().lower() for u in _familia_raw.split(",") if u.strip()
}

# ── Rate limiting ─────────────────────────────────────────────────────────────
# RATE_LIMIT_ATTEMPTS: Max requests per window for guest endpoints.
# Default: 20 requests per window.
RATE_LIMIT_ATTEMPTS: int = int(os.environ.get("RATE_LIMIT_ATTEMPTS", "20"))

# RATE_LIMIT_WINDOW_SECONDS: Duration of the rate limit window in seconds.
# Default: 60 seconds (1 minute).
RATE_LIMIT_WINDOW_SECONDS: int = int(os.environ.get("RATE_LIMIT_WINDOW_SECONDS", "60"))

# INVITATION_RATE_LIMIT_ATTEMPTS: Max invitation creations per window (admin).
# More restrictive than guest rate limit to prevent invitation spam.
# Default: 30 requests per window.
INVITATION_RATE_LIMIT_ATTEMPTS: int = int(
    os.environ.get("INVITATION_RATE_LIMIT_ATTEMPTS", "30")
)

# INVITATION_RATE_LIMIT_WINDOW_SECONDS: Window for invitation creation rate limit.
# Default: 60 seconds (1 minute).
INVITATION_RATE_LIMIT_WINDOW_SECONDS: int = int(
    os.environ.get("INVITATION_RATE_LIMIT_WINDOW_SECONDS", "60")
)

# ── Telegram notifications ────────────────────────────────────────────────────
# TELEGRAM_BOT_TOKEN: Bot token from @BotFather for sending notifications.
# Required for notifications to work.
TELEGRAM_BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", "") or ""

# TELEGRAM_CHAT_IDS: Comma-separated chat IDs to receive notifications.
# Preferred over TELEGRAM_CHAT_ID for multi-recipient support.
TELEGRAM_CHAT_IDS_RAW: str = os.environ.get("TELEGRAM_CHAT_IDS", "") or ""

# TELEGRAM_CHAT_ID: Single chat ID (legacy, fallback for backwards compatibility).
TELEGRAM_CHAT_ID_SINGLE: str = os.environ.get("TELEGRAM_CHAT_ID", "") or ""

# ── Security ──────────────────────────────────────────────────────────────────
# TRUSTED_PROXY_IPS: IPs of trusted reverse proxies (nginx container).
# Only requests from these IPs will have X-Forwarded-For headers trusted.
# Default: Docker bridge gateway (172.18.0.1) and localhost (127.0.0.1).
_trusted_raw: str = os.environ.get("TRUSTED_PROXY_IPS", "172.18.0.1,127.0.0.1") or ""
TRUSTED_PROXY_IPS: set[str] = {
    ip.strip() for ip in _trusted_raw.split(",") if ip.strip()
}
