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
    "category": "transporte",
    "priority": 1,  # 1=alta, 2=media, 3=baja
    "reserved_by": null,  # invitation token, "user:username", or null
    "reserved_by_name": null,  # guest name or username
    "reserved_at": null,  # ISO timestamp
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
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────────────
DATA_DIR = Path(os.environ.get("DATA_DIR", "/app/data"))
GIFTS_FILE = DATA_DIR / "gifts.json"
DB_FILE = DATA_DIR / "baby_gifts.db"
_lock = threading.Lock()

# ── Constants ─────────────────────────────────────────────────────────────────
INVITATION_EXPIRY_DAYS = 180  # 6 months

# ── Database setup ────────────────────────────────────────────────────────────
def _init_db():
    """Initialize SQLite database for invitations."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_FILE))
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

def _get_db():
    """Get a database connection."""
    _init_db()
    conn = sqlite3.connect(str(DB_FILE))
    conn.row_factory = sqlite3.Row
    return conn

# ── Gifts data ────────────────────────────────────────────────────────────────
def _load_gifts() -> dict:
    """Load gifts data from JSON file."""
    if not GIFTS_FILE.exists():
        return {"gifts": [], "categories": _default_categories()}
    try:
        return json.loads(GIFTS_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error(f"Error loading gifts: {e}")
        return {"gifts": [], "categories": _default_categories()}

def _save_gifts(data: dict):
    """Save gifts data to JSON file."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    GIFTS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def _default_categories() -> list:
    """Default gift categories."""
    return [
        {"id": "ropa", "name": "Ropa", "icon": "👕"},
        {"id": "transporte", "name": "Transporte", "icon": "🚗"},
        {"id": "alimentacion", "name": "Alimentación", "icon": "🍼"},
        {"id": "higiene", "name": "Higiene", "icon": "🛁"},
        {"id": "dormitorio", "name": "Dormitorio", "icon": "🛏️"},
        {"id": "juguetes", "name": "Juguetes", "icon": "🧸"},
        {"id": "otros", "name": "Otros", "icon": "🎁"},
    ]

def get_gifts_data(include_admin: bool = False) -> dict:
    """Get all gifts data. If not admin, hide who reserved (privacy)."""
    with _lock:
        data = _load_gifts()
        if not include_admin:
            # For guests: show if reserved, but not by whom (unless it's them)
            # This will be filtered in the API layer based on the guest's token
            pass
        return data

def get_gift(gift_id: str) -> Optional[dict]:
    """Get a single gift by ID."""
    with _lock:
        data = _load_gifts()
        for gift in data.get("gifts", []):
            if gift["id"] == gift_id:
                return gift
        return None

def add_gift(gift: dict) -> dict:
    """Add a new gift (admin only)."""
    with _lock:
        data = _load_gifts()
        gift_id = f"g_{int(datetime.now().timestamp() * 1000)}"
        new_gift = {
            "id": gift_id,
            "name": gift.get("name", ""),
            "description": gift.get("description", ""),
            "url": gift.get("url", ""),
            "price_range": gift.get("price_range", ""),
            "category": gift.get("category", "otros"),
            "priority": gift.get("priority", 2),
            "reserved_by": None,
            "reserved_by_name": None,
            "reserved_at": None,
        }
        data["gifts"].append(new_gift)
        _save_gifts(data)
        return new_gift

def update_gift(gift_id: str, updates: dict) -> Optional[dict]:
    """Update a gift (admin only)."""
    with _lock:
        data = _load_gifts()
        for i, gift in enumerate(data.get("gifts", [])):
            if gift["id"] == gift_id:
                # Only update allowed fields
                for key in ["name", "description", "url", "price_range", "category", "priority"]:
                    if key in updates:
                        gift[key] = updates[key]
                data["gifts"][i] = gift
                _save_gifts(data)
                return gift
        return None

def delete_gift(gift_id: str) -> bool:
    """Delete a gift (admin only)."""
    with _lock:
        data = _load_gifts()
        original_len = len(data.get("gifts", []))
        data["gifts"] = [g for g in data.get("gifts", []) if g["id"] != gift_id]
        if len(data["gifts"]) < original_len:
            _save_gifts(data)
            return True
        return False

def reserve_gift(gift_id: str, token: str, guest_name: str) -> dict:
    """Reserve a gift for a guest or authenticated user.
    
    Args:
        gift_id: The gift to reserve
        token: Either an invitation token or "user:username" for authenticated users
        guest_name: Display name for the reservation
    """
    with _lock:
        data = _load_gifts()
        for i, gift in enumerate(data.get("gifts", [])):
            if gift["id"] == gift_id:
                if gift.get("reserved_by"):
                    return {"status": "error", "message": "Este regalo ya está reservado"}
                gift["reserved_by"] = token
                gift["reserved_by_name"] = guest_name
                gift["reserved_at"] = datetime.now().isoformat()
                data["gifts"][i] = gift
                _save_gifts(data)
                return {"status": "ok", "gift": gift}
        return {"status": "error", "message": "Regalo no encontrado"}

def unreserve_gift(gift_id: str, token: str, is_admin: bool = False) -> dict:
    """Cancel a reservation. Users can only cancel their own."""
    with _lock:
        data = _load_gifts()
        for i, gift in enumerate(data.get("gifts", [])):
            if gift["id"] == gift_id:
                if not gift.get("reserved_by"):
                    return {"status": "error", "message": "Este regalo no está reservado"}
                # Check permission
                if not is_admin and gift["reserved_by"] != token:
                    return {"status": "error", "message": "No puedes cancelar la reserva de otro"}
                gift["reserved_by"] = None
                gift["reserved_by_name"] = None
                gift["reserved_at"] = None
                data["gifts"][i] = gift
                _save_gifts(data)
                return {"status": "ok", "gift": gift}
        return {"status": "error", "message": "Regalo no encontrado"}

def update_categories(categories: list) -> dict:
    """Update categories (admin only)."""
    with _lock:
        data = _load_gifts()
        data["categories"] = categories
        _save_gifts(data)
        return {"status": "ok", "categories": categories}

# ── Invitations ───────────────────────────────────────────────────────────────
def create_invitation(name: str) -> dict:
    """Create a new invitation with a unique token. Expires in 6 months."""
    token = secrets.token_urlsafe(24)  # 32 chars
    now = datetime.now()
    expires_at = now + timedelta(days=INVITATION_EXPIRY_DAYS)
    
    conn = _get_db()
    try:
        conn.execute(
            "INSERT INTO invitations (token, name, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token, name, now.isoformat(), expires_at.isoformat())
        )
        conn.commit()
        return {
            "status": "ok", 
            "token": token, 
            "name": name, 
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat()
        }
    except sqlite3.IntegrityError:
        # Extremely unlikely collision, retry
        return create_invitation(name)
    finally:
        conn.close()

def validate_invitation(token: str) -> Optional[dict]:
    """Validate an invitation token. Returns guest info or None if invalid/expired/revoked."""
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT * FROM invitations WHERE token = ? AND revoked = 0",
            (token,)
        ).fetchone()
        if row:
            # Check expiry
            if row["expires_at"]:
                expires_at = datetime.fromisoformat(row["expires_at"])
                if datetime.now() > expires_at:
                    return None  # Expired
            
            # Update last access
            now = datetime.now().isoformat()
            conn.execute(
                "UPDATE invitations SET last_access = ? WHERE token = ?",
                (now, token)
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

def list_invitations() -> list:
    """List all invitations (admin only)."""
    conn = _get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM invitations ORDER BY created_at DESC"
        ).fetchall()
        now = datetime.now()
        result = []
        for row in rows:
            expired = False
            if row["expires_at"]:
                try:
                    expires_at = datetime.fromisoformat(row["expires_at"])
                    expired = now > expires_at
                except Exception:
                    pass
            result.append({
                "id": row["id"],
                "token": row["token"],
                "name": row["name"],
                "created_at": row["created_at"],
                "expires_at": row["expires_at"],
                "last_access": row["last_access"],
                "revoked": bool(row["revoked"]),
                "expired": expired,
            })
        return result
    finally:
        conn.close()

def revoke_invitation(token: str) -> dict:
    """Revoke an invitation (admin only)."""
    conn = _get_db()
    try:
        result = conn.execute(
            "UPDATE invitations SET revoked = 1 WHERE token = ?",
            (token,)
        )
        conn.commit()
        if result.rowcount > 0:
            return {"status": "ok", "message": "Invitación revocada"}
        return {"status": "error", "message": "Invitación no encontrada"}
    finally:
        conn.close()

def delete_invitation(token: str) -> dict:
    """Delete an invitation completely (admin only)."""
    conn = _get_db()
    try:
        result = conn.execute(
            "DELETE FROM invitations WHERE token = ?",
            (token,)
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
        data = _load_gifts()
        count = sum(1 for g in data.get("gifts", []) if g.get("reserved_by") == token)
        return count

# ── Rate limiting ─────────────────────────────────────────────────────────────
RATE_LIMIT_ATTEMPTS = 20
RATE_LIMIT_WINDOW_SECONDS = 60

def check_rate_limit(ip: str) -> bool:
    """Check if IP is rate limited. Returns True if allowed, False if blocked."""
    conn = _get_db()
    try:
        now = datetime.now()
        row = conn.execute(
            "SELECT attempts, window_start FROM rate_limits WHERE ip = ?",
            (ip,)
        ).fetchone()
        if row:
            window_start = datetime.fromisoformat(row["window_start"])
            elapsed = (now - window_start).total_seconds()
            if elapsed > RATE_LIMIT_WINDOW_SECONDS:
                # Reset window
                conn.execute(
                    "UPDATE rate_limits SET attempts = 1, window_start = ? WHERE ip = ?",
                    (now.isoformat(), ip)
                )
                conn.commit()
                return True
            if row["attempts"] >= RATE_LIMIT_ATTEMPTS:
                return False
            # Increment attempts
            conn.execute(
                "UPDATE rate_limits SET attempts = attempts + 1 WHERE ip = ?",
                (ip,)
            )
            conn.commit()
            return True
        else:
            # First attempt from this IP
            conn.execute(
                "INSERT INTO rate_limits (ip, attempts, window_start) VALUES (?, 1, ?)",
                (ip, now.isoformat())
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
    except Exception:
        return False
