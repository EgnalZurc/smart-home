"""Valheim Admin — lightweight management web app for the Valheim dedicated server.
Runs alongside valheim-server in the same docker-compose.
Shares the .env file and server_data volume with the game container.
Port: 8080 (internal, proxied by nginx via /valheim-admin/)
Auth: nginx handles auth_request — this service trusts all incoming requests.
Endpoints:
  GET  /              → serves index.html
  GET  /health        → health check
  GET  /api/status    → server state, world, join code, players
  GET  /api/config    → current .env config
  POST /api/config    → save .env + restart server
  GET  /api/worlds    → list available worlds in worlds_local/
  POST /api/worlds/activate  → set WORLD_NAME and restart
  POST /api/server/restart   → restart valheim-server container
  POST /api/server/stop      → stop valheim-server container
  POST /api/server/start     → start valheim-server container
  GET  /api/logs      → last N lines of today's log file
  POST /api/worlds/upload    → upload world save:
                               - Valheim 1.0: single .zip of the world folder
                               - Legacy/backup: .db + .fwl pair
"""
import os
import re
import time
import zipfile
import shutil
import tempfile
import subprocess
import httpx
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ── Paths ─────────────────────────────────────────────────────────────────────
ENV_FILE    = Path(os.environ.get("VALHEIM_ENV_FILE",    "/config/.env"))
WORLDS_DIR  = Path(os.environ.get("VALHEIM_WORLDS_DIR",  "/server_data/worlds_local"))
LOGS_DIR    = Path(os.environ.get("VALHEIM_LOGS_DIR",    "/server_data/logs"))

# docker-socket-proxy — same one the smart-home backend uses
DOCKER_PROXY   = "http://docker-socket-proxy:2375/v1.41"
GAME_CONTAINER = "valheim-server"

# Valid extensions in a Valheim 1.0 world folder
WORLD_V1_EXTS = {".db2", ".fwl2", ".ok", ".chunks", ".chunk"}
# Valid extensions for legacy saves / backups
WORLD_LEGACY_EXTS = {".db", ".fwl"}
# Max upload size: 600 MB (world zips can be large)
MAX_UPLOAD_BYTES = 600 * 1024 * 1024

app = FastAPI(title="Valheim Admin", version="1.0.0")

# ── Helpers ───────────────────────────────────────────────────────────────────
def read_env() -> dict[str, str]:
    """Read .env file into a dict."""
    env: dict[str, str] = {}
    if not ENV_FILE.exists():
        return env
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    return env


def write_env(env: dict[str, str]) -> None:
    """Write dict back to .env, preserving comments as best as possible."""
    lines = []
    if ENV_FILE.exists():
        existing = ENV_FILE.read_text().splitlines()
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
    ENV_FILE.write_text("\n".join(lines) + "\n")


async def docker_get(path: str) -> dict:
    async with httpx.AsyncClient(timeout=5.0) as client:
        r = await client.get(f"{DOCKER_PROXY}{path}")
        r.raise_for_status()
        return r.json()


async def docker_post(path: str) -> int:
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.post(f"{DOCKER_PROXY}{path}")
        return r.status_code


async def recreate_game_container() -> str:
    """Force-recreate valheim-server so new env vars from .env take effect.
    Strategy:
    1. Stop the container via Docker API (docker-socket-proxy)
    2. Remove the container via Docker socket directly (bypass proxy)
    3. Run docker compose up via subprocess to recreate with new env vars
    Falls back to plain restart if any step fails.
    """
    import socket as _socket

    compose_file = os.environ.get("VALHEIM_COMPOSE_FILE", "/compose/docker-compose.yml")
    compose_dir  = str(Path(compose_file).parent)
    sock_path    = "/var/run/docker.sock"

    def _docker_api(method: str, path: str, body: bytes = b"") -> tuple[int, bytes]:
        """Minimal raw Docker API call via Unix socket."""
        with _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM) as s:
            s.connect(sock_path)
            content_header = f"Content-Length: {len(body)}\r\n" if body else ""
            content_type   = "Content-Type: application/json\r\n" if body else ""
            req = (
                f"{method} {path} HTTP/1.1\r\n"
                f"Host: localhost\r\n"
                f"{content_type}{content_header}"
                f"Connection: close\r\n\r\n"
            ).encode() + body
            s.sendall(req)
            resp = b""
            while chunk := s.recv(4096):
                resp += chunk
        header, _, rbody = resp.partition(b"\r\n\r\n")
        status_line = header.split(b"\r\n")[0]
        code = int(status_line.split(b" ")[1])
        return code, rbody

    try:
        # 1. Stop (15s grace)
        _docker_api("POST", f"/v1.41/containers/{GAME_CONTAINER}/stop?t=15")

        # 2. Remove
        rc, body = _docker_api("DELETE", f"/v1.41/containers/{GAME_CONTAINER}?force=true")
        if rc not in (204, 200):
            raise RuntimeError(f"rm failed: {rc} {body[:200]}")

        # 3. Recreate via docker compose up
        result = subprocess.run(
            ["docker", "compose", "-f", compose_file, "up", "-d", GAME_CONTAINER],
            cwd=compose_dir,
            capture_output=True, text=True, timeout=90
        )
        if result.returncode == 0:
            return "recreated"
        raise RuntimeError(
            f"compose up failed (rc={result.returncode}): "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )

    except Exception as exc:
        # Last resort: plain restart via proxy
        try:
            code = await docker_post(f"/containers/{GAME_CONTAINER}/restart?t=15")
            return f"restarted_fallback (recreate failed: {exc})"
        except Exception:
            raise HTTPException(500, f"Failed to recreate container: {exc}")


def latest_log_file() -> Optional[Path]:
    """Return the most recent log file in the logs directory."""
    if not LOGS_DIR.exists():
        return None
    logs = sorted(LOGS_DIR.glob("valheim_*.log"), reverse=True)
    return logs[0] if logs else None


def parse_join_code(log_lines: str) -> Optional[str]:
    """Extract 6-digit join code from Valheim server logs."""
    match = re.search(r'with join code\s+(\d{6})\b', log_lines, re.IGNORECASE)
    if match:
        return match.group(1)
    match = re.search(r'join code[:\s]+(\d{6})\b', log_lines, re.IGNORECASE)
    return match.group(1) if match else None


def parse_players(log_lines: str) -> int:
    connects    = len(re.findall(r'Got handshake from client', log_lines))
    disconnects = len(re.findall(r'Closing socket.*ZDOID', log_lines))
    return max(0, connects - disconnects)


def _world_format(world_path: Path) -> str:
    """Return 'v1' (Valheim 1.0 chunks), 'legacy' (.db/.fwl), or 'empty'."""
    if any(world_path.glob("*.db2")) or any(world_path.glob("*.fwl2")):
        return "v1"
    if any(world_path.glob("*.db")) or any(world_path.glob("*.fwl")):
        return "legacy"
    return "empty"


def _sanitize_name(name: str) -> str:
    return re.sub(r'[^a-zA-Z0-9_\-]', '', name.strip())


# ── Valheim binary validators ─────────────────────────────────────────────────
# Valheim 1.0 uses a binary protocol version tag (int32 LE = 41 = 0x29)
# as the first meaningful integer in all world files.
VALHEIM_V1_VERSION = 41
VALHEIM_V1_VERSION_BYTES = VALHEIM_V1_VERSION.to_bytes(4, "little")  # b'\x29\x00\x00\x00'

def _validate_fwl2(data: bytes, expected_world_name: str) -> Optional[str]:
    """Validate a .fwl2 file. Returns None if valid, error string if invalid.

    fwl2 binary layout (little-endian):
      [0..3]  int32  total data length (=len(data)-4 typically)
      [4..7]  int32  protocol version  (must be 41 for Valheim 1.0)
      [8]     byte   world name string length
      [9..]   utf8   world name string
    """
    if len(data) < 16:
        return "Fichero .fwl2 demasiado pequeño para ser válido."
    version = int.from_bytes(data[4:8], "little")
    if version != VALHEIM_V1_VERSION:
        return f"Versión de .fwl2 inesperada ({version}), se esperaba {VALHEIM_V1_VERSION}."
    try:
        name_len = data[8]
        if 9 + name_len > len(data):
            return "Longitud de nombre de mundo inválida en .fwl2."
        world_name_in_file = data[9:9 + name_len].decode("utf-8")
        if world_name_in_file != expected_world_name:
            return (
                f"El nombre del mundo en .fwl2 ('{world_name_in_file}') "
                f"no coincide con la carpeta ('{expected_world_name}'). "
                f"Asegúrate de comprimir la carpeta correcta."
            )
    except (UnicodeDecodeError, IndexError):
        return "No se pudo leer el nombre del mundo del .fwl2."
    return None


def _validate_db2(data: bytes) -> Optional[str]:
    """Validate a .db2 file. Returns None if valid, error string if invalid.

    db2 binary layout:
      [0..3]  int32  protocol version  (must be 41 for Valheim 1.0)
      ... rest is world data
    """
    if len(data) < 8:
        return "Fichero .db2 demasiado pequeño para ser válido."
    version = int.from_bytes(data[0:4], "little")
    if version != VALHEIM_V1_VERSION:
        return f"Versión de .db2 inesperada ({version}), se esperaba {VALHEIM_V1_VERSION}."
    return None


def _validate_ok(data: bytes) -> Optional[str]:
    """Validate a .ok file. Must be exactly 4 bytes = protocol version."""
    if len(data) != 4:
        return f"Fichero .ok tiene tamaño inesperado ({len(data)} bytes, se esperaban 4)."
    version = int.from_bytes(data, "little")
    if version != VALHEIM_V1_VERSION:
        return f"Fichero .ok con versión inesperada ({version})."
    return None


def _validate_chunk(data: bytes) -> Optional[str]:
    """Validate a .chunk file. First 2 bytes should be 0x29 0x00."""
    if len(data) < 4:
        return f"Fichero .chunk demasiado pequeño ({len(data)} bytes)."
    if data[0] != 0x29 or data[1] != 0x00:
        return f"Cabecera de .chunk inesperada ({data[0]:02X} {data[1]:02X})."
    return None


def _validate_world_files(dest: Path, world_name: str) -> list[str]:
    """Run binary validation on all extracted world files.
    Returns a list of warning strings (non-fatal issues).
    Raises HTTPException on fatal errors.
    """
    warnings: list[str] = []
    fatal: list[str] = []

    fwl2_files = list(dest.glob("*.fwl2"))
    db2_files  = list(dest.glob("*.db2"))
    ok_files   = list(dest.glob("*.ok"))
    chunk_files = list(dest.glob("*.chunk"))

    # Must have at least one .fwl2 and one .db2
    if not fwl2_files:
        fatal.append("No se encontró ningún fichero .fwl2 en el mundo.")
    if not db2_files:
        fatal.append("No se encontró ningún fichero .db2 en el mundo.")

    if fatal:
        raise HTTPException(400, " ".join(fatal))

    # Validate .fwl2
    for f in fwl2_files:
        data = f.read_bytes()
        err = _validate_fwl2(data, world_name)
        if err:
            fatal.append(f"{f.name}: {err}")

    # Validate .db2
    for f in db2_files:
        data = f.read_bytes()
        err = _validate_db2(data)
        if err:
            fatal.append(f"{f.name}: {err}")

    if fatal:
        raise HTTPException(400, " | ".join(fatal))

    # Validate .ok (non-fatal — server regenerates it if missing)
    for f in ok_files:
        data = f.read_bytes()
        err = _validate_ok(data)
        if err:
            warnings.append(f"{f.name}: {err}")

    # Validate chunks (sample first 3 to avoid reading hundreds of MB)
    for f in chunk_files[:3]:
        data = f.read_bytes()
        err = _validate_chunk(data)
        if err:
            warnings.append(f"{f.name}: {err}")

    return warnings


# ── Routes ────────────────────────────────────────────────────────────────────
@app.get("/api/network")
async def get_network():
    env = read_env()
    host_ip = env.get("HOST_IP", "").strip()
    if host_ip:
        return {"local_ip": host_ip, "port": 2456}
    try:
        fib = Path("/proc/net/fib_trie").read_text()
        import re as _re
        candidates = _re.findall(r'(\d+\.\d+\.\d+\.\d+)', fib)
        seen = set()
        for ip in candidates:
            if ip in seen:
                continue
            seen.add(ip)
            parts = ip.split(".")
            if parts[0] in ("127", "172", "100", "0"):
                continue
            if ip.endswith(".0") or ip.endswith(".255"):
                continue
            return {"local_ip": ip, "port": 2456}
    except Exception:
        pass
    return {"local_ip": "raspberrypi.local", "port": 2456}


@app.get("/health")
def health():
    return {"online": True, "service": "valheim-admin"}


@app.get("/", response_class=HTMLResponse)
async def serve_index():
    path = Path(__file__).parent / "static" / "index.html"
    content = path.read_text(encoding="utf-8")
    content = content.replace("</head>", f"<!-- v:{int(time.time())} -->\n</head>")
    return HTMLResponse(content=content, headers={
        "Cache-Control": "no-cache, no-store, must-revalidate"
    })


@app.get("/api/status")
async def get_status():
    env = read_env()
    status = {
        "running":        False,
        "world":          env.get("WORLD_NAME", "—"),
        "server_name":    env.get("SERVER_NAME", "—"),
        "crossplay":      env.get("CROSSPLAY", "0") == "true",
        "join_code":      None,
        "players":        0,
        "uptime_seconds": None,
    }
    try:
        data  = await docker_get(f"/containers/{GAME_CONTAINER}/json")
        state = data.get("State", {})
        status["running"] = state.get("Status") == "running"
        started = state.get("StartedAt", "")
        if started and status["running"]:
            from datetime import datetime, timezone
            try:
                dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
                status["uptime_seconds"] = int((datetime.now(timezone.utc) - dt).total_seconds())
            except Exception:
                pass
    except Exception:
        pass
    log = latest_log_file()
    if log and log.exists():
        try:
            lines  = log.read_text(errors="replace").splitlines()
            recent = "\n".join(lines[-500:])
            status["join_code"] = parse_join_code(recent)
            status["players"]   = parse_players(recent)
        except Exception:
            pass
    return status


@app.get("/api/config")
def get_config():
    env = read_env()
    return {
        "server_name":   env.get("SERVER_NAME", ""),
        "world_name":    env.get("WORLD_NAME", ""),
        "server_pass":   env.get("SERVER_PASS", ""),
        "server_public": env.get("SERVER_PUBLIC", "0") == "1",
        "crossplay":     env.get("CROSSPLAY", "false") == "true",
        "save_interval": int(env.get("SAVE_INTERVAL", "1800")),
        "backups":       int(env.get("BACKUPS", "4")),
    }


class ConfigUpdate(BaseModel):
    server_name:   str
    world_name:    str
    server_pass:   str
    server_public: bool = False
    crossplay:     bool = False
    save_interval: int  = 1800
    backups:       int  = 4


@app.post("/api/config")
async def update_config(cfg: ConfigUpdate):
    if len(cfg.server_pass) < 5:
        raise HTTPException(400, "Password must be at least 5 characters")
    if not cfg.world_name.strip():
        raise HTTPException(400, "World name cannot be empty")
    env = read_env()
    env["SERVER_NAME"]   = cfg.server_name
    env["WORLD_NAME"]    = cfg.world_name
    env["SERVER_PASS"]   = cfg.server_pass
    env["SERVER_PUBLIC"] = "1" if cfg.server_public else "0"
    env["CROSSPLAY"]     = "true" if cfg.crossplay else "false"
    env["SAVE_INTERVAL"] = str(cfg.save_interval)
    env["BACKUPS"]       = str(cfg.backups)
    write_env(env)
    await recreate_game_container()
    return {"status": "ok", "message": "Config saved, server restarting…"}


@app.get("/api/worlds")
def list_worlds():
    """List available world folders."""
    if not WORLDS_DIR.exists():
        return {"worlds": [], "active": None}
    env    = read_env()
    active = env.get("WORLD_NAME", "")
    worlds = []
    for p in sorted(WORLDS_DIR.iterdir()):
        if not p.is_dir():
            continue
        # Skip backup folders created by the game engine
        if re.search(r'_backup_(auto|20\d{6})', p.name, re.IGNORECASE):
            continue
        fmt = _world_format(p)
        worlds.append({
            "name":     p.name,
            "active":   p.name == active,
            "has_data": fmt != "empty",
            "format":   fmt,   # 'v1' | 'legacy' | 'empty'
        })
    return {"worlds": worlds, "active": active}


@app.post("/api/worlds/new")
async def create_world(world_name: str = Form(...)):
    """Create a new empty world folder."""
    if not world_name.strip():
        raise HTTPException(400, "World name cannot be empty")
    safe = _sanitize_name(world_name)
    if not safe:
        raise HTTPException(400, "Invalid world name — use letters, numbers, _ or -")
    world_path = WORLDS_DIR / safe
    if world_path.exists():
        raise HTTPException(400, f"World '{safe}' already exists")
    world_path.mkdir(parents=True, exist_ok=True)
    return {"status": "ok", "world": safe, "message": f"World '{safe}' created. Activate it to start playing."}


@app.post("/api/worlds/activate")
async def activate_world(world_name: str = Form(...)):
    """Switch active world and force-recreate the server container so new env vars apply."""
    world_path = WORLDS_DIR / world_name
    world_path.mkdir(parents=True, exist_ok=True)
    env = read_env()
    env["WORLD_NAME"] = world_name
    write_env(env)
    action = await recreate_game_container()
    return {"status": "ok", "action": action,
            "message": f"Switched to {world_name}, server {action}…"}


@app.post("/api/worlds/upload")
async def upload_world(file: UploadFile = File(...)):
    """Upload a Valheim world save.

    Accepted formats:
    ─────────────────────────────────────────────────────────────────
    Valheim 1.0 (cloud save / worlds_local folder):
      • A single .zip file containing the world folder contents.
        The zip must contain a root folder named after the world, e.g.:
          Egnal1/
            _main.1.db2
            _main.1.fwl2
            _main.1.ok
            *.chunk  (optional)
        OR a flat zip (no root folder) with at least one .db2 / .fwl2.

    Legacy / backup format (pre-1.0 or manual backups):
      • Two files: WorldName.db + WorldName.fwl
        (Use the /api/worlds/upload-legacy endpoint for this mode)
    ─────────────────────────────────────────────────────────────────
    """
    filename = file.filename or ""
    ext = Path(filename).suffix.lower()

    if ext != ".zip":
        raise HTTPException(
            400,
            "Sube un fichero .zip con la carpeta del mundo (formato Valheim 1.0). "
            "Si tienes un save antiguo (.db + .fwl), usa la opción 'Subir backup legacy'."
        )

    content = await file.read()
    if len(content) < 10:
        raise HTTPException(400, "El fichero zip está vacío.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, f"El fichero supera el límite de {MAX_UPLOAD_BYTES // (1024*1024)} MB.")

    # ── Validate zip and extract world name ──────────────────────────────────
    try:
        with zipfile.ZipFile(tempfile.SpooledTemporaryFile(max_size=MAX_UPLOAD_BYTES)) as _test:
            pass
    except Exception:
        pass

    tmpdir = Path(tempfile.mkdtemp())
    try:
        zip_path = tmpdir / "upload.zip"
        zip_path.write_bytes(content)

        with zipfile.ZipFile(zip_path, "r") as zf:
            # Normalize separators: Windows zips use backslash
            raw_names = zf.namelist()
            names = [n.replace("\\", "/") for n in raw_names]
            if not names:
                raise HTTPException(400, "El zip está vacío.")

            # Detect structure: rooted (Egnal1/file) or flat (file)
            # Rooted: most entries start with the same folder prefix
            root_dirs = {n.split("/")[0] for n in names if "/" in n}
            flat_files = [n for n in names if "/" not in n and n.strip()]

            # Check for Valheim 1.0 files anywhere in the zip
            all_exts = {Path(n).suffix.lower() for n in names}
            has_v1   = bool(all_exts & {".db2", ".fwl2"})
            has_legacy = bool(all_exts & {".db", ".fwl"})

            if not has_v1 and not has_legacy:
                raise HTTPException(
                    400,
                    "El zip no contiene ficheros de save de Valheim. "
                    "Debe incluir ficheros .db2/.fwl2 (formato 1.0) o .db/.fwl (backup)."
                )

            # Determine world name from zip structure
            if len(root_dirs) == 1:
                world_name = next(iter(root_dirs))
            elif flat_files:
                # Flat zip: infer from .fwl2 or .fwl stem
                for n in names:
                    if Path(n).suffix.lower() in (".fwl2", ".fwl"):
                        stem = Path(n).stem
                        # Remove Valheim internal prefix _main.N
                        stem = re.sub(r'^_main\.\d+', '', stem).strip(".")
                        if stem:
                            world_name = stem
                            break
                else:
                    raise HTTPException(400, "No se pudo determinar el nombre del mundo desde el zip.")
            else:
                raise HTTPException(400, "Estructura de zip no reconocida.")

            # Sanitize world name
            world_name = _sanitize_name(world_name)
            if not world_name:
                raise HTTPException(400, "Nombre de mundo inválido en el zip.")
            if not re.match(r'^[a-zA-Z0-9_\-]+$', world_name):
                raise HTTPException(400, f"Nombre de mundo inválido: '{world_name}'.")

            dest = WORLDS_DIR / world_name
            if dest.exists():
                raise HTTPException(400, f"El mundo '{world_name}' ya existe. Bórralo primero.")

            # Extract
            dest.mkdir(parents=True, exist_ok=True)
            for member in zf.infolist():
                member_path = Path(member.filename.replace("\\", "/"))
                # Strip the root folder if present
                if len(root_dirs) == 1:
                    parts = member_path.parts
                    if len(parts) <= 1:
                        continue  # skip the root dir entry itself
                    rel = Path(*parts[1:])
                else:
                    rel = member_path

                # Security: prevent path traversal
                target = dest / rel
                if not str(target.resolve()).startswith(str(dest.resolve())):
                    continue
                norm_name = member.filename.replace("\\", "/")
                is_dir_entry = norm_name.endswith("/") or member.is_dir()
                if is_dir_entry:
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(zf.read(member.filename))

        extracted = list(dest.rglob("*"))
        file_count = sum(1 for f in extracted if f.is_file())
        fmt = _world_format(dest)

        # ── Binary validation ────────────────────────────────────────────────
        validation_warnings: list[str] = []
        if fmt == "v1":
            try:
                validation_warnings = _validate_world_files(dest, world_name)
            except HTTPException:
                shutil.rmtree(dest, ignore_errors=True)
                raise

        return {
            "status":   "ok",
            "world":    world_name,
            "format":   fmt,
            "files":    file_count,
            "warnings": validation_warnings,
            "message":  f"Mundo '{world_name}' importado ({file_count} ficheros, formato {fmt})."
                        + (f" ⚠️ {len(validation_warnings)} aviso(s)." if validation_warnings else ""),
        }

    except HTTPException:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise
    except zipfile.BadZipFile:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise HTTPException(400, "El fichero no es un zip válido.")
    except Exception as e:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise HTTPException(500, f"Error al procesar el zip: {e}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@app.post("/api/worlds/upload-legacy")
async def upload_world_legacy(files: list[UploadFile] = File(...)):
    """Upload a legacy world save: exactly one .db and one .fwl with the same base name.
    Used for pre-1.0 saves and backup files generated by the Valheim server.
    """
    if len(files) != 2:
        raise HTTPException(400, f"Se esperan 2 ficheros (.db y .fwl), se recibieron {len(files)}.")

    exts = sorted(Path(f.filename).suffix.lower() for f in files)
    if exts != [".db", ".fwl"]:
        raise HTTPException(400, f"Se esperan un .db y un .fwl. Recibido: {', '.join(exts)}.")

    base_names = {Path(f.filename).stem for f in files}
    if len(base_names) != 1:
        names_str = " y ".join(f'"{n}"' for n in sorted(base_names))
        raise HTTPException(400, f"Los dos ficheros deben tener el mismo nombre de mundo. Encontrado: {names_str}.")

    world_name = _sanitize_name(next(iter(base_names)))
    if not world_name or not re.match(r'^[a-zA-Z0-9_\-]+$', world_name):
        raise HTTPException(400, f"Nombre de mundo inválido: '{world_name}'.")

    dest = WORLDS_DIR / world_name
    if dest.exists():
        raise HTTPException(400, f"El mundo '{world_name}' ya existe. Bórralo primero.")

    file_contents: list[tuple[str, bytes]] = []
    for f in files:
        content = await f.read()
        if len(content) < 10:
            raise HTTPException(400, f"El fichero '{f.filename}' está vacío.")
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(400, f"El fichero '{f.filename}' supera el límite de {MAX_UPLOAD_BYTES // (1024*1024)} MB.")
        file_contents.append((f.filename, content))

    dest.mkdir(parents=True, exist_ok=True)
    saved = []
    for filename, content in file_contents:
        (dest / filename).write_bytes(content)
        saved.append(filename)

    return {"status": "ok", "world": world_name, "files": saved,
            "message": f"Mundo '{world_name}' importado (backup legacy)."}


@app.delete("/api/worlds/{world_name}")
async def delete_world(world_name: str):
    env    = read_env()
    active = env.get("WORLD_NAME", "")
    if world_name == active:
        raise HTTPException(400, f"No puedes borrar el mundo activo '{world_name}'. Activa otro primero.")
    world_path = WORLDS_DIR / world_name
    if not world_path.exists():
        raise HTTPException(404, f"Mundo '{world_name}' no encontrado.")
    deleted = [world_name]
    shutil.rmtree(world_path)
    for p in WORLDS_DIR.iterdir():
        if p.is_dir() and p.name.startswith(f"{world_name}_backup_"):
            shutil.rmtree(p)
            deleted.append(p.name)
    return {"status": "ok", "deleted": deleted}


@app.post("/api/server/restart")
async def restart_server():
    code = await docker_post(f"/containers/{GAME_CONTAINER}/restart?t=15")
    return {"status": "ok" if code in (204, 304) else "error", "http": code}


@app.post("/api/server/stop")
async def stop_server():
    code = await docker_post(f"/containers/{GAME_CONTAINER}/stop?t=15")
    return {"status": "ok" if code in (204, 304) else "error", "http": code}


@app.post("/api/server/start")
async def start_server():
    code = await docker_post(f"/containers/{GAME_CONTAINER}/start")
    return {"status": "ok" if code in (204, 304) else "error", "http": code}


@app.get("/api/logs")
def get_logs(lines: int = 80):
    log = latest_log_file()
    if not log or not log.exists():
        return {"lines": [], "file": None}
    try:
        all_lines = log.read_text(errors="replace").splitlines()
        return {"lines": all_lines[-lines:], "file": log.name}
    except Exception as e:
        return {"lines": [], "error": str(e)}


# ── Static files ──────────────────────────────────────────────────────────────
_static = Path(__file__).parent / "static"
if _static.exists():
    app.mount("/static", StaticFiles(directory=str(_static)), name="static")
