"""Persistent trusted-device tokens using the Jaspan pattern.

Cookie format (stored client-side, HttpOnly):
    smh_device=<series_b64>:<token_b64>

Database table (device_tokens):
    series      TEXT  — stable identifier for one device/browser (never changes)
    token_hash  TEXT  — SHA-256 of current one-time token (rotates on every use)
    prev_hash   TEXT  — SHA-256 of previous token (grace window for race conditions)
    prev_until  REAL  — unix timestamp until prev_hash is still valid
    username    TEXT  — owner
    user_agent  TEXT  — for display in future device management UI
    ip_address  TEXT  — for display / logging
    created_at  REAL  — unix timestamp
    last_used   REAL  — unix timestamp (updated on each rotation)
    expires_at  REAL  — unix timestamp (1 year from creation)

Security properties:
    - Token rotates on every use → stolen cookie window = until victim next accesses
    - Only hash is stored → DB leak does not directly yield valid cookie values
    - Series mismatch (valid series + wrong token outside grace window) → token invalid →
      only THAT device token is deleted (not all user devices)
    - Race condition handled: previous token valid for 1 hour after rotation
      to handle parallel requests, laptop sleep/wake, and network issues
"""

import hashlib
import logging
import secrets
import sqlite3
import time
from contextlib import AbstractContextManager

from smart_home_common.sqlite_helpers import sqlite_connection

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration (injected from main.py lifespan)
# ---------------------------------------------------------------------------
AUTH_DB_PATH: str = "/app/data/auth.db"
DEVICE_TOKEN_TTL: int = 365 * 24 * 3600  # 1 year in seconds
GRACE_WINDOW_SECONDS: int = 3600  # Previous token valid for 1 hour after rotation

DEVICE_COOKIE_NAME = "smh_device"
_SEPARATOR = ":"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
# Connection management is delegated to smart_home_common.sqlite_helpers, which
# enables WAL, commits on success, rolls back on error and ALWAYS closes the
# connection so WAL (-wal/-shm) file handles are released (prevents WinError 32
# on Windows temp-dir cleanup and state leaking between tests). ``_db`` reads
# ``AUTH_DB_PATH`` at call time so late injection from main.py's lifespan still
# takes effect.


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Create the device_tokens table and run idempotent column migrations."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS device_tokens (
            series      TEXT PRIMARY KEY,
            token_hash  TEXT NOT NULL,
            prev_hash   TEXT DEFAULT NULL,
            prev_until  REAL DEFAULT NULL,
            username    TEXT NOT NULL,
            user_agent  TEXT NOT NULL DEFAULT '',
            ip_address  TEXT NOT NULL DEFAULT '',
            created_at  REAL NOT NULL,
            last_used   REAL NOT NULL,
            expires_at  REAL NOT NULL,
            pending_cookie TEXT DEFAULT NULL
        )
    """)
    # Migration: add prev_hash and prev_until columns if they don't exist
    try:
        conn.execute("ALTER TABLE device_tokens ADD COLUMN prev_hash TEXT DEFAULT NULL")
    except sqlite3.OperationalError:
        pass  # Column already exists
    try:
        conn.execute(
            "ALTER TABLE device_tokens ADD COLUMN prev_until REAL DEFAULT NULL"
        )
    except sqlite3.OperationalError:
        pass  # Column already exists
    # Migration: add pending_cookie for deferred delivery
    try:
        conn.execute(
            "ALTER TABLE device_tokens ADD COLUMN pending_cookie TEXT DEFAULT NULL"
        )
    except sqlite3.OperationalError:
        pass  # Column already exists


def _db() -> AbstractContextManager[sqlite3.Connection]:
    """Yield an auth DB connection, committing on success and always closing.

    Delegates to :func:`smart_home_common.sqlite_helpers.sqlite_connection`,
    which guarantees ``conn.close()`` in ``finally`` so WAL file handles are
    released (prevents WinError 32 on Windows temp-dir cleanup).
    """
    return sqlite_connection(AUTH_DB_PATH, init=_ensure_schema)


def _hash(token: str) -> str:
    """Return the SHA-256 hex digest of a token string."""
    return hashlib.sha256(token.encode()).hexdigest()


def _generate() -> str:
    """Return a URL-safe base64 random token (32 bytes → 43 chars)."""
    return secrets.token_urlsafe(32)


def _encode_cookie(series: str, token: str) -> str:
    return f"{series}{_SEPARATOR}{token}"


def _decode_cookie(value: str) -> tuple[str, str] | None:
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


def create_device_token(
    username: str, user_agent: str, ip_address: str, pending: bool = False
) -> str:
    """Create a new device token entry and return the cookie value.

    Args:
        username: The user who owns this device token.
        user_agent: Browser/device identifier for display.
        ip_address: IP address for logging/display.
        pending: If True, store cookie value for deferred delivery (admin approval flow).
                 If False (default), token is immediately active.

    Returns:
        Cookie value string: "<series>:<token>"
    """
    series = _generate()
    token = _generate()
    cookie_value = _encode_cookie(series, token)
    now = time.time()

    with _db() as conn:
        conn.execute(
            """
            INSERT INTO device_tokens
                (series, token_hash, username, user_agent, ip_address,
                 created_at, last_used, expires_at, pending_cookie)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                series,
                _hash(token),
                username,
                user_agent,
                ip_address,
                now,
                now,
                now + DEVICE_TOKEN_TTL,
                cookie_value if pending else None,
            ),
        )

    if pending:
        logger.info(
            "Device token created (pending delivery) for user %r (series prefix: %s)",
            username,
            series[:8],
        )
    else:
        logger.info(
            "Device token created for user %r (series prefix: %s)", username, series[:8]
        )
    return cookie_value


class VerifyResult:
    """Result of verify_and_rotate_device_token()."""

    __slots__ = ("new_cookie_value", "ok", "theft_detected", "username")

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
    """Verify a device cookie and rotate the token (Jaspan pattern with grace window).

    Cases:
        1. Cookie malformed / series not found → VerifyResult(ok=False)
        2. Series found, current token hash matches, not expired
           → rotate token (keep old as prev_hash for grace window),
             return VerifyResult(ok=True, new_cookie_value=...)
        3. Series found, previous token hash matches AND within grace window
           → return VerifyResult(ok=True) with CURRENT cookie (no re-rotation)
        4. Series found, token hash DOES NOT match (neither current nor prev in grace)
           → revoke THIS device only (not all user devices),
             return VerifyResult(ok=False, theft_detected=True)
        5. Series found, token matches, but expired
           → delete row, return VerifyResult(ok=False)
    """
    parsed = _decode_cookie(cookie_value)
    if parsed is None:
        return VerifyResult(ok=False)

    series, token = parsed
    incoming_hash = _hash(token)
    now = time.time()

    with _db() as conn:
        row = conn.execute(
            "SELECT * FROM device_tokens WHERE series = ?", (series,)
        ).fetchone()

        if row is None:
            # Unknown series — ignore silently
            return VerifyResult(ok=False)

        username = row["username"]

        # Check expiry first
        if now > row["expires_at"]:
            logger.info(
                "Expired device token for user %r (series %s)", username, series[:8]
            )
            conn.execute("DELETE FROM device_tokens WHERE series = ?", (series,))
            return VerifyResult(ok=False)

        # Case 2: Current token matches → rotate
        if row["token_hash"] == incoming_hash:
            new_token = _generate()
            # Store current as prev with grace window
            conn.execute(
                """UPDATE device_tokens 
                   SET token_hash = ?, prev_hash = ?, prev_until = ?, last_used = ? 
                   WHERE series = ?""",
                (
                    _hash(new_token),
                    row["token_hash"],
                    now + GRACE_WINDOW_SECONDS,
                    now,
                    series,
                ),
            )
            new_cookie = _encode_cookie(series, new_token)
            logger.debug(
                "Device token rotated for user %r (series prefix: %s)",
                username,
                series[:8],
            )
            return VerifyResult(ok=True, username=username, new_cookie_value=new_cookie)

        # Case 3: Previous token within grace window → accept but don't rotate again
        prev_hash = row["prev_hash"]
        prev_until = row["prev_until"]
        if (
            prev_hash
            and prev_until
            and incoming_hash == prev_hash
            and now <= prev_until
        ):
            logger.debug(
                "Device token validated via grace window for user %r (series %s)",
                username,
                series[:8],
            )
            # Return the CURRENT token (client should update to this)
            # We need to get the current token... but we only have the hash.
            # Solution: return empty new_cookie_value to signal "use existing JWT, don't update cookie"
            # The middleware will still issue a fresh JWT but won't overwrite the device cookie
            return VerifyResult(ok=True, username=username, new_cookie_value="")

        # Case 4: Token mismatch — invalid token, revoke only THIS device
        # Note: Traditional Jaspan pattern deletes ALL user tokens on mismatch
        # (assuming theft). We take a softer approach: only revoke the affected
        # device. This avoids nuking all devices due to network glitches, browser
        # cache issues, or a single compromised device. A real attacker with one
        # stolen cookie can only access until the victim uses that device again.
        logger.warning(
            "Token mismatch for series %s (user %r) — revoking this device only",
            series[:8],
            username,
        )
        conn.execute("DELETE FROM device_tokens WHERE series = ?", (series,))
        return VerifyResult(ok=False, theft_detected=True, username=username)


def revoke_all_devices(username: str) -> int:
    """Delete all device tokens for a user. Returns number of rows deleted."""
    with _db() as conn:
        cur = conn.execute("DELETE FROM device_tokens WHERE username = ?", (username,))
        count = cur.rowcount
    logger.info("Revoked %d device token(s) for user %r", count, username)
    return count


def revoke_device(series: str) -> bool:
    """Delete a single device token by series. Returns True if found."""
    with _db() as conn:
        cur = conn.execute("DELETE FROM device_tokens WHERE series = ?", (series,))
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


def get_device_cookie_from_request(request) -> str | None:
    """Extract the device cookie value from a request."""
    return request.cookies.get(DEVICE_COOKIE_NAME)


def get_pending_token(username: str, user_agent: str) -> str | None:
    """Return the pending cookie value for this user+device, if any.

    Only returns a pending token if the user_agent matches the one that
    originally requested the trust (stored when admin approved). This
    prevents device A from receiving device B's token.
    """
    with _db() as conn:
        row = conn.execute(
            "SELECT pending_cookie FROM device_tokens "
            "WHERE username = ? AND user_agent = ? AND pending_cookie IS NOT NULL LIMIT 1",
            (username, user_agent),
        ).fetchone()
    return row["pending_cookie"] if row else None


def mark_token_delivered(username: str, user_agent: str) -> None:
    """Clear pending_cookie flag after the token has been delivered to the user's browser."""
    with _db() as conn:
        conn.execute(
            "UPDATE device_tokens SET pending_cookie = NULL "
            "WHERE username = ? AND user_agent = ? AND pending_cookie IS NOT NULL",
            (username, user_agent),
        )
    logger.info("Pending device token delivered to user %r", username)
