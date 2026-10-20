"""Valheim Admin — Proxy service to pc-agent on Windows PC.

This module implements a FastAPI-based proxy service that bridges the smart-home
dashboard running on the Raspberry Pi with the pc-agent service running on the
Windows PC that controls the actual Valheim dedicated server.

Architecture:
    Dashboard (Pi) → valheim-admin (Pi) → pc-agent (Windows PC) → valheim-server

The service runs on the Raspberry Pi and proxies ALL commands to pc-agent.
The actual Valheim server, worlds, logs, and config live on the Windows PC.

Features:
    - Server lifecycle management (start/stop/restart)
    - Configuration viewing and updates
    - World management (create, activate, delete)
    - Log streaming
    - Rate limiting on server control endpoints

Security:
    - Port 8080 internal, proxied by nginx via /valheim-admin/
    - nginx handles auth_request — this service trusts all incoming requests
    - Input validation on all user-provided data
    - Rate limiting prevents abuse of server control endpoints

Example:
    The service is typically started via Docker::

        docker compose up -d valheim-admin

    Or directly for development::

        uvicorn main:app --host 0.0.0.0 --port 8080
"""

import logging
import re
import shlex
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from async_http_client import AsyncServiceClient, ServiceClientConfig
from config import (
    BACKUPS_DEFAULT,
    BACKUPS_MAX,
    BACKUPS_MIN,
    LOGS_DEFAULT_LINES,
    LOGS_MAX_LINES,
    LOGS_MIN_LINES,
    PC_AGENT_TIMEOUT,
    PC_AGENT_TOKEN,
    PC_AGENT_URL,
    RATE_LIMIT_MAX_REQUESTS,
    RATE_LIMIT_WINDOW_SECONDS,
    SAVE_INTERVAL_DEFAULT_SECONDS,
    SAVE_INTERVAL_MAX_SECONDS,
    SAVE_INTERVAL_MIN_SECONDS,
    SERVER_NAME_MAX_LENGTH,
    SERVER_NAME_PATTERN,
    SERVER_PASS_MAX_LENGTH,
    SERVICE_NAME,
    SERVICE_TITLE,
    SERVICE_VERSION,
    WORLD_NAME_MAX_LENGTH,
    WORLD_NAME_PATTERN,
    is_internal_url,
)
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from smart_home_common.rate_limiter import InMemoryRateLimiter


class ConfigUpdateRequest(BaseModel):
    """Request body for updating server configuration."""

    server_name: str
    world_name: str
    server_pass: str
    server_public: bool = False
    crossplay: bool = False
    save_interval: int = SAVE_INTERVAL_DEFAULT_SECONDS
    backups: int = BACKUPS_DEFAULT


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# Service Initialization
# ══════════════════════════════════════════════════════════════════════════════

if not PC_AGENT_TOKEN:
    raise RuntimeError("PC_AGENT_TOKEN environment variable is required")

if not is_internal_url(PC_AGENT_URL):
    raise RuntimeError(
        f"PC_AGENT_URL must be internal network address, got: {PC_AGENT_URL}"
    )

# Create shared async client for pc-agent communication
_client_config = ServiceClientConfig(
    base_url=PC_AGENT_URL,
    token=PC_AGENT_TOKEN,
    timeout=PC_AGENT_TIMEOUT,
)
pc_agent = AsyncServiceClient(_client_config)

# Rate limiter for server control endpoints
# Note: Rate limiting is intentionally applied only to server control endpoints
# (/api/server/start, /stop, /restart) since they have significant side effects.
# Read-only endpoints (/api/status, /api/logs, /api/config GET, /api/worlds) are
# not rate limited as they don't mutate state and are needed for UI polling.
server_control_limiter = InMemoryRateLimiter(
    max_requests=RATE_LIMIT_MAX_REQUESTS,
    window_seconds=RATE_LIMIT_WINDOW_SECONDS,
)

# Compiled regex patterns for validation
_WORLD_NAME_RE = re.compile(WORLD_NAME_PATTERN)
_SERVER_NAME_RE = re.compile(SERVER_NAME_PATTERN)


# ══════════════════════════════════════════════════════════════════════════════
# Utility Functions
# ══════════════════════════════════════════════════════════════════════════════


def _sanitize_shell_arg(arg: str) -> str:
    """Sanitize an argument for safe shell command construction.

    Uses shlex.quote to properly escape special characters that could be
    interpreted by the shell.

    Note:
        valheim-admin is a proxy service and does not execute shell commands
        directly. This utility is provided for consistency with other services
        and potential future use.

    Args:
        arg: The argument string to sanitize.

    Returns:
        The shell-escaped argument string.

    Example:
        >>> _sanitize_shell_arg("hello world")
        "'hello world'"
        >>> _sanitize_shell_arg("test; rm -rf /")
        "'test; rm -rf /'"
    """
    return shlex.quote(arg)


def _check_rate_limit(request: Request) -> None:
    """Check if the request exceeds the rate limit for server control.

    This function enforces rate limiting on server control endpoints to prevent
    abuse. It uses the client's IP address as the identifier.

    Args:
        request: The incoming FastAPI request object.

    Raises:
        HTTPException: 429 status if the rate limit is exceeded, includes
            Retry-After header with the reset timestamp.
    """
    client_ip = request.client.host if request.client else "unknown"
    if not server_control_limiter.is_allowed(client_ip):
        status = server_control_limiter.get_status(client_ip)
        logger.warning("Rate limit exceeded for IP: %s", client_ip)
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Try again later.",
            headers={"Retry-After": str(int(status.reset_at.timestamp()))},
        )


# ══════════════════════════════════════════════════════════════════════════════
# Application Lifecycle
# ══════════════════════════════════════════════════════════════════════════════


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage the FastAPI application lifecycle.

    This async context manager handles startup and shutdown events for the
    application. On shutdown, it closes the shared pc-agent HTTP client to
    ensure proper resource cleanup.

    Args:
        app: The FastAPI application instance.

    Yields:
        None: Control returns to FastAPI for normal operation.
    """
    yield
    await pc_agent.aclose()


app = FastAPI(title=SERVICE_TITLE, version=SERVICE_VERSION, lifespan=lifespan)


# ══════════════════════════════════════════════════════════════════════════════
# Security Headers Middleware
# ══════════════════════════════════════════════════════════════════════════════


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    """Add security headers to all HTTP responses.

    This middleware adds standard security headers to protect against common
    web vulnerabilities:

    - X-Content-Type-Options: nosniff — Prevents MIME type sniffing attacks
    - X-Frame-Options: DENY — Prevents clickjacking by disallowing framing
    - Content-Security-Policy: default-src 'self' — Restricts resource loading
    - X-XSS-Protection: 1; mode=block — Legacy XSS filter (for older browsers)
    - Referrer-Policy: strict-origin-when-cross-origin — Controls referrer info

    Args:
        request: The incoming HTTP request.
        call_next: The next middleware or route handler in the chain.

    Returns:
        The HTTP response with security headers added.
    """
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
        "font-src 'self'; connect-src 'self'"
    )
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


# ══════════════════════════════════════════════════════════════════════════════
# Input Validation
# ══════════════════════════════════════════════════════════════════════════════


def validate_world_name(world_name: str) -> str:
    """Validate a world name before forwarding to pc-agent.

    World names are used to build filesystem paths on the Windows PC, so they
    must be restricted to a safe character set to prevent path traversal and
    injection attacks (e.g., "../", slashes, shell metacharacters).

    Args:
        world_name: The world name to validate.

    Returns:
        The validated world name (unchanged if valid).

    Raises:
        HTTPException: 400 status if the world name is empty, too long,
            or contains invalid characters.

    Example:
        >>> validate_world_name("MyWorld_01")
        'MyWorld_01'
        >>> validate_world_name("../etc/passwd")  # Raises HTTPException
    """
    if not world_name or len(world_name) > WORLD_NAME_MAX_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid world_name: must be 1 to {WORLD_NAME_MAX_LENGTH} characters.",
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


def validate_server_name(name: str) -> str:
    """Validate a server name before forwarding to pc-agent.

    Server names are displayed in the Valheim server browser and should be
    human-readable. Allowed characters are ASCII alphanumerics and spaces.

    Args:
        name: The server name to validate.

    Returns:
        The validated server name (unchanged if valid).

    Raises:
        HTTPException: 400 status if the name is empty, too long,
            or contains invalid characters.

    Example:
        >>> validate_server_name("My Valheim Server")
        'My Valheim Server'
    """
    if not name or not _SERVER_NAME_RE.match(name):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid server_name: must be 1 to {SERVER_NAME_MAX_LENGTH} "
                "characters, only letters, digits and spaces allowed."
            ),
        )
    return name


def validate_server_pass(password: str) -> str:
    """Validate a server password before forwarding to pc-agent.

    Passwords are written to configuration files, so newlines and null bytes
    are prohibited as they would corrupt the config format.

    Args:
        password: The password to validate.

    Returns:
        The validated password (unchanged if valid).

    Raises:
        HTTPException: 400 status if the password is too long or contains
            newlines or null bytes.

    Example:
        >>> validate_server_pass("secret123")
        'secret123'
    """
    if len(password) > SERVER_PASS_MAX_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid server_pass: max {SERVER_PASS_MAX_LENGTH} characters.",
        )
    if "\n" in password or "\0" in password:
        raise HTTPException(
            status_code=400,
            detail="Invalid server_pass: newlines and null bytes not allowed.",
        )
    return password


def clamp_save_interval(value: int) -> int:
    """Clamp save interval to valid bounds.

    Ensures the save interval stays within reasonable limits to prevent
    data loss (too long) or excessive disk I/O (too short).

    Args:
        value: The requested save interval in seconds.

    Returns:
        The clamped value between SAVE_INTERVAL_MIN_SECONDS (5 min)
        and SAVE_INTERVAL_MAX_SECONDS (24 hours).

    Example:
        >>> clamp_save_interval(60)  # Too short
        300
        >>> clamp_save_interval(100000)  # Too long
        86400
        >>> clamp_save_interval(1800)  # Valid
        1800
    """
    return max(SAVE_INTERVAL_MIN_SECONDS, min(value, SAVE_INTERVAL_MAX_SECONDS))


def clamp_backups(value: int) -> int:
    """Clamp backup count to valid bounds.

    Ensures the backup count stays within reasonable limits to prevent
    running out of disk space (too many) or losing too much history (too few).

    Args:
        value: The requested number of backups to keep.

    Returns:
        The clamped value between BACKUPS_MIN (1) and BACKUPS_MAX (100).

    Example:
        >>> clamp_backups(0)  # Too few
        1
        >>> clamp_backups(500)  # Too many
        100
        >>> clamp_backups(10)  # Valid
        10
    """
    return max(BACKUPS_MIN, min(value, BACKUPS_MAX))


# ══════════════════════════════════════════════════════════════════════════════
# Health Check Endpoints
# ══════════════════════════════════════════════════════════════════════════════


@app.get("/health")
def health() -> dict[str, Any]:
    """Return basic health status for valheim-admin.

    This is a lightweight liveness check that always returns online. It does
    not verify backend connectivity — use /health/ready for that.

    Returns:
        A dictionary with online status and service name.

    Example response::

        {"online": true, "service": "valheim-admin"}
    """
    return {"online": True, "service": SERVICE_NAME}


@app.get("/health/ready")
async def health_ready() -> dict[str, Any]:
    """Check readiness by verifying connectivity to pc-agent.

    This endpoint performs an actual health check against pc-agent to verify
    the backend is reachable. Useful for Kubernetes-style readiness probes
    to prevent routing traffic to an instance that can't reach its backend.

    Returns:
        A dictionary with ready status and backend connectivity info.

    Raises:
        HTTPException: 503 status if pc-agent is unreachable.

    Example success response::

        {
            "ready": true,
            "service": "valheim-admin",
            "backend": "pc-agent",
            "backend_status": "reachable"
        }
    """
    try:
        await pc_agent.get("/health")
        return {
            "ready": True,
            "service": SERVICE_NAME,
            "backend": "pc-agent",
            "backend_status": "reachable",
        }
    except (httpx.ConnectError, httpx.TimeoutException):
        pass
    except HTTPException:
        pass

    raise HTTPException(
        status_code=503,
        detail={
            "ready": False,
            "service": SERVICE_NAME,
            "backend": "pc-agent",
            "backend_status": "unreachable",
        },
    )


# ══════════════════════════════════════════════════════════════════════════════
# Static Files / SPA
# ══════════════════════════════════════════════════════════════════════════════


@app.get("/", response_class=HTMLResponse)
async def serve_index() -> HTMLResponse:
    """Serve the Valheim Admin single-page application.

    Reads index.html from the static directory and injects a cache-busting
    version comment to ensure browsers always get the latest version.

    Returns:
        HTML response with the admin SPA, or a fallback message if
        index.html is not found.
    """
    path = Path(__file__).parent / "static" / "index.html"
    if not path.exists():
        return HTMLResponse("<h1>Valheim Admin</h1><p>index.html not found</p>")
    content = path.read_text(encoding="utf-8")
    content = content.replace("</head>", f"<!-- v:{int(time.time())} -->\n</head>")
    return HTMLResponse(
        content=content,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


# ══════════════════════════════════════════════════════════════════════════════
# Server Status & Control Endpoints
# ══════════════════════════════════════════════════════════════════════════════


@app.get("/api/status")
async def get_status() -> dict[str, Any]:
    """Get current Valheim server status from pc-agent.

    Queries pc-agent for the server's running state, player count, and
    other status information.

    Returns:
        Server status dictionary from pc-agent, or a fallback status
        indicating pc-agent is unreachable.

    Example success response::

        {
            "running": true,
            "players": 2,
            "world": "MyWorld",
            "uptime": 3600
        }

    Example failure response::

        {
            "running": false,
            "status": "pc_unreachable",
            "pc_agent": "offline"
        }
    """
    try:
        return await pc_agent.get("/valheim/status")
    except HTTPException:
        return {
            "running": False,
            "status": "pc_unreachable",
            "pc_agent": "offline",
        }


@app.post("/api/server/start")
async def start_server(request: Request) -> dict[str, Any]:
    """Start the Valheim dedicated server.

    Sends a start command to pc-agent, which launches the Valheim server
    process on the Windows PC. Rate limited to prevent abuse.

    Args:
        request: The incoming request (used for rate limiting).

    Returns:
        Result dictionary from pc-agent with operation status.

    Raises:
        HTTPException: 429 if rate limit exceeded.
    """
    _check_rate_limit(request)
    logger.info("Server start requested")
    result = await pc_agent.post("/valheim/start")
    logger.info("Server start completed: %s", result.get("status", "unknown"))
    return result


@app.post("/api/server/stop")
async def stop_server(request: Request) -> dict[str, Any]:
    """Stop the Valheim dedicated server.

    Sends a stop command to pc-agent, which gracefully shuts down the
    Valheim server process. Rate limited to prevent abuse.

    Args:
        request: The incoming request (used for rate limiting).

    Returns:
        Result dictionary from pc-agent with operation status.

    Raises:
        HTTPException: 429 if rate limit exceeded.
    """
    _check_rate_limit(request)
    logger.info("Server stop requested")
    result = await pc_agent.post("/valheim/stop")
    logger.info("Server stop completed: %s", result.get("status", "unknown"))
    return result


@app.post("/api/server/restart")
async def restart_server(request: Request) -> dict[str, Any]:
    """Restart the Valheim dedicated server.

    Sends a restart command to pc-agent, which stops and then starts the
    Valheim server. Rate limited to prevent abuse.

    Args:
        request: The incoming request (used for rate limiting).

    Returns:
        Result dictionary from pc-agent with operation status.

    Raises:
        HTTPException: 429 if rate limit exceeded.
    """
    _check_rate_limit(request)
    logger.info("Server restart requested")
    result = await pc_agent.post("/valheim/restart")
    logger.info("Server restart completed: %s", result.get("status", "unknown"))
    return result


# ══════════════════════════════════════════════════════════════════════════════
# Configuration Endpoints
# ══════════════════════════════════════════════════════════════════════════════


@app.get("/api/config")
async def get_config() -> dict[str, Any]:
    """Get current Valheim server configuration.

    Retrieves the server configuration from pc-agent, including server name,
    world name, password status, and other settings.

    Returns:
        Configuration dictionary from pc-agent.

    Example response::

        {
            "server_name": "My Server",
            "world_name": "MyWorld",
            "server_public": true,
            "crossplay": true,
            "save_interval": 1800,
            "backups": 4
        }
    """
    return await pc_agent.get("/valheim/config")


@app.post("/api/config")
async def update_config(config: ConfigUpdateRequest) -> dict[str, Any]:
    """Update Valheim server configuration.

    Validates all inputs and forwards the configuration update to pc-agent.
    The server may need to be restarted for some changes to take effect.

    Args:
        config: JSON body with configuration fields:
            - server_name: Display name for the server (1-64 chars, alphanumeric
              and spaces).
            - world_name: Name of the world to use (1-64 chars, alphanumeric,
              underscore, hyphen).
            - server_pass: Server password (max 128 chars, no newlines).
            - server_public: Whether the server appears in the public browser.
            - crossplay: Whether to enable crossplay with Xbox/console players.
            - save_interval: World save interval in seconds (300-86400).
            - backups: Number of backup copies to keep (1-100).

    Returns:
        Result dictionary from pc-agent confirming the update.

    Raises:
        HTTPException: 400 if any input validation fails.
    """
    validate_server_name(config.server_name)
    validate_world_name(config.world_name)
    validate_server_pass(config.server_pass)
    save_interval = clamp_save_interval(config.save_interval)
    backups = clamp_backups(config.backups)
    logger.info(
        "Config update: world=%s, server_name=%s, public=%s",
        config.world_name,
        config.server_name,
        config.server_public,
    )
    result = await pc_agent.post(
        "/valheim/config",
        {
            "server_name": config.server_name,
            "world_name": config.world_name,
            "server_pass": config.server_pass,
            "server_public": config.server_public,
            "crossplay": config.crossplay,
            "save_interval": save_interval,
            "backups": backups,
        },
    )
    logger.info("Config update completed")
    return result


# ══════════════════════════════════════════════════════════════════════════════
# Logs Endpoints
# ══════════════════════════════════════════════════════════════════════════════


@app.get("/api/logs")
async def get_logs(lines: int = LOGS_DEFAULT_LINES) -> dict[str, Any]:
    """Get recent Valheim server log entries.

    Retrieves the most recent log lines from the Valheim server via pc-agent.
    The number of lines is capped to prevent excessive memory usage.

    Args:
        lines: Number of log lines to retrieve (default: 80, max: 10000).

    Returns:
        Dictionary containing log entries from pc-agent.

    Example response::

        {
            "logs": [
                "10:23:45 - Player 'Viking' connected",
                "10:24:01 - World saved"
            ]
        }
    """
    lines = max(LOGS_MIN_LINES, min(lines, LOGS_MAX_LINES))
    return await pc_agent.get("/valheim/logs", params={"lines": str(lines)})


# ══════════════════════════════════════════════════════════════════════════════
# World Management Endpoints
# ══════════════════════════════════════════════════════════════════════════════


@app.get("/api/worlds")
async def list_worlds() -> dict[str, Any]:
    """List all available Valheim worlds.

    Retrieves the list of world files from pc-agent, including which
    world is currently active.

    Returns:
        Dictionary containing list of worlds from pc-agent.

    Example response::

        {
            "worlds": [
                {"name": "MyWorld", "active": true, "size_mb": 15.2},
                {"name": "TestWorld", "active": false, "size_mb": 2.1}
            ]
        }
    """
    return await pc_agent.get("/valheim/worlds")


@app.post("/api/worlds/new")
async def create_world(world_name: str = Form(...)) -> dict[str, Any]:
    """Create a new Valheim world.

    Creates a new empty world with the specified name. The world will not
    be activated automatically — use /api/worlds/activate for that.

    Args:
        world_name: Name for the new world (1-64 chars, alphanumeric,
            underscore, hyphen only).

    Returns:
        Result dictionary from pc-agent confirming creation.

    Raises:
        HTTPException: 400 if world_name is invalid.
    """
    validate_world_name(world_name)
    logger.info("Creating new world: %s", world_name)
    result = await pc_agent.post("/valheim/worlds/new", {"world_name": world_name})
    logger.info("World creation completed: %s", world_name)
    return result


@app.post("/api/worlds/activate")
async def activate_world(world_name: str = Form(...)) -> dict[str, Any]:
    """Activate a world for the server to use.

    Sets the specified world as the active world. The server should be
    restarted for the change to take effect.

    Args:
        world_name: Name of the world to activate.

    Returns:
        Result dictionary from pc-agent confirming activation.

    Raises:
        HTTPException: 400 if world_name is invalid.
    """
    validate_world_name(world_name)
    logger.info("Activating world: %s", world_name)
    result = await pc_agent.post("/valheim/worlds/activate", {"world_name": world_name})
    logger.info("World activation completed: %s", world_name)
    return result


@app.delete("/api/worlds/{world_name}")
async def delete_world(world_name: str) -> dict[str, Any]:
    """Delete a Valheim world.

    Permanently deletes the specified world and all its data. This action
    cannot be undone.

    Args:
        world_name: Name of the world to delete.

    Returns:
        Result dictionary from pc-agent confirming deletion.

    Raises:
        HTTPException: 400 if world_name is invalid.
    """
    validate_world_name(world_name)
    logger.warning("Deleting world: %s", world_name)
    result = await pc_agent.delete(f"/valheim/worlds/{world_name}")
    logger.warning("World deleted: %s", world_name)
    return result


# ══════════════════════════════════════════════════════════════════════════════
# Static File Mounting
# ══════════════════════════════════════════════════════════════════════════════

_static = Path(__file__).parent / "static"
if _static.exists():
    app.mount("/static", StaticFiles(directory=str(_static)), name="static")
