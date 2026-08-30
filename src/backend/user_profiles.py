"""User profiles and app permission system for Cuchi Casa.

Profiles
--------
Each user has a profile stored in the ``user_profiles`` table of auth.db.
A profile defines:

- ``can_view_level``   : max app view_level the user can see  (int, lower = more restrictive)
- ``can_edit_level``   : max app edit_level the user can use  (int, lower = more restrictive)
- ``show_config_apps`` : whether config-type apps are listed in the dashboard (bool)

App attributes
--------------
Every app in APP_REGISTRY carries:

- ``type``         : "standard" | "config"   — config apps are hidden from restricted profiles
- ``view_level``   : int — user needs can_view_level <= view_level to see it
- ``edit_level``   : int — user needs can_edit_level <= edit_level to interact

Level semantics
---------------
Level 1 = highest permission required (only power users).
Higher numbers = less permission needed (more users can access).
Example: an app with view_level=5 is visible even to guests; view_level=1 requires a power user.

Built-in profiles
-----------------
SUPER          → sees and does everything (both types, all levels)
FAMILIA_PRINCIPAL → standard apps only, levels 1+ (sees all current apps, full edit)

Database
--------
Table ``user_profiles`` in auth.db:
    username TEXT PRIMARY KEY
    profile  TEXT NOT NULL  -- profile key, e.g. "SUPER" or "FAMILIA_PRINCIPAL"
"""
import logging
import sqlite3
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration (injected from main.py lifespan)
# ---------------------------------------------------------------------------
AUTH_DB_PATH: str = "/app/data/auth.db"


# ---------------------------------------------------------------------------
# Profile definitions
# ---------------------------------------------------------------------------

PROFILES: dict[str, dict] = {
    "SUPER": {
        "can_view_level": 1,
        "can_edit_level": 1,
        "show_config_apps": True,
    },
    "FAMILIA_PRINCIPAL": {
        "can_view_level": 1,
        "can_edit_level": 1,
        "show_config_apps": False,
    },
}

_DEFAULT_PROFILE = "FAMILIA_PRINCIPAL"


# ---------------------------------------------------------------------------
# App registry
# ---------------------------------------------------------------------------

APP_REGISTRY: list[dict] = [
    {
        "key": "ac",
        "type": "standard",
        "view_level": 1,
        "edit_level": 1,
    },
    {
        "key": "photos",
        "type": "standard",
        "view_level": 1,
        "edit_level": 1,
    },
    {
        "key": "vacaciones",
        "type": "standard",
        "view_level": 1,
        "edit_level": 1,
    },
    {
        "key": "casita",
        "type": "standard",
        "view_level": 1,
        "edit_level": 1,
    },
    {
        "key": "zigbee",
        "type": "config",
        "view_level": 1,
        "edit_level": 1,
    },
]


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def _db() -> sqlite3.Connection:
    db_path = Path(AUTH_DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_profiles (
            username TEXT PRIMARY KEY,
            profile  TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_profile(username: str) -> dict:
    """Return the profile dict for a user. Falls back to _DEFAULT_PROFILE."""
    with _db() as conn:
        row = conn.execute(
            "SELECT profile FROM user_profiles WHERE username = ?", (username,)
        ).fetchone()
    key = row["profile"] if row else _DEFAULT_PROFILE
    return PROFILES.get(key, PROFILES[_DEFAULT_PROFILE])


def get_profile_key(username: str) -> str:
    """Return the profile key string for a user."""
    with _db() as conn:
        row = conn.execute(
            "SELECT profile FROM user_profiles WHERE username = ?", (username,)
        ).fetchone()
    return row["profile"] if row else _DEFAULT_PROFILE


def set_profile(username: str, profile_key: str) -> None:
    """Assign a profile to a user. Raises ValueError for unknown profiles."""
    if profile_key not in PROFILES:
        raise ValueError(f"Unknown profile: {profile_key!r}")
    with _db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO user_profiles (username, profile) VALUES (?, ?)",
            (username, profile_key),
        )
    logger.info("Profile %r assigned to user %r", profile_key, username)


def visible_app_keys(username: str) -> list[str]:
    """Return the list of app keys visible to a user, in registry order."""
    profile = get_profile(username)
    return [
        app["key"]
        for app in APP_REGISTRY
        if _can_view(app, profile)
    ]


def app_permissions(username: str) -> list[dict]:
    """Return visible apps with their resolved permissions for the user.

    Each entry: {"key": str, "type": str, "can_edit": bool}
    """
    profile = get_profile(username)
    result = []
    for app in APP_REGISTRY:
        if not _can_view(app, profile):
            continue
        result.append({
            "key": app["key"],
            "type": app["type"],
            "can_edit": profile["can_edit_level"] <= app["edit_level"],
        })
    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _can_view(app: dict, profile: dict) -> bool:
    if app["type"] == "config" and not profile["show_config_apps"]:
        return False
    return profile["can_view_level"] <= app["view_level"]
