"""Core authentication helpers: JWT sign/verify and password verification.

Password format: Apache apr_md5_crypt ($apr1$...) read from .htpasswd file.
Session tokens: short-lived JWT (24h), stored as HttpOnly cookie 'smh_session'.
Device tokens: long-lived opaque Jaspan tokens, stored as HttpOnly cookie
               'smh_device' — see auth_devices.py.
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import jwt
from passlib.hash import apr_md5_crypt

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration (injected from main.py lifespan)
# ---------------------------------------------------------------------------
AUTH_SECRET: str = ""           # REQUIRED: random 32+ char hex secret
AUTH_SESSION_TTL: int = 86400   # 24 hours (seconds) — standard session JWT
AUTH_TRUSTED_TTL: int = 31536000  # kept for reference; device tokens use auth_devices.py

COOKIE_NAME = "smh_session"
ALGORITHM   = "HS256"


# ---------------------------------------------------------------------------
# Password verification
# ---------------------------------------------------------------------------

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against an apr_md5_crypt hash ($apr1$...).

    Supports the standard Apache .htpasswd format used by nginx.
    """
    try:
        return apr_md5_crypt.verify(plain_password, hashed_password)
    except Exception as exc:
        logger.warning("Password verification error: %s", exc)
        return False


# ---------------------------------------------------------------------------
# JWT session helpers
# ---------------------------------------------------------------------------

def create_token(username: str) -> str:
    """Create a signed JWT session token (24h).

    Args:
        username: Authenticated username.

    Returns:
        Encoded JWT string.
    """
    if not AUTH_SECRET:
        raise RuntimeError("AUTH_SECRET is not configured")

    now = datetime.now(timezone.utc)
    payload = {
        "sub": username,
        "iat": now,
        "exp": now + timedelta(seconds=AUTH_SESSION_TTL),
    }
    return jwt.encode(payload, AUTH_SECRET, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    """Decode and validate a JWT session token.

    Returns the payload dict on success, or None if invalid/expired.
    """
    if not AUTH_SECRET:
        return None
    try:
        return jwt.decode(token, AUTH_SECRET, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        logger.debug("Session token expired")
        return None
    except jwt.InvalidTokenError as exc:
        logger.debug("Invalid session token: %s", exc)
        return None


def decode_token_expired_ok(token: str) -> Optional[dict]:
    """Decode a JWT without checking expiry.

    Used by the middleware to read the username from an expired JWT before
    attempting a device-token refresh — avoids a second DB lookup.
    """
    if not AUTH_SECRET:
        return None
    try:
        return jwt.decode(
            token,
            AUTH_SECRET,
            algorithms=[ALGORITHM],
            options={"verify_exp": False},
        )
    except jwt.InvalidTokenError as exc:
        logger.debug("Invalid (expired-ok) token: %s", exc)
        return None


def get_token_from_cookie(request) -> Optional[str]:
    """Extract the session JWT from the request cookie jar."""
    return request.cookies.get(COOKIE_NAME)


def get_current_user(request) -> Optional[str]:
    """Return the authenticated username from the session cookie, or None.

    Only returns a value if the JWT is valid AND not expired.
    For the expired-but-refreshable case, see the AuthMiddleware in main.py.
    """
    token = get_token_from_cookie(request)
    if not token:
        return None
    payload = decode_token(token)
    if payload is None:
        return None
    return payload.get("sub")


def set_session_cookie(response, token: str) -> None:
    """Attach the 24h session JWT cookie to a response."""
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=AUTH_SESSION_TTL,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )


def clear_session_cookie(response) -> None:
    """Delete the session JWT cookie."""
    response.delete_cookie(
        key=COOKIE_NAME,
        path="/",
        httponly=True,
        secure=True,
        samesite="strict",
    )
