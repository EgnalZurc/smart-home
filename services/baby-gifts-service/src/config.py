"""Baby Gifts Service — Configuration.

Centralizes all configuration from environment variables with sensible defaults.
"""

import os
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
DATA_DIR = Path(os.environ.get("DATA_DIR", "/app/data"))
GIFTS_FILE = DATA_DIR / "gifts.json"
DB_FILE = DATA_DIR / "baby_gifts.db"

# ── Invitations ───────────────────────────────────────────────────────────────
INVITATION_EXPIRY_DAYS = int(os.environ.get("INVITATION_EXPIRY_DAYS", "180"))

# ── User permissions ──────────────────────────────────────────────────────────
# Users with FAMILIA permission (can see hidden gifts, toggle visibility)
_familia_raw = os.environ.get("FAMILIA_USERS", "egnal,virchu")
FAMILIA_USERS = {u.strip().lower() for u in _familia_raw.split(",") if u.strip()}

# ── Rate limiting ─────────────────────────────────────────────────────────────
RATE_LIMIT_ATTEMPTS = int(os.environ.get("RATE_LIMIT_ATTEMPTS", "20"))
RATE_LIMIT_WINDOW_SECONDS = int(os.environ.get("RATE_LIMIT_WINDOW_SECONDS", "60"))

# ── Telegram notifications ────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_IDS_RAW = os.environ.get("TELEGRAM_CHAT_IDS", "")
TELEGRAM_CHAT_ID_SINGLE = os.environ.get("TELEGRAM_CHAT_ID", "")

# ── Security ──────────────────────────────────────────────────────────────────
# IPs of trusted reverse proxies (nginx container)
_trusted_raw = os.environ.get("TRUSTED_PROXY_IPS", "172.18.0.1,127.0.0.1")
TRUSTED_PROXY_IPS = {ip.strip() for ip in _trusted_raw.split(",") if ip.strip()}
