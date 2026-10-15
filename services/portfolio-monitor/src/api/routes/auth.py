"""
Portfolio Monitor — Authentication dependency.

Provides bearer token authentication for POST endpoints. When AUTH_TOKEN is set,
requests must include `Authorization: Bearer <token>` header. When AUTH_TOKEN is
empty or unset, authentication is disabled for backwards compatibility.
"""

import logging
import os
from typing import Annotated

from fastapi import Header, HTTPException, status

logger = logging.getLogger(__name__)


def _get_auth_token() -> str:
    """Return the configured auth token from environment.

    Reads on every call to support testing and dynamic configuration.
    """
    return os.environ.get("AUTH_TOKEN", "")


async def require_auth(
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """Dependency that enforces bearer token authentication.

    If AUTH_TOKEN is not configured (empty), authentication is skipped.
    Otherwise, the request must include a valid Authorization header.

    Raises:
        HTTPException 401: Missing or invalid authorization header.
        HTTPException 403: Token mismatch.
    """
    token = _get_auth_token()

    # Auth disabled — allow all requests
    if not token:
        return

    if not authorization:
        logger.warning("Auth required but no Authorization header provided")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Expect "Bearer <token>"
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        logger.warning("Invalid Authorization header format")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header format. Expected: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"},
        )

    provided_token = parts[1]
    if provided_token != token:
        logger.warning("Invalid auth token provided")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid token",
        )

    # Token valid — request proceeds
