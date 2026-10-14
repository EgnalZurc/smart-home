"""User preferences endpoints.

Persists per-user UI preferences (currently the dark-mode toggle) in the
``users`` table of the auth database, so a user's theme choice follows them
across devices and sessions instead of living only in browser localStorage.

Both endpoints require an authenticated session (any profile level): a user
reads and writes only their own preferences, keyed by the authenticated
username, so no admin check is needed.
"""

import auth_users
from fastapi import APIRouter, Request
from pydantic import BaseModel

from api.auth_helpers import require_authenticated

router = APIRouter(prefix="/api/user", tags=["User"])


class Preferences(BaseModel):
    """UI preferences payload. Currently only the dark-mode flag."""

    dark_mode: bool


@router.get("/preferences")
def get_preferences(request: Request) -> dict:
    """Return the current user's UI preferences.

    Returns:
        ``{"dark_mode": bool}`` for the authenticated user.
    """
    username = require_authenticated(request)
    return auth_users.get_user_preferences(username)


@router.post("/preferences")
def update_preferences(prefs: Preferences, request: Request) -> dict:
    """Persist the current user's UI preferences.

    Body:
        ``{"dark_mode": true|false}``

    Returns:
        The stored preferences after the update.
    """
    username = require_authenticated(request)
    auth_users.set_user_preferences(username, prefs.dark_mode)
    return auth_users.get_user_preferences(username)
