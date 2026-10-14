"""User store and trusted-device management.

Users are stored in SQLite with: id (UUID), username, password_hash, display_name, icon.
The id and username are immutable once created.
Password hash uses apr_md5_crypt format for nginx compatibility.
Trusted device requests are persisted for admin approval via email links.
"""

import hashlib
import hmac
import json
import logging
import secrets
import sqlite3
import time
import uuid
from contextlib import AbstractContextManager

from auth import verify_password
from passlib.hash import apr_md5_crypt
from smart_home_common.sqlite_helpers import open_connection, sqlite_connection

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration (injected from main.py lifespan)
# ---------------------------------------------------------------------------
HTPASSWD_PATH: str = "/etc/nginx/.htpasswd"  # for migration — override via env
AUTH_DB_PATH: str = "/app/data/auth.db"  # default — override via env
TRUST_SECRET: str = ""  # REQUIRED — same as AUTH_SECRET

# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------
# Connection management is delegated to smart_home_common.sqlite_helpers, which
# enables WAL, commits on success, rolls back on error and ALWAYS closes the
# connection so WAL (-wal/-shm) file handles are released (prevents WinError 32
# on Windows temp-dir cleanup and state leaking between tests). The wrappers
# below keep this module's historical API and read ``AUTH_DB_PATH`` at call time
# so late injection from main.py's lifespan still takes effect.


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Create the users and trusted_devices tables if they do not exist."""
    # Users table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id            TEXT PRIMARY KEY,
            username      TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            display_name  TEXT NOT NULL DEFAULT '',
            icon          TEXT DEFAULT NULL,
            dark_mode     INTEGER NOT NULL DEFAULT 1
        )
    """)

    # Idempotent migration: add dark_mode to pre-existing user tables that were
    # created before the column existed. ``CREATE TABLE IF NOT EXISTS`` above is
    # a no-op for already-created tables, so new columns must be added here.
    cols = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    if "dark_mode" not in cols:
        conn.execute(
            "ALTER TABLE users ADD COLUMN dark_mode INTEGER NOT NULL DEFAULT 1"
        )

    # Trusted devices table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trusted_devices (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            token       TEXT    NOT NULL UNIQUE,
            username    TEXT    NOT NULL,
            user_agent  TEXT    NOT NULL DEFAULT '',
            ip_address  TEXT    NOT NULL DEFAULT '',
            requested_at REAL   NOT NULL,
            status      TEXT    NOT NULL DEFAULT 'pending',
            resolved_at  REAL
        )
    """)

    # Per-user widget (dashboard app-card) configuration.
    #
    # One row per (username, widget_id). ``position`` drives ordering,
    # ``visible`` toggles whether the widget is rendered, ``size`` is a free-form
    # size hint (e.g. "sm"/"md"/"lg") and ``custom_settings`` is an opaque JSON
    # blob so widgets can store their own options without a schema change. The
    # row is keyed by username (not the immutable user id) to match the rest of
    # this module's preference helpers (``get_user_preferences`` et al.), which
    # all key by the authenticated username.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_widget_config (
            username        TEXT    NOT NULL,
            widget_id       TEXT    NOT NULL,
            visible         INTEGER NOT NULL DEFAULT 1,
            position        INTEGER NOT NULL DEFAULT 0,
            size            TEXT    NOT NULL DEFAULT 'md',
            custom_settings TEXT    NOT NULL DEFAULT '{}',
            PRIMARY KEY (username, widget_id)
        )
    """)


def _open_db() -> sqlite3.Connection:
    """Open the auth SQLite database, creating schema on first use.

    Returns a bare connection. Prefer the :func:`_get_db` context manager,
    which guarantees the connection is committed on success and ALWAYS closed
    — leaving connections open keeps WAL (-wal/-shm) file handles alive, which
    makes temp-dir cleanup fail on Windows (WinError 32) and leaks state
    between tests.
    """
    conn = open_connection(AUTH_DB_PATH)
    _ensure_schema(conn)
    conn.commit()
    return conn


def _get_db() -> AbstractContextManager[sqlite3.Connection]:
    """Yield an auth DB connection, committing on success and always closing.

    Delegates to :func:`smart_home_common.sqlite_helpers.sqlite_connection`,
    which guarantees ``conn.close()`` in a ``finally`` block so WAL file handles
    are released (prevents WinError 32 on Windows temp-dir cleanup).
    """
    return sqlite_connection(AUTH_DB_PATH, init=_ensure_schema)


# ---------------------------------------------------------------------------
# Migration from .htpasswd
# ---------------------------------------------------------------------------


def _load_htpasswd(path: str) -> dict[str, str]:
    """Parse an .htpasswd file into {username: hash} dict."""
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
        logger.debug("htpasswd file not found: %s (may be expected)", path)
    except OSError as exc:
        logger.error("Failed to read htpasswd: %s", exc)
    return users


def _migrate_from_htpasswd():
    """Migrate users from .htpasswd file to database if not already migrated."""
    htpasswd_users = _load_htpasswd(HTPASSWD_PATH)
    if not htpasswd_users:
        return

    with _get_db() as conn:
        # Check if we already have users
        existing = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if existing > 0:
            return  # Already have users, skip migration

        logger.info(
            "Migrating %d users from .htpasswd to database", len(htpasswd_users)
        )
        for username, pw_hash in htpasswd_users.items():
            user_id = str(uuid.uuid4())
            # Use username as display_name initially
            display_name = username.capitalize()
            conn.execute(
                """
                INSERT INTO users (id, username, password_hash, display_name)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, username, pw_hash, display_name),
            )
        conn.commit()
        logger.info("Migration complete")


# ---------------------------------------------------------------------------
# User management
# ---------------------------------------------------------------------------


def get_all_users() -> list[dict]:
    """Return all users as list of dicts (without password_hash)."""
    with _get_db() as conn:
        rows = conn.execute(
            "SELECT id, username, display_name, icon FROM users ORDER BY username"
        ).fetchall()
    return [dict(row) for row in rows]


def get_user_by_id(user_id: str) -> dict | None:
    """Return user dict by ID (without password_hash), or None if not found."""
    with _get_db() as conn:
        row = conn.execute(
            "SELECT id, username, display_name, icon FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    return dict(row) if row else None


def get_user_by_username(username: str) -> dict | None:
    """Return user dict by username (without password_hash), or None."""
    with _get_db() as conn:
        row = conn.execute(
            "SELECT id, username, display_name, icon FROM users WHERE username = ?",
            (username,),
        ).fetchone()
    return dict(row) if row else None


def get_user_preferences(username: str) -> dict:
    """Return the UI preferences for a user.

    Currently only ``dark_mode`` (bool). Defaults to ``{"dark_mode": True}``
    when the user does not exist, so the dashboard always has a usable value
    (the UI is dark-first).
    """
    with _get_db() as conn:
        row = conn.execute(
            "SELECT dark_mode FROM users WHERE username = ?",
            (username,),
        ).fetchone()
    if row is None:
        return {"dark_mode": True}
    return {"dark_mode": bool(row["dark_mode"])}


def set_user_preferences(username: str, dark_mode: bool) -> None:
    """Persist a user's UI preferences (currently ``dark_mode``).

    Raises ValueError if the user does not exist.
    """
    with _get_db() as conn:
        cur = conn.execute(
            "UPDATE users SET dark_mode = ? WHERE username = ?",
            (1 if dark_mode else 0, username),
        )
        if cur.rowcount == 0:
            raise ValueError(f"User not found: {username}")
        conn.commit()


# ---------------------------------------------------------------------------
# Per-user widget configuration
# ---------------------------------------------------------------------------
# Widgets are the dashboard app-cards (keyed by their app ``key``). Each user
# can hide widgets, reorder them and attach free-form settings. The config is a
# list of rows ({widget_id, visible, order, size, custom_settings}); the client
# sends the complete desired set and we replace the user's rows atomically, so
# the stored state always mirrors the UI (no orphaned rows when a widget is
# removed from the layout).

#: Allowed values for the ``size`` hint. Anything else is rejected so a typo in
#: the client cannot silently persist an unrenderable size.
_WIDGET_SIZES = ("sm", "md", "lg")


def get_widget_config(username: str) -> list[dict]:
    """Return the saved widget configuration for a user.

    Returns a list of ``{widget_id, visible, order, size, custom_settings}``
    dicts ordered by ``order`` then ``widget_id``. An empty list means the user
    has no saved layout yet (the client then falls back to its defaults).
    """
    with _get_db() as conn:
        rows = conn.execute(
            """
            SELECT widget_id, visible, position, size, custom_settings
            FROM user_widget_config
            WHERE username = ?
            ORDER BY position, widget_id
            """,
            (username,),
        ).fetchall()

    config: list[dict] = []
    for row in rows:
        try:
            custom = json.loads(row["custom_settings"])
        except (ValueError, TypeError):
            custom = {}
        config.append(
            {
                "widget_id": row["widget_id"],
                "visible": bool(row["visible"]),
                "order": row["position"],
                "size": row["size"],
                "custom_settings": custom,
            }
        )
    return config


def set_widget_config(username: str, widgets: list[dict]) -> None:
    """Replace a user's widget configuration with ``widgets``.

    Each item must contain ``widget_id`` and may contain ``visible`` (bool),
    ``order`` (int), ``size`` (one of ``sm``/``md``/``lg``) and
    ``custom_settings`` (JSON-serialisable mapping). The whole set is replaced
    inside a single transaction so a failure never leaves a half-written layout.

    Raises:
        ValueError: if an item is missing ``widget_id`` or carries an invalid
            ``size`` or non-serialisable ``custom_settings``.
    """
    # Validate everything BEFORE touching the DB so a bad item cannot leave the
    # user with a partially cleared layout.
    normalised: list[tuple] = []
    seen: set[str] = set()
    for idx, w in enumerate(widgets):
        widget_id = w.get("widget_id")
        if not widget_id or not isinstance(widget_id, str):
            raise ValueError(f"Widget at index {idx} is missing a 'widget_id'")
        if widget_id in seen:
            raise ValueError(f"Duplicate widget_id: {widget_id!r}")
        seen.add(widget_id)

        size = w.get("size", "md")
        if size not in _WIDGET_SIZES:
            raise ValueError(
                f"Invalid size {size!r} for widget {widget_id!r} "
                f"(allowed: {', '.join(_WIDGET_SIZES)})"
            )

        # ``order`` defaults to the item's position in the submitted list so a
        # client can simply send widgets in the desired order without computing
        # indices explicitly.
        order = w.get("order", idx)
        try:
            order = int(order)
        except (ValueError, TypeError) as exc:
            raise ValueError(
                f"Invalid order {order!r} for widget {widget_id!r}"
            ) from exc

        custom = w.get("custom_settings", {})
        try:
            custom_json = json.dumps(custom)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"custom_settings for widget {widget_id!r} is not JSON-serialisable"
            ) from exc

        visible = 1 if w.get("visible", True) else 0
        normalised.append((username, widget_id, visible, order, size, custom_json))

    with _get_db() as conn:
        conn.execute("DELETE FROM user_widget_config WHERE username = ?", (username,))
        conn.executemany(
            """
            INSERT INTO user_widget_config
                (username, widget_id, visible, position, size, custom_settings)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            normalised,
        )
        conn.commit()
    logger.info("Saved %d widget(s) for user %r", len(normalised), username)


def create_user(username: str, password: str, display_name: str = "") -> str:
    """Create a new user and return their ID.

    Raises ValueError if username already exists.
    """
    user_id = str(uuid.uuid4())
    password_hash = apr_md5_crypt.hash(password)
    if not display_name:
        display_name = username.capitalize()

    with _get_db() as conn:
        try:
            conn.execute(
                """
                INSERT INTO users (id, username, password_hash, display_name)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, username, password_hash, display_name),
            )
            conn.commit()
        except sqlite3.IntegrityError as e:
            raise ValueError(f"Username '{username}' already exists") from e

    return user_id


def update_user(
    user_id: str,
    display_name: str | None = None,
    icon: str | None = None,
    password: str | None = None,
) -> None:
    """Update user fields. Only provided fields are updated.

    Note: username cannot be changed (immutable).
    Raises ValueError if user not found.
    """
    updates = []
    params = []

    if display_name is not None:
        updates.append("display_name = ?")
        params.append(display_name)

    if icon is not None:
        updates.append("icon = ?")
        params.append(icon if icon else None)

    if password is not None:
        updates.append("password_hash = ?")
        params.append(apr_md5_crypt.hash(password))

    if not updates:
        return

    params.append(user_id)
    with _get_db() as conn:
        # nosec B608 - updates list only contains hardcoded column names, not user input
        cur = conn.execute(
            f"UPDATE users SET {', '.join(updates)} WHERE id = ?",  # nosec B608
            params,
        )
        if cur.rowcount == 0:
            raise ValueError(f"User not found: {user_id}")
        conn.commit()


def delete_user(user_id: str) -> None:
    """Delete a user by ID.

    Raises ValueError if user not found.
    """
    with _get_db() as conn:
        cur = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        if cur.rowcount == 0:
            raise ValueError(f"User not found: {user_id}")
        conn.commit()


def authenticate_user(username: str, password: str) -> bool:
    """Return True if username/password match."""
    with _get_db() as conn:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE username = ?", (username,)
        ).fetchone()

    if row is None:
        # Constant-time dummy check to prevent user enumeration
        verify_password("dummy", "$apr1$dummy$dummyhashvalueforconsistency00")
        return False

    return verify_password(password, row["password_hash"])


def user_exists(username: str) -> bool:
    """Return True if the username exists in the database."""
    with _get_db() as conn:
        row = conn.execute(
            "SELECT 1 FROM users WHERE username = ?", (username,)
        ).fetchone()
    return row is not None


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


def resolve_trust_request(token: str, action: str) -> dict | None:
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


def get_trust_status(token: str) -> str | None:
    """Return the status of a trust request token, or None if not found."""
    with _get_db() as conn:
        row = conn.execute(
            "SELECT status FROM trusted_devices WHERE token = ?", (token,)
        ).fetchone()
    return row["status"] if row else None


def has_active_trust_request(username: str) -> bool:
    """Return True if the user already has a pending trust request.

    Used to avoid sending duplicate approval emails. Approved requests are
    deleted immediately when the device token is created, so we only check
    for pending ones.
    """
    with _get_db() as conn:
        row = conn.execute(
            "SELECT id FROM trusted_devices WHERE username = ? AND status = 'pending' LIMIT 1",
            (username,),
        ).fetchone()
    return row is not None


def get_approved_trust_request(username: str) -> dict | None:
    """Return the first approved (not yet consumed) trust request for a user, or None."""
    with _get_db() as conn:
        row = conn.execute(
            "SELECT * FROM trusted_devices WHERE username = ? AND status = 'approved' LIMIT 1",
            (username,),
        ).fetchone()
    return dict(row) if row else None


def delete_trust_request(token: str) -> bool:
    """Delete a trust request row by its token (consumed after device token issued).

    Returns True if the row was found and deleted.
    """
    with _get_db() as conn:
        cur = conn.execute("DELETE FROM trusted_devices WHERE token = ?", (token,))
    return cur.rowcount > 0


# ---------------------------------------------------------------------------
# HMAC-signed action tokens for email links
# ---------------------------------------------------------------------------
# The approval email contains links of the form:
#   /api/auth/trust/approve?token=<opaque_token>&sig=<hmac>
#   /api/auth/trust/reject?token=<opaque_token>&sig=<hmac>
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
    return f"{base_url}/api/auth/trust/{action}?token={token}&sig={sig}"


def verify_action_sig(token: str, action: str, sig: str) -> bool:
    """Return True if the HMAC signature is valid for (token, action)."""
    expected = _sign(token, action)
    return hmac.compare_digest(expected, sig)
