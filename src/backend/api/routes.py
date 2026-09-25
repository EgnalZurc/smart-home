"""REST API endpoints for the backend dashboard.

This module contains only:
  - Health check proxies for all external services
  - Casita Sueños proxy routes
  - Proxy routes for external APIs (flood, firms - kept here for auth)

AC endpoints (/api/status, /api/sensors, etc.) → proxied by nginx to ac-service:8002
Vacaciones endpoints (/api/vacaciones/*) → proxied by nginx to vacaciones-service:8003
"""
import httpx
from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api")


# ── Health checks ────────────────────────────────────────────────────────────


@router.get("/health/backend")
async def get_backend_health():
    """Health check for the backend itself.
    Returns JSON (unlike nginx /health which returns plain text).
    Used by the dashboard infrastructure bar to check backend status.
    """
    return {"online": True}


@router.get("/health/zigbee")
async def get_zigbee_health():
    """Proxy health check to ac-service (which manages Zigbee/MQTT)."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get("http://ac-service:8002/api/health/zigbee")
            return r.json()
    except Exception:
        return {"online": False, "mqtt_connected": False, "active_sensors": 0}


@router.get("/health/ac")
async def get_ac_health():
    """Health check for AC service."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get("http://ac-service:8002/health")
            data = r.json()
            return {"online": data.get("online", False)}
    except Exception:
        return {"online": False}


@router.get("/health/vacaciones")
async def get_vacaciones_health():
    """Health check for Vacaciones service."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get("http://vacaciones-service:8003/health")
            data = r.json()
            return {"online": data.get("online", False)}
    except Exception:
        return {"online": False}


@router.get("/health/immich")
async def get_immich_health():
    """Health check for Immich photo server."""
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            r = await client.get("http://immich-server:2283/api/server/ping")
            return {"online": r.status_code == 200 and r.json().get("res") == "pong"}
    except Exception:
        return {"online": False}


@router.get("/health/casita")
async def get_casita_health():
    """Health check for Casita Sueños service."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get("http://casita-suenos:8001/health")
            data = resp.json()
            return {"online": data.get("online", False)}
    except Exception:
        return {"online": False}


@router.get("/health/passwords")
async def get_passwords_health():
    """Health check for Vaultwarden."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get("http://vaultwarden:80/")
            return {"online": resp.status_code == 200}
    except Exception:
        return {"online": False}



@router.get("/health/valheim")
async def get_valheim_health():
    """Health check for Valheim dedicated server.

    Two-level check to avoid false positives:
    1. Container must be in 'running' state (via docker-socket-proxy)
    2. valheim-admin /api/status must confirm running=true

    This prevents showing "online" during the 3-5 min startup window
    when the container is running but the game has not loaded yet,
    and avoids false positives when the container restarts after an OOM.
    """
    # Level 1: container state
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(
                "http://docker-socket-proxy:2375/v1.41/containers/valheim-server/json"
            )
            if r.status_code != 200:
                return {"online": False}
            state = r.json().get("State", {})
            if state.get("Status") != "running":
                return {"online": False}
    except Exception:
        return {"online": False}

    # Level 2: confirm via valheim-admin that the game itself has loaded
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get("http://valheim-admin:8080/api/status")
            if r.status_code == 200:
                data = r.json()
                # running=True means valheim-admin also confirmed the container is up
                # join_code present means the game fully initialized and registered with PlayFab
                running = data.get("running", False)
                join_code = data.get("join_code")
                online = running and join_code is not None
                return {"online": online, "join_code": join_code, "players": data.get("players", 0)}
    except Exception:
        pass

    # Container running but game not yet loaded (starting up)
    return {"online": False}



@router.get("/health/valheim-admin")
async def get_valheim_admin_health():
    """Health check for Valheim Admin web app."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get("http://valheim-admin:8080/health")
            data = r.json()
            return {"online": data.get("online", False)}
    except Exception:
        return {"online": False}


# ── Casita Sueños proxy routes ───────────────────────────────────────────────

@router.get("/casita/status")
async def get_casita_status():
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get("http://casita-suenos:8001/status")
            return resp.json()
    except Exception as e:
        return {"online": False, "error": str(e), "total_properties": 0,
                "scraper_errors": [], "top_properties": []}


@router.get("/casita/radar")
async def get_casita_radar(request: Request):
    qs = str(request.url.query)
    url = "http://casita-suenos:8001/radar"
    if qs:
        url = f"{url}?{qs}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            return resp.json()
    except Exception as e:
        return {"items": [], "total": 0, "offset": 0, "limit": 20, "has_more": False, "error": str(e)}


@router.get("/casita/dismissed")
async def get_casita_dismissed():
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get("http://casita-suenos:8001/dismissed")
            return resp.json()
    except Exception as e:
        return {"properties": [], "error": str(e)}


@router.get("/casita/schedule")
async def get_casita_schedule():
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get("http://casita-suenos:8001/schedule")
            return resp.json()
    except Exception as e:
        return {"error": str(e)}


@router.post("/casita/schedule")
async def save_casita_schedule(request: Request):
    try:
        body = await request.json()
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post("http://casita-suenos:8001/schedule", json=body)
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/casita/dismiss")
async def dismiss_casita_property(request: Request):
    try:
        body = await request.json()
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post("http://casita-suenos:8001/dismiss", json=body)
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/casita/undismiss")
async def undismiss_casita_property(request: Request):
    try:
        body = await request.json()
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post("http://casita-suenos:8001/undismiss", json=body)
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/casita/mark-viewed")
async def mark_casita_viewed(request: Request):
    try:
        body = await request.json()
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post("http://casita-suenos:8001/mark-viewed", json=body)
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/casita/save-comment")
async def save_casita_comment(request: Request):
    try:
        body = await request.json()
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post("http://casita-suenos:8001/save-comment", json=body)
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/casita/summary")
async def get_casita_summary():
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get("http://casita-suenos:8001/summary")
            return resp.json()
    except Exception as e:
        return {"content": None, "sent_at": None, "error": str(e)}


@router.post("/casita/run-scraping")
async def run_casita_scraping():
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post("http://casita-suenos:8001/run-scraping")
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/casita/run-summary")
async def run_casita_summary():
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post("http://casita-suenos:8001/run-summary")
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


"""Container control endpoints — appended to routes.py.

Only SUPER profile can call these endpoints.
Uses docker-socket-proxy:2375 (CONTAINERS=1, POST=1 — read + start/stop).

Endpoints:
  GET  /api/containers          → state of all controllable services
  POST /api/containers/{name}/stop  → stop a container by name
  POST /api/containers/{name}/start → start a container by name

Auth: verified via /auth/me profile check on every call.
      Returns 403 if caller is not SUPER.
"""

# ── Container control (SUPER only) ───────────────────────────────────────────

# Mapping: app key → list of container names to stop/start together.
# Immich requires stopping all 3 (server + db + redis) as a group.
CONTROLLABLE_CONTAINERS: dict[str, list[str]] = {
    "ac":         ["ac-service"],
    "vacaciones": ["vacaciones-service"],
    "casita":     ["casita-suenos"],
    "photos":     ["immich_postgres", "immich_redis", "immich_server"],
    "passwords":  ["vaultwarden"],
    "valheim":    ["valheim-server"],
}

DOCKER_PROXY = "http://docker-socket-proxy:2375/v1.41"
# Seconds to wait before starting each container after the previous one.
# Needed for services where later containers depend on earlier ones being healthy.
CONTAINER_START_DELAYS: dict[str, int] = {
    "photos": 5,  # wait 5s between redis and immich_server (postgres cold-start)
}


def _require_super(request: Request) -> str:
    """Return username if caller is SUPER, raise 403 otherwise."""
    import user_profiles
    import auth as auth_core
    user = auth_core.get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    profile_key = user_profiles.get_profile_key(user)
    profile = user_profiles.PROFILES.get(profile_key, {})
    if not profile.get("show_config_apps", False):
        raise HTTPException(status_code=403, detail="SUPER profile required")
    return user





@router.get("/containers")
async def get_containers(request: Request):
    """Return running state for all controllable services.

    Response example:
    {
      "ac":        {"containers": ["ac-service"],        "running": true},
      "photos":    {"containers": ["immich_server", ...], "running": true},
      ...
    }
    Only accessible to SUPER profile.
    """
    _require_super(request)
    result = {}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{DOCKER_PROXY}/containers/json?all=true")
            all_containers = r.json()
            # Build name→state index
            state_by_name: dict[str, str] = {}
            for c in all_containers:
                for name in c.get("Names", []):
                    clean = name.lstrip("/")
                    state_by_name[clean] = c.get("State", "unknown")
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Docker proxy unreachable: {e}")

    for key, container_names in CONTROLLABLE_CONTAINERS.items():
        states = [state_by_name.get(n, "unknown") for n in container_names]
        # "running" = ALL containers in the group are running
        running = all(s == "running" for s in states)
        result[key] = {
            "containers": container_names,
            "running": running,
            "states": {n: state_by_name.get(n, "unknown") for n in container_names},
        }
    return result


@router.post("/containers/{app_key}/stop")
async def stop_service(app_key: str, request: Request):
    """Stop all containers for the given service app key.

    Stops containers with a 10-second graceful timeout.
    Only accessible to SUPER profile.
    """
    _require_super(request)
    containers = CONTROLLABLE_CONTAINERS.get(app_key)
    if not containers:
        raise HTTPException(status_code=404, detail=f"Unknown service: {app_key}")

    results = {}
    async with httpx.AsyncClient(timeout=20.0) as client:
        for name in containers:
            try:
                r = await client.post(f"{DOCKER_PROXY}/containers/{name}/stop?t=10")
                # 204 = stopped, 304 = already stopped — both are OK
                results[name] = "ok" if r.status_code in (204, 304) else f"http_{r.status_code}"
            except Exception as e:
                results[name] = f"error: {e}"

    all_ok = all(v == "ok" or v == "http_304" for v in results.values())
    return {"status": "ok" if all_ok else "partial", "results": results}


@router.post("/containers/{app_key}/start")
async def start_service(app_key: str, request: Request):
    """Start all containers for the given service app key.

    Only accessible to SUPER profile.
    """
    _require_super(request)
    containers = CONTROLLABLE_CONTAINERS.get(app_key)
    if not containers:
        raise HTTPException(status_code=404, detail=f"Unknown service: {app_key}")

    results = {}
    delay = CONTAINER_START_DELAYS.get(app_key, 0)
    async with httpx.AsyncClient(timeout=20.0) as client:
        for i, name in enumerate(containers):
            if i > 0 and delay > 0:
                await __import__("asyncio").sleep(delay)
            try:
                r = await client.post(f"{DOCKER_PROXY}/containers/{name}/start")
                # 204 = started, 304 = already running — both are OK
                results[name] = "ok" if r.status_code in (204, 304) else f"http_{r.status_code}"
            except Exception as e:
                results[name] = f"error: {e}"

    all_ok = all(v == "ok" or v == "http_304" for v in results.values())
    return {"status": "ok" if all_ok else "partial", "results": results}


# ── System resource stats (SUPER only) ───────────────────────────────────────

import os as _os
import time as _time


def _read_cpu_times() -> tuple[float, float]:
    """Read total and idle CPU jiffies from /proc/stat."""
    try:
        line = open("/proc/stat").readline()  # first line: cpu aggregate
        fields = [float(x) for x in line.split()[1:]]
        idle = fields[3] + (fields[4] if len(fields) > 4 else 0)  # idle + iowait
        total = sum(fields)
        return total, idle
    except Exception:
        return 0.0, 0.0


@router.get("/system/stats")
async def get_system_stats(request: Request):
    """Return Raspberry Pi system resource usage.

    Reads from /proc/meminfo, /proc/stat, statvfs('/'), and the SoC thermal zone.
    All paths are available inside the Docker container because Linux exposes
    /proc (host memory/CPU) and /sys/class/thermal to all containers by default.

    Only accessible to SUPER profile.

    Response:
    {
      "ram":  {"total_mb": int, "used_mb": int, "available_mb": int, "percent": float},
      "swap": {"total_mb": int, "used_mb": int, "percent": float},
      "cpu":  {"percent": float},          # 1-second sample
      "disk": {"total_gb": float, "used_gb": float, "free_gb": float, "percent": float},
      "temp": {"celsius": float},          # SoC temperature
    }
    """
    _require_super(request)

    stats: dict = {}

    # ── RAM ──────────────────────────────────────────────────────────────────
    try:
        mem: dict[str, int] = {}
        for line in open("/proc/meminfo"):
            parts = line.split()
            if len(parts) >= 2:
                mem[parts[0].rstrip(":")] = int(parts[1])  # kB
        total_kb  = mem.get("MemTotal", 0)
        avail_kb  = mem.get("MemAvailable", 0)
        free_kb   = mem.get("MemFree", 0)
        buffers_kb = mem.get("Buffers", 0)
        cached_kb  = mem.get("Cached", 0) + mem.get("SReclaimable", 0) - mem.get("Shmem", 0)
        used_kb   = total_kb - free_kb - buffers_kb - max(0, cached_kb)
        stats["ram"] = {
            "total_mb":     round(total_kb / 1024),
            "used_mb":      round(used_kb  / 1024),
            "available_mb": round(avail_kb / 1024),
            "cache_mb":     round((buffers_kb + max(0, cached_kb)) / 1024),
            "percent":      round(used_kb / total_kb * 100, 1) if total_kb else 0.0,
        }
        swap_total = mem.get("SwapTotal", 0)
        swap_free  = mem.get("SwapFree",  0)
        swap_used  = swap_total - swap_free
        stats["swap"] = {
            "total_mb": round(swap_total / 1024),
            "used_mb":  round(swap_used  / 1024),
            "percent":  round(swap_used / swap_total * 100, 1) if swap_total else 0.0,
        }
    except Exception as e:
        stats["ram"]  = {"error": str(e)}
        stats["swap"] = {"error": str(e)}

    # ── CPU (1-second sample) ────────────────────────────────────────────────
    try:
        t1, i1 = _read_cpu_times()
        await __import__("asyncio").sleep(0.5)
        t2, i2 = _read_cpu_times()
        dt = t2 - t1
        di = i2 - i1
        cpu_pct = round((1.0 - di / dt) * 100, 1) if dt > 0 else 0.0
        stats["cpu"] = {"percent": cpu_pct}
    except Exception as e:
        stats["cpu"] = {"error": str(e)}

    # ── Disk ─────────────────────────────────────────────────────────────────
    try:
        sv = _os.statvfs("/")
        total_b = sv.f_frsize * sv.f_blocks
        free_b  = sv.f_frsize * sv.f_bavail
        used_b  = total_b - free_b
        GB = 1024 ** 3
        stats["disk"] = {
            "total_gb": round(total_b / GB, 1),
            "used_gb":  round(used_b  / GB, 1),
            "free_gb":  round(free_b  / GB, 1),
            "percent":  round(used_b / total_b * 100, 1) if total_b else 0.0,
        }
    except Exception as e:
        stats["disk"] = {"error": str(e)}

    # ── Temperature ──────────────────────────────────────────────────────────
    try:
        raw = int(open("/sys/class/thermal/thermal_zone0/temp").read().strip())
        stats["temp"] = {"celsius": round(raw / 1000, 1)}
    except Exception as e:
        stats["temp"] = {"error": str(e)}

    return stats


# ── Pi Mode management (SUPER only) ──────────────────────────────────────────
# Controls mutually exclusive service groups to optimize RAM usage.
# Modes: gaming (Valheim), photos (Immich), minimal (core services only)

import subprocess as _subprocess

PI_MODES = {
    "gaming": {
        "stop":  ["immich_postgres", "immich_redis", "immich_server", "casita-suenos", "vacaciones-service"],
        "start": ["valheim-server"],
    },
    "photos": {
        "stop":  ["valheim-server"],
        "start": ["immich_postgres", "immich_redis", "immich_server", "casita-suenos", "vacaciones-service"],
    },
    "minimal": {
        "stop":  ["valheim-server", "immich_postgres", "immich_redis", "immich_server", "casita-suenos", "vacaciones-service"],
        "start": [],
    },
}


@router.get("/system/mode")
async def get_system_mode(request: Request):
    """Return current Pi mode based on which heavy services are running.

    Returns: {"mode": "gaming"|"photos"|"minimal", "ram_available_mb": int}
    """
    _require_super(request)

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{DOCKER_PROXY}/containers/json?all=true")
            all_containers = r.json()
            running = {c["Names"][0].lstrip("/") for c in all_containers if c.get("State") == "running"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Docker proxy unreachable: {e}")

    # Determine mode
    valheim_up = "valheim-server" in running
    immich_up = "immich_server" in running

    if valheim_up and not immich_up:
        mode = "gaming"
    elif immich_up and not valheim_up:
        mode = "photos"
    else:
        mode = "minimal"

    # Get available RAM
    try:
        for line in open("/proc/meminfo"):
            if line.startswith("MemAvailable:"):
                avail_kb = int(line.split()[1])
                break
        else:
            avail_kb = 0
    except Exception:
        avail_kb = 0

    return {
        "mode": mode,
        "ram_available_mb": round(avail_kb / 1024),
        "valheim_running": valheim_up,
        "immich_running": immich_up,
    }


@router.post("/system/mode/{mode}")
async def set_system_mode(mode: str, request: Request):
    """Switch Pi to specified mode by stopping/starting container groups.

    Modes:
      - gaming:  Stop Immich/casita/vacaciones, start Valheim
      - photos:  Stop Valheim, start Immich/casita/vacaciones
      - minimal: Stop all heavy services (only core remains)

    Only accessible to SUPER profile.
    """
    _require_super(request)

    if mode not in PI_MODES:
        raise HTTPException(status_code=400, detail=f"Invalid mode: {mode}. Valid: gaming, photos, minimal")

    config = PI_MODES[mode]
    results = {"stopped": {}, "started": {}}

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Stop containers first
        for name in config["stop"]:
            try:
                r = await client.post(f"{DOCKER_PROXY}/containers/{name}/stop?t=10")
                results["stopped"][name] = "ok" if r.status_code in (204, 304) else f"http_{r.status_code}"
            except Exception as e:
                results["stopped"][name] = f"error: {e}"

        # Small delay to let RAM free up
        await __import__("asyncio").sleep(2)

        # Start containers
        for name in config["start"]:
            try:
                r = await client.post(f"{DOCKER_PROXY}/containers/{name}/start")
                results["started"][name] = "ok" if r.status_code in (204, 304) else f"http_{r.status_code}"
            except Exception as e:
                results["started"][name] = f"error: {e}"

    # Get final RAM state
    try:
        for line in open("/proc/meminfo"):
            if line.startswith("MemAvailable:"):
                avail_kb = int(line.split()[1])
                break
        else:
            avail_kb = 0
    except Exception:
        avail_kb = 0

    return {
        "status": "ok",
        "mode": mode,
        "ram_available_mb": round(avail_kb / 1024),
        "results": results,
    }
