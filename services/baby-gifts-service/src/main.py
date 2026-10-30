"""Baby Gifts Service — standalone microservice for baby gift registry.

Three access modes:
1. Admin (authenticated via nginx auth_request + SUPER profile): full CRUD
2. Authenticated User (via nginx auth_request): view gifts + reserve/unreserve
3. Guest (via invitation token): view gifts + reserve/unreserve own

Serves:
  GET  /smart-home/baby-gifts       → SPA (admin/user view, requires auth)
  GET  /guest/baby-gifts/{token}    → SPA (guest view, token-based access)

  # Admin endpoints (protected by nginx auth_request, requires SUPER)
  GET  /api/baby-gifts              → all gifts (with reservation details)
  POST /api/baby-gifts              → add gift
  PUT  /api/baby-gifts/{id}         → update gift
  DELETE /api/baby-gifts/{id}       → delete gift
  POST /api/baby-gifts/{id}/unreserve → admin can unreserve any gift
  GET  /api/baby-gifts/invitations  → list all invitations
  POST /api/baby-gifts/invitations  → create invitation
  DELETE /api/baby-gifts/invitations/{token} → delete invitation
  POST /api/baby-gifts/invitations/{token}/revoke → revoke invitation

  # Authenticated user endpoints (protected by nginx auth_request)
  GET  /api/baby-gifts/user              → get gifts for authenticated user
  POST /api/baby-gifts/user/reserve/{id} → reserve a gift as authenticated user
  POST /api/baby-gifts/user/unreserve/{id} → unreserve own gift

  # Guest endpoints (token-based, public)
  GET  /api/baby-gifts/guest/{token}           → get gifts for guest
  POST /api/baby-gifts/guest/{token}/reserve/{id}   → reserve a gift
  POST /api/baby-gifts/guest/{token}/unreserve/{id} → unreserve own gift

  GET  /health                      → health check
  GET  /api/health/baby-gifts       → health check alias

Port: 8004
"""

import hashlib
import ipaddress
import logging
import re
from collections.abc import Callable
from html import escape as html_escape
from pathlib import Path
from typing import Any

from config import TRUSTED_PROXY_IPS
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi import Path as PathParam
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from gifts_controller import (
    add_gift,
    check_invitation_rate_limit,
    check_rate_limit,
    create_invitation,
    delete_gift,
    delete_invitation,
    get_gift,
    get_gifts_data,
    is_familia_user,
    is_healthy,
    list_invitations,
    reserve_gift,
    revoke_invitation,
    toggle_gift_visibility,
    unreserve_gift,
    update_gift,
    validate_invitation,
)
from notifier import send_gift_notification
from pydantic import BaseModel, ValidationInfo, field_validator
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
from utils import parse_price


# ═══════════════════════════════════════════════════════════════════════════════
# Input sanitization
# ═══════════════════════════════════════════════════════════════════════════════
def sanitize_string(value: str, max_length: int) -> str:
    """Sanitize user-provided string: strip whitespace, limit length, escape HTML.

    Args:
        value: Raw user input string.
        max_length: Maximum allowed length after stripping.

    Returns:
        Sanitized string safe for storage and display.
    """
    if not value:
        return ""
    # Strip leading/trailing whitespace
    cleaned: str = value.strip()
    # Truncate to max length
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length]
    # Escape HTML characters to prevent XSS
    return html_escape(cleaned)


# Import serve_html from shared lib (path added via PYTHONPATH in Dockerfile/CI;
# fallback inserts repo root for local development — mirrors notifier.py).
try:
    from libs.html_serving import serve_html
except ImportError:  # pragma: no cover
    import sys

    sys.path.insert(0, str(__file__).replace("\\", "/").split("/services/")[0])
    from libs.html_serving import serve_html

# Structured logging using python-json-logger for better log aggregation.
# JSON format enables easier parsing by log management systems (ELK, Grafana Loki).
try:
    from pythonjsonlogger import jsonlogger

    handler = logging.StreamHandler()
    formatter = jsonlogger.JsonFormatter(
        fmt="%(asctime)s %(name)s %(levelname)s %(message)s",
        rename_fields={"asctime": "timestamp", "levelname": "level"},
    )
    handler.setFormatter(formatter)
    logging.root.handlers.clear()
    logging.root.addHandler(handler)
    logging.root.setLevel(logging.INFO)
except ImportError:
    # Fallback to text format if python-json-logger not installed
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
logger: logging.Logger = logging.getLogger(__name__)

app: FastAPI = FastAPI(
    title="Baby Gifts Service",
    version="1.0.0",
    docs_url="/swagger",
    redoc_url="/redoc",
)


# ═══════════════════════════════════════════════════════════════════════════════
# Security middleware
# ═══════════════════════════════════════════════════════════════════════════════
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses.

    Headers added:
        - X-Content-Type-Options: nosniff - Prevents MIME type sniffing
        - X-Frame-Options: DENY - Prevents clickjacking via iframes
        - X-XSS-Protection: 1; mode=block - Legacy XSS protection for older browsers
        - Content-Security-Policy: default-src 'self' - Restricts resource loading
        - Referrer-Policy: strict-origin-when-cross-origin - Controls referrer info
    """

    def __init__(self, app: ASGIApp) -> None:
        """Initialize middleware with ASGI application."""
        super().__init__(app)

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Response]
    ) -> Response:
        """Process request and add security headers to response."""
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        # SECURITY: unsafe-inline required for SPA with inline scripts/styles/event handlers.
        # This is an ACCEPTED_RISK documented in docs/SECURITY_FIXES.md under
        # "[infrastructure] CSP unsafe-inline". Mitigations:
        # - Application served via Tailscale VPN only (not public internet)
        # - nginx auth_request guards all endpoints
        # - Other security headers provide defense-in-depth
        # Future: Consider nonce-based CSP migration (dashboard already migrated)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "connect-src 'self'"
        )
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response


app.add_middleware(SecurityHeadersMiddleware)


# ═══════════════════════════════════════════════════════════════════════════════
# Input validation constants
# ═══════════════════════════════════════════════════════════════════════════════
MAX_NAME_LENGTH: int = 200
MAX_DESCRIPTION_LENGTH: int = 1000
MAX_PRICE_RANGE_LENGTH: int = 100
MAX_URL_LENGTH: int = 2000
MAX_INVITATION_NAME_LENGTH: int = 100
# Token preview length for safe logging (show first N chars only)
TOKEN_PREVIEW_LENGTH: int = 4
# Prefix for authenticated user tokens (distinguishes from guest invitation tokens)
USER_TOKEN_PREFIX: str = "user:"
# Max length for tokens in path parameters (H1: prevent DoS via oversized tokens)
# secrets.token_urlsafe(24) produces 32 chars; allow some margin for future changes
MAX_TOKEN_LENGTH: int = 64


# ═══════════════════════════════════════════════════════════════════════════════
# Pydantic models with input sanitization
# ═══════════════════════════════════════════════════════════════════════════════
class GiftCreate(BaseModel):
    """Model for creating a new gift."""

    name: str
    description: str = ""
    url: str = ""
    price_range: str = ""
    priority: int = 2

    @field_validator("name", "description", "price_range", mode="after")
    @classmethod
    def sanitize_text_fields(cls, v: str, info: ValidationInfo) -> str:
        """Sanitize text fields: strip, truncate, escape HTML."""
        max_lengths: dict[str, int] = {
            "name": MAX_NAME_LENGTH,
            "description": MAX_DESCRIPTION_LENGTH,
            "price_range": MAX_PRICE_RANGE_LENGTH,
        }
        return sanitize_string(
            v, max_lengths.get(info.field_name or "", MAX_NAME_LENGTH)
        )

    @field_validator("url", mode="after")
    @classmethod
    def sanitize_url(cls, v: str) -> str:
        """Sanitize URL: strip, truncate, validate protocol (no HTML escape)."""
        if not v:
            return ""
        cleaned: str = v.strip()
        # Block non-HTTP schemes (javascript:, data:, vbscript:, etc.)
        if cleaned and not cleaned.lower().startswith(("http://", "https://")):
            return ""
        return cleaned[:MAX_URL_LENGTH] if len(cleaned) > MAX_URL_LENGTH else cleaned


class GiftUpdate(BaseModel):
    """Model for updating an existing gift."""

    name: str | None = None
    description: str | None = None
    url: str | None = None
    price_range: str | None = None
    priority: int | None = None

    @field_validator("name", "description", "price_range", mode="after")
    @classmethod
    def sanitize_text_fields(cls, v: str | None, info: ValidationInfo) -> str | None:
        """Sanitize text fields if provided."""
        if v is None:
            return None
        max_lengths: dict[str, int] = {
            "name": MAX_NAME_LENGTH,
            "description": MAX_DESCRIPTION_LENGTH,
            "price_range": MAX_PRICE_RANGE_LENGTH,
        }
        return sanitize_string(
            v, max_lengths.get(info.field_name or "", MAX_NAME_LENGTH)
        )

    @field_validator("url", mode="after")
    @classmethod
    def sanitize_url(cls, v: str | None) -> str | None:
        """Sanitize URL if provided: strip, truncate, validate protocol."""
        if v is None:
            return ""
        cleaned: str = v.strip()
        # Block non-HTTP schemes (javascript:, data:, vbscript:, etc.)
        if cleaned and not cleaned.lower().startswith(("http://", "https://")):
            return ""
        return cleaned[:MAX_URL_LENGTH] if len(cleaned) > MAX_URL_LENGTH else cleaned


class InvitationCreate(BaseModel):
    """Model for creating a new invitation."""

    name: str

    @field_validator("name", mode="after")
    @classmethod
    def sanitize_name(cls, v: str) -> str:
        """Sanitize invitation name: strip, truncate, escape HTML."""
        return sanitize_string(v, MAX_INVITATION_NAME_LENGTH)


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════
_STATIC_DIR: Path = Path(__file__).parent / "static"

# Regex for validating IP format in X-Forwarded-For header (M5)
# Matches both IPv4 (dotted decimal) and IPv6 (colon-separated hex)
_IP_FORMAT_PATTERN: re.Pattern[str] = re.compile(
    r"^(?:(?:\d{1,3}\.){3}\d{1,3}|[0-9a-fA-F:]+)$"
)


def _validate_ip_format(ip: str) -> bool:
    """Validate that a string looks like a valid IP address.

    Uses the ipaddress module for strict validation, which correctly handles
    both IPv4 and IPv6 addresses including edge cases (leading zeros, etc.).

    Args:
        ip: String to validate as IP address.

    Returns:
        True if valid IPv4 or IPv6 address, False otherwise.
    """
    if not ip or not _IP_FORMAT_PATTERN.match(ip):
        return False
    try:
        ipaddress.ip_address(ip)
        return True
    except ValueError:
        return False


def _hash_name_for_log(name: str) -> str:
    """Hash a guest name for GDPR-compliant logging (M3).

    Uses SHA256 truncated to 8 chars for pseudonymization while still
    allowing correlation of actions by the same guest within logs.

    Args:
        name: Guest name to hash.

    Returns:
        Truncated SHA256 hash (8 chars) prefixed with 'guest_'.
    """
    if not name:
        return "guest_unknown"
    return f"guest_{hashlib.sha256(name.encode()).hexdigest()[:8]}"


def _get_client_ip(request: Request) -> str:
    """Get client IP from request, considering trusted proxies only.

    Only trusts X-Forwarded-For header if the direct connection comes from
    a trusted proxy IP (e.g., nginx container). This prevents IP spoofing.

    Note: Full IP is logged for rate limiting enforcement. This is necessary
    for security (abuse prevention) and is a legitimate interest under GDPR
    Article 6(1)(f). IPs are not stored long-term beyond the rate limit window.
    """
    # GDPR Art. 6(1)(f): IP logged for rate limiting (legitimate interest).
    # Retained only in memory, not persisted.
    client_ip: str = request.client.host if request.client else "unknown"
    forwarded: str | None = request.headers.get("X-Forwarded-For")

    # Only trust X-Forwarded-For if request comes from trusted proxy
    if forwarded and client_ip in TRUSTED_PROXY_IPS:
        # Extract first IP and validate format (M5)
        first_ip: str = forwarded.split(",")[0].strip()
        if _validate_ip_format(first_ip):
            return first_ip
        # Invalid format - fall back to direct client IP
        logger.warning(
            f"Invalid X-Forwarded-For format: {first_ip[:50]}..., "
            f"falling back to client_ip={client_ip}"
        )

    return client_ip


def require_rate_limit(request: Request) -> str:
    """FastAPI dependency: enforce the per-IP rate limit for guest endpoints.

    Resolves the client IP (honouring trusted proxies) and raises 429 when the
    limit is exceeded. Returns the resolved client IP so handlers can reuse it.
    """
    client_ip: str = _get_client_ip(request)
    if not check_rate_limit(client_ip):
        raise HTTPException(
            status_code=429, detail="Demasiados intentos. Espera un momento."
        )
    return client_ip


def require_invitation_rate_limit(request: Request) -> str:
    """FastAPI dependency: enforce rate limit for invitation creation (30/min).

    Resolves the client IP (honouring trusted proxies) and raises 429 when the
    limit is exceeded. Returns the resolved client IP so handlers can reuse it.
    """
    client_ip: str = _get_client_ip(request)
    if not check_invitation_rate_limit(client_ip):
        raise HTTPException(
            status_code=429,
            detail="Demasiadas invitaciones creadas. Espera un momento.",
        )
    return client_ip


def _get_auth_user(request: Request) -> str | None:
    """Get authenticated username from nginx auth_request header."""
    return request.headers.get("X-Auth-User")


def require_auth_user(request: Request) -> str:
    """FastAPI dependency: require X-Auth-User header for admin endpoints.

    Defense-in-depth: verify auth header in code, not just nginx.
    Even though nginx auth_request protects admin endpoints, we verify
    the header is present as an extra layer of security.

    Args:
        request: FastAPI request object.

    Returns:
        str: Authenticated username.

    Raises:
        HTTPException: 401 if X-Auth-User header is missing.
    """
    username: str | None = request.headers.get("X-Auth-User")
    if not username:
        raise HTTPException(status_code=401, detail="Authentication required")
    return username


def _truncate_token(token: str) -> str:
    """Truncate token for safe logging (show first N chars only).

    Args:
        token: Full token string.

    Returns:
        str: Truncated token showing only first TOKEN_PREVIEW_LENGTH chars + '...',
            or full token if shorter than or equal to TOKEN_PREVIEW_LENGTH.
    """
    if len(token) > TOKEN_PREVIEW_LENGTH:
        return f"{token[:TOKEN_PREVIEW_LENGTH]}..."
    return token


# ═══════════════════════════════════════════════════════════════════════════════
# Health endpoints
# ═══════════════════════════════════════════════════════════════════════════════
@app.get("/health")
def health() -> dict[str, Any]:
    """Health check endpoint for nginx and the dashboard.

    Returns:
        dict: Status with 'online' bool and 'service' name.
    """
    return {"online": is_healthy(), "service": "baby-gifts"}


@app.get("/api/health/baby-gifts")
def health_alias() -> dict[str, bool]:
    """Health check alias matching path expected by the dashboard.

    Returns:
        dict: Status with 'online' bool.
    """
    return {"online": is_healthy()}


# ═══════════════════════════════════════════════════════════════════════════════
# SPA serving
# ═══════════════════════════════════════════════════════════════════════════════
@app.get("/smart-home/baby-gifts")
async def serve_admin(request: Request) -> HTMLResponse:
    """Serve the admin/user SPA (protected by nginx auth_request).

    If user is an admin (SUPER profile), they get full management capabilities.
    If user is a regular authenticated user, they can view and reserve gifts.

    Args:
        request: FastAPI request object.

    Returns:
        HTMLResponse: Rendered baby-gifts.html with user context.
    """
    username: str | None = _get_auth_user(request)
    if username:
        return serve_html(
            _STATIC_DIR, "baby-gifts.html", auth_user={"username": username}
        )
    else:
        return serve_html(_STATIC_DIR, "baby-gifts.html")


@app.get("/guest/baby-gifts/{token}")
async def serve_guest(
    token: str = PathParam(..., max_length=MAX_TOKEN_LENGTH),
    client_ip: str = Depends(require_rate_limit),
) -> HTMLResponse:
    """Serve the guest SPA (public, token-validated).

    H2 FIX: Rate limiting applied BEFORE token validation to prevent
    timing attacks and DoS via invalid token enumeration.

    Args:
        token: Invitation token from URL path (max 64 chars).
        client_ip: Resolved client IP (injected by rate limit dependency).

    Returns:
        HTMLResponse: Rendered baby-gifts.html with guest token.

    Raises:
        HTTPException: 429 if rate limited, 404 if token is invalid or expired.
    """
    guest: dict[str, Any] | None = validate_invitation(token)
    if not guest:
        raise HTTPException(status_code=404, detail="Enlace no válido o expirado")

    # M3: Log with hashed name for GDPR compliance
    logger.info(
        f"Guest access: {_hash_name_for_log(guest['name'])} "
        f"(token: {_truncate_token(token)}) from {client_ip}"
    )
    return serve_html(_STATIC_DIR, "baby-gifts.html", guest_token=token)


# ═══════════════════════════════════════════════════════════════════════════════
# Admin API (protected by nginx auth_request)
# ═══════════════════════════════════════════════════════════════════════════════
@app.get("/api/baby-gifts")
def get_all_gifts(username: str = Depends(require_auth_user)) -> dict[str, Any]:
    """Get all gifts with full reservation details (admin only).

    Args:
        username: Authenticated username (injected by auth dependency).

    Returns:
        dict: Gifts list, FAMILIA status, and username.
    """
    user_is_familia: bool = is_familia_user(username)
    data: dict[str, Any] = get_gifts_data(include_admin=True)
    return {
        "gifts": data.get("gifts", []),
        "is_familia": user_is_familia,
        "user_name": username,
    }


@app.post("/api/baby-gifts")
def create_gift(
    gift: GiftCreate, username: str = Depends(require_auth_user)
) -> dict[str, Any]:
    """Add a new gift to the registry (admin only).

    Args:
        gift: Gift creation payload.
        username: Authenticated username (injected by auth dependency).

    Returns:
        dict: Status and newly created gift.
    """
    new_gift: dict[str, Any] = add_gift(gift.model_dump())
    return {"status": "ok", "gift": new_gift}


@app.put("/api/baby-gifts/{gift_id}")
def modify_gift(
    gift_id: str, gift: GiftUpdate, username: str = Depends(require_auth_user)
) -> dict[str, Any]:
    """Update an existing gift (admin only).

    Args:
        gift_id: ID of the gift to update.
        gift: Fields to update (only non-None values applied).
        username: Authenticated username (injected by auth dependency).

    Returns:
        dict: Status and updated gift.

    Raises:
        HTTPException: 400 if no changes or validation error, 404 if not found.
    """
    updates: dict[str, Any] = {
        k: v for k, v in gift.model_dump().items() if v is not None
    }
    if not updates:
        raise HTTPException(status_code=400, detail="No hay cambios")
    result: dict[str, Any] | None | tuple[None, int, str] = update_gift(
        gift_id, updates
    )

    # Handle validation errors (tuple: None, status_code, message)
    if isinstance(result, tuple):
        _, status_code, message = result
        raise HTTPException(status_code=status_code, detail=message)

    # Handle not found (None)
    if result is None:
        raise HTTPException(status_code=404, detail="Regalo no encontrado")

    return {"status": "ok", "gift": result}


@app.delete("/api/baby-gifts/{gift_id}")
def remove_gift(
    gift_id: str, username: str = Depends(require_auth_user)
) -> dict[str, str]:
    """Delete a gift from the registry (admin only).

    Args:
        gift_id: ID of the gift to delete.
        username: Authenticated username (injected by auth dependency).

    Returns:
        dict: Status confirmation.

    Raises:
        HTTPException: 404 if gift not found.
    """
    if delete_gift(gift_id):
        return {"status": "ok"}
    raise HTTPException(status_code=404, detail="Regalo no encontrado")


@app.post("/api/baby-gifts/{gift_id}/unreserve")
def admin_unreserve(
    gift_id: str, username: str = Depends(require_auth_user)
) -> dict[str, Any]:
    """Unreserve any gift (admin only, bypasses ownership check).

    Args:
        gift_id: ID of the gift to unreserve.
        username: Authenticated username (injected by auth dependency).

    Returns:
        dict: Status and updated gift.

    Raises:
        HTTPException: 400 if gift not reserved or other error.
    """
    result: dict[str, Any] = unreserve_gift(gift_id, token="", is_admin=True)
    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result["message"])
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Invitation management (admin only)
# ═══════════════════════════════════════════════════════════════════════════════
@app.get("/api/baby-gifts/invitations")
def get_invitations(
    username: str = Depends(require_auth_user),
) -> dict[str, list[dict[str, Any]]]:
    """List all invitations with reservation counts (admin only).

    Args:
        username: Authenticated username (injected by auth dependency).

    Returns:
        dict: List of invitations with computed stats.
    """
    invitations: list[dict[str, Any]] = list_invitations()

    # Count reservations per guest and compute gift stats
    gifts_data: dict[str, Any] = get_gifts_data(include_admin=True)
    all_gifts: list[dict[str, Any]] = gifts_data.get("gifts", [])
    reservation_counts: dict[str, int] = {}
    for gift in all_gifts:
        if gift.get("reserved_by"):
            token: str = gift["reserved_by"]
            reservation_counts[token] = reservation_counts.get(token, 0) + 1

    # Compute visible_gifts and available_gifts counts
    visible_gifts: int = sum(1 for g in all_gifts if not g.get("hidden", False))
    available_gifts: int = sum(
        1 for g in all_gifts if not g.get("hidden", False) and not g.get("reserved_by")
    )

    # Add reservation count and gift stats to each invitation
    for inv in invitations:
        inv["reservations"] = reservation_counts.get(inv["token"], 0)
        inv["visible_gifts"] = visible_gifts
        inv["available_gifts"] = available_gifts

    return {"invitations": invitations}


@app.post("/api/baby-gifts/invitations")
def create_new_invitation(
    data: InvitationCreate,
    username: str = Depends(require_auth_user),
    client_ip: str = Depends(require_invitation_rate_limit),
) -> dict[str, Any]:
    """Create a new invitation with 6-month expiry (admin only).

    Rate limited to 30 requests/minute per IP to prevent abuse.

    Args:
        data: Invitation creation payload with guest name.
        username: Authenticated username (injected by auth dependency).
        client_ip: Resolved client IP (injected by rate limit dependency).

    Returns:
        dict: Status and invitation details including token.

    Raises:
        HTTPException: 400 if name is empty, 401 unauthenticated, 429 rate limited.
    """
    if not data.name.strip():
        raise HTTPException(status_code=400, detail="El nombre es obligatorio")
    result: dict[str, Any] = create_invitation(data.name.strip())
    return result


@app.delete("/api/baby-gifts/invitations/{token}")
def remove_invitation(
    token: str = PathParam(..., max_length=MAX_TOKEN_LENGTH),
    username: str = Depends(require_auth_user),
) -> dict[str, Any]:
    """Delete an invitation completely (admin only).

    Args:
        token: Invitation token to delete.
        username: Authenticated username (injected by auth dependency).

    Returns:
        dict: Status confirmation.

    Raises:
        HTTPException: 401 if not authenticated, 404 if invitation not found.
    """
    result: dict[str, Any] = delete_invitation(token)
    if result["status"] == "error":
        raise HTTPException(status_code=404, detail=result["message"])
    return result


@app.post("/api/baby-gifts/invitations/{token}/revoke")
def revoke_inv(
    token: str = PathParam(..., max_length=MAX_TOKEN_LENGTH),
    username: str = Depends(require_auth_user),
) -> dict[str, Any]:
    """Revoke an invitation without deleting it (admin only).

    Revoked invitations remain in the database but cannot be used.

    Args:
        token: Invitation token to revoke.
        username: Authenticated username (injected by auth dependency).

    Returns:
        dict: Status confirmation.

    Raises:
        HTTPException: 401 if not authenticated, 404 if invitation not found.
    """
    result: dict[str, Any] = revoke_invitation(token)
    if result["status"] == "error":
        raise HTTPException(status_code=404, detail=result["message"])
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Authenticated User API (protected by nginx auth_request)
# ═══════════════════════════════════════════════════════════════════════════════
@app.get("/api/baby-gifts/user")
def get_gifts_for_user(request: Request) -> dict[str, Any]:
    """Get gifts for an authenticated user.

    Shows what's reserved but not by whom (except own).
    FAMILIA users (egnal, virchu) can see hidden gifts.
    Gifts sorted: visible first by price descending, then hidden by price descending.

    Args:
        request: FastAPI request object.

    Returns:
        dict: User name, FAMILIA status, and filtered gifts list.

    Raises:
        HTTPException: 401 if user not authenticated.
    """
    username: str | None = _get_auth_user(request)
    if not username:
        raise HTTPException(status_code=401, detail="Usuario no autenticado")

    user_token: str = f"{USER_TOKEN_PREFIX}{username}"
    user_is_familia: bool = is_familia_user(username)

    # Get gifts and filter reservation info
    data: dict[str, Any] = get_gifts_data(include_admin=False)
    filtered_gifts: list[dict[str, Any]] = []

    for gift in data.get("gifts", []):
        # Filter hidden gifts for non-FAMILIA users
        if gift.get("hidden", False) and not user_is_familia:
            continue

        if gift.get("reserved_by"):
            if gift["reserved_by"] == user_token:
                gift["reserved_by_me"] = True
            else:
                gift["reserved_by_me"] = False
                # For hidden gifts, don't show who reserved
                if gift.get("hidden", False):
                    gift["reserved_by"] = "oculto"
                    gift["reserved_by_name"] = None
                else:
                    gift["reserved_by"] = "otro"
                    gift["reserved_by_name"] = "Alguien"
        else:
            gift["reserved_by_me"] = False

        filtered_gifts.append(gift)

    # Sort: visible gifts by price descending, then hidden gifts by price descending
    visible_gifts: list[dict[str, Any]] = [
        g for g in filtered_gifts if not g.get("hidden", False)
    ]
    hidden_gifts: list[dict[str, Any]] = [
        g for g in filtered_gifts if g.get("hidden", False)
    ]

    visible_gifts.sort(
        key=lambda g: parse_price(g.get("price_range", "")), reverse=True
    )
    hidden_gifts.sort(key=lambda g: parse_price(g.get("price_range", "")), reverse=True)

    return {
        "user_name": username,
        "is_familia": user_is_familia,
        "gifts": visible_gifts + hidden_gifts,
    }


@app.post("/api/baby-gifts/user/reserve/{gift_id}")
def user_reserve(gift_id: str, request: Request) -> dict[str, Any]:
    """Reserve a gift as an authenticated user.

    Args:
        gift_id: ID of the gift to reserve.
        request: FastAPI request object.

    Returns:
        dict: Status and reserved gift details.

    Raises:
        HTTPException: 401 if not authenticated, 400 if already reserved.
    """
    username: str | None = _get_auth_user(request)
    if not username:
        raise HTTPException(status_code=401, detail="Usuario no autenticado")

    user_token: str = f"{USER_TOKEN_PREFIX}{username}"
    result: dict[str, Any] = reserve_gift(gift_id, user_token, username)

    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result["message"])

    logger.info(f"Gift reserved: {gift_id} by user {username}")
    send_gift_notification(result["gift"]["name"], username, "reserved")
    return result


@app.post("/api/baby-gifts/user/unreserve/{gift_id}")
def user_unreserve(gift_id: str, request: Request) -> dict[str, Any]:
    """Cancel own reservation as an authenticated user.

    Args:
        gift_id: ID of the gift to unreserve.
        request: FastAPI request object.

    Returns:
        dict: Status and updated gift details.

    Raises:
        HTTPException: 401 if not authenticated, 400 if not own reservation.
    """
    username: str | None = _get_auth_user(request)
    if not username:
        raise HTTPException(status_code=401, detail="Usuario no autenticado")

    user_token: str = f"{USER_TOKEN_PREFIX}{username}"
    gift: dict[str, Any] | None = get_gift(gift_id)
    gift_name: str = gift["name"] if gift else "Unknown"

    result: dict[str, Any] = unreserve_gift(gift_id, user_token, is_admin=False)
    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result["message"])

    logger.info(f"Gift unreserved: {gift_id} by user {username}")
    send_gift_notification(gift_name, username, "unreserved")
    return result


@app.post("/api/baby-gifts/user/toggle-visibility/{gift_id}")
def user_toggle_visibility(gift_id: str, request: Request) -> dict[str, Any]:
    """Toggle gift visibility (FAMILIA users only: egnal, virchu).

    Args:
        gift_id: ID of the gift to toggle.
        request: FastAPI request object.

    Returns:
        dict: Status, updated gift, and new hidden state.

    Raises:
        HTTPException: 401 if not authenticated, 403 if not FAMILIA, 404 not found.
    """
    username: str | None = _get_auth_user(request)
    if not username:
        raise HTTPException(status_code=401, detail="Usuario no autenticado")

    if not is_familia_user(username):
        raise HTTPException(
            status_code=403, detail="No tienes permiso para esta acción"
        )

    result: dict[str, Any] = toggle_gift_visibility(gift_id)
    if result["status"] == "error":
        raise HTTPException(status_code=404, detail=result["message"])

    logger.info(
        f"Gift visibility toggled: {gift_id} by {username}, hidden={result['hidden']}"
    )
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Guest API (public, token-based)
# ═══════════════════════════════════════════════════════════════════════════════
@app.get("/api/baby-gifts/guest/{token}")
def get_gifts_for_guest(
    token: str = PathParam(..., max_length=MAX_TOKEN_LENGTH),
    client_ip: str = Depends(require_rate_limit),
) -> dict[str, Any]:
    """Get gifts for a guest via invitation token.

    Shows what's reserved but not by whom (except own).
    Hidden gifts are not shown to guests.
    Gifts are sorted by price descending.

    Args:
        token: Invitation token from URL path.
        client_ip: Resolved client IP (injected by rate limit dependency).

    Returns:
        dict: Guest name and filtered gifts list.

    Raises:
        HTTPException: 401 if token invalid/expired, 429 if rate limited.
    """
    guest: dict[str, Any] | None = validate_invitation(token)
    if not guest:
        raise HTTPException(status_code=401, detail="Token inválido o expirado")

    # Get gifts and filter reservation info
    data: dict[str, Any] = get_gifts_data(include_admin=False)
    filtered_gifts: list[dict[str, Any]] = []

    for gift in data.get("gifts", []):
        # Filter out hidden gifts for guests
        if gift.get("hidden", False):
            continue

        if gift.get("reserved_by"):
            if gift["reserved_by"] == token:
                gift["reserved_by_me"] = True
            else:
                gift["reserved_by_me"] = False
                gift["reserved_by"] = "otro"
                gift["reserved_by_name"] = "Alguien"
        else:
            gift["reserved_by_me"] = False

        filtered_gifts.append(gift)

    # Sort by price descending
    filtered_gifts.sort(
        key=lambda g: parse_price(g.get("price_range", "")), reverse=True
    )

    return {
        "guest_name": guest["name"],
        "gifts": filtered_gifts,
    }


@app.post("/api/baby-gifts/guest/{token}/reserve/{gift_id}")
def guest_reserve(
    gift_id: str,
    token: str = PathParam(..., max_length=MAX_TOKEN_LENGTH),
    client_ip: str = Depends(require_rate_limit),
) -> dict[str, Any]:
    """Reserve a gift as a guest.

    Args:
        token: Invitation token from URL path.
        gift_id: ID of the gift to reserve.
        client_ip: Resolved client IP (injected by rate limit dependency).

    Returns:
        dict: Status and reserved gift details.

    Raises:
        HTTPException: 401 if token invalid, 400 already reserved, 429 rate limited.
    """
    guest: dict[str, Any] | None = validate_invitation(token)
    if not guest:
        raise HTTPException(status_code=401, detail="Token inválido o expirado")

    result: dict[str, Any] = reserve_gift(gift_id, token, guest["name"])
    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result["message"])

    logger.info(f"Gift reserved: {gift_id} by {guest['name']}")
    send_gift_notification(result["gift"]["name"], guest["name"], "reserved")
    return result


@app.post("/api/baby-gifts/guest/{token}/unreserve/{gift_id}")
def guest_unreserve(
    gift_id: str,
    token: str = PathParam(..., max_length=MAX_TOKEN_LENGTH),
    client_ip: str = Depends(require_rate_limit),
) -> dict[str, Any]:
    """Cancel own reservation as a guest.

    Args:
        token: Invitation token from URL path.
        gift_id: ID of the gift to unreserve.
        client_ip: Resolved client IP (injected by rate limit dependency).

    Returns:
        dict: Status and updated gift details.

    Raises:
        HTTPException: 401 token invalid, 400 not own reservation, 429 rate limited.
    """
    guest: dict[str, Any] | None = validate_invitation(token)
    if not guest:
        raise HTTPException(status_code=401, detail="Token inválido o expirado")

    gift: dict[str, Any] | None = get_gift(gift_id)
    gift_name: str = gift["name"] if gift else "Unknown"

    result: dict[str, Any] = unreserve_gift(gift_id, token, is_admin=False)
    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result["message"])

    logger.info(f"Gift unreserved: {gift_id} by {guest['name']}")
    send_gift_notification(gift_name, guest["name"], "unreserved")
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Static assets
# ═══════════════════════════════════════════════════════════════════════════════
if _STATIC_DIR.exists():
    app.mount(
        "/static/baby-gifts", StaticFiles(directory=str(_STATIC_DIR)), name="static"
    )
