"""Baby Gifts Service — standalone microservice for baby gift registry.

Three access modes:
1. Admin (authenticated via nginx auth_request + SUPER profile): full CRUD + invitation management
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

import logging
from pathlib import Path

from config import TRUSTED_PROXY_IPS
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from gifts_controller import (
    add_gift,
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
from pydantic import BaseModel
from utils import parse_price

# Import serve_html from shared lib (path added via PYTHONPATH in Dockerfile/CI;
# fallback inserts repo root for local development — mirrors notifier.py).
try:
    from libs.html_serving import serve_html
except ImportError:  # pragma: no cover
    import sys

    sys.path.insert(0, str(__file__).replace("\\", "/").split("/services/")[0])
    from libs.html_serving import serve_html

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Baby Gifts Service",
    version="1.0.0",
    docs_url="/swagger",
    redoc_url="/redoc",
)


# ═══════════════════════════════════════════════════════════════════════════════
# Pydantic models
# ═══════════════════════════════════════════════════════════════════════════════
class GiftCreate(BaseModel):
    name: str
    description: str = ""
    url: str = ""
    price_range: str = ""
    priority: int = 2


class GiftUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    url: str | None = None
    price_range: str | None = None
    priority: int | None = None


class InvitationCreate(BaseModel):
    name: str


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════
_STATIC_DIR = Path(__file__).parent / "static"


def _get_client_ip(request: Request) -> str:
    """Get client IP from request, considering trusted proxies only.

    Only trusts X-Forwarded-For header if the direct connection comes from
    a trusted proxy IP (e.g., nginx container). This prevents IP spoofing.
    """
    client_ip = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("X-Forwarded-For")

    # Only trust X-Forwarded-For if request comes from trusted proxy
    if forwarded and client_ip in TRUSTED_PROXY_IPS:
        return forwarded.split(",")[0].strip()

    return client_ip


def require_rate_limit(request: Request) -> str:
    """FastAPI dependency: enforce the per-IP rate limit for guest endpoints.

    Resolves the client IP (honouring trusted proxies) and raises 429 when the
    limit is exceeded. Returns the resolved client IP so handlers can reuse it.
    """
    client_ip = _get_client_ip(request)
    if not check_rate_limit(client_ip):
        raise HTTPException(
            status_code=429, detail="Demasiados intentos. Espera un momento."
        )
    return client_ip


def _get_auth_user(request: Request) -> str | None:
    """Get authenticated username from nginx auth_request header."""
    return request.headers.get("X-Auth-User")


def _truncate_token(token: str) -> str:
    """Truncate token for safe logging (show last 6 chars only)."""
    if len(token) > 6:
        return f"...{token[-6:]}"
    return token


# ═══════════════════════════════════════════════════════════════════════════════
# Health endpoints
# ═══════════════════════════════════════════════════════════════════════════════
@app.get("/health")
def health():
    """Health check — used by nginx and the dashboard."""
    return {"online": is_healthy(), "service": "baby-gifts"}


@app.get("/api/health/baby-gifts")
def health_alias():
    """Health check alias — matches path expected by the dashboard."""
    return {"online": is_healthy()}


# ═══════════════════════════════════════════════════════════════════════════════
# SPA serving
# ═══════════════════════════════════════════════════════════════════════════════
@app.get("/smart-home/baby-gifts")
async def serve_admin(request: Request):
    """Serves the admin/user SPA (protected by nginx auth_request).

    If user is an admin (SUPER profile), they get full management capabilities.
    If user is a regular authenticated user, they can view and reserve gifts.
    """
    username = _get_auth_user(request)
    if username:
        return serve_html(
            _STATIC_DIR, "baby-gifts.html", auth_user={"username": username}
        )
    else:
        return serve_html(_STATIC_DIR, "baby-gifts.html")


@app.get("/guest/baby-gifts/{token}")
async def serve_guest(token: str, request: Request):
    """Serves the guest SPA (public, token-validated).

    NOTE: No rate limiting here - we only validate token once on page load.
    Rate limiting is done on API calls instead.
    """
    guest = validate_invitation(token)
    if not guest:
        raise HTTPException(status_code=404, detail="Enlace no válido o expirado")

    client_ip = _get_client_ip(request)
    logger.info(
        f"Guest access: {guest['name']} (token: {_truncate_token(token)}) from {client_ip}"
    )
    return serve_html(_STATIC_DIR, "baby-gifts.html", guest_token=token)


# ═══════════════════════════════════════════════════════════════════════════════
# Admin API (protected by nginx auth_request)
# ═══════════════════════════════════════════════════════════════════════════════
@app.get("/api/baby-gifts")
def get_all_gifts(request: Request):
    """Get all gifts with full reservation details (admin only)."""
    username = _get_auth_user(request)
    user_is_familia = is_familia_user(username) if username else False
    data = get_gifts_data(include_admin=True)
    return {
        "gifts": data.get("gifts", []),
        "is_familia": user_is_familia,
        "user_name": username,
    }


@app.post("/api/baby-gifts")
def create_gift(gift: GiftCreate):
    """Add a new gift (admin only)."""
    new_gift = add_gift(gift.model_dump())
    return {"status": "ok", "gift": new_gift}


@app.put("/api/baby-gifts/{gift_id}")
def modify_gift(gift_id: str, gift: GiftUpdate):
    """Update a gift (admin only)."""
    updates = {k: v for k, v in gift.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No hay cambios")
    updated = update_gift(gift_id, updates)
    if not updated:
        raise HTTPException(status_code=404, detail="Regalo no encontrado")
    return {"status": "ok", "gift": updated}


@app.delete("/api/baby-gifts/{gift_id}")
def remove_gift(gift_id: str):
    """Delete a gift (admin only)."""
    if delete_gift(gift_id):
        return {"status": "ok"}
    raise HTTPException(status_code=404, detail="Regalo no encontrado")


@app.post("/api/baby-gifts/{gift_id}/unreserve")
def admin_unreserve(gift_id: str):
    """Admin can unreserve any gift."""
    result = unreserve_gift(gift_id, token="", is_admin=True)
    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result["message"])
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Invitation management (admin only)
# ═══════════════════════════════════════════════════════════════════════════════
@app.get("/api/baby-gifts/invitations")
def get_invitations():
    """List all invitations (admin only)."""
    invitations = list_invitations()

    # Count reservations per guest and compute gift stats
    gifts_data = get_gifts_data(include_admin=True)
    all_gifts = gifts_data.get("gifts", [])
    reservation_counts: dict[str, int] = {}
    for gift in all_gifts:
        if gift.get("reserved_by"):
            token = gift["reserved_by"]
            reservation_counts[token] = reservation_counts.get(token, 0) + 1

    # Compute visible_gifts and available_gifts counts
    visible_gifts = sum(1 for g in all_gifts if not g.get("hidden", False))
    available_gifts = sum(
        1 for g in all_gifts if not g.get("hidden", False) and not g.get("reserved_by")
    )

    # Add reservation count and gift stats to each invitation
    for inv in invitations:
        inv["reservations"] = reservation_counts.get(inv["token"], 0)
        inv["visible_gifts"] = visible_gifts
        inv["available_gifts"] = available_gifts

    return {"invitations": invitations}


@app.post("/api/baby-gifts/invitations")
def create_new_invitation(data: InvitationCreate):
    """Create a new invitation (admin only)."""
    if not data.name.strip():
        raise HTTPException(status_code=400, detail="El nombre es obligatorio")
    result = create_invitation(data.name.strip())
    return result


@app.delete("/api/baby-gifts/invitations/{token}")
def remove_invitation(token: str):
    """Delete an invitation (admin only)."""
    result = delete_invitation(token)
    if result["status"] == "error":
        raise HTTPException(status_code=404, detail=result["message"])
    return result


@app.post("/api/baby-gifts/invitations/{token}/revoke")
def revoke_inv(token: str):
    """Revoke an invitation without deleting it (admin only)."""
    result = revoke_invitation(token)
    if result["status"] == "error":
        raise HTTPException(status_code=404, detail=result["message"])
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Authenticated User API (protected by nginx auth_request)
# ═══════════════════════════════════════════════════════════════════════════════
@app.get("/api/baby-gifts/user")
def get_gifts_for_user(request: Request):
    """Get gifts for an authenticated user.

    Shows what's reserved but not by whom (except own).
    FAMILIA users (egnal, virchu) can see hidden gifts.
    Gifts are sorted: visible first by price descending, then hidden by price descending.
    """
    username = _get_auth_user(request)
    if not username:
        raise HTTPException(status_code=401, detail="Usuario no autenticado")

    user_token = f"user:{username}"
    user_is_familia = is_familia_user(username)

    # Get gifts and filter reservation info
    data = get_gifts_data(include_admin=False)
    filtered_gifts = []

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
    visible_gifts = [g for g in filtered_gifts if not g.get("hidden", False)]
    hidden_gifts = [g for g in filtered_gifts if g.get("hidden", False)]

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
def user_reserve(gift_id: str, request: Request):
    """Reserve a gift as an authenticated user."""
    username = _get_auth_user(request)
    if not username:
        raise HTTPException(status_code=401, detail="Usuario no autenticado")

    user_token = f"user:{username}"
    result = reserve_gift(gift_id, user_token, username)

    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result["message"])

    logger.info(f"Gift reserved: {gift_id} by user {username}")
    send_gift_notification(result["gift"]["name"], username, "reserved")
    return result


@app.post("/api/baby-gifts/user/unreserve/{gift_id}")
def user_unreserve(gift_id: str, request: Request):
    """Cancel own reservation as an authenticated user."""
    username = _get_auth_user(request)
    if not username:
        raise HTTPException(status_code=401, detail="Usuario no autenticado")

    user_token = f"user:{username}"
    gift = get_gift(gift_id)
    gift_name = gift["name"] if gift else "Unknown"

    result = unreserve_gift(gift_id, user_token, is_admin=False)
    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result["message"])

    logger.info(f"Gift unreserved: {gift_id} by user {username}")
    send_gift_notification(gift_name, username, "unreserved")
    return result


@app.post("/api/baby-gifts/user/toggle-visibility/{gift_id}")
def user_toggle_visibility(gift_id: str, request: Request):
    """Toggle gift visibility (FAMILIA users only: egnal, virchu)."""
    username = _get_auth_user(request)
    if not username:
        raise HTTPException(status_code=401, detail="Usuario no autenticado")

    if not is_familia_user(username):
        raise HTTPException(
            status_code=403, detail="No tienes permiso para esta acción"
        )

    result = toggle_gift_visibility(gift_id)
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
    token: str,
    client_ip: str = Depends(require_rate_limit),
):
    """Get gifts for a guest.

    Shows what's reserved but not by whom (except own).
    Hidden gifts are not shown to guests.
    Gifts are sorted by price descending.
    """
    guest = validate_invitation(token)
    if not guest:
        raise HTTPException(status_code=401, detail="Token inválido o expirado")

    # Get gifts and filter reservation info
    data = get_gifts_data(include_admin=False)
    filtered_gifts = []

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
    token: str,
    gift_id: str,
    client_ip: str = Depends(require_rate_limit),
):
    """Reserve a gift as a guest."""
    guest = validate_invitation(token)
    if not guest:
        raise HTTPException(status_code=401, detail="Token inválido o expirado")

    result = reserve_gift(gift_id, token, guest["name"])
    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result["message"])

    logger.info(f"Gift reserved: {gift_id} by {guest['name']}")
    send_gift_notification(result["gift"]["name"], guest["name"], "reserved")
    return result


@app.post("/api/baby-gifts/guest/{token}/unreserve/{gift_id}")
def guest_unreserve(
    token: str,
    gift_id: str,
    client_ip: str = Depends(require_rate_limit),
):
    """Cancel own reservation as a guest."""
    guest = validate_invitation(token)
    if not guest:
        raise HTTPException(status_code=401, detail="Token inválido o expirado")

    gift = get_gift(gift_id)
    gift_name = gift["name"] if gift else "Unknown"

    result = unreserve_gift(gift_id, token, is_admin=False)
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
