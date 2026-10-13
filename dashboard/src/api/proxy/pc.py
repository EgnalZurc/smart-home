"""PC control proxy routes.

Proxies requests directly to pc-agent on Windows PC for power profile control.
"""

import logging
import os
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request

from api.auth_helpers import require_super

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pc", tags=["PC"])

# ── Configuration ─────────────────────────────────────────────────────────────

PC_AGENT_URL = os.environ.get("PC_AGENT_URL", "http://192.168.1.164:8090")
PC_AGENT_TOKEN = os.environ.get("PC_AGENT_TOKEN", "")
PC_AGENT_TIMEOUT = float(os.environ.get("PC_AGENT_TIMEOUT", "10.0"))


def _get_auth_headers() -> dict[str, str]:
    """Get authentication headers for pc-agent requests."""
    if PC_AGENT_TOKEN:
        return {"X-Api-Token": PC_AGENT_TOKEN}
    return {}


def _extract_detail(resp: httpx.Response) -> str:
    """Extract error detail from response."""
    try:
        return resp.json().get("detail", resp.text)
    except Exception:
        return resp.text


async def _proxy_get(
    path: str,
    *,
    default_on_error: Any = None,
) -> Any:
    """Perform authenticated GET request to pc-agent."""
    url = f"{PC_AGENT_URL.rstrip('/')}{path}"
    try:
        async with httpx.AsyncClient(timeout=PC_AGENT_TIMEOUT) as client:
            resp = await client.get(url, headers=_get_auth_headers())
            if resp.status_code >= 400:
                if default_on_error is not None:
                    return default_on_error
                detail = _extract_detail(resp)
                raise HTTPException(status_code=resp.status_code, detail=detail)
            return resp.json()
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("Proxy GET %s failed: %s", url, e)
        if default_on_error is not None:
            return default_on_error
        raise HTTPException(status_code=503, detail=str(e))


async def _proxy_post(path: str) -> Any:
    """Perform authenticated POST request to pc-agent."""
    url = f"{PC_AGENT_URL.rstrip('/')}{path}"
    try:
        async with httpx.AsyncClient(timeout=PC_AGENT_TIMEOUT) as client:
            resp = await client.post(url, headers=_get_auth_headers())
            if resp.status_code >= 400:
                detail = _extract_detail(resp)
                raise HTTPException(status_code=resp.status_code, detail=detail)
            return resp.json()
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("Proxy POST %s failed: %s", url, e)
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/status")
async def get_pc_status():
    """Get PC agent status (online, docker available).

    Note: /health endpoint doesn't require authentication on pc-agent.
    """
    return await _proxy_get(
        "/health",
        default_on_error={"online": False, "docker": False},
    )


@router.get("/mode")
async def get_pc_mode():
    """Get current PC power profile mode."""
    return await _proxy_get(
        "/system/mode",
        default_on_error={"mode": "unknown", "error": "PC unreachable"},
    )


@router.post("/mode/{mode}")
async def set_pc_mode(mode: str, request: Request):
    """Set PC power profile mode (gaming, servidor, balanced)."""
    require_super(request)
    if mode not in ("gaming", "servidor", "balanced"):
        raise HTTPException(400, "Invalid mode. Use: gaming, servidor, balanced")
    return await _proxy_post(f"/system/mode/{mode}")
