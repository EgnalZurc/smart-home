"""
Portfolio Monitor — Authentication dependency.

Provides bearer token authentication for POST endpoints. AUTH_TOKEN must be set
in environment; requests must include `Authorization: Bearer <token>` header.
"""

import hmac
import logging
import os
from typing import Annotated

from fastapi import Header, HTTPException, status

logger = logging.getLogger(__name__)

# Module-level flag to track if token was validated at startup
_startup_validated = False


class AuthConfigurationError(Exception):
    """Raised when AUTH_TOKEN is not configured."""

    pass


def validate_auth_config() -> None:
    """Validate that AUTH_TOKEN is configured. Call at application startup.

    Raises:
        AuthConfigurationError: If AUTH_TOKEN is empty or not set.
    """
    global _startup_validated
    token = os.environ.get("AUTH_TOKEN", "")
    if not token:
        raise AuthConfigurationError(
            "AUTH_TOKEN environment variable is required but not set. "
            "Set AUTH_TOKEN to enable bearer token authentication."
        )
    _startup_validated = True
    logger.info("AUTH_TOKEN configured - authentication enabled")


def _get_auth_token() -> str:
    """Return the configured auth token from environment.

    Reads on every call to support testing and dynamic configuration.
    """
    return os.environ.get("AUTH_TOKEN", "")


async def require_auth(
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """Dependency that enforces bearer token authentication.

    AUTH_TOKEN must be configured (validated at startup).
    Requests must include a valid Authorization header.

    Raises:
        HTTPException 401: Missing or invalid authorization header.
        HTTPException 403: Token mismatch.
        HTTPException 500: AUTH_TOKEN not configured (should not happen if
            validate_auth_config was called at startup).
    """
    token = _get_auth_token()

    # Safety check - should never happen if validate_auth_config was called
    if not token:
        logger.error(
            "AUTH_TOKEN not configured - this should have been caught at startup"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server authentication not configured",
        )

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
    # Use constant-time comparison to prevent timing attacks
    if not hmac.compare_digest(provided_token.encode(), token.encode()):
        logger.warning("Invalid auth token provided")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid token",
        )

    # Token valid — request proceeds
