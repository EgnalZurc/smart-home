"""PC control proxy routes.

Proxies requests directly to pc-agent on Windows PC for power profile control.

SECURITY: PC_AGENT_TOKEN is only sent over the internal network (localhost,
172.x.x.x, 192.168.x.x, 10.x.x.x). The URL is validated at startup to prevent
accidental exposure of the token to external hosts.
"""

import logging
import os
import re
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException, Request

from api.auth_helpers import require_super

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pc", tags=["PC"])

# ── Configuration ─────────────────────────────────────────────────────────────

PC_AGENT_URL = os.environ.get("PC_AGENT_URL", "http://192.168.1.164:8090")
PC_AGENT_TOKEN = os.environ.get("PC_AGENT_TOKEN", "")
PC_AGENT_TIMEOUT = float(os.environ.get("PC_AGENT_TIMEOUT", "10.0"))

# ── Internal network validation ───────────────────────────────────────────────
# SECURITY: Patterns that match internal/private network addresses.
# Token is ONLY sent to these destinations. External URLs are rejected.
_INTERNAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^localhost$", re.IGNORECASE),
    re.compile(r"^127\.\d{1,3}\.\d{1,3}\.\d{1,3}$"),  # 127.0.0.0/8
    re.compile(r"^10\.\d{1,3}\.\d{1,3}\.\d{1,3}$"),  # 10.0.0.0/8
    re.compile(r"^172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}$"),  # 172.16.0.0/12
    re.compile(r"^192\.168\.\d{1,3}\.\d{1,3}$"),  # 192.168.0.0/16
)


def _is_internal_host(hostname: str) -> bool:
    """Check if hostname is an internal/private network address."""
    return any(pattern.match(hostname) for pattern in _INTERNAL_PATTERNS)


def _validate_pc_agent_url() -> None:
    """Validate that PC_AGENT_URL points to an internal network address.

    SECURITY: Called at module load time. Raises RuntimeError if the URL
    would send PC_AGENT_TOKEN to a non-internal address.
    """
    if not PC_AGENT_TOKEN:
        return  # No token, no risk
    parsed = urlparse(PC_AGENT_URL)
    hostname = parsed.hostname or ""
    if not _is_internal_host(hostname):
        raise RuntimeError(
            f"SECURITY: PC_AGENT_URL host '{hostname}' is not an internal network "
            f"address. PC_AGENT_TOKEN must only be sent over internal networks "
            f"(localhost, 127.x, 10.x, 172.16-31.x, 192.168.x)."
        )
    logger.info("PC agent URL validated as internal network: %s", PC_AGENT_URL)


# Validate URL at module load time
_validate_pc_agent_url()


def _get_auth_headers() -> dict[str, str]:
    """Get authentication headers for pc-agent requests.

    SECURITY: Token only sent over internal network (validated at startup).
    """
    if PC_AGENT_TOKEN:
        return {"X-Api-Token": PC_AGENT_TOKEN}
    return {}


def _extract_detail(resp: httpx.Response) -> str:
    """Extract error detail from response."""
    try:
        return resp.json().get("detail", resp.text)
    except (ValueError, KeyError):
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
    except httpx.HTTPError as e:
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
    except httpx.HTTPError as e:
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
# Wake: Sends Wake-on-LAN magic packet using the wakeonlan Python library.

# MAC address of EgnalPC's WiFi adapter (Intel AX200)
EGNALPC_MAC = os.environ.get("EGNALPC_MAC", "A4:B1:C1:92:76:B0")
# Broadcast address of the physical LAN subnet (NOT 255.255.255.255)
# Required because the container is on a Docker bridge network (172.18.x.x)
# and global broadcast doesn't reach the physical network.
WOL_BROADCAST = os.environ.get("WOL_BROADCAST", "192.168.1.255")


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
    except httpx.HTTPError as e:
        logger.warning("PC sleep request failed: %s", e)
        raise HTTPException(status_code=503, detail="PC agent unreachable")


@router.post("/wake")
async def pc_wake(request: Request):
    """Wake EgnalPC from sleep using Wake-on-LAN magic packet.

    Sends a magic packet using the wakeonlan Python library.
    Only works if the PC is in sleep mode (S3) with Wake-on-WLAN enabled.

    Requires:
    - SUPER access (level 0)
    - X-Confirm-Action header set to "WAKE"
    """
    from wakeonlan import send_magic_packet

    require_super(request)

    # Check confirmation header
    confirm = request.headers.get("X-Confirm-Action")
    if confirm != "WAKE":
        raise HTTPException(
            400,
            "Confirmation required: send X-Confirm-Action: WAKE header",
        )

    logger.warning("PC WAKE requested by user via dashboard")

    try:
        # Send magic packet to the subnet broadcast address (NOT 255.255.255.255)
        # The container is on a Docker bridge network, so global broadcast
        # doesn't reach the physical LAN. We must target the subnet broadcast.
        send_magic_packet(EGNALPC_MAC, ip_address=WOL_BROADCAST)

        logger.info(
            "Wake-on-LAN magic packet sent to %s via %s", EGNALPC_MAC, WOL_BROADCAST
        )
        return {
            "status": "ok",
            "message": f"Magic packet sent to {EGNALPC_MAC}",
            "broadcast": WOL_BROADCAST,
        }

    except ValueError as e:
        # Invalid MAC address format
        logger.error("Invalid MAC address: %s", e)
        raise HTTPException(500, f"Invalid MAC address: {e}")
    except OSError as e:
        logger.error("Wake-on-LAN error: %s", e)
        raise HTTPException(500, f"Failed to send wake packet: {e}")
