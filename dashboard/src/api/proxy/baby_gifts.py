"""Baby Gifts service proxy routes.

Proxies requests to the baby-gifts-service for gift registry.
"""

import httpx
from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/baby-gifts", tags=["Baby Gifts"])

SERVICE_URL = "http://baby-gifts-service:8004"


# ── Admin endpoints ──────────────────────────────────────────────────────────


@router.get("")
async def get_all_baby_gifts():
    """Get all gifts with full reservation details (admin only)."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{SERVICE_URL}/api/baby-gifts")
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("")
async def create_baby_gift(request: Request):
    """Add a new gift (admin only)."""
    try:
        body = await request.json()
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(f"{SERVICE_URL}/api/baby-gifts", json=body)
            if resp.status_code >= 400:
                raise HTTPException(
                    status_code=resp.status_code,
                    detail=resp.json().get("detail", "Error"),
                )
            return resp.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.put("/{gift_id}")
async def update_baby_gift(gift_id: str, request: Request):
    """Update a gift (admin only)."""
    try:
        body = await request.json()
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.put(
                f"{SERVICE_URL}/api/baby-gifts/{gift_id}", json=body
            )
            if resp.status_code >= 400:
                raise HTTPException(
                    status_code=resp.status_code,
                    detail=resp.json().get("detail", "Error"),
                )
            return resp.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.delete("/{gift_id}")
async def delete_baby_gift(gift_id: str):
    """Delete a gift (admin only)."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.delete(f"{SERVICE_URL}/api/baby-gifts/{gift_id}")
            if resp.status_code >= 400:
                raise HTTPException(
                    status_code=resp.status_code,
                    detail=resp.json().get("detail", "Error"),
                )
            return resp.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/{gift_id}/unreserve")
async def admin_unreserve_baby_gift(gift_id: str):
    """Admin can unreserve any gift."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{SERVICE_URL}/api/baby-gifts/{gift_id}/unreserve"
            )
            if resp.status_code >= 400:
                raise HTTPException(
                    status_code=resp.status_code,
                    detail=resp.json().get("detail", "Error"),
                )
            return resp.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.put("/categories")
async def update_baby_gifts_categories(request: Request):
    """Update gift categories (admin only)."""
    try:
        body = await request.json()
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.put(
                f"{SERVICE_URL}/api/baby-gifts/categories", json=body
            )
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


# ── Invitation management ────────────────────────────────────────────────────


@router.get("/invitations")
async def get_baby_gifts_invitations():
    """List all invitations (admin only)."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{SERVICE_URL}/api/baby-gifts/invitations")
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/invitations")
async def create_baby_gifts_invitation(request: Request):
    """Create a new invitation (admin only)."""
    try:
        body = await request.json()
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{SERVICE_URL}/api/baby-gifts/invitations", json=body
            )
            if resp.status_code >= 400:
                raise HTTPException(
                    status_code=resp.status_code,
                    detail=resp.json().get("detail", "Error"),
                )
            return resp.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.delete("/invitations/{token}")
async def delete_baby_gifts_invitation(token: str):
    """Delete an invitation (admin only)."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.delete(
                f"{SERVICE_URL}/api/baby-gifts/invitations/{token}"
            )
            if resp.status_code >= 400:
                raise HTTPException(
                    status_code=resp.status_code,
                    detail=resp.json().get("detail", "Error"),
                )
            return resp.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/invitations/{token}/revoke")
async def revoke_baby_gifts_invitation(token: str):
    """Revoke an invitation without deleting it (admin only)."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{SERVICE_URL}/api/baby-gifts/invitations/{token}/revoke"
            )
            if resp.status_code >= 400:
                raise HTTPException(
                    status_code=resp.status_code,
                    detail=resp.json().get("detail", "Error"),
                )
            return resp.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


# ── Authenticated user endpoints ─────────────────────────────────────────────


@router.get("/user")
async def get_baby_gifts_for_user(request: Request):
    """Get gifts for an authenticated user."""
    try:
        headers = {}
        if "X-Auth-User" in request.headers:
            headers["X-Auth-User"] = request.headers["X-Auth-User"]
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{SERVICE_URL}/api/baby-gifts/user", headers=headers
            )
            if resp.status_code >= 400:
                raise HTTPException(
                    status_code=resp.status_code,
                    detail=resp.json().get("detail", "Error"),
                )
            return resp.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/user/reserve/{gift_id}")
async def user_reserve_baby_gift(gift_id: str, request: Request):
    """Reserve a gift as an authenticated user."""
    try:
        headers = {}
        if "X-Auth-User" in request.headers:
            headers["X-Auth-User"] = request.headers["X-Auth-User"]
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{SERVICE_URL}/api/baby-gifts/user/reserve/{gift_id}",
                headers=headers,
            )
            if resp.status_code >= 400:
                raise HTTPException(
                    status_code=resp.status_code,
                    detail=resp.json().get("detail", "Error"),
                )
            return resp.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/user/unreserve/{gift_id}")
async def user_unreserve_baby_gift(gift_id: str, request: Request):
    """Cancel own reservation as an authenticated user."""
    try:
        headers = {}
        if "X-Auth-User" in request.headers:
            headers["X-Auth-User"] = request.headers["X-Auth-User"]
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{SERVICE_URL}/api/baby-gifts/user/unreserve/{gift_id}",
                headers=headers,
            )
            if resp.status_code >= 400:
                raise HTTPException(
                    status_code=resp.status_code,
                    detail=resp.json().get("detail", "Error"),
                )
            return resp.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


# ── Guest endpoints (public, token-based) ────────────────────────────────────


@router.get("/guest/{token}")
async def get_baby_gifts_for_guest(token: str, request: Request):
    """Get gifts for a guest."""
    try:
        headers = {}
        if "X-Forwarded-For" in request.headers:
            headers["X-Forwarded-For"] = request.headers["X-Forwarded-For"]
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{SERVICE_URL}/api/baby-gifts/guest/{token}",
                headers=headers,
            )
            if resp.status_code >= 400:
                raise HTTPException(
                    status_code=resp.status_code,
                    detail=resp.json().get("detail", "Error"),
                )
            return resp.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/guest/{token}/reserve/{gift_id}")
async def guest_reserve_baby_gift(token: str, gift_id: str, request: Request):
    """Reserve a gift as a guest."""
    try:
        headers = {}
        if "X-Forwarded-For" in request.headers:
            headers["X-Forwarded-For"] = request.headers["X-Forwarded-For"]
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{SERVICE_URL}/api/baby-gifts/guest/{token}/reserve/{gift_id}",
                headers=headers,
            )
            if resp.status_code >= 400:
                raise HTTPException(
                    status_code=resp.status_code,
                    detail=resp.json().get("detail", "Error"),
                )
            return resp.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/guest/{token}/unreserve/{gift_id}")
async def guest_unreserve_baby_gift(token: str, gift_id: str, request: Request):
    """Cancel own reservation as a guest."""
    try:
        headers = {}
        if "X-Forwarded-For" in request.headers:
            headers["X-Forwarded-For"] = request.headers["X-Forwarded-For"]
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{SERVICE_URL}/api/baby-gifts/guest/{token}/unreserve/{gift_id}",
                headers=headers,
            )
            if resp.status_code >= 400:
                raise HTTPException(
                    status_code=resp.status_code,
                    detail=resp.json().get("detail", "Error"),
                )
            return resp.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))
