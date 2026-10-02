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
import time
from pathlib import Path

import httpx
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

app = FastAPI(title="Valheim Admin", version="2.0.0")


# ── pc-agent HTTP client ──────────────────────────────────────────────────────


def _headers() -> dict[str, str]:
    """Headers for pc-agent requests."""
    h = {}
    if PC_AGENT_TOKEN:
        h["X-Api-Token"] = PC_AGENT_TOKEN
    return h


async def _get(path: str) -> dict:
    """GET request to pc-agent."""
    try:
        async with httpx.AsyncClient(timeout=PC_AGENT_TIMEOUT) as client:
            r = await client.get(f"{PC_AGENT_URL}{path}", headers=_headers())
            r.raise_for_status()
            return r.json()
    except httpx.ConnectError:
        raise HTTPException(503, "PC unreachable")
    except httpx.TimeoutException:
        raise HTTPException(504, "PC timeout")
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, e.response.text)


async def _post(path: str, data: dict | None = None) -> dict:
    """POST request to pc-agent."""
    try:
        async with httpx.AsyncClient(timeout=PC_AGENT_TIMEOUT) as client:
            r = await client.post(f"{PC_AGENT_URL}{path}", headers=_headers(), data=data)
            r.raise_for_status()
            return r.json()
    except httpx.ConnectError:
        raise HTTPException(503, "PC unreachable")
    except httpx.TimeoutException:
        raise HTTPException(504, "PC timeout")
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, e.response.text)


async def _delete(path: str) -> dict:
    """DELETE request to pc-agent."""
    try:
        async with httpx.AsyncClient(timeout=PC_AGENT_TIMEOUT) as client:
            r = await client.delete(f"{PC_AGENT_URL}{path}", headers=_headers())
            r.raise_for_status()
            return r.json()
    except httpx.ConnectError:
        raise HTTPException(503, "PC unreachable")
    except httpx.TimeoutException:
        raise HTTPException(504, "PC timeout")
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, e.response.text)


# ── Health ────────────────────────────────────────────────────────────────────


@app.get("/health")
def health():
    """Health check for valheim-admin (Pi side)."""
    return {"online": True, "service": "valheim-admin"}


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
        return await _get("/valheim/status")
    except HTTPException:
        return {
            "running": False,
            "status": "pc_unreachable",
            "pc_agent": "offline",
        }


@app.post("/api/server/start")
async def start_server():
    """Start Valheim server."""
    return await _post("/valheim/start")


@app.post("/api/server/stop")
async def stop_server():
    """Stop Valheim server."""
    return await _post("/valheim/stop")


@app.post("/api/server/restart")
async def restart_server():
    """Restart Valheim server."""
    return await _post("/valheim/restart")


# ── Config ────────────────────────────────────────────────────────────────────


@app.get("/api/config")
async def get_config():
    """Get Valheim server configuration."""
    return await _get("/valheim/config")


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
    return await _post("/valheim/config", {
        "server_name": server_name,
        "world_name": world_name,
        "server_pass": server_pass,
        "server_public": server_public,
        "crossplay": crossplay,
        "save_interval": save_interval,
        "backups": backups,
    })


# ── Logs ──────────────────────────────────────────────────────────────────────


@app.get("/api/logs")
async def get_logs(lines: int = 80):
    """Get recent server logs."""
    return await _get(f"/valheim/logs?lines={lines}")


# ── Worlds ────────────────────────────────────────────────────────────────────


@app.get("/api/worlds")
async def list_worlds():
    """List available worlds."""
    return await _get("/valheim/worlds")


@app.post("/api/worlds/new")
async def create_world(world_name: str = Form(...)):
    """Create a new world."""
    return await _post("/valheim/worlds/new", {"world_name": world_name})


@app.post("/api/worlds/activate")
async def activate_world(world_name: str = Form(...)):
    """Activate a world."""
    return await _post("/valheim/worlds/activate", {"world_name": world_name})


@app.delete("/api/worlds/{world_name}")
async def delete_world(world_name: str):
    """Delete a world."""
    return await _delete(f"/valheim/worlds/{world_name}")


# ── PC Control ────────────────────────────────────────────────────────────────


@app.get("/api/pc/status")
async def get_pc_status():
    """Get PC agent status."""
    try:
        return await _get("/health")
    except HTTPException:
        return {"online": False, "docker": False}


@app.get("/api/pc/mode")
async def get_pc_mode():
    """Get current PC power profile."""
    return await _get("/system/mode")


@app.post("/api/pc/mode/{mode}")
async def set_pc_mode(mode: str):
    """Set PC power profile."""
    if mode not in ("gaming", "servidor", "balanced"):
        raise HTTPException(400, "Invalid mode")
    return await _post(f"/system/mode/{mode}")


# ── Static files ──────────────────────────────────────────────────────────────

_static = Path(__file__).parent / "static"
if _static.exists():
    app.mount("/static", StaticFiles(directory=str(_static)), name="static")
