"""Baby Gifts Controller — data and invitation management.

Data model:
- gifts.json: list of gift items with reservation status
- invitations table in SQLite: token-based access for guests (6-month expiry)

Gift structure:
{
    "id": "g_123456",
    "name": "Carrito de bebé",
    "description": "Preferiblemente ligero y plegable",
    "url": "https://...",  # optional link
    "price_range": "€€€",  # €, €€, €€€ or empty
    "priority": 1,  # 1=alta, 2=media, 3=baja
    "reserved_by": null,  # invitation token, "user:username", or null
    "reserved_by_name": null,  # guest name or username
    "reserved_at": null,  # ISO timestamp
    "hidden": false,  # if true, only FAMILIA users can see it
}

Invitation structure (SQLite):
- id: auto
- token: unique 32-char string
- name: guest name (e.g. "Tía María")
- created_at: timestamp
- expires_at: timestamp (6 months from creation)
- last_access: timestamp (updated on each visit)
- revoked: boolean
"""

import json
import logging
import os
import secrets
import sqlite3
import tempfile
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import config

logger: logging.Logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
DB_TIMEOUT_SECONDS: float = 5.0
INVITATION_TOKEN_BYTES: int = 24

_lock: threading.Lock = threading.Lock()

# Module-level references that can be patched by tests
DATA_DIR: Path = config.DATA_DIR
GIFTS_FILE: Path = config.GIFTS_FILE
DB_FILE: Path = config.DB_FILE


# ── Database setup ────────────────────────────────────────────────────────────
def _init_db() -> None:
    """Initialize SQLite database for invitations.

    Creates the invitations and rate_limits tables if they don't exist,
    and handles schema migrations (e.g., adding expires_at column).
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn: sqlite3.Connection = sqlite3.connect(str(DB_FILE), timeout=DB_TIMEOUT_SECONDS)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS invitations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT,
            last_access TEXT,
            revoked INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rate_limits (
            ip TEXT PRIMARY KEY,
            attempts INTEGER DEFAULT 0,
            window_start TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_rate_limits_ip ON rate_limits(ip)
    """)
    # Migration: add expires_at column if it doesn't exist
    try:
        conn.execute("ALTER TABLE invitations ADD COLUMN expires_at TEXT")
        # Set expiry for existing invitations (6 months from created_at)
        conn.execute("""
            UPDATE invitations
            SET expires_at = datetime(created_at, '+180 days')
            WHERE expires_at IS NULL
        """)
        conn.commit()
    except sqlite3.OperationalError:
        pass  # Column already exists
    conn.commit()
    conn.close()


def _get_db() -> sqlite3.Connection:
    """Get a database connection.

    Ensures the database is initialized before returning a connection.
    Uses timeout=5.0 to prevent indefinite blocking on locked database.
    Caller is responsible for closing the connection.
    """
    _init_db()
    conn: sqlite3.Connection = sqlite3.connect(str(DB_FILE), timeout=DB_TIMEOUT_SECONDS)
    conn.row_factory = sqlite3.Row
    return conn


# ── Gift ID validation ────────────────────────────────────────────────────────
# Regex patterns for valid gift IDs:
# - New format: g_<timestamp_ms>_<hex8> (e.g., g_1729432800000_a1b2c3d4)
# - Legacy format: g_<timestamp_s_or_ms> (e.g., g_1790764472872) - no hex suffix
# timestamp: 10+ digits (seconds or milliseconds since epoch)
# hex: 8 hex characters (from secrets.token_hex(4)) - optional for legacy
import re

_GIFT_ID_PATTERN: re.Pattern[str] = re.compile(r"^g_\d{10,}(_[0-9a-f]{8})?$")


def _validate_gift_id(gift_id: str) -> bool:
    """Validate gift_id format for security.

    Accepts:
    - New format: g_<timestamp_ms>_<hex8> (e.g., g_1729432800000_a1b2c3d4)
    - Legacy format: g_<timestamp> (e.g., g_1790764472872) - no hex suffix
    - UUID format: for future compatibility

    Rejects:
    - Empty/None values
    - Path traversal attempts (../, /, \\)
    - Non-alphanumeric characters outside the expected pattern
    - Excessively long IDs (max 50 chars)

    Args:
        gift_id: The gift ID to validate.

    Returns:
        bool: True if valid, False otherwise.
    """
    # Must be a non-empty string
    if not gift_id or not isinstance(gift_id, str):
        return False

    # Length check to prevent DoS via regex
    if len(gift_id) > 50:
        return False

    # Block path traversal attempts
    if ".." in gift_id or "/" in gift_id or "\\" in gift_id:
        return False

    # Check native format: g_<timestamp>_<hex>
    if _GIFT_ID_PATTERN.match(gift_id):
        return True

    # Check UUID format for future compatibility
    try:
        uuid.UUID(gift_id)
        return True
    except (ValueError, AttributeError, TypeError):
        pass

    return False


# ── Gifts data ────────────────────────────────────────────────────────────────
def _load_gifts() -> dict[str, Any]:
    """Load gifts data from JSON file."""
    if not GIFTS_FILE.exists():
        return {"gifts": []}
    try:
        return json.loads(GIFTS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        # OSError covers file permission issues, disk errors, and other I/O
        # failures that may occur in containerized/volume-mounted environments.
        # Returning empty data is safer than crashing the service; admins can
        # restore from backup. The error is logged for investigation.
        logger.error(f"Error loading gifts: {e}")
        return {"gifts": []}


def _save_gifts(data: dict[str, Any]) -> None:
    """Save gifts data to JSON file atomically.

    Writes to a temporary file in the same directory, fsyncs it, then renames
    it over the target with os.replace() (atomic on POSIX and Windows). A crash
    mid-write therefore leaves either the old complete gifts.json or the new
    complete one — never a half-written file that _load_gifts would discard,
    losing every reservation. The temp file must share the target's filesystem
    for the rename to be atomic, hence dir=DATA_DIR.

    This mirrors smart_home_common.persistence.atomic_write_json; it is inlined
    because baby-gifts does not ship the shared library.

    Args:
        data: Dictionary containing gifts data to persist.

    Raises:
        OSError: If the data directory cannot be created, or the temporary file
            cannot be written, fsynced, or renamed to the target path.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=DATA_DIR,
            prefix=f".{GIFTS_FILE.name}.",
            suffix=".tmp",
            delete=False,
        ) as f:
            temp_path = f.name
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, GIFTS_FILE)  # atomic on POSIX and Windows
        temp_path = None
    finally:
        # If replace never ran (exception during write), drop the stray temp file.
        if temp_path is not None and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError as e:
                logger.warning(f"Could not remove temp file {temp_path}: {e}")


def get_gifts_data(include_admin: bool = False) -> dict[str, Any]:
    """Get all gifts data. If not admin, hide who reserved (privacy)."""
    with _lock:
        data: dict[str, Any] = _load_gifts()
        if not include_admin:
            # For guests: show if reserved, but not by whom (unless it's them)
            # This will be filtered in the API layer based on the guest's token
            pass
        return data


def get_gift(gift_id: str) -> dict[str, Any] | None:
    """Get a single gift by ID.

    Args:
        gift_id: The gift ID to retrieve.

    Returns:
        Gift dict if found, None if not found or invalid ID.
    """
    # Validate gift_id format
    if not _validate_gift_id(gift_id):
        return None

    with _lock:
        data: dict[str, Any] = _load_gifts()
        for gift in data.get("gifts", []):
            if gift["id"] == gift_id:
                return gift
        return None


def add_gift(gift: dict[str, Any]) -> dict[str, Any]:
    """Add a new gift (admin only)."""
    with _lock:
        data: dict[str, Any] = _load_gifts()
        # Use timestamp + random suffix to ensure unique IDs even in rapid succession
        gift_id: str = (
            f"g_{int(datetime.now().timestamp() * 1000)}_{secrets.token_hex(4)}"
        )
        new_gift: dict[str, Any] = {
            "id": gift_id,
            "name": gift.get("name", ""),
            "description": gift.get("description", ""),
            "url": gift.get("url", ""),
            "price_range": gift.get("price_range", ""),
            "priority": gift.get("priority", 2),
            "reserved_by": None,
            "reserved_by_name": None,
            "reserved_at": None,
            "hidden": gift.get("hidden", False),
        }
        data["gifts"].append(new_gift)
        _save_gifts(data)
        return new_gift


def update_gift(
    gift_id: str, updates: dict[str, Any]
) -> dict[str, Any] | None | tuple[None, int, str]:
    """Update a gift (admin only).

    Returns:
        - dict: Updated gift on success
        - None: Gift not found (legacy behavior, returns 404 at API layer)
        - tuple[None, int, str]: (None, status_code, error_message) for validation
    """
    # Validate gift_id format using centralized validation
    if not _validate_gift_id(gift_id):
        return (None, 400, "Invalid gift_id format")

    with _lock:
        data: dict[str, Any] = _load_gifts()
        for i, gift in enumerate(data.get("gifts", [])):
            if gift["id"] == gift_id:
                # Only update allowed fields
                for key in [
                    "name",
                    "description",
                    "url",
                    "price_range",
                    "priority",
                    "hidden",
                ]:
                    if key in updates:
                        gift[key] = updates[key]
                data["gifts"][i] = gift
                _save_gifts(data)
                return gift
        # Gift not found - return None for 404 (legacy behavior)
        return None


def delete_gift(gift_id: str) -> bool:
    """Delete a gift (admin only).

    Args:
        gift_id: The gift ID to delete.

    Returns:
        True if gift was deleted, False if not found or invalid ID.
    """
    # Validate gift_id format
    if not _validate_gift_id(gift_id):
        return False

    with _lock:
        data: dict[str, Any] = _load_gifts()
        original_len: int = len(data.get("gifts", []))
        data["gifts"] = [g for g in data.get("gifts", []) if g["id"] != gift_id]
        if len(data["gifts"]) < original_len:
            _save_gifts(data)
            return True
        return False


def reserve_gift(gift_id: str, token: str, guest_name: str) -> dict[str, Any]:
    """Reserve a gift for a guest or authenticated user.

    Args:
        gift_id: The gift to reserve.
        token: Either an invitation token or "user:username" for authenticated users.
        guest_name: Display name for the reservation.

    Returns:
        Dict with status 'ok' and gift, or status 'error' with message.
    """
    # Validate gift_id format
    if not _validate_gift_id(gift_id):
        logger.warning(
            "reserve_gift failed: invalid gift_id format, "
            f"gift_id={gift_id!r}, guest={guest_name}"
        )
        return {"status": "error", "message": "Invalid gift_id format"}

    with _lock:
        data: dict[str, Any] = _load_gifts()
        for i, gift in enumerate(data.get("gifts", [])):
            if gift["id"] == gift_id:
                if gift.get("reserved_by"):
                    logger.info(
                        f"reserve_gift rejected: already reserved, "
                        f"gift_id={gift_id}, guest={guest_name}"
                    )
                    return {
                        "status": "error",
                        "message": "Este regalo ya está reservado",
                    }
                gift["reserved_by"] = token
                gift["reserved_by_name"] = guest_name
                gift["reserved_at"] = datetime.now().isoformat()
                data["gifts"][i] = gift
                _save_gifts(data)
                return {"status": "ok", "gift": gift}
        logger.warning(
            f"reserve_gift failed: gift not found, "
            f"gift_id={gift_id}, guest={guest_name}"
        )
        return {"status": "error", "message": "Regalo no encontrado"}


def unreserve_gift(gift_id: str, token: str, is_admin: bool = False) -> dict[str, Any]:
    """Cancel a reservation. Users can only cancel their own.

    Args:
        gift_id: The gift to unreserve.
        token: The token of the user attempting to unreserve.
        is_admin: If True, bypass ownership check.

    Returns:
        Dict with status 'ok' and gift, or status 'error' with message.
    """
    # Validate gift_id format
    if not _validate_gift_id(gift_id):
        logger.warning(
            f"unreserve_gift failed: invalid gift_id format, "
            f"gift_id={gift_id!r}, is_admin={is_admin}"
        )
        return {"status": "error", "message": "Invalid gift_id format"}

    with _lock:
        data: dict[str, Any] = _load_gifts()
        for i, gift in enumerate(data.get("gifts", [])):
            if gift["id"] == gift_id:
                if not gift.get("reserved_by"):
                    logger.info(
                        f"unreserve_gift rejected: not reserved, gift_id={gift_id}"
                    )
                    return {
                        "status": "error",
                        "message": "Este regalo no está reservado",
                    }
                # Check permission
                if not is_admin and gift["reserved_by"] != token:
                    logger.warning(
                        f"unreserve_gift rejected: ownership mismatch, "
                        f"gift_id={gift_id}, requester_token=redacted, "
                        f"owner_token=redacted"
                    )
                    return {
                        "status": "error",
                        "message": "No puedes cancelar la reserva de otro",
                    }
                gift["reserved_by"] = None
                gift["reserved_by_name"] = None
                gift["reserved_at"] = None
                data["gifts"][i] = gift
                _save_gifts(data)
                return {"status": "ok", "gift": gift}
        logger.warning(f"unreserve_gift failed: gift not found, gift_id={gift_id}")
        return {"status": "error", "message": "Regalo no encontrado"}


def toggle_gift_visibility(gift_id: str) -> dict[str, Any]:
    """Toggle a gift's hidden status (FAMILIA users only).

    Args:
        gift_id: The gift ID to toggle visibility.

    Returns:
        Dict with status 'ok', gift and hidden state, or status 'error'.
    """
    # Validate gift_id format
    if not _validate_gift_id(gift_id):
        return {"status": "error", "message": "Invalid gift_id format"}

    with _lock:
        data: dict[str, Any] = _load_gifts()
        for i, gift in enumerate(data.get("gifts", [])):
            if gift["id"] == gift_id:
                gift["hidden"] = not gift.get("hidden", False)
                data["gifts"][i] = gift
                _save_gifts(data)
                return {"status": "ok", "gift": gift, "hidden": gift["hidden"]}
        return {"status": "error", "message": "Regalo no encontrado"}


def is_familia_user(username: str) -> bool:
    """Check if a user has FAMILIA permission."""
    return username.lower() in config.FAMILIA_USERS


# ── Invitations ───────────────────────────────────────────────────────────────
MAX_INVITATION_RETRIES: int = 3


def create_invitation(name: str, _retries: int = 0) -> dict[str, Any]:
    """Create a new invitation with a unique token. Expires in 6 months.

    Args:
        name: Guest name for the invitation.
        _retries: Internal retry counter (do not set manually).

    Returns:
        Dict with status 'ok' and invitation details, or status 'error' if
        token generation fails after MAX_INVITATION_RETRIES attempts.
    """
    if _retries >= MAX_INVITATION_RETRIES:
        logger.error(
            "Failed to create invitation after %d retries for name=%s",
            MAX_INVITATION_RETRIES,
            name,
        )
        return {"status": "error", "message": "Failed to generate unique token"}

    token: str = secrets.token_urlsafe(INVITATION_TOKEN_BYTES)  # 32 chars
    now: datetime = datetime.now()
    expires_at: datetime = now + timedelta(days=config.INVITATION_EXPIRY_DAYS)

    conn: sqlite3.Connection = _get_db()
    try:
        conn.execute(
            "INSERT INTO invitations (token, name, created_at, expires_at) "
            "VALUES (?, ?, ?, ?)",
            (token, name, now.isoformat(), expires_at.isoformat()),
        )
        conn.commit()
        return {
            "status": "ok",
            "token": token,
            "name": name,
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
        }
    except sqlite3.IntegrityError:
        # Token collision (extremely unlikely), retry with incremented counter
        return create_invitation(name, _retries + 1)
    finally:
        conn.close()


def validate_invitation(token: str) -> dict[str, Any] | None:
    """Validate invitation token. Returns guest info or None if invalid."""
    conn: sqlite3.Connection = _get_db()
    try:
        row: sqlite3.Row | None = conn.execute(
            "SELECT * FROM invitations WHERE token = ? AND revoked = 0", (token,)
        ).fetchone()
        if row:
            # Check expiry
            if row["expires_at"]:
                expires_at: datetime = datetime.fromisoformat(row["expires_at"])
                if datetime.now() > expires_at:
                    return None  # Expired

            # Update last access
            now: str = datetime.now().isoformat()
            conn.execute(
                "UPDATE invitations SET last_access = ? WHERE token = ?", (now, token)
            )
            conn.commit()
            return {
                "id": row["id"],
                "token": row["token"],
                "name": row["name"],
                "created_at": row["created_at"],
                "expires_at": row["expires_at"],
                "last_access": now,
            }
        return None
    finally:
        conn.close()


def list_invitations() -> list[dict[str, Any]]:
    """List all invitations (admin only)."""
    conn: sqlite3.Connection = _get_db()
    try:
        rows: list[sqlite3.Row] = conn.execute(
            "SELECT * FROM invitations ORDER BY created_at DESC"
        ).fetchall()
        now: datetime = datetime.now()
        result: list[dict[str, Any]] = []
        for row in rows:
            expired: bool = False
            if row["expires_at"]:
                try:
                    expires_at: datetime = datetime.fromisoformat(row["expires_at"])
                    expired = now > expires_at
                except ValueError:
                    pass
            result.append(
                {
                    "id": row["id"],
                    "token": row["token"],
                    "name": row["name"],
                    "created_at": row["created_at"],
                    "expires_at": row["expires_at"],
                    "last_access": row["last_access"],
                    "revoked": bool(row["revoked"]),
                    "expired": expired,
                }
            )
        return result
    finally:
        conn.close()


def revoke_invitation(token: str) -> dict[str, Any]:
    """Revoke an invitation (admin only)."""
    conn: sqlite3.Connection = _get_db()
    try:
        result: sqlite3.Cursor = conn.execute(
            "UPDATE invitations SET revoked = 1 WHERE token = ?", (token,)
        )
        conn.commit()
        if result.rowcount > 0:
            return {"status": "ok", "message": "Invitación revocada"}
        return {"status": "error", "message": "Invitación no encontrada"}
    finally:
        conn.close()


def delete_invitation(token: str) -> dict[str, Any]:
    """Delete an invitation completely (admin only)."""
    conn: sqlite3.Connection = _get_db()
    try:
        result: sqlite3.Cursor = conn.execute(
            "DELETE FROM invitations WHERE token = ?", (token,)
        )
        conn.commit()
        if result.rowcount > 0:
            return {"status": "ok", "message": "Invitación eliminada"}
        return {"status": "error", "message": "Invitación no encontrada"}
    finally:
        conn.close()


def get_invitation_reservations(token: str) -> int:
    """Count how many gifts are reserved by this invitation."""
    with _lock:
        data: dict[str, Any] = _load_gifts()
        count: int = sum(
            1 for g in data.get("gifts", []) if g.get("reserved_by") == token
        )
        return count


# ── Rate limiting ─────────────────────────────────────────────────────────────


def check_rate_limit(ip: str) -> bool:
    """Check if IP is rate limited. Returns True if allowed, False if blocked."""
    conn: sqlite3.Connection = _get_db()
    try:
        now: datetime = datetime.now()
        row: sqlite3.Row | None = conn.execute(
            "SELECT attempts, window_start FROM rate_limits WHERE ip = ?", (ip,)
        ).fetchone()
        if row:
            window_start: datetime = datetime.fromisoformat(row["window_start"])
            elapsed: float = (now - window_start).total_seconds()
            if elapsed > config.RATE_LIMIT_WINDOW_SECONDS:
                # Reset window
                conn.execute(
                    "UPDATE rate_limits SET attempts = 1, window_start = ? "
                    "WHERE ip = ?",
                    (now.isoformat(), ip),
                )
                conn.commit()
                return True
            if row["attempts"] >= config.RATE_LIMIT_ATTEMPTS:
                return False
            # Increment attempts
            conn.execute(
                "UPDATE rate_limits SET attempts = attempts + 1 WHERE ip = ?", (ip,)
            )
            conn.commit()
            return True
        else:
            # First attempt from this IP
            conn.execute(
                "INSERT INTO rate_limits (ip, attempts, window_start) VALUES (?, 1, ?)",
                (ip, now.isoformat()),
            )
            conn.commit()
            return True
    finally:
        conn.close()


def check_invitation_rate_limit(ip: str) -> bool:
    """Check rate limit for invitation creation (30 req/min per IP).

    Uses a separate rate limit table (invitation_rate_limits) to avoid
    interference with guest endpoint rate limits. This separation is intentional:
    - Guest endpoints have stricter limits (abuse prevention for public APIs)
    - Invitation creation is admin-only with different thresholds
    - Keeping them separate allows independent tuning without side effects

    The table is created lazily here rather than in _init_db() because:
    - It was added later and this ensures backwards compatibility
    - Avoids migration complexity for a simple rate limit table
    - The CREATE IF NOT EXISTS is idempotent and fast

    Returns True if allowed, False if blocked.
    """
    conn: sqlite3.Connection = _get_db()
    try:
        # Ensure invitation_rate_limits table exists (lazy creation for
        # backwards compatibility - see docstring for rationale)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS invitation_rate_limits (
                ip TEXT PRIMARY KEY,
                attempts INTEGER DEFAULT 0,
                window_start TEXT NOT NULL
            )
        """)
        conn.commit()

        now: datetime = datetime.now()
        row: sqlite3.Row | None = conn.execute(
            "SELECT attempts, window_start FROM invitation_rate_limits WHERE ip = ?",
            (ip,),
        ).fetchone()
        if row:
            window_start: datetime = datetime.fromisoformat(row["window_start"])
            elapsed: float = (now - window_start).total_seconds()
            if elapsed > config.INVITATION_RATE_LIMIT_WINDOW_SECONDS:
                # Reset window
                conn.execute(
                    "UPDATE invitation_rate_limits SET attempts = 1, window_start = ? "
                    "WHERE ip = ?",
                    (now.isoformat(), ip),
                )
                conn.commit()
                return True
            if row["attempts"] >= config.INVITATION_RATE_LIMIT_ATTEMPTS:
                return False
            # Increment attempts
            conn.execute(
                "UPDATE invitation_rate_limits SET attempts = attempts + 1 "
                "WHERE ip = ?",
                (ip,),
            )
            conn.commit()
            return True
        else:
            # First attempt from this IP
            conn.execute(
                "INSERT INTO invitation_rate_limits (ip, attempts, window_start) "
                "VALUES (?, 1, ?)",
                (ip, now.isoformat()),
            )
            conn.commit()
            return True
    finally:
        conn.close()


def is_healthy() -> bool:
    """Health check."""
    try:
        _get_db().close()
        return True
    except sqlite3.Error:
        return False
