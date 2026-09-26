"""Baby Gifts Service ??? standalone microservice for baby gift registry.
Three access modes:
1. Admin (authenticated via nginx auth_request + SUPER profile): full CRUD + invitation management
2. Authenticated User (via nginx auth_request): view gifts + reserve/unreserve
3. Guest (via invitation token): view gifts + reserve/unreserve own
Serves:
  GET  /smart-home/baby-gifts       ??? SPA (admin/user view, requires auth)
  GET  /baby-gifts/i/{token}        ??? SPA (guest view, token-based access)
  # Admin endpoints (protected by nginx auth_request, requires SUPER)
  GET  /api/baby-gifts              ??? all gifts (with reservation details)
  POST /api/baby-gifts              ??? add gift
  PUT  /api/baby-gifts/{id}         ??? update gift
  DELETE /api/baby-gifts/{id}       ??? delete gift
  POST /api/baby-gifts/{id}/unreserve ??? admin can unreserve any gift
  GET  /api/baby-gifts/invitations  ??? list all invitations
  POST /api/baby-gifts/invitations  ??? create invitation
  DELETE /api/baby-gifts/invitations/{token} ??? delete invitation
  POST /api/baby-gifts/invitations/{token}/revoke ??? revoke invitation
  PUT  /api/baby-gifts/categories   ??? update categories
  # Authenticated user endpoints (protected by nginx auth_request)
  GET  /api/baby-gifts/user              ??? get gifts for authenticated user
  POST /api/baby-gifts/user/reserve/{id} ??? reserve a gift as authenticated user
  POST /api/baby-gifts/user/unreserve/{id} ??? unreserve own gift
  # Guest endpoints (token-based, public)
  GET  /api/baby-gifts/guest/{token}           ??? get gifts for guest
  POST /api/baby-gifts/guest/{token}/reserve/{id}   ??? reserve a gift
  POST /api/baby-gifts/guest/{token}/unreserve/{id} ??? unreserve own gift
  GET  /health                      ??? health check
  GET  /api/health/baby-gifts       ??? health check alias
Port: 8004
"""
import logging
import time
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from gifts_controller import (
    add_gift,
    check_rate_limit,
    create_invitation,
    delete_gift,
    delete_invitation,
    get_gift,
    get_gifts_data,
    is_healthy,
    list_invitations,
    reserve_gift,
    revoke_invitation,
    unreserve_gift,
    update_categories,
    update_gift,
    validate_invitation,
)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)
app = FastAPI(title="Baby Gifts Service", version="1.0.0")
# ?????? Pydantic models ?????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????
class GiftCreate(BaseModel):
    name: str
    description: str = ""
    url: str = ""
    price_range: str = ""
    category: str = "otros"
    priority: int = 2
class GiftUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    url: Optional[str] = None
    price_range: Optional[str] = None
    category: Optional[str] = None
    priority: Optional[int] = None
class InvitationCreate(BaseModel):
    name: str
class CategoriesUpdate(BaseModel):
    categories: list
# ?????? Helpers ?????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????
def _serve_html(filename: str, guest_token: str = None, auth_user: dict = None) -> HTMLResponse:
    """Serve an HTML file with no-cache headers and optional guest token or auth user injection."""
    path = Path(__file__).parent / "static" / filename
    content = path.read_text(encoding="utf-8")
    # Inject cache buster
    content = content.replace("</head>", f"<!-- v:{int(time.time())} -->\n</head>")
    # Inject guest token if provided (for guest view)
    if guest_token:
        import json
        content = content.replace(
            "window.GUEST_TOKEN = null;",
            f'window.GUEST_TOKEN = {json.dumps(guest_token)};'
        )
    # Inject auth user if provided (for authenticated user view)
    if auth_user:
        import json
        content = content.replace(
            "window.AUTH_USER = null;",
            f'window.AUTH_USER = {json.dumps(auth_user)};'
        )
    return HTMLResponse(
        content=content,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )
def _get_client_ip(request: Request) -> str:
    """Get client IP from request, considering proxies."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
def _get_auth_user(request: Request) -> Optional[str]:
    """Get authenticated username from nginx auth_request header."""
    return request.headers.get("X-Auth-User")
def _is_admin(request: Request) -> bool:
    """Check if the user is an admin (has babygifts management in their profile).
    For now, we consider all users with X-Auth-User header as potential admins
    if they access the admin endpoints. The nginx config should enforce which
    users can access which endpoints based on their profiles.
    In practice, only users with 'babygifts' in their profile with view_level >= 2
    should be able to manage invitations and gifts.
    """
    # Check for special admin header that backend could set
    # For now, we rely on nginx to filter admin endpoints
    return request.headers.get("X-Auth-Role") == "admin"
# ?????? Health ????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????
@app.get("/health")
def health():
    """Health check ??? used by nginx and the dashboard."""
    return {"online": is_healthy(), "service": "baby-gifts"}
@app.get("/api/health/baby-gifts")
def health_alias():
    """Health check alias ??? matches path expected by the dashboard."""
    return {"online": is_healthy()}
# ?????? SPA serving ?????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????
@app.get("/smart-home/baby-gifts")
async def serve_admin(request: Request):
    """Serves the admin/user SPA (protected by nginx auth_request).
    If user is an admin (SUPER profile), they get full management capabilities.
    If user is a regular authenticated user, they can view and reserve gifts.
    """
    username = _get_auth_user(request)
    if username:
        # Authenticated user - pass their info to the frontend
        # The frontend will detect if they're admin based on available endpoints
        return _serve_html("baby-gifts.html", auth_user={"username": username})
    else:
        # Admin view (legacy, no specific user info)
        return _serve_html("baby-gifts.html")
@app.get("/baby-gifts/i/{token}")
async def serve_guest(token: str, request: Request):
    """Serves the guest SPA (public, token-validated).
    NOTE: No rate limiting here - we only validate token once on page load.
    Rate limiting is done on API calls instead.
    """
    # Validate token (no rate limit for initial page load)
    guest = validate_invitation(token)
    if not guest:
        raise HTTPException(
            status_code=404,
            detail="Enlace no v??lido o expirado"
        )
    client_ip = _get_client_ip(request)
    logger.info(f"Guest access: {guest['name']} from {client_ip}")
    return _serve_html("baby-gifts.html", guest_token=token)
# ?????? Admin API (protected by nginx auth_request) ?????????????????????????????????????????????????????????????????????????????????????????????
@app.get("/api/baby-gifts")
def get_all_gifts():
    """Get all gifts with full reservation details (admin only)."""
    return get_gifts_data(include_admin=True)
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
@app.put("/api/baby-gifts/categories")
def modify_categories(data: CategoriesUpdate):
    """Update gift categories (admin only)."""
    return update_categories(data.categories)
# ?????? Invitation management (admin only) ????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????
@app.get("/api/baby-gifts/invitations")
def get_invitations():
    """List all invitations (admin only)."""
    invitations = list_invitations()
    # Count reservations per guest
    gifts_data = get_gifts_data(include_admin=True)
    reservation_counts = {}
    for gift in gifts_data.get("gifts", []):
        if gift.get("reserved_by"):
            token = gift["reserved_by"]
            reservation_counts[token] = reservation_counts.get(token, 0) + 1
    # Add reservation count to each invitation
    for inv in invitations:
        inv["reservations"] = reservation_counts.get(inv["token"], 0)
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
# ?????? Authenticated User API (protected by nginx auth_request) ??????????????????????????????????????????????????????
@app.get("/api/baby-gifts/user")
def get_gifts_for_user(request: Request):
    """Get gifts for an authenticated user. Shows what's reserved but not by whom (except own)."""
    username = _get_auth_user(request)
    if not username:
        raise HTTPException(status_code=401, detail="Usuario no autenticado")
    # User token format: "user:username"
    user_token = f"user:{username}"
    # Get gifts and filter reservation info
    data = get_gifts_data(include_admin=False)
    for gift in data.get("gifts", []):
        if gift.get("reserved_by"):
            if gift["reserved_by"] == user_token:
                # User's own reservation
                gift["reserved_by_me"] = True
            else:
                # Someone else's reservation - hide details
                gift["reserved_by_me"] = False
                gift["reserved_by"] = "otro"
                gift["reserved_by_name"] = "Alguien"
        else:
            gift["reserved_by_me"] = False
    return {
        "user_name": username,
        "gifts": data.get("gifts", []),
        "categories": data.get("categories", []),
    }
@app.post("/api/baby-gifts/user/reserve/{gift_id}")
def user_reserve(gift_id: str, request: Request):
    """Reserve a gift as an authenticated user."""
    username = _get_auth_user(request)
    if not username:
        raise HTTPException(status_code=401, detail="Usuario no autenticado")
    # User token format: "user:username"
    user_token = f"user:{username}"
    # Reserve
    result = reserve_gift(gift_id, user_token, username)
    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result["message"])
    logger.info(f"Gift reserved: {gift_id} by user {username}")
    return result
@app.post("/api/baby-gifts/user/unreserve/{gift_id}")
def user_unreserve(gift_id: str, request: Request):
    """Cancel own reservation as an authenticated user."""
    username = _get_auth_user(request)
    if not username:
        raise HTTPException(status_code=401, detail="Usuario no autenticado")
    # User token format: "user:username"
    user_token = f"user:{username}"
    # Unreserve (only own)
    result = unreserve_gift(gift_id, user_token, is_admin=False)
    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result["message"])
    logger.info(f"Gift unreserved: {gift_id} by user {username}")
    return result
# ?????? Guest API (public, token-based) ?????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????
@app.get("/api/baby-gifts/guest/{token}")
def get_gifts_for_guest(token: str, request: Request):
    """Get gifts for a guest. Shows what's reserved but not by whom (except own)."""
    # Rate limit
    client_ip = _get_client_ip(request)
    if not check_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail="Demasiados intentos. Espera un momento.")
    # Validate
    guest = validate_invitation(token)
    if not guest:
        raise HTTPException(status_code=401, detail="Token inv??lido o expirado")
    # Get gifts and filter reservation info
    data = get_gifts_data(include_admin=False)
    for gift in data.get("gifts", []):
        if gift.get("reserved_by"):
            if gift["reserved_by"] == token:
                # Guest's own reservation - show their name
                gift["reserved_by_me"] = True
            else:
                # Someone else's reservation - hide details
                gift["reserved_by_me"] = False
                gift["reserved_by"] = "otro"
                gift["reserved_by_name"] = "Alguien"
        else:
            gift["reserved_by_me"] = False
    return {
        "guest_name": guest["name"],
        "gifts": data.get("gifts", []),
        "categories": data.get("categories", []),
    }
@app.post("/api/baby-gifts/guest/{token}/reserve/{gift_id}")
def guest_reserve(token: str, gift_id: str, request: Request):
    """Reserve a gift as a guest."""
    # Rate limit
    client_ip = _get_client_ip(request)
    if not check_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail="Demasiados intentos. Espera un momento.")
    # Validate
    guest = validate_invitation(token)
    if not guest:
        raise HTTPException(status_code=401, detail="Token inv??lido o expirado")
    # Reserve
    result = reserve_gift(gift_id, token, guest["name"])
    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result["message"])
    logger.info(f"Gift reserved: {gift_id} by {guest['name']}")
    return result
@app.post("/api/baby-gifts/guest/{token}/unreserve/{gift_id}")
def guest_unreserve(token: str, gift_id: str, request: Request):
    """Cancel own reservation as a guest."""
    # Rate limit
    client_ip = _get_client_ip(request)
    if not check_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail="Demasiados intentos. Espera un momento.")
    # Validate
    guest = validate_invitation(token)
    if not guest:
        raise HTTPException(status_code=401, detail="Token inv??lido o expirado")
    # Unreserve (only own)
    result = unreserve_gift(gift_id, token, is_admin=False)
    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result["message"])
    logger.info(f"Gift unreserved: {gift_id} by {guest['name']}")
    return result
# ?????? Static assets ???????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????
_static_dir = Path(__file__).parent / "static"
if _static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")
