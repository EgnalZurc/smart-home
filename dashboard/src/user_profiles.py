"""User profiles and app permission system for Cuchi Casa.

Profiles
--------
Each profile has an immutable ID (UUID) that is used for all references.
The name and description are editable (except for SUPER which is fully protected).

Profile attributes:
- ``id``          : UUID, immutable, primary key
- ``name``        : display name, editable
- ``level``       : permission level (0-3), editable
- ``description`` : description text, editable

Level semantics
---------------
Level 0 = SUPER — sees everything, configures everything, admin access
Level 1 = Full family access — sees all standard apps
Level 2 = Reserved for future use
Level 3 = Restricted — only specific apps (e.g., GAMER sees only Valheim)

Database
--------
Table ``profiles`` in auth.db:
    id          TEXT PRIMARY KEY (UUID)
    name        TEXT NOT NULL UNIQUE
    level       INTEGER NOT NULL
    description TEXT DEFAULT ''
    protected   INTEGER DEFAULT 0 (1 = cannot edit/delete)

Table ``user_profiles`` in auth.db:
    username   TEXT NOT NULL
    profile_id TEXT NOT NULL (references profiles.id)
    PRIMARY KEY (username, profile_id)
"""

import logging
import sqlite3
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration (injected from main.py lifespan)
# ---------------------------------------------------------------------------
AUTH_DB_PATH: str = "/app/data/auth.db"

# ---------------------------------------------------------------------------
# Built-in profile definitions with fixed UUIDs
# These are seeded into the database on first run
# ---------------------------------------------------------------------------
BUILTIN_PROFILES: dict[str, dict] = {
    "super-0000-0000-0000-000000000000": {
        "name": "SUPER",
        "level": 0,
        "description": "Administrador completo — acceso total",
        "protected": True,  # Cannot be edited or deleted
    },
    "familia-all-0000-0000-000000000001": {
        "name": "FAMILIA_ALL",
        "level": 1,
        "description": "Familia con acceso total a apps",
        "protected": False,
    },
    "familia-principal-0000-000000000002": {
        "name": "FAMILIA_PRINCIPAL",
        "level": 1,
        "description": "Familia estándar",
        "protected": False,
    },
    "gamer-0000-0000-0000-000000000003": {
        "name": "GAMER",
        "level": 3,
        "description": "Jugador — solo Valheim",
        "protected": False,
    },
}

# Default profile ID for new users
_DEFAULT_PROFILE_ID = "familia-principal-0000-000000000002"

# Quick lookup: name -> id for built-ins
_BUILTIN_NAME_TO_ID = {p["name"]: pid for pid, p in BUILTIN_PROFILES.items()}

# ---------------------------------------------------------------------------
# App registry
# ---------------------------------------------------------------------------
APP_REGISTRY: list[dict] = [
    {"key": "ac", "view_level": 1, "edit_level": 1},
    {"key": "photos", "view_level": 1, "edit_level": 1},
    {"key": "vacaciones", "view_level": 1, "edit_level": 1},
    {"key": "casita", "view_level": 1, "edit_level": 1},
    {"key": "zigbee", "view_level": 0, "edit_level": 0},
    {"key": "passwords", "view_level": 0, "edit_level": 0},
    {"key": "babygifts", "view_level": 1, "edit_level": 1},
    {"key": "valheim", "view_level": 3, "edit_level": 3},
    {"key": "portfolio", "view_level": 0, "edit_level": 0},
]

EXTERNAL_SERVICES: list[dict] = [
    {
        "key": "ai",
        "view_level": 1,
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
        "view_level": 0,
        "url": "/passwords/",
        "statusUrl": "/api/health/passwords",
    },
]


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------
def _raw_db() -> sqlite3.Connection:
    """Get raw DB connection without schema creation (for migrations)."""
    db_path = Path(AUTH_DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _db() -> sqlite3.Connection:
    """Get DB connection, creating tables if needed."""
    conn = _raw_db()

    # Profiles table with UUID primary key
    conn.execute("""
        CREATE TABLE IF NOT EXISTS profiles (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL UNIQUE,
            level       INTEGER NOT NULL,
            description TEXT DEFAULT '',
            protected   INTEGER DEFAULT 0
        )
    """)

    # User-profile assignments using profile_id
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_profiles (
            username   TEXT NOT NULL,
            profile_id TEXT NOT NULL,
            PRIMARY KEY (username, profile_id)
        )
    """)

    conn.commit()
    return conn


def _migrate_profiles_table():
    """Migrate profiles table from old schema (name PK) to new schema (id PK)."""
    with _raw_db() as conn:
        # Check if profiles table exists
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='profiles'"
        )
        if not cursor.fetchone():
            return  # Table doesn't exist, nothing to migrate

        # Check if it has the old schema (name as PK, no id column)
        cursor = conn.execute("PRAGMA table_info(profiles)")
        columns = {row[1]: row for row in cursor.fetchall()}

        if "id" in columns:
            return  # Already has new schema

        logger.info("Migrating profiles table from name-based to ID-based schema")

        # Old schema variations:
        # - Variant A: name (PK), level, description, builtin
        # - Variant B: name (PK), level, description (no builtin column)
        # New schema: id (PK), name (UNIQUE), level, description, protected

        has_builtin = "builtin" in columns

        # Save old data
        if has_builtin:
            old_profiles = conn.execute(
                "SELECT name, level, description, builtin FROM profiles"
            ).fetchall()
        else:
            old_profiles = conn.execute(
                "SELECT name, level, description FROM profiles"
            ).fetchall()

        # Drop old table
        conn.execute("DROP TABLE profiles")

        # Create new table
        conn.execute("""
            CREATE TABLE profiles (
                id          TEXT PRIMARY KEY,
                name        TEXT NOT NULL UNIQUE,
                level       INTEGER NOT NULL,
                description TEXT DEFAULT '',
                protected   INTEGER DEFAULT 0
            )
        """)

        # Migrate data - convert names to IDs
        for row in old_profiles:
            if has_builtin:
                name, level, description, _builtin = row
            else:
                name, level, description = row

            # Find ID for builtin profiles
            profile_id = _BUILTIN_NAME_TO_ID.get(name)
            if profile_id:
                # Builtin profile - use known ID and protected flag from definition
                protected = 1 if BUILTIN_PROFILES[profile_id]["protected"] else 0
            else:
                # Custom profile - generate new UUID
                profile_id = str(uuid.uuid4())
                protected = 0

            conn.execute(
                """
                INSERT OR IGNORE INTO profiles (id, name, level, description, protected)
                VALUES (?, ?, ?, ?, ?)
                """,
                (profile_id, name, level, description or "", protected),
            )

        conn.commit()
        logger.info("Migrated %d profiles to ID-based schema", len(old_profiles))


def _migrate_user_profiles_table():
    """Migrate user_profiles table from name-based to ID-based."""
    with _raw_db() as conn:
        # Check if user_profiles table exists
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='user_profiles'"
        )
        if not cursor.fetchone():
            return  # Table doesn't exist, nothing to migrate

        # Check if it has old schema (profile column instead of profile_id)
        cursor = conn.execute("PRAGMA table_info(user_profiles)")
        columns = {row[1] for row in cursor.fetchall()}

        if "profile_id" in columns:
            return  # Already has new schema

        if "profile" not in columns:
            return  # Unknown schema

        logger.info("Migrating user_profiles from name-based to ID-based schema")

        # Get old assignments
        old_data = conn.execute(
            "SELECT username, profile FROM user_profiles"
        ).fetchall()

        # Drop and recreate table
        conn.execute("DROP TABLE user_profiles")
        conn.execute("""
            CREATE TABLE user_profiles (
                username   TEXT NOT NULL,
                profile_id TEXT NOT NULL,
                PRIMARY KEY (username, profile_id)
            )
        """)

        # Migrate data - convert names to IDs
        for row in old_data:
            username, profile_name = row
            # Find profile ID by name
            profile_id = _BUILTIN_NAME_TO_ID.get(profile_name)
            if not profile_id:
                # Check custom profiles in DB
                result = conn.execute(
                    "SELECT id FROM profiles WHERE name = ?", (profile_name,)
                ).fetchone()
                if result:
                    profile_id = result[0]
                else:
                    # Unknown profile, use default
                    profile_id = _DEFAULT_PROFILE_ID
                    logger.warning(
                        "Unknown profile %r for user %r, using default",
                        profile_name,
                        username,
                    )

            conn.execute(
                "INSERT OR IGNORE INTO user_profiles (username, profile_id) VALUES (?, ?)",
                (username, profile_id),
            )

        conn.commit()
        logger.info("Migrated %d user-profile assignments", len(old_data))


def _ensure_builtin_profiles():
    """Seed built-in profiles into database if not present."""
    with _db() as conn:
        for profile_id, profile in BUILTIN_PROFILES.items():
            conn.execute(
                """
                INSERT OR IGNORE INTO profiles (id, name, level, description, protected)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    profile_id,
                    profile["name"],
                    profile["level"],
                    profile["description"],
                    1 if profile["protected"] else 0,
                ),
            )
        conn.commit()


# Run migrations on module load
try:
    # Migrations must run BEFORE _db() creates tables with new schema
    _migrate_profiles_table()
    _migrate_user_profiles_table()
    # Now seed builtin profiles
    _ensure_builtin_profiles()
except Exception as e:
    logger.warning("Profile initialization failed: %s", e)


# ---------------------------------------------------------------------------
# Profile management
# ---------------------------------------------------------------------------
def get_all_profiles() -> dict[str, dict]:
    """Return all profiles as {id: {name, level, description, protected}}."""
    with _db() as conn:
        rows = conn.execute(
            "SELECT id, name, level, description, protected FROM profiles"
        ).fetchall()

    return {
        row["id"]: {
            "name": row["name"],
            "level": row["level"],
            "description": row["description"] or "",
            "protected": bool(row["protected"]),
        }
        for row in rows
    }


def get_profile_by_id(profile_id: str) -> dict | None:
    """Get a single profile by ID."""
    with _db() as conn:
        row = conn.execute(
            "SELECT id, name, level, description, protected FROM profiles WHERE id = ?",
            (profile_id,),
        ).fetchone()

    if not row:
        return None

    return {
        "id": row["id"],
        "name": row["name"],
        "level": row["level"],
        "description": row["description"] or "",
        "protected": bool(row["protected"]),
    }


def get_profile_by_name(name: str) -> dict | None:
    """Get a single profile by name."""
    with _db() as conn:
        row = conn.execute(
            "SELECT id, name, level, description, protected FROM profiles WHERE name = ?",
            (name,),
        ).fetchone()

    if not row:
        return None

    return {
        "id": row["id"],
        "name": row["name"],
        "level": row["level"],
        "description": row["description"] or "",
        "protected": bool(row["protected"]),
    }


def create_profile(name: str, level: int, description: str = "") -> str:
    """Create a new custom profile. Returns the new profile ID."""
    if not 0 <= level <= 3:
        raise ValueError(f"Level must be 0-3, got {level}")

    # Check name doesn't exist
    if get_profile_by_name(name):
        raise ValueError(f"Profile name already exists: {name}")

    profile_id = str(uuid.uuid4())

    with _db() as conn:
        conn.execute(
            "INSERT INTO profiles (id, name, level, description, protected) VALUES (?, ?, ?, ?, 0)",
            (profile_id, name, level, description),
        )

    logger.info("Created profile %r (id=%s) with level %d", name, profile_id, level)
    return profile_id


def update_profile(
    profile_id: str,
    name: str | None = None,
    level: int | None = None,
    description: str | None = None,
) -> None:
    """Update a profile. Cannot modify protected profiles (only SUPER)."""
    profile = get_profile_by_id(profile_id)
    if not profile:
        raise ValueError(f"Profile not found: {profile_id}")

    if profile["protected"]:
        raise ValueError(f"Cannot modify protected profile: {profile['name']}")

    with _db() as conn:
        if name is not None:
            # Check name doesn't conflict
            existing = get_profile_by_name(name)
            if existing and existing["id"] != profile_id:
                raise ValueError(f"Profile name already exists: {name}")
            conn.execute(
                "UPDATE profiles SET name = ? WHERE id = ?", (name, profile_id)
            )

        if level is not None:
            if not 0 <= level <= 3:
                raise ValueError(f"Level must be 0-3, got {level}")
            conn.execute(
                "UPDATE profiles SET level = ? WHERE id = ?", (level, profile_id)
            )

        if description is not None:
            conn.execute(
                "UPDATE profiles SET description = ? WHERE id = ?",
                (description, profile_id),
            )

    logger.info("Updated profile %s", profile_id)


def delete_profile(profile_id: str) -> None:
    """Delete a profile. Cannot delete protected profiles."""
    profile = get_profile_by_id(profile_id)
    if not profile:
        raise ValueError(f"Profile not found: {profile_id}")

    if profile["protected"]:
        raise ValueError(f"Cannot delete protected profile: {profile['name']}")

    # Check if it's a built-in profile (even if not protected, we don't delete built-ins)
    if profile_id in BUILTIN_PROFILES:
        raise ValueError(f"Cannot delete built-in profile: {profile['name']}")

    with _db() as conn:
        # Remove from users first
        conn.execute("DELETE FROM user_profiles WHERE profile_id = ?", (profile_id,))
        conn.execute("DELETE FROM profiles WHERE id = ?", (profile_id,))

    logger.info("Deleted profile %s (%s)", profile_id, profile["name"])


# ---------------------------------------------------------------------------
# User-profile assignment
# ---------------------------------------------------------------------------
def get_user_profiles(username: str) -> list[str]:
    """Return list of profile IDs assigned to a user."""
    with _db() as conn:
        rows = conn.execute(
            "SELECT profile_id FROM user_profiles WHERE username = ?", (username,)
        ).fetchall()

    profile_ids = [row["profile_id"] for row in rows]
    return profile_ids if profile_ids else [_DEFAULT_PROFILE_ID]


def get_user_profiles_detailed(username: str) -> list[dict]:
    """Return list of full profile objects for a user."""
    profile_ids = get_user_profiles(username)
    all_profiles = get_all_profiles()
    return [
        {"id": pid, **all_profiles[pid]} for pid in profile_ids if pid in all_profiles
    ]


def set_user_profiles(username: str, profile_ids: list[str]) -> None:
    """Set the profiles for a user (replaces existing assignments)."""
    all_profiles = get_all_profiles()
    for pid in profile_ids:
        if pid not in all_profiles:
            raise ValueError(f"Unknown profile ID: {pid}")

    with _db() as conn:
        conn.execute("DELETE FROM user_profiles WHERE username = ?", (username,))
        for pid in profile_ids:
            conn.execute(
                "INSERT INTO user_profiles (username, profile_id) VALUES (?, ?)",
                (username, pid),
            )

    logger.info("Assigned profiles %r to user %r", profile_ids, username)


def add_user_profile(username: str, profile_id: str) -> None:
    """Add a profile to a user (keeps existing profiles)."""
    all_profiles = get_all_profiles()
    if profile_id not in all_profiles:
        raise ValueError(f"Unknown profile ID: {profile_id}")

    with _db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO user_profiles (username, profile_id) VALUES (?, ?)",
            (username, profile_id),
        )

    logger.info("Added profile %r to user %r", profile_id, username)


def remove_user_profile(username: str, profile_id: str) -> None:
    """Remove a profile from a user."""
    with _db() as conn:
        conn.execute(
            "DELETE FROM user_profiles WHERE username = ? AND profile_id = ?",
            (username, profile_id),
        )

    logger.info("Removed profile %r from user %r", profile_id, username)


# ---------------------------------------------------------------------------
# Effective permissions
# ---------------------------------------------------------------------------
def get_effective_level(username: str) -> int:
    """Return the effective permission level for a user.

    This is the MINIMUM level across all assigned profiles (lower = more permissions).
    """
    profile_ids = get_user_profiles(username)
    all_profiles = get_all_profiles()

    levels = []
    for pid in profile_ids:
        if pid in all_profiles:
            levels.append(all_profiles[pid]["level"])

    if not levels:
        # Fallback to default profile level
        default = all_profiles.get(_DEFAULT_PROFILE_ID)
        return default["level"] if default else 1

    return min(levels)


def is_super(username: str) -> bool:
    """Return True if user has level 0 (SUPER/admin) access."""
    return get_effective_level(username) == 0


# ---------------------------------------------------------------------------
# Legacy compatibility
# ---------------------------------------------------------------------------
def get_profile_key(username: str) -> str:
    """Return the primary profile name for a user (legacy compatibility)."""
    profile_ids = get_user_profiles(username)
    all_profiles = get_all_profiles()

    if profile_ids and profile_ids[0] in all_profiles:
        return all_profiles[profile_ids[0]]["name"]

    return "FAMILIA_PRINCIPAL"


def get_profile(username: str) -> dict:
    """Return a profile-like dict for compatibility."""
    level = get_effective_level(username)
    return {
        "level": level,
        "can_view_level": level,
        "can_edit_level": level,
        "show_config_apps": level == 0,
    }


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------
def get_user_info(username: str) -> dict:
    """Get complete user info for API responses."""
    profiles = get_user_profiles_detailed(username)
    effective_level = get_effective_level(username)

    # Build app permissions based on effective level
    apps = [
        {"key": app["key"], "can_view": effective_level <= app["view_level"]}
        for app in APP_REGISTRY
        if effective_level <= app["view_level"]
    ]

    # External services
    external = [
        svc for svc in EXTERNAL_SERVICES if effective_level <= svc["view_level"]
    ]

    return {
        "username": username,
        "profiles": profiles,
        "effective_level": effective_level,
        "is_admin": effective_level == 0,
        "apps": apps,
        "external_services": external,
    }


# ---------------------------------------------------------------------------
# App permissions helpers (used by /api/me)
# ---------------------------------------------------------------------------
def app_permissions(username: str) -> list[dict]:
    """Return visible apps with their resolved permissions for the user."""
    level = get_effective_level(username)
    result = []
    for app in APP_REGISTRY:
        if level <= app["view_level"]:
            result.append(
                {
                    "key": app["key"],
                    "can_edit": level <= app.get("edit_level", app["view_level"]),
                }
            )
    return result


def visible_external_services(username: str) -> list[dict]:
    """Return external services visible to a user."""
    level = get_effective_level(username)
    return [svc for svc in EXTERNAL_SERVICES if level <= svc["view_level"]]
