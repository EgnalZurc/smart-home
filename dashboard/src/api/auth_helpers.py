"""Shared authentication helpers for API endpoints.

This module provides common authentication utilities used across
multiple API routers (auth_routes, system/stats, system/containers).
"""

from fastapi import HTTPException, Request


def _get_authenticated_user(request: Request) -> str:
    """Get the authenticated username from request, or raise 401."""
    import auth as auth_core

    user = auth_core.get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def require_super(request: Request) -> str:
    """Check that the current user has level 0 (SUPER) access.

    Args:
        request: The FastAPI request object.

    Returns:
        The authenticated username if authorized.

    Raises:
        HTTPException: 401 if not authenticated, 403 if not SUPER level.
    """
    import user_profiles

    user = _get_authenticated_user(request)
    if not user_profiles.is_super(user):
        raise HTTPException(status_code=403, detail="Admin access required (level 0)")
    return user


def require_app_write(request: Request, app_key: str) -> str:
    """Check that the current user can write to a specific app.

    Permission model:
    - SUPER (level 0): can write to any app
    - Others: can write if their effective level falls within the app's
      [min_level, max_level] range (same as view permissions)

    Args:
        request: The FastAPI request object.
        app_key: The app identifier (e.g., "ac", "vacaciones", "casita").

    Returns:
        The authenticated username if authorized.

    Raises:
        HTTPException: 401 if not authenticated, 403 if no write permission.
    """
    import user_profiles
    from profiles.constants import APP_REGISTRY

    user = _get_authenticated_user(request)
    level = user_profiles.get_effective_level(user)

    # SUPER can always write
    if level == 0:
        return user

    # Find app in registry
    app = next((a for a in APP_REGISTRY if a["key"] == app_key), None)
    if app is None:
        # Unknown app — default to SUPER-only for safety
        raise HTTPException(
            status_code=403, detail=f"Unknown app '{app_key}' — admin access required"
        )

    # Check if user's level is within app's allowed range
    min_lvl = app.get("min_level", 0)
    max_lvl = app.get("max_level", 0)
    if min_lvl <= level <= max_lvl:
        return user

    raise HTTPException(
        status_code=403,
        detail=f"No write permission for '{app_key}' (requires level {min_lvl}-{max_lvl})",
    )
