"""Baby Gifts service proxy routes.

Proxies requests to the baby-gifts-service for gift registry.
"""

from fastapi import APIRouter, Request

from api.auth_helpers import require_app_write

from .base import ServiceProxy

router = APIRouter(prefix="/api/baby-gifts", tags=["Baby Gifts"])

SERVICE_URL = "http://baby-gifts-service:8004"

_proxy = ServiceProxy(SERVICE_URL)


def _forward_headers(request: Request, *names: str) -> dict | None:
    """Collect the subset of inbound headers that must reach the service.

    Returns ``None`` when none of the requested headers are present so the
    proxy call omits the ``headers`` argument entirely.
    """
    headers = {n: request.headers[n] for n in names if n in request.headers}
    return headers or None


# ── Admin endpoints ──────────────────────────────────────────────────────────


@router.get("")
async def get_all_baby_gifts(request: Request):
    """Get all gifts with full reservation details (admin only)."""
    require_app_write(request, "babygifts")
    return await _proxy.get("/api/baby-gifts")


@router.post("")
async def create_baby_gift(request: Request):
    """Add a new gift (admin only)."""
    require_app_write(request, "babygifts")
    body = await request.json()
    return await _proxy.post("/api/baby-gifts", json=body)


@router.put("/{gift_id}")
async def update_baby_gift(gift_id: str, request: Request):
    """Update a gift (admin only)."""
    require_app_write(request, "babygifts")
    body = await request.json()
    return await _proxy.put(f"/api/baby-gifts/{gift_id}", json=body)


@router.delete("/{gift_id}")
async def delete_baby_gift(gift_id: str, request: Request):
    """Delete a gift (admin only)."""
    require_app_write(request, "babygifts")
    return await _proxy.delete(f"/api/baby-gifts/{gift_id}")


@router.post("/{gift_id}/unreserve")
async def admin_unreserve_baby_gift(gift_id: str, request: Request):
    """Admin can unreserve any gift."""
    require_app_write(request, "babygifts")
    return await _proxy.post(f"/api/baby-gifts/{gift_id}/unreserve")


@router.put("/categories")
async def update_baby_gifts_categories(request: Request):
    """Update gift categories (admin only)."""
    require_app_write(request, "babygifts")
    body = await request.json()
    return await _proxy.put("/api/baby-gifts/categories", json=body)


# ── Invitation management ────────────────────────────────────────────────────


@router.get("/invitations")
async def get_baby_gifts_invitations(request: Request):
    """List all invitations (admin only)."""
    require_app_write(request, "babygifts")
    return await _proxy.get("/api/baby-gifts/invitations")


@router.post("/invitations")
async def create_baby_gifts_invitation(request: Request):
    """Create a new invitation (admin only)."""
    require_app_write(request, "babygifts")
    body = await request.json()
    return await _proxy.post("/api/baby-gifts/invitations", json=body)


@router.delete("/invitations/{token}")
async def delete_baby_gifts_invitation(token: str, request: Request):
    """Delete an invitation (admin only)."""
    require_app_write(request, "babygifts")
    return await _proxy.delete(f"/api/baby-gifts/invitations/{token}")


@router.post("/invitations/{token}/revoke")
async def revoke_baby_gifts_invitation(token: str, request: Request):
    """Revoke an invitation without deleting it (admin only)."""
    require_app_write(request, "babygifts")
    return await _proxy.post(f"/api/baby-gifts/invitations/{token}/revoke")


# ── Authenticated user endpoints ─────────────────────────────────────────────


@router.get("/user")
async def get_baby_gifts_for_user(request: Request):
    """Get gifts for an authenticated user."""
    headers = _forward_headers(request, "X-Auth-User")
    return await _proxy.get("/api/baby-gifts/user", headers=headers)


@router.post("/user/reserve/{gift_id}")
async def user_reserve_baby_gift(gift_id: str, request: Request):
    """Reserve a gift as an authenticated user."""
    headers = _forward_headers(request, "X-Auth-User")
    return await _proxy.post(f"/api/baby-gifts/user/reserve/{gift_id}", headers=headers)


@router.post("/user/unreserve/{gift_id}")
async def user_unreserve_baby_gift(gift_id: str, request: Request):
    """Cancel own reservation as an authenticated user."""
    headers = _forward_headers(request, "X-Auth-User")
    return await _proxy.post(
        f"/api/baby-gifts/user/unreserve/{gift_id}", headers=headers
    )


# ── Guest endpoints (public, token-based) ────────────────────────────────────


@router.get("/guest/{token}")
async def get_baby_gifts_for_guest(token: str, request: Request):
    """Get gifts for a guest."""
    headers = _forward_headers(request, "X-Forwarded-For")
    return await _proxy.get(f"/api/baby-gifts/guest/{token}", headers=headers)


@router.post("/guest/{token}/reserve/{gift_id}")
async def guest_reserve_baby_gift(token: str, gift_id: str, request: Request):
    """Reserve a gift as a guest."""
    headers = _forward_headers(request, "X-Forwarded-For")
    return await _proxy.post(
        f"/api/baby-gifts/guest/{token}/reserve/{gift_id}", headers=headers
    )


@router.post("/guest/{token}/unreserve/{gift_id}")
async def guest_unreserve_baby_gift(token: str, gift_id: str, request: Request):
    """Cancel own reservation as a guest."""
    headers = _forward_headers(request, "X-Forwarded-For")
    return await _proxy.post(
        f"/api/baby-gifts/guest/{token}/unreserve/{gift_id}", headers=headers
    )
