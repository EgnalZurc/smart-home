"""Valheim Admin — Proxy to pc-agent on Windows PC.

Architecture:
  Dashboard (Pi) → valheim-admin (Pi) → pc-agent (Windows PC) → valheim-server

This service runs on the Raspberry Pi and proxies ALL commands to pc-agent.
The actual Valheim server, worlds, logs, and config live on the Windows PC.

Port: 8080 (internal, proxied by nginx via /valheim-admin/)
Auth: nginx handles auth_request — this service trusts all incoming requests.
"""

import logging
import os
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from async_http_client import AsyncServiceClient, ServiceClientConfig
from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

PC_AGENT_URL = os.environ.get("PC_AGENT_URL", "http://192.168.1.164:8090")
PC_AGENT_TOKEN = os.environ.get("PC_AGENT_TOKEN", "")
PC_AGENT_TIMEOUT = float(os.environ.get("PC_AGENT_TIMEOUT", "30.0"))

# Create shared async client for pc-agent communication
_client_config = ServiceClientConfig(
    base_url=PC_AGENT_URL,
    token=PC_AGENT_TOKEN,
    timeout=PC_AGENT_TIMEOUT,
)
pc_agent = AsyncServiceClient(_client_config)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle.

    On shutdown, close the shared pc-agent HTTP client.
    """
    yield
    await pc_agent.aclose()


app = FastAPI(title="Valheim Admin", version="2.1.0", lifespan=lifespan)


# ── Validation ──────────────────────────────────────────────────────────────

# world_name is forwarded to pc-agent, which uses it to build filesystem paths
# and URL path segments. Restrict it to a safe charset to prevent path traversal
# and injection (e.g. "../", slashes, shell metacharacters).
WORLD_NAME_MAX_LENGTH = 64
_WORLD_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def validate_world_name(world_name: str) -> str:
    """Validate a world name before forwarding it to pc-agent.

    Allowed: ASCII alphanumerics, underscore and hyphen, 1..64 chars.
    Raises HTTPException(400) if the value is empty, too long, or contains
    any other character.
    """
    if not world_name or len(world_name) > WORLD_NAME_MAX_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid world_name: must be 1 to {WORLD_NAME_MAX_LENGTH} characters."
            ),
        )
    if not _WORLD_NAME_RE.match(world_name):
        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid world_name: only letters, digits, underscore and "
                "hyphen are allowed."
            ),
        )
    return world_name


# ── Health ────────────────────────────────────────────────────────────────────


@app.get("/health")
def health():
    """Health check for valheim-admin (Pi side). Always returns online."""
    return {"online": True, "service": "valheim-admin"}


@app.get("/health/ready")
async def health_ready():
    """
    Readiness check that verifies connectivity to pc-agent.

    Returns 200 if pc-agent is reachable, 503 otherwise.
    Useful for kubernetes-style readiness probes.
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                f"{PC_AGENT_URL}/health",
                headers={"X-Api-Token": PC_AGENT_TOKEN} if PC_AGENT_TOKEN else {},
            )
            if response.status_code == 200:
                return {
                    "ready": True,
                    "service": "valheim-admin",
                    "backend": "pc-agent",
                    "backend_status": "reachable",
                }
    except (httpx.ConnectError, httpx.TimeoutException):
        pass

    raise HTTPException(
        status_code=503,
        detail={
            "ready": False,
            "service": "valheim-admin",
            "backend": "pc-agent",
            "backend_status": "unreachable",
        },
    )


# ── Static / SPA ──────────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
async def serve_index():
    """Serve the admin SPA."""
    path = Path(__file__).parent / "static" / "index.html"
    if not path.exists():
        return HTMLResponse("<h1>Valheim Admin</h1><p>index.html not found</p>")
    content = path.read_text(encoding="utf-8")
    content = content.replace("</head>", f"<!-- v:{int(time.time())} -->\n</head>")
    return HTMLResponse(
        content=content,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


# ── Server status & control ───────────────────────────────────────────────────


@app.get("/api/status")
async def get_status():
    """Get Valheim server status."""
    try:
        return await pc_agent.get("/valheim/status")
    except HTTPException:
        return {
            "running": False,
            "status": "pc_unreachable",
            "pc_agent": "offline",
        }


@app.post("/api/server/start")
async def start_server():
    """Start Valheim server."""
    return await pc_agent.post("/valheim/start")


@app.post("/api/server/stop")
async def stop_server():
    """Stop Valheim server."""
    return await pc_agent.post("/valheim/stop")


@app.post("/api/server/restart")
async def restart_server():
    """Restart Valheim server."""
    return await pc_agent.post("/valheim/restart")


# ── Config ────────────────────────────────────────────────────────────────────


@app.get("/api/config")
async def get_config():
    """Get Valheim server configuration."""
    return await pc_agent.get("/valheim/config")


@app.post("/api/config")
async def update_config(
    server_name: str = Form(...),
    world_name: str = Form(...),
    server_pass: str = Form(...),
    server_public: bool = Form(False),
    crossplay: bool = Form(False),
    save_interval: int = Form(1800),
    backups: int = Form(4),
):
    """Update Valheim server configuration."""
    validate_world_name(world_name)
    return await pc_agent.post(
        "/valheim/config",
        {
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


@app.get("/api/logs")
async def get_logs(lines: int = 80):
    """Get recent server logs."""
    return await pc_agent.get("/valheim/logs", params={"lines": str(lines)})


# ── Worlds ────────────────────────────────────────────────────────────────────


@app.get("/api/worlds")
async def list_worlds():
    """List available worlds."""
    return await pc_agent.get("/valheim/worlds")


@app.post("/api/worlds/new")
async def create_world(world_name: str = Form(...)):
    """Create a new world."""
    validate_world_name(world_name)
    return await pc_agent.post("/valheim/worlds/new", {"world_name": world_name})


@app.post("/api/worlds/activate")
async def activate_world(world_name: str = Form(...)):
    """Activate a world."""
    validate_world_name(world_name)
    return await pc_agent.post("/valheim/worlds/activate", {"world_name": world_name})


@app.delete("/api/worlds/{world_name}")
async def delete_world(world_name: str):
    """Delete a world."""
    validate_world_name(world_name)
    return await pc_agent.delete(f"/valheim/worlds/{world_name}")


# ── PC Control ────────────────────────────────────────────────────────────────


@app.get("/api/pc/status")
async def get_pc_status():
    """Get PC agent status."""
    try:
        return await pc_agent.get("/health")
    except HTTPException:
        return {"online": False, "docker": False}


@app.get("/api/pc/mode")
async def get_pc_mode():
    """Get current PC power profile."""
    return await pc_agent.get("/system/mode")


@app.post("/api/pc/mode/{mode}")
async def set_pc_mode(mode: str):
    """Set PC power profile."""
    if mode not in ("gaming", "servidor", "balanced"):
        raise HTTPException(400, "Invalid mode")
    return await pc_agent.post(f"/system/mode/{mode}")


# ── Static files ──────────────────────────────────────────────────────────────

_static = Path(__file__).parent / "static"
if _static.exists():
    app.mount("/static", StaticFiles(directory=str(_static)), name="static")
