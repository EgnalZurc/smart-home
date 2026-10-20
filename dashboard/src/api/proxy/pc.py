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
    """Perform authenticated GET request to pc-agent.

    Args:
        path: API path on pc-agent (e.g. "/health").
        default_on_error: Value to return on failure instead of raising.

    Returns:
        JSON response from pc-agent, or default_on_error on failure.

    Raises:
        HTTPException: 503 if pc-agent is unreachable, or upstream status code.
    """
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
        raise HTTPException(status_code=503, detail="PC agent unreachable")


async def _proxy_post(path: str) -> Any:
    """Perform authenticated POST request to pc-agent.

    Args:
        path: API path on pc-agent (e.g. "/system/mode/gaming").

    Returns:
        JSON response from pc-agent.

    Raises:
        HTTPException: 503 if pc-agent is unreachable, or upstream status code.
    """
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
        raise HTTPException(status_code=503, detail="PC agent unreachable")


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


# ── Power control (sleep/wake) ────────────────────────────────────────────────
#
# DANGEROUS OPERATIONS — require SUPER access + confirmation header.
# Sleep: Proxies to pc-agent which suspends the Windows PC.
# Wake: Executes etherwake locally on the Pi to send Wake-on-LAN magic packet.

# MAC address of EgnalPC's WiFi adapter (Intel AX200)
EGNALPC_MAC = os.environ.get("EGNALPC_MAC", "A4:B1:C1:92:76:B0")
# Network interface on the Pi to send WoL packet from
WOL_INTERFACE = os.environ.get("WOL_INTERFACE", "wlan0")


@router.post("/sleep")
async def pc_sleep(request: Request):
    """Put EgnalPC into sleep mode.

    DANGEROUS: The PC will become unreachable until woken via Wake-on-LAN.

    Requires:
    - SUPER access (level 0)
    - X-Confirm-Action header set to "SLEEP"
    """
    require_super(request)

    # Check confirmation header
    confirm = request.headers.get("X-Confirm-Action")
    if confirm != "SLEEP":
        raise HTTPException(
            400,
            "Confirmation required: send X-Confirm-Action: SLEEP header",
        )

    logger.warning("PC SLEEP requested by user via dashboard")

    # Proxy to pc-agent with the confirmation header
    url = f"{PC_AGENT_URL.rstrip('/')}/system/sleep"
    try:
        async with httpx.AsyncClient(timeout=PC_AGENT_TIMEOUT) as client:
            headers = _get_auth_headers()
            headers["X-Confirm-Action"] = "SLEEP"
            resp = await client.post(url, headers=headers)
            if resp.status_code >= 400:
                detail = _extract_detail(resp)
                raise HTTPException(status_code=resp.status_code, detail=detail)
            return resp.json()
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("PC sleep request failed: %s", e)
        raise HTTPException(status_code=503, detail="PC agent unreachable")


@router.post("/wake")
async def pc_wake(request: Request):
    """Wake EgnalPC from sleep using Wake-on-LAN magic packet.

    Executes etherwake locally on the Pi to send the magic packet.
    Only works if the PC is in sleep mode (S3) with Wake-on-WLAN enabled.

    Requires:
    - SUPER access (level 0)
    - X-Confirm-Action header set to "WAKE"
    """
    import asyncio

    require_super(request)

    # Check confirmation header
    confirm = request.headers.get("X-Confirm-Action")
    if confirm != "WAKE":
        raise HTTPException(
            400,
            "Confirmation required: send X-Confirm-Action: WAKE header",
        )

    logger.warning("PC WAKE requested by user via dashboard")

    # Execute etherwake locally
    cmd = ["sudo", "etherwake", "-i", WOL_INTERFACE, EGNALPC_MAC]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10.0)

        if proc.returncode != 0:
            error_msg = stderr.decode().strip() if stderr else "Unknown error"
            logger.error("etherwake failed: %s", error_msg)
            raise HTTPException(500, f"Wake-on-LAN failed: {error_msg}")

        logger.info("Wake-on-LAN packet sent to %s via %s", EGNALPC_MAC, WOL_INTERFACE)
        return {
            "status": "ok",
            "message": f"Magic packet sent to {EGNALPC_MAC}",
            "interface": WOL_INTERFACE,
        }

    except asyncio.TimeoutError:
        raise HTTPException(500, "etherwake command timed out")
    except FileNotFoundError:
        raise HTTPException(500, "etherwake not installed on this system")
    except Exception as e:
        logger.error("Wake-on-LAN error: %s", e)
        raise HTTPException(500, f"Failed to send wake packet: {e}")
