"""PC control proxy routes.

Proxies requests to valheim-admin which controls the PC agent.
"""

import httpx
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/pc", tags=["PC"])


@router.get("/status")
async def get_pc_status():
    """Get PC agent status (online, docker available)."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get("http://valheim-admin:8080/api/pc/status")
            return r.json()
    except Exception:
        return {"online": False, "docker": False}


@router.get("/mode")
async def get_pc_mode():
    """Get current PC power profile mode."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get("http://valheim-admin:8080/api/pc/mode")
            return r.json()
    except Exception:
        return {"mode": "unknown", "error": "PC unreachable"}


@router.post("/mode/{mode}")
async def set_pc_mode(mode: str):
    """Set PC power profile mode (gaming, servidor, balanced)."""
    if mode not in ("gaming", "servidor", "balanced"):
        raise HTTPException(400, "Invalid mode. Use: gaming, servidor, balanced")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(f"http://valheim-admin:8080/api/pc/mode/{mode}")
            r.raise_for_status()
            return r.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, e.response.text)
    except Exception as e:
        raise HTTPException(503, f"PC unreachable: {e}")
