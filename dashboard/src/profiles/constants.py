"""Profile constants and application registry.

This module contains all constant definitions for the profile system:
- Built-in profile definitions
- App registry
- External services configuration
"""

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
DEFAULT_PROFILE_ID = "familia-principal-0000-000000000002"

# Quick lookup: name -> id for built-ins
BUILTIN_NAME_TO_ID = {p["name"]: pid for pid, p in BUILTIN_PROFILES.items()}

# ---------------------------------------------------------------------------
# App registry
# ---------------------------------------------------------------------------
APP_REGISTRY: list[dict] = [
    {"key": "ac", "min_level": 0, "max_level": 1},
    {"key": "photos", "min_level": 0, "max_level": 1},
    {"key": "vacaciones", "min_level": 0, "max_level": 1},
    {"key": "casita", "min_level": 0, "max_level": 1},
    {"key": "zigbee", "min_level": 0, "max_level": 0},  # SUPER only
    {"key": "passwords", "min_level": 0, "max_level": 0},  # SUPER only
    {"key": "babygifts", "min_level": 0, "max_level": 1},
    {"key": "valheim", "min_level": 3, "max_level": 3},  # GAMER only (and SUPER)
    {"key": "portfolio", "min_level": 0, "max_level": 0},  # SUPER only
]

# ---------------------------------------------------------------------------
# External services configuration
# ---------------------------------------------------------------------------
EXTERNAL_SERVICES: list[dict] = [
    {
        "key": "ai",
        "min_level": 0,
        "max_level": 1,
        "url": "https://raspberrypi.tailaa37cd.ts.net:8443/",
        "statusUrl": "/api/health/ai",
    },
    {
        "key": "photos_ext",
        "min_level": 0,
        "max_level": 1,
        "url": "https://raspberrypi.tailaa37cd.ts.net:10000/",
        "statusUrl": "/api/health/immich",
    },
    {
        "key": "passwords_ext",
        "min_level": 0,
        "max_level": 0,  # SUPER only
        "url": "/passwords/",
        "statusUrl": "/api/health/passwords",
    },
]
