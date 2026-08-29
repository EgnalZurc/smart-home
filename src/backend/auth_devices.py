"""Persistent trusted-device tokens using the Jaspan pattern.

Cookie format (stored client-side, HttpOnly):
    smh_device=<series_b64>:<token_b64>

Database table (device_tokens):
    series      TEXT  — stable identifier for one device/browser (never changes)
    token_hash  TEXT  — SHA-256 of current one-time token (rotates on every use)
    username    TEXT  — owner
    user_agent  TEXT  — for display in future device management UI
    ip_address  TEXT  — for display / logging
    created_at  REAL  — unix timestamp
    last_used   REAL  — unix timestamp (updated on each rotation)
    expires_at  REAL  — unix timestamp (1 year from creation)

Security properties:
    - Token rotates on every use → stolen cookie window = until victim next accesses
    - Only hash is stored → DB leak does not directly yield valid cookie values
    - Series mismatch (valid series + wrong token) → theft assumed →
      ALL device tokens for that user are deleted immediately
    - Race condition safe: device cookie is ONLY used on session refresh
      (when JWT has expired), never on parallel API requests → no token
      rotation race condition possible
"""
import hashlib
import logging
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration (injected from main.py lifespan)
# ---------------------------------------------------------------------------
AUTH_DB_PATH: str = "/app/data/auth.db"
DEVICE_TOKEN_TTL: int = 365 * 24 * 3600   # 1 year in seconds

DEVICE_COOKIE_NAME = "smh_device"
_SEPARATOR = ":"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _db() -> sqlite3.Connection:
    """Open the auth SQLite database and ensure schema exists."""
    db_path = Path(AUTH_DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS device_tokens (
            series      TEXT PRIMARY KEY,
            token_hash  TEXT NOT NULL,
            username    TEXT NOT NULL,
            user_agent  TEXT NOT NULL DEFAULT '',
            ip_address  TEXT NOT NULL DEFAULT '',
            created_at  REAL NOT NULL,
            last_used   REAL NOT NULL,
            expires_at  REAL NOT NULL
        )
    """)
    conn.commit()
    return conn


def _hash(token: str) -> str:
    """Return the SHA-256 hex digest of a token string."""
    return hashlib.sha256(token.encode()).hexdigest()


def _generate() -> str:
    """Return a URL-safe base64 random token (32 bytes → 43 chars)."""
    return secrets.token_urlsafe(32)


def _encode_cookie(series: str, token: str) -> str:
    return f"{series}{_SEPARATOR}{token}"


def _decode_cookie(value: str) -> Optional[tuple[str, str]]:
    """Parse 'series:token' from cookie value. Returns None if malformed."""
    if not value or _SEPARATOR not in value:
        return None
    parts = value.split(_SEPARATOR, 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return None
    return parts[0], parts[1]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_device_token(username: str, user_agent: str, ip_address: str) -> str:
    """Create a new device token entry and return the cookie value.

    Called once when admin approves a trusted-device request and the user
    logs in with 'Remember device' checked.

    Returns:
        Cookie value string: "<series>:<token>"
    """
    series = _generate()
    token  = _generate()
    now    = time.time()

    with _db() as conn:
        conn.execute(
            """
            INSERT INTO device_tokens
                (series, token_hash, username, user_agent, ip_address,
                 created_at, last_used, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (series, _hash(token), username, user_agent, ip_address,
             now, now, now + DEVICE_TOKEN_TTL),
        )

    logger.info(
        "Device token created for user %r (series prefix: %s)", username, series[:8]
    )
    return _encode_cookie(series, token)


class VerifyResult:
    """Result of verify_and_rotate_device_token()."""
    __slots__ = ("ok", "username", "new_cookie_value", "theft_detected")

    def __init__(
        self,
        ok: bool,
        username: str = "",
        new_cookie_value: str = "",
        theft_detected: bool = False,
    ):
        self.ok = ok
        self.username = username
        self.new_cookie_value = new_cookie_value
        self.theft_detected = theft_detected


def verify_and_rotate(cookie_value: str) -> VerifyResult:
    """Verify a device cookie and rotate the token (Jaspan pattern).

    Cases:
        1. Cookie malformed / series not found → VerifyResult(ok=False)
        2. Series found, token hash matches, not expired
           → rotate token, return VerifyResult(ok=True, new_cookie_value=...)
        3. Series found, token hash DOES NOT match
           → theft assumed, delete ALL device tokens for that user,
             return VerifyResult(ok=False, theft_detected=True)
        4. Series found, token matches, but expired
           → delete row, return VerifyResult(ok=False)
    """
    parsed = _decode_cookie(cookie_value)
    if parsed is None:
        return VerifyResult(ok=False)

    series, token = parsed
    incoming_hash = _hash(token)

    with _db() as conn:
        row = conn.execute(
            "SELECT * FROM device_tokens WHERE series = ?", (series,)
        ).fetchone()

        if row is None:
            # Unknown series — ignore silently
            return VerifyResult(ok=False)

        username = row["username"]

        # Check for theft: series exists but token hash does not match
        if row["token_hash"] != incoming_hash:
            logger.warning(
                "THEFT DETECTED: series %s for user %r — "
                "deleting ALL device tokens for this user",
                series[:8], username,
            )
            conn.execute(
                "DELETE FROM device_tokens WHERE username = ?", (username,)
            )
            return VerifyResult(ok=False, theft_detected=True, username=username)

        # Check expiry
        if time.time() > row["expires_at"]:
            logger.info(
                "Expired device token for user %r (series %s)", username, series[:8]
            )
            conn.execute("DELETE FROM device_tokens WHERE series = ?", (series,))
            return VerifyResult(ok=False)

        # Valid — rotate token
        new_token = _generate()
        conn.execute(
            "UPDATE device_tokens SET token_hash = ?, last_used = ? WHERE series = ?",
            (_hash(new_token), time.time(), series),
        )

    new_cookie = _encode_cookie(series, new_token)
    logger.debug(
        "Device token rotated for user %r (series prefix: %s)", username, series[:8]
    )
    return VerifyResult(ok=True, username=username, new_cookie_value=new_cookie)


def revoke_all_devices(username: str) -> int:
    """Delete all device tokens for a user. Returns number of rows deleted."""
    with _db() as conn:
        cur = conn.execute(
            "DELETE FROM device_tokens WHERE username = ?", (username,)
        )
        count = cur.rowcount
    logger.info("Revoked %d device token(s) for user %r", count, username)
    return count


def revoke_device(series: str) -> bool:
    """Delete a single device token by series. Returns True if found."""
    with _db() as conn:
        cur = conn.execute(
            "DELETE FROM device_tokens WHERE series = ?", (series,)
        )
    return cur.rowcount > 0


def list_devices(username: str) -> list[dict]:
    """Return all active device tokens for a user (for future management UI)."""
    with _db() as conn:
        rows = conn.execute(
            """
            SELECT series, user_agent, ip_address, created_at, last_used, expires_at
            FROM device_tokens WHERE username = ?
            ORDER BY last_used DESC
            """,
            (username,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_device_cookie_from_request(request) -> Optional[str]:
    """Extract the device cookie value from a request."""
    return request.cookies.get(DEVICE_COOKIE_NAME)
