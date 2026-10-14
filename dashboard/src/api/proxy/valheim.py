"""Valheim server control proxy routes.

Proxies requests directly to pc-agent on Windows PC for Valheim server control.
This replaces the separate valheim-admin service with direct integration.

Architecture:
  Dashboard (Pi) → pc-agent (Windows PC) → valheim-server container

Auth: All routes are protected by the dashboard's auth system.
Rate limiting: Server control endpoints are rate-limited to prevent abuse.
"""

import logging
import os
import re
from typing import Any

import httpx
from fastapi import APIRouter, Form, HTTPException, Request
from smart_home_common.rate_limiter import InMemoryRateLimiter

from api.auth_helpers import require_super

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/valheim", tags=["Valheim"])

# ── Configuration ─────────────────────────────────────────────────────────────

PC_AGENT_URL = os.environ.get("PC_AGENT_URL", "http://192.168.1.164:8090")
PC_AGENT_TOKEN = os.environ.get("PC_AGENT_TOKEN", "")
PC_AGENT_TIMEOUT = float(os.environ.get("PC_AGENT_TIMEOUT", "30.0"))

# Rate limiter for server control endpoints (10 requests per minute per IP)
_server_control_limiter = InMemoryRateLimiter(max_requests=10, window_seconds=60)


def _get_auth_headers() -> dict[str, str]:
    """Get authentication headers for pc-agent requests."""
    if PC_AGENT_TOKEN:
        return {"X-Api-Token": PC_AGENT_TOKEN}
    return {}


async def _proxy_get(
    path: str,
    *,
    params: dict | None = None,
    default_on_error: Any = None,
) -> Any:
    """Perform authenticated GET request to pc-agent.

    Args:
        path: API path on pc-agent (e.g. "/valheim/status").
        params: Optional query parameters.
        default_on_error: Value to return on failure instead of raising.

    Returns:
        JSON response from pc-agent, or default_on_error on failure.

    Raises:
        HTTPException: 503 if pc-agent is unreachable, or upstream status code.
    """
    url = f"{PC_AGENT_URL.rstrip('/')}{path}"
    try:
        async with httpx.AsyncClient(timeout=PC_AGENT_TIMEOUT) as client:
            resp = await client.get(url, params=params, headers=_get_auth_headers())
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


async def _proxy_post(path: str, *, json: dict | None = None) -> Any:
    """Perform authenticated POST request to pc-agent.

    Args:
        path: API path on pc-agent (e.g. "/valheim/start").
        json: Optional JSON body to send.

    Returns:
        JSON response from pc-agent.

    Raises:
        HTTPException: 503 if pc-agent is unreachable, or upstream status code.
    """
    url = f"{PC_AGENT_URL.rstrip('/')}{path}"
    try:
        async with httpx.AsyncClient(timeout=PC_AGENT_TIMEOUT) as client:
            resp = await client.post(url, json=json, headers=_get_auth_headers())
            if resp.status_code >= 400:
                detail = _extract_detail(resp)
                raise HTTPException(status_code=resp.status_code, detail=detail)
            return resp.json()
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("Proxy POST %s failed: %s", url, e)
        raise HTTPException(status_code=503, detail="PC agent unreachable")


async def _proxy_delete(path: str) -> Any:
    """Perform authenticated DELETE request to pc-agent.

    Args:
        path: API path on pc-agent (e.g. "/valheim/worlds/world_name").

    Returns:
        JSON response from pc-agent.

    Raises:
        HTTPException: 503 if pc-agent is unreachable, or upstream status code.
    """
    url = f"{PC_AGENT_URL.rstrip('/')}{path}"
    try:
        async with httpx.AsyncClient(timeout=PC_AGENT_TIMEOUT) as client:
            resp = await client.delete(url, headers=_get_auth_headers())
            if resp.status_code >= 400:
                detail = _extract_detail(resp)
                raise HTTPException(status_code=resp.status_code, detail=detail)
            return resp.json()
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("Proxy DELETE %s failed: %s", url, e)
        raise HTTPException(status_code=503, detail="PC agent unreachable")


def _extract_detail(resp: httpx.Response) -> str:
    """Extract error detail from response."""
    try:
        return resp.json().get("detail", resp.text)
    except Exception:
        return resp.text


def _check_rate_limit(request: Request) -> None:
    """Check rate limit for server control endpoints.

    Raises HTTPException 429 if rate limit exceeded.
    """
    client_ip = request.client.host if request.client else "unknown"
    if not _server_control_limiter.is_allowed(client_ip):
        status = _server_control_limiter.get_status(client_ip)
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Try again later.",
            headers={"Retry-After": str(int(status.reset_at.timestamp()))},
        )


# ── Validation ────────────────────────────────────────────────────────────────

WORLD_NAME_MAX_LENGTH = 64
_WORLD_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _validate_world_name(world_name: str) -> str:
    """Validate a world name before forwarding it to pc-agent.

    Allowed: ASCII alphanumerics, underscore and hyphen, 1..64 chars.
    Raises HTTPException(400) if the value is empty, too long, or contains
    any other character.
    """
    if not world_name or len(world_name) > WORLD_NAME_MAX_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid world_name: must be 1 to {WORLD_NAME_MAX_LENGTH} characters.",
        )
    if not _WORLD_NAME_RE.match(world_name):
        raise HTTPException(
            status_code=400,
            detail="Invalid world_name: only letters, digits, underscore and hyphen are allowed.",
        )
    return world_name


# ── Server status & control ───────────────────────────────────────────────────


@router.get("/status")
async def get_status():
    """Get Valheim server status."""
    return await _proxy_get(
        "/valheim/status",
        default_on_error={
            "running": False,
            "status": "pc_unreachable",
            "pc_agent": "offline",
        },
    )


@router.post("/server/start")
async def start_server(request: Request):
    """Start Valheim server."""
    require_super(request)
    _check_rate_limit(request)
    return await _proxy_post("/valheim/start")


@router.post("/server/stop")
async def stop_server(request: Request):
    """Stop Valheim server."""
    require_super(request)
    _check_rate_limit(request)
    return await _proxy_post("/valheim/stop")


@router.post("/server/restart")
async def restart_server(request: Request):
    """Restart Valheim server."""
    require_super(request)
    _check_rate_limit(request)
    return await _proxy_post("/valheim/restart")


# ── Config ────────────────────────────────────────────────────────────────────


@router.get("/config")
async def get_config(request: Request):
    """Get Valheim server configuration."""
    require_super(request)
    return await _proxy_get("/valheim/config")


@router.post("/config")
async def update_config(
    request: Request,
    server_name: str = Form(...),
    world_name: str = Form(...),
    server_pass: str = Form(...),
    server_public: bool = Form(False),
    crossplay: bool = Form(False),
    save_interval: int = Form(1800),
    backups: int = Form(4),
):
    """Update Valheim server configuration."""
    require_super(request)
    _validate_world_name(world_name)
    return await _proxy_post(
        "/valheim/config",
        json={
            "server_name": server_name,
            "world_name": world_name,
            "server_pass": server_pass,
            "server_public": server_public,
            "crossplay": crossplay,
            "save_interval": save_interval,
            "backups": backups,
        },
    )


# ── Logs ──────────────────────────────────────────────────────────────────────


@router.get("/logs")
async def get_logs(request: Request, lines: int = 80):
    """Get recent server logs."""
    require_super(request)
    return await _proxy_get("/valheim/logs", params={"lines": str(lines)})


# ── Worlds ────────────────────────────────────────────────────────────────────


@router.get("/worlds")
async def list_worlds(request: Request):
    """List available worlds."""
    require_super(request)
    return await _proxy_get("/valheim/worlds")


@router.post("/worlds/new")
async def create_world(request: Request, world_name: str = Form(...)):
    """Create a new world."""
    require_super(request)
    _validate_world_name(world_name)
    return await _proxy_post("/valheim/worlds/new", json={"world_name": world_name})


@router.post("/worlds/activate")
async def activate_world(request: Request, world_name: str = Form(...)):
    """Activate a world."""
    require_super(request)
    _validate_world_name(world_name)
    return await _proxy_post(
        "/valheim/worlds/activate", json={"world_name": world_name}
    )


@router.delete("/worlds/{world_name}")
async def delete_world(request: Request, world_name: str):
    """Delete a world."""
    require_super(request)
    _validate_world_name(world_name)
    return await _proxy_delete(f"/valheim/worlds/{world_name}")
