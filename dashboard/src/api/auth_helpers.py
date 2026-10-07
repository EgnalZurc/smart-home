"""Shared authentication helpers for API endpoints.

This module provides common authentication utilities used across
multiple API routers (auth_routes, system/stats, system/containers).
"""

from fastapi import HTTPException, Request


def require_super(request: Request) -> str:
    """Check that the current user has level 0 (SUPER) access.

    Args:
        request: The FastAPI request object.

    Returns:
        The authenticated username if authorized.

    Raises:
        HTTPException: 401 if not authenticated, 403 if not SUPER level.
    """
    import auth as auth_core
    import user_profiles

    user = auth_core.get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if not user_profiles.is_super(user):
        raise HTTPException(status_code=403, detail="Admin access required (level 0)")
    return user
