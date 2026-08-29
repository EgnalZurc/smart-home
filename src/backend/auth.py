"""Core authentication helpers: JWT sign/verify and password verification.

Password format: Apache apr_md5_crypt ($apr1$...) read from .htpasswd file.
Tokens: JWT signed with HS256, stored as HttpOnly cookie.
"""
import os
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import jwt
from passlib.hash import apr_md5_crypt

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration (injected from environment — set in main.py lifespan)
# ---------------------------------------------------------------------------
AUTH_SECRET: str = ""          # REQUIRED: random 32+ char secret for JWT signing
AUTH_SESSION_TTL: int = 86400       # 24 hours (seconds) — standard session
AUTH_TRUSTED_TTL: int = 31536000    # 365 days (seconds) — trusted device session

COOKIE_NAME = "smh_session"
ALGORITHM = "HS256"


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
# JWT helpers
# ---------------------------------------------------------------------------

def create_token(username: str, trusted: bool = False) -> str:
    """Create a signed JWT session token.

    Args:
        username: Authenticated username.
        trusted: If True, token expires in AUTH_TRUSTED_TTL (1 year).
                 If False, token expires in AUTH_SESSION_TTL (24h).

    Returns:
        Encoded JWT string.
    """
    if not AUTH_SECRET:
        raise RuntimeError("AUTH_SECRET is not configured")

    ttl = AUTH_TRUSTED_TTL if trusted else AUTH_SESSION_TTL
    now = datetime.now(timezone.utc)
    payload = {
        "sub": username,
        "iat": now,
        "exp": now + timedelta(seconds=ttl),
        "trusted": trusted,
    }
    return jwt.encode(payload, AUTH_SECRET, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    """Decode and validate a JWT token.

    Returns the payload dict on success, or None if invalid/expired.
    """
    if not AUTH_SECRET:
        return None
    try:
        payload = jwt.decode(token, AUTH_SECRET, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        logger.debug("Token expired")
        return None
    except jwt.InvalidTokenError as exc:
        logger.debug("Invalid token: %s", exc)
        return None


def get_token_from_cookie(request) -> Optional[str]:
    """Extract the session token from the request cookie jar."""
    return request.cookies.get(COOKIE_NAME)


def get_current_user(request) -> Optional[str]:
    """Return the authenticated username from the session cookie, or None."""
    token = get_token_from_cookie(request)
    if not token:
        return None
    payload = decode_token(token)
    if payload is None:
        return None
    return payload.get("sub")
