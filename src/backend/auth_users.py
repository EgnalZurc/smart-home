"""User store and trusted-device management.

Users are loaded from the nginx .htpasswd file (apr_md5_crypt format).
Trusted device requests are persisted in a small SQLite table so the
admin can approve or reject them via signed email links.
"""
import hashlib
import hmac
import logging
import os
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Optional

from auth import verify_password

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration (injected from main.py lifespan)
# ---------------------------------------------------------------------------
HTPASSWD_PATH: str = "/etc/nginx/.htpasswd"  # default — override via env
AUTH_DB_PATH: str = "/app/data/auth.db"       # default — override via env
TRUST_SECRET: str = ""                         # REQUIRED — same as AUTH_SECRET

# ---------------------------------------------------------------------------
# .htpasswd user store
# ---------------------------------------------------------------------------

def _load_htpasswd(path: str) -> dict[str, str]:
    """Parse an .htpasswd file into {username: hash} dict.

    Ignores blank lines and comment lines starting with '#'.
    """
    users: dict[str, str] = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if ":" not in line:
                    continue
                username, pw_hash = line.split(":", 1)
                users[username.strip()] = pw_hash.strip()
    except FileNotFoundError:
        logger.error("htpasswd file not found: %s", path)
    except OSError as exc:
        logger.error("Failed to read htpasswd: %s", exc)
    return users


def authenticate_user(username: str, password: str) -> bool:
    """Return True if username/password match the .htpasswd store."""
    users = _load_htpasswd(HTPASSWD_PATH)
    pw_hash = users.get(username)
    if pw_hash is None:
        # Constant-time dummy check to prevent user enumeration timing attacks
        verify_password("dummy", "$apr1$dummy$dummyhashvalueforconsistency00")
        return False
    return verify_password(password, pw_hash)


def user_exists(username: str) -> bool:
    """Return True if the username is present in .htpasswd."""
    return username in _load_htpasswd(HTPASSWD_PATH)


# ---------------------------------------------------------------------------
# Trusted-device SQLite store
# ---------------------------------------------------------------------------

def _get_db() -> sqlite3.Connection:
    """Open the auth SQLite database, creating schema on first use."""
    db_path = Path(AUTH_DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trusted_devices (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            token       TEXT    NOT NULL UNIQUE,   -- opaque approval token (used in email links)
            username    TEXT    NOT NULL,
            user_agent  TEXT    NOT NULL DEFAULT '',
            ip_address  TEXT    NOT NULL DEFAULT '',
            requested_at REAL   NOT NULL,           -- unix timestamp
            status      TEXT    NOT NULL DEFAULT 'pending',  -- pending | approved | rejected
            resolved_at  REAL                        -- unix timestamp or NULL
        )
    """)
    conn.commit()
    return conn


def create_trust_request(username: str, user_agent: str, ip_address: str) -> str:
    """Insert a pending trusted-device request and return the opaque approval token."""
    token = secrets.token_urlsafe(32)
    with _get_db() as conn:
        conn.execute(
            """
            INSERT INTO trusted_devices (token, username, user_agent, ip_address, requested_at, status)
            VALUES (?, ?, ?, ?, ?, 'pending')
            """,
            (token, username, user_agent, ip_address, time.time()),
        )
    return token


def resolve_trust_request(token: str, action: str) -> Optional[dict]:
    """Approve or reject a pending trust request by its token.

    Args:
        token: The opaque token from the approval email link.
        action: 'approved' or 'rejected'.

    Returns:
        The row dict if found and previously pending, else None.
    """
    if action not in ("approved", "rejected"):
        raise ValueError(f"Invalid action: {action!r}")

    with _get_db() as conn:
        row = conn.execute(
            "SELECT * FROM trusted_devices WHERE token = ?", (token,)
        ).fetchone()
        if row is None or row["status"] != "pending":
            return None
        conn.execute(
            "UPDATE trusted_devices SET status = ?, resolved_at = ? WHERE token = ?",
            (action, time.time(), token),
        )
        return dict(row)


def get_trust_status(token: str) -> Optional[str]:
    """Return the status of a trust request token, or None if not found."""
    with _get_db() as conn:
        row = conn.execute(
            "SELECT status FROM trusted_devices WHERE token = ?", (token,)
        ).fetchone()
    return row["status"] if row else None


# ---------------------------------------------------------------------------
# HMAC-signed action tokens for email links
# ---------------------------------------------------------------------------
# The approval email contains links of the form:
#   /auth/trust/approve?token=<opaque_token>&sig=<hmac>
#   /auth/trust/reject?token=<opaque_token>&sig=<hmac>
#
# The HMAC prevents anyone who guesses a token from approving/rejecting
# without the AUTH_SECRET.

def _sign(token: str, action: str) -> str:
    """Return a URL-safe HMAC signature for (token, action)."""
    msg = f"{action}:{token}".encode()
    return hmac.new(TRUST_SECRET.encode(), msg, hashlib.sha256).hexdigest()


def make_action_url(base_url: str, token: str, action: str) -> str:
    """Build a signed approval/rejection URL for inclusion in the email."""
    sig = _sign(token, action)
    return f"{base_url}/auth/trust/{action}?token={token}&sig={sig}"


def verify_action_sig(token: str, action: str, sig: str) -> bool:
    """Return True if the HMAC signature is valid for (token, action)."""
    expected = _sign(token, action)
    return hmac.compare_digest(expected, sig)
