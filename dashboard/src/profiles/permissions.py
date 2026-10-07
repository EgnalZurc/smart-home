"""Permission logic for the profile system.

This module handles permission calculations and app visibility:
- Effective level calculation
- App permission checks
- User info aggregation
"""

from .constants import APP_REGISTRY, DEFAULT_PROFILE_ID, EXTERNAL_SERVICES
from .db import get_all_profiles, get_user_profiles


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
        default = all_profiles.get(DEFAULT_PROFILE_ID)
        return default["level"] if default else 1

    return min(levels)


def is_super(username: str) -> bool:
    """Return True if user has level 0 (SUPER/admin) access."""
    return get_effective_level(username) == 0


# ---------------------------------------------------------------------------
# App permissions
# ---------------------------------------------------------------------------
def _can_view(user_level: int, item: dict) -> bool:
    """Check if a user can view an app/service.

    - SUPER (level 0) sees everything
    - Others see items where min_level <= their level <= max_level
    """
    if user_level == 0:
        return True
    min_lvl = item.get("min_level", 0)
    max_lvl = item.get("max_level", 3)
    return min_lvl <= user_level <= max_lvl


def app_permissions(username: str) -> list[dict]:
    """Return visible apps with their resolved permissions for the user."""
    level = get_effective_level(username)
    result = []
    for app in APP_REGISTRY:
        if _can_view(level, app):
            result.append(
                {
                    "key": app["key"],
                    "can_edit": _can_view(level, app),  # Same as view for now
                }
            )
    return result


def visible_external_services(username: str) -> list[dict]:
    """Return external services visible to a user."""
    level = get_effective_level(username)
    return [svc for svc in EXTERNAL_SERVICES if _can_view(level, svc)]


# ---------------------------------------------------------------------------
# User info aggregation
# ---------------------------------------------------------------------------
def get_user_profiles_detailed(username: str) -> list[dict]:
    """Return list of full profile objects for a user."""
    profile_ids = get_user_profiles(username)
    all_profiles = get_all_profiles()
    return [
        {"id": pid, **all_profiles[pid]} for pid in profile_ids if pid in all_profiles
    ]


def get_user_info(username: str) -> dict:
    """Get complete user info for API responses."""
    profiles = get_user_profiles_detailed(username)
    effective_level = get_effective_level(username)

    # Build app permissions based on effective level
    apps = [
        {"key": app["key"], "can_view": _can_view(effective_level, app)}
        for app in APP_REGISTRY
        if _can_view(effective_level, app)
    ]

    # External services
    external = [svc for svc in EXTERNAL_SERVICES if _can_view(effective_level, svc)]

    return {
        "username": username,
        "profiles": profiles,
        "effective_level": effective_level,
        "is_admin": effective_level == 0,
        "apps": apps,
        "external_services": external,
    }


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
