"""Admin API endpoints for user and profile management.

These endpoints are only accessible to users with SUPER (level 0) access.
Extracted from auth_routes.py for better separation of concerns.
"""

import logging

import auth as auth_core
import auth_users
import user_profiles
from fastapi import APIRouter, HTTPException, Request

from api.auth_helpers import require_super

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth/admin", tags=["Admin"])


# ── User Management ──────────────────────────────────────────────────────────


@router.get("/users")
async def list_users(request: Request):
    """List all users with their assigned profiles.

    Returns: [{"id": str, "username": str, "display_name": str, "icon": str|null,
               "profiles": [{id, name, level, ...}], "effective_level": int}, ...]
    """
    require_super(request)
    users = auth_users.get_all_users()
    result = []
    for user in users:
        profiles = user_profiles.get_user_profiles_detailed(user["username"])
        effective_level = user_profiles.get_effective_level(user["username"])
        result.append(
            {
                "id": user["id"],
                "username": user["username"],
                "display_name": user["display_name"],
                "icon": user["icon"],
                "profiles": profiles,
                "effective_level": effective_level,
            }
        )
    return result


@router.post("/users")
async def create_user_endpoint(request: Request):
    """Create a new user.

    Body: {"username": str, "password": str, "display_name": str (optional)}
    Returns: {"id": str, "username": str, "display_name": str, "icon": null}
    """
    require_super(request)

    body = await request.json()
    username = body.get("username", "").strip().lower()
    password = body.get("password", "")
    display_name = body.get("display_name", "").strip()

    if not username:
        raise HTTPException(status_code=400, detail="Username required")
    if not password:
        raise HTTPException(status_code=400, detail="Password required")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password too short (min 8)")

    try:
        user_id = auth_users.create_user(username, password, display_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    # Assign default profile
    default_profile = user_profiles.DEFAULT_PROFILE_ID
    user_profiles.add_user_profile(username, default_profile)

    return auth_users.get_user_by_id(user_id)


@router.put("/users/{user_id}")
async def update_user_endpoint(user_id: str, request: Request):
    """Update a user's display_name, icon, or password.

    Body: {"display_name": str, "icon": str|null, "password": str} (all optional)
    Returns: {"id": str, "username": str, "display_name": str, "icon": str|null}
    """
    require_super(request)

    user = auth_users.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail=f"User not found: {user_id}")

    body = await request.json()
    display_name = body.get("display_name")
    icon = body.get("icon")
    password = body.get("password")

    if password is not None and len(password) < 8:
        raise HTTPException(status_code=400, detail="Password too short (min 8)")

    try:
        auth_users.update_user(
            user_id,
            display_name=display_name,
            icon=icon,
            password=password if password else None,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return auth_users.get_user_by_id(user_id)


@router.delete("/users/{user_id}")
async def delete_user_endpoint(user_id: str, request: Request):
    """Delete a user by ID.

    Cannot delete the current user (yourself).
    """
    require_super(request)
    current_user = auth_core.get_current_user(request)

    user = auth_users.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail=f"User not found: {user_id}")

    if user["username"] == current_user:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")

    # Remove user's profile assignments first
    user_profiles.set_user_profiles(user["username"], [])

    try:
        auth_users.delete_user(user_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return {"deleted": True, "id": user_id}


# ── User Profile Assignment ──────────────────────────────────────────────────


@router.put("/users/{username}/profiles")
async def set_user_profiles_endpoint(username: str, request: Request):
    """Set the profiles for a user (replaces all existing).

    Body: {"profile_ids": ["uuid1", "uuid2", ...]}
    """
    require_super(request)

    if not auth_users.user_exists(username):
        raise HTTPException(status_code=404, detail=f"User not found: {username}")

    body = await request.json()
    profile_ids = body.get("profile_ids", [])

    if not profile_ids:
        raise HTTPException(status_code=400, detail="At least one profile required")

    all_profiles = user_profiles.get_all_profiles()
    for pid in profile_ids:
        if pid not in all_profiles:
            raise HTTPException(status_code=400, detail=f"Unknown profile ID: {pid}")

    user_profiles.set_user_profiles(username, profile_ids)
    logger.info("Profiles %r assigned to user %r by admin", profile_ids, username)

    return {
        "username": username,
        "profiles": user_profiles.get_user_profiles_detailed(username),
        "effective_level": user_profiles.get_effective_level(username),
    }


@router.post("/users/{username}/profiles/{profile_id}")
async def add_user_profile_endpoint(username: str, profile_id: str, request: Request):
    """Add a profile to a user (keeps existing profiles)."""
    require_super(request)

    if not auth_users.user_exists(username):
        raise HTTPException(status_code=404, detail=f"User not found: {username}")

    all_profiles = user_profiles.get_all_profiles()
    if profile_id not in all_profiles:
        raise HTTPException(status_code=400, detail=f"Unknown profile ID: {profile_id}")

    user_profiles.add_user_profile(username, profile_id)

    return {
        "username": username,
        "profiles": user_profiles.get_user_profiles_detailed(username),
        "effective_level": user_profiles.get_effective_level(username),
    }


@router.delete("/users/{username}/profiles/{profile_id}")
async def remove_user_profile_endpoint(
    username: str, profile_id: str, request: Request
):
    """Remove a profile from a user."""
    require_super(request)

    if not auth_users.user_exists(username):
        raise HTTPException(status_code=404, detail=f"User not found: {username}")

    current_profiles = user_profiles.get_user_profiles(username)
    if len(current_profiles) <= 1:
        raise HTTPException(status_code=400, detail="Cannot remove last profile")

    user_profiles.remove_user_profile(username, profile_id)

    return {
        "username": username,
        "profiles": user_profiles.get_user_profiles_detailed(username),
        "effective_level": user_profiles.get_effective_level(username),
    }


# ── Profile Management ───────────────────────────────────────────────────────


@router.get("/profiles")
async def list_profiles(request: Request):
    """List all available profiles with their settings.

    Returns: {"profile_id": {name, level, description, protected}, ...}
    """
    require_super(request)
    return user_profiles.get_all_profiles()


@router.post("/profiles")
async def create_profile_endpoint(request: Request):
    """Create a new custom profile.

    Body: {"name": str, "level": int (0-3), "description": str}
    Returns: {"id": str, "name": str, "level": int, "description": str, "protected": false}
    """
    require_super(request)

    body = await request.json()
    name = body.get("name", "").strip().upper()
    level = body.get("level")
    description = body.get("description", "")

    if not name:
        raise HTTPException(status_code=400, detail="Profile name required")
    if level is None or not isinstance(level, int):
        raise HTTPException(status_code=400, detail="Level required (0-3)")
    if not 0 <= level <= 3:
        raise HTTPException(status_code=400, detail="Level must be 0-3")

    try:
        profile_id = user_profiles.create_profile(name, level, description)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "id": profile_id,
        "name": name,
        "level": level,
        "description": description,
        "protected": False,
    }


@router.put("/profiles/{profile_id}")
async def update_profile_endpoint(profile_id: str, request: Request):
    """Update a profile. Cannot modify protected profiles (SUPER).

    Body: {"name": str (optional), "level": int (optional), "description": str (optional)}
    """
    require_super(request)

    body = await request.json()
    name = body.get("name")
    level = body.get("level")
    description = body.get("description")

    if level is not None and not 0 <= level <= 3:
        raise HTTPException(status_code=400, detail="Level must be 0-3")

    try:
        user_profiles.update_profile(
            profile_id, name=name, level=level, description=description
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return user_profiles.get_profile_by_id(profile_id)


@router.delete("/profiles/{profile_id}")
async def delete_profile_endpoint(profile_id: str, request: Request):
    """Delete a profile. Cannot delete protected or built-in profiles."""
    require_super(request)

    try:
        user_profiles.delete_profile(profile_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"deleted": profile_id}


# ── Legacy endpoint for backward compatibility ───────────────────────────────


@router.put("/users/{username}/profile")
async def set_user_profile_legacy(username: str, request: Request):
    """Legacy: Assign a single profile to a user (replaces all).

    Body: {"profile": "PROFILE_KEY"}

    Deprecated: Use PUT /users/{username}/profiles with profile_ids instead.
    """
    require_super(request)

    if not auth_users.user_exists(username):
        raise HTTPException(status_code=404, detail=f"User not found: {username}")

    body = await request.json()
    profile_key = body.get("profile")
    if not profile_key:
        raise HTTPException(status_code=400, detail="Missing 'profile' field")

    all_profiles = user_profiles.get_all_profiles()
    if profile_key not in all_profiles:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid profile: {profile_key}. Valid: {list(all_profiles.keys())}",
        )

    user_profiles.set_user_profiles(username, [profile_key])
    logger.info("Profile %r assigned to user %r by admin", profile_key, username)
    return {"username": username, "profile": profile_key}
