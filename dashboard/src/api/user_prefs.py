"""User preferences endpoints.

Persists per-user UI preferences in the auth database so a user's choices
follow them across devices and sessions instead of living only in browser
localStorage:

* ``/api/user/preferences`` — the dark-mode toggle (a single flag).
* ``/api/user/widget-config`` — the dashboard widget (app-card) layout:
  per-widget visibility, order, size and free-form settings.

Both resources require an authenticated session (any profile level): a user
reads and writes only their own data, keyed by the authenticated username, so
no admin check is needed.
"""

from __future__ import annotations

import logging

import auth_users
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from api.auth_helpers import require_authenticated

router = APIRouter(prefix="/api/user", tags=["User"])

__all__ = [
    "router",
    "get_preferences",
    "update_preferences",
    "get_widget_config",
    "update_widget_config",
    "Preferences",
    "WidgetConfig",
    "WidgetConfigPayload",
]

logger = logging.getLogger(__name__)


class Preferences(BaseModel):
    """UI preferences payload. Currently only the dark-mode flag."""

    dark_mode: bool


class WidgetConfig(BaseModel):
    """Configuration for a single dashboard widget (app-card)."""

    widget_id: str = Field(..., min_length=1)
    visible: bool = True
    order: int = 0
    size: str = "md"
    custom_settings: dict = Field(default_factory=dict)


class WidgetConfigPayload(BaseModel):
    """POST body for ``/api/user/widget-config``: the full widget layout."""

    widgets: list[WidgetConfig]


@router.get("/preferences")
async def get_preferences(request: Request) -> dict:
    """Return the current user's UI preferences.

    Returns:
        ``{"dark_mode": bool}`` for the authenticated user.
    """
    username = require_authenticated(request)
    return auth_users.get_user_preferences(username)


@router.post("/preferences")
async def update_preferences(prefs: Preferences, request: Request) -> dict:
    """Persist the current user's UI preferences.

    Body:
        ``{"dark_mode": true|false}``

    Returns:
        The stored preferences after the update.
    """
    username = require_authenticated(request)
    auth_users.set_user_preferences(username, prefs.dark_mode)
    return auth_users.get_user_preferences(username)


@router.get("/widget-config")
async def get_widget_config(request: Request) -> dict:
    """Return the current user's dashboard widget layout.

    Returns:
        ``{"widgets": [{widget_id, visible, order, size, custom_settings}, ...]}``
        ordered by ``order``. An empty list means the user has no saved layout
        yet and the client should fall back to its defaults.
    """
    username = require_authenticated(request)
    return {"widgets": auth_users.get_widget_config(username)}


@router.post("/widget-config")
async def update_widget_config(payload: WidgetConfigPayload, request: Request) -> dict:
    """Persist the current user's dashboard widget layout.

    Body:
        ``{"widgets": [{widget_id, visible, order, size, custom_settings}, ...]}``

    The full set is replaced atomically, so the stored layout always mirrors
    what the client sends.

    Returns:
        The stored widgets after the update.

    Raises:
        HTTPException: 422 if a widget carries an invalid field (bad size,
            duplicate id, non-serialisable settings).
    """
    username = require_authenticated(request)
    try:
        auth_users.set_widget_config(
            username, [w.model_dump() for w in payload.widgets]
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"widgets": auth_users.get_widget_config(username)}
