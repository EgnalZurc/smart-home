"""User profiles and app permission system for Cuchi Casa.

Profiles
--------
Each user can have MULTIPLE profiles stored in the ``user_profiles`` table.
The effective permission level is the MINIMUM (most permissive) across all profiles.

A profile defines:
- ``level`` : permission level (0-3, lower = more permissions)

Level semantics
---------------
Level 0 = SUPER — sees everything, configures everything, admin access
Level 1 = Full family access — sees all standard apps
Level 2 = Reserved for future use
Level 3 = Restricted — only specific apps (e.g., GAMER sees only Valheim)

App attributes
--------------
Every app in APP_REGISTRY carries:
- ``view_level``   : int — user needs effective_level <= view_level to see it
- ``edit_level``   : int — user needs effective_level <= edit_level to interact

Built-in profiles
-----------------
SUPER             → level 0, full admin access
FAMILIA_ALL       → level 1, sees all apps
FAMILIA_PRINCIPAL → level 1, sees all apps
GAMER             → level 3, only sees Valheim

Database
--------
Table ``user_profiles`` in auth.db:
    username TEXT NOT NULL
    profile  TEXT NOT NULL
    PRIMARY KEY (username, profile)

Table ``profiles`` in auth.db (custom profiles):
    name        TEXT PRIMARY KEY
    level       INTEGER NOT NULL
    description TEXT
"""

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration (injected from main.py lifespan)
# ---------------------------------------------------------------------------
AUTH_DB_PATH: str = "/app/data/auth.db"

# ---------------------------------------------------------------------------
# Built-in profile definitions (cannot be deleted, but level can be viewed)
# ---------------------------------------------------------------------------
BUILTIN_PROFILES: dict[str, dict] = {
    "SUPER": {
        "level": 0,
        "description": "Administrador completo — acceso total",
        "builtin": True,
    },
    "FAMILIA_ALL": {
        "level": 1,
        "description": "Familia con acceso total a apps",
        "builtin": True,
    },
    "FAMILIA_PRINCIPAL": {
        "level": 1,
        "description": "Familia estándar",
        "builtin": True,
    },
    "GAMER": {
        "level": 3,
        "description": "Jugador — solo Valheim",
        "builtin": True,
    },
}

_DEFAULT_PROFILE = "FAMILIA_PRINCIPAL"

# ---------------------------------------------------------------------------
# App registry
# ---------------------------------------------------------------------------
APP_REGISTRY: list[dict] = [
    {
        "key": "ac",
        "view_level": 1,
        "edit_level": 1,
    },
    {
        "key": "photos",
        "view_level": 1,
        "edit_level": 1,
    },
    {
        "key": "vacaciones",
        "view_level": 1,
        "edit_level": 1,
    },
    {
        "key": "casita",
        "view_level": 1,
        "edit_level": 1,
    },
    {
        "key": "zigbee",
        "view_level": 0,  # Only SUPER can see Zigbee config
        "edit_level": 0,
    },
    {
        "key": "passwords",
        "view_level": 0,  # Only SUPER can see passwords
        "edit_level": 0,
    },
    {
        "key": "babygifts",
        "view_level": 1,
        "edit_level": 1,
    },
    {
        "key": "valheim",
        "view_level": 3,  # GAMER (level 3) can see and control Valheim
        "edit_level": 3,
    },
    {
        "key": "portfolio",
        "view_level": 0,  # Only SUPER can see financial data
        "edit_level": 0,
    },
]

# External services shown in the Services modal (not in main app list)
EXTERNAL_SERVICES: list[dict] = [
    {
        "key": "ai",
        "view_level": 1,  # FAMILIA_ALL and above
        "url": "https://raspberrypi.tailaa37cd.ts.net:8443/",
        "statusUrl": "/api/health/ai",
    },
    {
        "key": "photos_ext",
        "view_level": 1,
        "url": "https://raspberrypi.tailaa37cd.ts.net:10000/",
        "statusUrl": "/api/health/immich",
    },
    {
        "key": "passwords_ext",
        "view_level": 0,  # Only SUPER
        "url": "/passwords/",
        "statusUrl": "/api/health/passwords",
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
    
    # User-profile assignments (many-to-many)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_profiles (
            username TEXT NOT NULL,
            profile  TEXT NOT NULL,
            PRIMARY KEY (username, profile)
        )
    """)
    
    # Custom profiles (beyond built-ins)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS profiles (
            name        TEXT PRIMARY KEY,
            level       INTEGER NOT NULL,
            description TEXT DEFAULT ''
        )
    """)
    
    conn.commit()
    return conn


def _migrate_old_schema():
    """Migrate from old single-profile schema if needed."""
    with _db() as conn:
        # Check if old schema exists (single profile column)
        cursor = conn.execute("PRAGMA table_info(user_profiles)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if "profile" in columns and len(columns) == 2:
            # Old schema detected, check if it's the old format
            try:
                # Try to read old data
                old_data = conn.execute(
                    "SELECT username, profile FROM user_profiles"
                ).fetchall()
                
                if old_data:
                    # Backup and recreate
                    conn.execute("ALTER TABLE user_profiles RENAME TO user_profiles_old")
                    conn.execute("""
                        CREATE TABLE user_profiles (
                            username TEXT NOT NULL,
                            profile  TEXT NOT NULL,
                            PRIMARY KEY (username, profile)
                        )
                    """)
                    # Migrate data
                    for row in old_data:
                        conn.execute(
                            "INSERT OR IGNORE INTO user_profiles (username, profile) VALUES (?, ?)",
                            (row[0], row[1])
                        )
                    conn.execute("DROP TABLE user_profiles_old")
                    conn.commit()
                    logger.info("Migrated %d users to new multi-profile schema", len(old_data))
            except Exception as e:
                logger.warning("Migration check failed (may be already migrated): %s", e)


# Run migration on module load
try:
    _migrate_old_schema()
except Exception as e:
    logger.warning("Profile migration failed: %s", e)


# ---------------------------------------------------------------------------
# Profile management
# ---------------------------------------------------------------------------
def get_all_profiles() -> dict[str, dict]:
    """Return all profiles (built-in + custom) as {name: {level, description, builtin}}."""
    result = dict(BUILTIN_PROFILES)
    
    with _db() as conn:
        rows = conn.execute("SELECT name, level, description FROM profiles").fetchall()
        for row in rows:
            result[row["name"]] = {
                "level": row["level"],
                "description": row["description"] or "",
                "builtin": False,
            }
    
    return result


def create_profile(name: str, level: int, description: str = "") -> None:
    """Create a new custom profile."""
    if name in BUILTIN_PROFILES:
        raise ValueError(f"Cannot create profile with built-in name: {name}")
    if not 0 <= level <= 3:
        raise ValueError(f"Level must be 0-3, got {level}")
    
    with _db() as conn:
        conn.execute(
            "INSERT INTO profiles (name, level, description) VALUES (?, ?, ?)",
            (name, level, description)
        )
    logger.info("Created profile %r with level %d", name, level)


def update_profile(name: str, level: int = None, description: str = None) -> None:
    """Update a custom profile. Cannot modify built-in profiles."""
    if name in BUILTIN_PROFILES:
        raise ValueError(f"Cannot modify built-in profile: {name}")
    
    with _db() as conn:
        if level is not None:
            if not 0 <= level <= 3:
                raise ValueError(f"Level must be 0-3, got {level}")
            conn.execute("UPDATE profiles SET level = ? WHERE name = ?", (level, name))
        if description is not None:
            conn.execute("UPDATE profiles SET description = ? WHERE name = ?", (description, name))
    logger.info("Updated profile %r", name)


def delete_profile(name: str) -> None:
    """Delete a custom profile. Cannot delete built-in profiles."""
    if name in BUILTIN_PROFILES:
        raise ValueError(f"Cannot delete built-in profile: {name}")
    
    with _db() as conn:
        # Remove from users first
        conn.execute("DELETE FROM user_profiles WHERE profile = ?", (name,))
        conn.execute("DELETE FROM profiles WHERE name = ?", (name,))
    logger.info("Deleted profile %r", name)


# ---------------------------------------------------------------------------
# User-profile assignment
# ---------------------------------------------------------------------------
def get_user_profiles(username: str) -> list[str]:
    """Return list of profile names assigned to a user."""
    with _db() as conn:
        rows = conn.execute(
            "SELECT profile FROM user_profiles WHERE username = ?", (username,)
        ).fetchall()
    
    profiles = [row["profile"] for row in rows]
    return profiles if profiles else [_DEFAULT_PROFILE]


def set_user_profiles(username: str, profiles: list[str]) -> None:
    """Set the profiles for a user (replaces existing assignments)."""
    all_profiles = get_all_profiles()
    for p in profiles:
        if p not in all_profiles:
            raise ValueError(f"Unknown profile: {p}")
    
    with _db() as conn:
        conn.execute("DELETE FROM user_profiles WHERE username = ?", (username,))
        for p in profiles:
            conn.execute(
                "INSERT INTO user_profiles (username, profile) VALUES (?, ?)",
                (username, p)
            )
    logger.info("Assigned profiles %r to user %r", profiles, username)


def add_user_profile(username: str, profile: str) -> None:
    """Add a profile to a user (keeps existing profiles)."""
    all_profiles = get_all_profiles()
    if profile not in all_profiles:
        raise ValueError(f"Unknown profile: {profile}")
    
    with _db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO user_profiles (username, profile) VALUES (?, ?)",
            (username, profile)
        )
    logger.info("Added profile %r to user %r", profile, username)


def remove_user_profile(username: str, profile: str) -> None:
    """Remove a profile from a user."""
    with _db() as conn:
        conn.execute(
            "DELETE FROM user_profiles WHERE username = ? AND profile = ?",
            (username, profile)
        )
    logger.info("Removed profile %r from user %r", profile, username)


# ---------------------------------------------------------------------------
# Effective permissions
# ---------------------------------------------------------------------------
def get_effective_level(username: str) -> int:
    """Return the effective permission level for a user.
    
    This is the MINIMUM level across all assigned profiles (lower = more permissions).
    """
    profiles = get_user_profiles(username)
    all_profiles = get_all_profiles()
    
    levels = []
    for p in profiles:
        if p in all_profiles:
            levels.append(all_profiles[p]["level"])
    
    return min(levels) if levels else all_profiles[_DEFAULT_PROFILE]["level"]


def is_super(username: str) -> bool:
    """Return True if user has level 0 (SUPER/admin) access."""
    return get_effective_level(username) == 0


# ---------------------------------------------------------------------------
# Legacy compatibility + new API
# ---------------------------------------------------------------------------
def get_profile(username: str) -> dict:
    """Return a profile-like dict for compatibility.

    Returns the effective level and computed permissions.
    """
    level = get_effective_level(username)
    return {
        "level": level,
        "can_view_level": level,
        "can_edit_level": level,
        "show_config_apps": level == 0,  # Only level 0 can configure
    }


def get_profile_key(username: str) -> str:
    """Return the primary profile key for a user (first assigned or default)."""
    profiles = get_user_profiles(username)
    return profiles[0] if profiles else _DEFAULT_PROFILE


def set_profile(username: str, profile_key: str) -> None:
    """Legacy: Set a single profile for a user (replaces all)."""
    set_user_profiles(username, [profile_key])


# Expose PROFILES for backward compatibility
PROFILES = BUILTIN_PROFILES


def visible_app_keys(username: str) -> list[str]:
    """Return the list of app keys visible to a user, in registry order."""
    level = get_effective_level(username)
    return [app["key"] for app in APP_REGISTRY if level <= app["view_level"]]


def app_permissions(username: str) -> list[dict]:
    """Return visible apps with their resolved permissions for the user."""
    level = get_effective_level(username)
    result = []
    for app in APP_REGISTRY:
        if level <= app["view_level"]:
            result.append(
                {
                    "key": app["key"],
                    "can_edit": level <= app["edit_level"],
                }
            )
    return result


def visible_external_services(username: str) -> list[dict]:
    """Return external services visible to a user."""
    level = get_effective_level(username)
    return [svc for svc in EXTERNAL_SERVICES if level <= svc["view_level"]]
