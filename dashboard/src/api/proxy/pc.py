"""PC control proxy routes.

Proxies requests to valheim-admin which controls the PC agent.
"""

from fastapi import APIRouter, HTTPException, Request

from api.auth_helpers import require_super

from .base import ServiceProxy

router = APIRouter(prefix="/api/pc", tags=["PC"])

_proxy = ServiceProxy("http://valheim-admin:8080")


@router.get("/status")
async def get_pc_status():
    """Get PC agent status (online, docker available)."""
    return await _proxy.get(
        "/api/pc/status",
        raise_on_error=False,
        default_on_error={"online": False, "docker": False},
    )


@router.get("/mode")
async def get_pc_mode():
    """Get current PC power profile mode."""
    return await _proxy.get(
        "/api/pc/mode",
        raise_on_error=False,
        default_on_error={"mode": "unknown", "error": "PC unreachable"},
    )


@router.post("/mode/{mode}")
async def set_pc_mode(mode: str, request: Request):
    """Set PC power profile mode (gaming, servidor, balanced)."""
    require_super(request)
    if mode not in ("gaming", "servidor", "balanced"):
        raise HTTPException(400, "Invalid mode. Use: gaming, servidor, balanced")
    return await _proxy.post(f"/api/pc/mode/{mode}")
