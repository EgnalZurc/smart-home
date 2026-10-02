"""pc-agent — Lightweight agent running on Windows PC.

Exposes HTTP API for remote control of:
- Valheim server container (start/stop/status)
- Valheim worlds management (list, activate, upload, delete)
- Valheim server configuration (.env)
- Valheim server logs
- Windows power profiles (gaming/servidor/balanced)

Runs as native Python on Windows (not containerized) to enable
direct PowerShell execution for power profile changes.

Port: 8090
Auth: X-Api-Token header (all routes except /health)
"""

import logging
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import docker
from dotenv import load_dotenv
from fastapi import FastAPI, Form, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

# Load .env from script directory
load_dotenv(Path(__file__).parent.parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

API_TOKEN = os.environ.get("PC_AGENT_TOKEN", "")
VALHEIM_CONTAINER = os.environ.get("VALHEIM_CONTAINER", "valheim-server")
SCRIPTS_DIR = Path(os.environ.get("SCRIPTS_DIR", r"C:\Users\acmls\Documents\Scripts"))

# Valheim server paths (on Windows PC)
VALHEIM_SERVER_DIR = Path(os.environ.get("VALHEIM_SERVER_DIR", r"E:\valheim-server"))
VALHEIM_ENV_FILE = VALHEIM_SERVER_DIR / ".env"
VALHEIM_WORLDS_DIR = VALHEIM_SERVER_DIR / "server_data" / "worlds_local"
VALHEIM_LOGS_DIR = VALHEIM_SERVER_DIR / "server_data" / "logs"

# Power profile script mapping
POWER_SCRIPTS = {
    "gaming": "ModoGaming.ps1",
    "servidor": "ModoServidor.ps1",
    "balanced": "ModoBalanced.ps1",
}

# Max upload size: 600 MB
MAX_UPLOAD_BYTES = 600 * 1024 * 1024

if not API_TOKEN:
    logger.warning("PC_AGENT_TOKEN not set — API is unprotected!")

# ── Docker client ─────────────────────────────────────────────────────────────

try:
    docker_client = docker.from_env()
    docker_client.ping()
    logger.info("Docker connection established")
except Exception as e:
    logger.error("Failed to connect to Docker: %s", e)
    docker_client = None

# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="pc-agent",
    version="1.0.0",
    description="Remote control agent for Windows PC (Valheim server + power profiles)",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Auth ──────────────────────────────────────────────────────────────────────


def require_auth(x_api_token: str = Header(None, alias="X-Api-Token")):
    """Validate API token from header."""
    if not API_TOKEN:
        return
    if x_api_token != API_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid or missing API token")


# ── Health (no auth) ──────────────────────────────────────────────────────────


@app.get("/health")
def health():
    """Health check — no authentication required."""
    docker_ok = docker_client is not None
    try:
        if docker_client:
            docker_client.ping()
    except Exception:
        docker_ok = False

    return {
        "online": True,
        "service": "pc-agent",
        "docker": docker_ok,
    }


# ── Valheim container control ─────────────────────────────────────────────────


@app.get("/valheim/status")
def valheim_status(x_api_token: str = Header(None, alias="X-Api-Token")):
    """Get Valheim server container status."""
    require_auth(x_api_token)

    if not docker_client:
        raise HTTPException(503, "Docker not available")

    try:
        container = docker_client.containers.get(VALHEIM_CONTAINER)
        state = container.attrs.get("State", {})

        # Calculate uptime
        uptime_seconds = None
        started_at = state.get("StartedAt")
        if started_at and container.status == "running":
            try:
                dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
                uptime_seconds = int((datetime.now(timezone.utc) - dt).total_seconds())
            except Exception:
                pass

        # Get join code and players from logs
        join_code = None
        players = 0
        log = _latest_log_file()
        if log and log.exists():
            try:
                lines = log.read_text(errors="replace")
                recent = "\n".join(lines.splitlines()[-500:])
                join_code = _parse_join_code(recent)
                players = _parse_players(recent)
            except Exception:
                pass

        # Get world info from .env
        env = _read_env()

        return {
            "container": VALHEIM_CONTAINER,
            "status": container.status,
            "running": container.status == "running",
            "started_at": started_at,
            "finished_at": state.get("FinishedAt"),
            "exit_code": state.get("ExitCode"),
            "health": state.get("Health", {}).get("Status"),
            "uptime_seconds": uptime_seconds,
            "world": env.get("WORLD_NAME", "—"),
            "server_name": env.get("SERVER_NAME", "—"),
            "crossplay": env.get("CROSSPLAY", "false") == "true",
            "join_code": join_code,
            "players": players,
        }
    except docker.errors.NotFound:
        return {
            "container": VALHEIM_CONTAINER,
            "status": "not_found",
            "running": False,
            "error": f"Container '{VALHEIM_CONTAINER}' not found",
        }
    except Exception as e:
        logger.error("Error getting container status: %s", e)
        raise HTTPException(500, f"Docker error: {e}")


@app.post("/valheim/start")
def valheim_start(x_api_token: str = Header(None, alias="X-Api-Token")):
    """Start Valheim server container."""
    require_auth(x_api_token)

    if not docker_client:
        raise HTTPException(503, "Docker not available")

    try:
        container = docker_client.containers.get(VALHEIM_CONTAINER)

        if container.status == "running":
            return {"status": "already_running", "container": VALHEIM_CONTAINER}

        container.start()
        logger.info("Started container: %s", VALHEIM_CONTAINER)

        return {"status": "started", "container": VALHEIM_CONTAINER}

    except docker.errors.NotFound:
        raise HTTPException(404, f"Container '{VALHEIM_CONTAINER}' not found")
    except Exception as e:
        logger.error("Error starting container: %s", e)
        raise HTTPException(500, f"Failed to start: {e}")


@app.post("/valheim/stop")
def valheim_stop(x_api_token: str = Header(None, alias="X-Api-Token")):
    """Stop Valheim server container gracefully."""
    require_auth(x_api_token)

    if not docker_client:
        raise HTTPException(503, "Docker not available")

    try:
        container = docker_client.containers.get(VALHEIM_CONTAINER)

        if container.status != "running":
            return {"status": "already_stopped", "container": VALHEIM_CONTAINER}

        container.stop(timeout=30)
        logger.info("Stopped container: %s", VALHEIM_CONTAINER)

        return {"status": "stopped", "container": VALHEIM_CONTAINER}

    except docker.errors.NotFound:
        raise HTTPException(404, f"Container '{VALHEIM_CONTAINER}' not found")
    except Exception as e:
        logger.error("Error stopping container: %s", e)
        raise HTTPException(500, f"Failed to stop: {e}")


@app.post("/valheim/restart")
def valheim_restart(x_api_token: str = Header(None, alias="X-Api-Token")):
    """Restart Valheim server container."""
    require_auth(x_api_token)

    if not docker_client:
        raise HTTPException(503, "Docker not available")

    try:
        container = docker_client.containers.get(VALHEIM_CONTAINER)
        container.restart(timeout=30)
        logger.info("Restarted container: %s", VALHEIM_CONTAINER)
        return {"status": "restarted", "container": VALHEIM_CONTAINER}

    except docker.errors.NotFound:
        raise HTTPException(404, f"Container '{VALHEIM_CONTAINER}' not found")
    except Exception as e:
        logger.error("Error restarting container: %s", e)
        raise HTTPException(500, f"Failed to restart: {e}")


# ── Valheim .env helpers ──────────────────────────────────────────────────────


def _read_env() -> dict[str, str]:
    """Read Valheim .env file into a dict."""
    env: dict[str, str] = {}
    if not VALHEIM_ENV_FILE.exists():
        return env
    for line in VALHEIM_ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    return env


def _write_env(env: dict[str, str]) -> None:
    """Write dict back to .env, preserving comments."""
    lines = []
    if VALHEIM_ENV_FILE.exists():
        existing = VALHEIM_ENV_FILE.read_text().splitlines()
        written = set()
        for line in existing:
            stripped = line.strip()
            if stripped.startswith("#") or not stripped:
                lines.append(line)
            elif "=" in stripped:
                k = stripped.split("=", 1)[0].strip()
                if k in env:
                    lines.append(f"{k}={env[k]}")
                    written.add(k)
                else:
                    lines.append(line)
        for k, v in env.items():
            if k not in written:
                lines.append(f"{k}={v}")
    else:
        lines = [f"{k}={v}" for k, v in env.items()]
    VALHEIM_ENV_FILE.write_text("\n".join(lines) + "\n")


# ── Valheim log helpers ───────────────────────────────────────────────────────


def _latest_log_file() -> Path | None:
    """Return the most recent log file."""
    if not VALHEIM_LOGS_DIR.exists():
        return None
    logs = sorted(VALHEIM_LOGS_DIR.glob("valheim_*.log"), reverse=True)
    return logs[0] if logs else None


def _parse_join_code(log_lines: str) -> str | None:
    """Extract 6-digit join code from logs."""
    match = re.search(r"with join code\s+(\d{6})\b", log_lines, re.IGNORECASE)
    if match:
        return match.group(1)
    match = re.search(r"join code[:\s]+(\d{6})\b", log_lines, re.IGNORECASE)
    return match.group(1) if match else None


def _parse_players(log_lines: str) -> int:
    """Estimate current players from logs."""
    connects = len(re.findall(r"Got handshake from client", log_lines))
    disconnects = len(re.findall(r"Closing socket.*ZDOID", log_lines))
    return max(0, connects - disconnects)


# ── Valheim config endpoints ──────────────────────────────────────────────────


@app.get("/valheim/config")
def get_config(x_api_token: str = Header(None, alias="X-Api-Token")):
    """Get Valheim server configuration."""
    require_auth(x_api_token)
    env = _read_env()
    return {
        "server_name": env.get("SERVER_NAME", ""),
        "world_name": env.get("WORLD_NAME", ""),
        "server_pass": env.get("SERVER_PASS", ""),
        "server_public": env.get("SERVER_PUBLIC", "0") == "1",
        "crossplay": env.get("CROSSPLAY", "false") == "true",
        "save_interval": int(env.get("SAVE_INTERVAL", "1800")),
        "backups": int(env.get("BACKUPS", "4")),
    }


@app.post("/valheim/config")
def update_config(
    server_name: str = Form(...),
    world_name: str = Form(...),
    server_pass: str = Form(...),
    server_public: bool = Form(False),
    crossplay: bool = Form(False),
    save_interval: int = Form(1800),
    backups: int = Form(4),
    x_api_token: str = Header(None, alias="X-Api-Token"),
):
    """Update Valheim server configuration and restart."""
    require_auth(x_api_token)

    if len(server_pass) < 5:
        raise HTTPException(400, "Password must be at least 5 characters")
    if not world_name.strip():
        raise HTTPException(400, "World name cannot be empty")

    env = _read_env()
    env["SERVER_NAME"] = server_name
    env["WORLD_NAME"] = world_name
    env["SERVER_PASS"] = server_pass
    env["SERVER_PUBLIC"] = "1" if server_public else "0"
    env["CROSSPLAY"] = "true" if crossplay else "false"
    env["SAVE_INTERVAL"] = str(save_interval)
    env["BACKUPS"] = str(backups)
    _write_env(env)

    # Restart container to apply new config
    if docker_client:
        try:
            container = docker_client.containers.get(VALHEIM_CONTAINER)
            if container.status == "running":
                container.restart(timeout=30)
                logger.info("Restarted container after config update")
        except Exception as e:
            logger.warning("Could not restart container: %s", e)

    return {"status": "ok", "message": "Config saved, server restarting…"}


# ── Valheim logs endpoint ─────────────────────────────────────────────────────


@app.get("/valheim/logs")
def get_logs(
    lines: int = 80,
    x_api_token: str = Header(None, alias="X-Api-Token"),
):
    """Get recent Valheim server logs."""
    require_auth(x_api_token)
    log = _latest_log_file()
    if not log or not log.exists():
        return {"lines": [], "file": None}
    try:
        all_lines = log.read_text(errors="replace").splitlines()
        return {"lines": all_lines[-lines:], "file": log.name}
    except Exception as e:
        return {"lines": [], "error": str(e)}


# ── Valheim worlds endpoints ──────────────────────────────────────────────────


def _world_format(world_path: Path) -> str:
    """Return 'v1', 'legacy', or 'empty'."""
    if any(world_path.glob("*.db2")) or any(world_path.glob("*.fwl2")):
        return "v1"
    if any(world_path.glob("*.db")) or any(world_path.glob("*.fwl")):
        return "legacy"
    return "empty"


def _sanitize_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_\-]", "", name.strip())


@app.get("/valheim/worlds")
def list_worlds(x_api_token: str = Header(None, alias="X-Api-Token")):
    """List available world folders."""
    require_auth(x_api_token)

    if not VALHEIM_WORLDS_DIR.exists():
        return {"worlds": [], "active": None}

    env = _read_env()
    active = env.get("WORLD_NAME", "")
    worlds = []

    for p in sorted(VALHEIM_WORLDS_DIR.iterdir()):
        if not p.is_dir():
            continue
        if re.search(r"_backup_(auto|20\d{6})", p.name, re.IGNORECASE):
            continue
        fmt = _world_format(p)
        worlds.append({
            "name": p.name,
            "active": p.name == active,
            "has_data": fmt != "empty",
            "format": fmt,
        })

    return {"worlds": worlds, "active": active}


@app.post("/valheim/worlds/new")
def create_world(
    world_name: str = Form(...),
    x_api_token: str = Header(None, alias="X-Api-Token"),
):
    """Create a new empty world folder."""
    require_auth(x_api_token)

    if not world_name.strip():
        raise HTTPException(400, "World name cannot be empty")
    safe = _sanitize_name(world_name)
    if not safe:
        raise HTTPException(400, "Invalid world name")

    world_path = VALHEIM_WORLDS_DIR / safe
    if world_path.exists():
        raise HTTPException(400, f"World '{safe}' already exists")

    world_path.mkdir(parents=True, exist_ok=True)
    return {"status": "ok", "world": safe}


@app.post("/valheim/worlds/activate")
def activate_world(
    world_name: str = Form(...),
    x_api_token: str = Header(None, alias="X-Api-Token"),
):
    """Switch active world and restart server."""
    require_auth(x_api_token)

    world_path = VALHEIM_WORLDS_DIR / world_name
    world_path.mkdir(parents=True, exist_ok=True)

    env = _read_env()
    env["WORLD_NAME"] = world_name
    _write_env(env)

    # Restart container
    if docker_client:
        try:
            container = docker_client.containers.get(VALHEIM_CONTAINER)
            if container.status == "running":
                container.restart(timeout=30)
                logger.info("Restarted container for world switch to %s", world_name)
        except Exception as e:
            logger.warning("Could not restart container: %s", e)

    return {"status": "ok", "world": world_name, "message": f"Switched to {world_name}"}


@app.delete("/valheim/worlds/{world_name}")
def delete_world(
    world_name: str,
    x_api_token: str = Header(None, alias="X-Api-Token"),
):
    """Delete a world (cannot delete active world)."""
    require_auth(x_api_token)

    env = _read_env()
    active = env.get("WORLD_NAME", "")
    if world_name == active:
        raise HTTPException(400, f"Cannot delete active world '{world_name}'")

    world_path = VALHEIM_WORLDS_DIR / world_name
    if not world_path.exists():
        raise HTTPException(404, f"World '{world_name}' not found")

    deleted = [world_name]
    shutil.rmtree(world_path)

    # Also delete backup folders
    for p in VALHEIM_WORLDS_DIR.iterdir():
        if p.is_dir() and p.name.startswith(f"{world_name}_backup_"):
            shutil.rmtree(p)
            deleted.append(p.name)

    return {"status": "ok", "deleted": deleted}


# ── Power profile control ─────────────────────────────────────────────────────


@app.get("/system/mode")
def get_power_mode(x_api_token: str = Header(None, alias="X-Api-Token")):
    """Get current power profile."""
    require_auth(x_api_token)

    try:
        result = subprocess.run(
            ["powercfg", "/getactivescheme"],
            capture_output=True,
            text=True,
            timeout=5,
        )

        if result.returncode != 0:
            return {"mode": "unknown", "error": result.stderr.strip()}

        output = result.stdout.strip()
        if "(" in output and ")" in output:
            name = output.split("(")[-1].rstrip(")")
            name_lower = name.lower()
            if "high" in name_lower or "rendimiento" in name_lower:
                mode = "gaming"
            elif "balanced" in name_lower or "equilibrado" in name_lower:
                mode = "balanced"
            elif "power saver" in name_lower or "economizador" in name_lower:
                mode = "servidor"
            else:
                mode = "custom"
            return {"mode": mode, "windows_name": name}

        return {"mode": "unknown", "raw": output}

    except Exception as e:
        return {"mode": "unknown", "error": str(e)}


@app.post("/system/mode/{mode}")
def set_power_mode(mode: str, x_api_token: str = Header(None, alias="X-Api-Token")):
    """Set power profile."""
    require_auth(x_api_token)

    if mode not in POWER_SCRIPTS:
        raise HTTPException(400, f"Invalid mode. Valid: {list(POWER_SCRIPTS.keys())}")

    script_path = SCRIPTS_DIR / POWER_SCRIPTS[mode]
    if not script_path.exists():
        raise HTTPException(404, f"Script not found: {script_path}")

    try:
        result = subprocess.run(
            ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(script_path)],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            raise HTTPException(500, f"Script failed: {result.stderr.strip()}")

        logger.info("Power mode changed to: %s", mode)
        return {"status": "ok", "mode": mode}

    except subprocess.TimeoutExpired:
        raise HTTPException(500, "Script timeout")
    except Exception as e:
        raise HTTPException(500, f"Failed: {e}")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8090)
