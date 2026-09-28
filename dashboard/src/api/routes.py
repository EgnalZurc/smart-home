"""REST API endpoints for the backend dashboard.

This module contains only:
  - Health check proxies for all external services
  - Casita Sueños proxy routes
  - Proxy routes for external APIs (flood, firms)
  - Container and system management

AC endpoints (/api/ac/*) → proxied by nginx to ac-service:8002
Vacaciones endpoints (/api/vacaciones/*) → proxied by nginx to vacaciones-service:8003
"""

import httpx
from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api")

# Injected by main.py lifespan
FIRMS_MAP_KEY: str = ""


# ── Health checks ────────────────────────────────────────────────────────────


@router.get("/health", tags=["Health"])
async def get_health():
    """Health check for the dashboard API."""
    return {"status": "ok", "service": "dashboard"}


@router.get("/health/backend", tags=["Health"])
async def get_backend_health():
    """Health check for the backend itself.
    Returns JSON (unlike nginx /health which returns plain text).
    Used by the dashboard infrastructure bar to check backend status.
    """
    return {"online": True}


@router.get("/health/zigbee", tags=["Health"])
async def get_zigbee_health():
    """Proxy health check to ac-service (which manages Zigbee/MQTT)."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get("http://ac-service:8002/api/ac/health/zigbee")
            return r.json()
    except Exception:
        return {"online": False, "mqtt_connected": False, "active_sensors": 0}


@router.get("/health/ac", tags=["Health"])
async def get_ac_health():
    """Health check for AC service."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get("http://ac-service:8002/api/health/ac")
            data = r.json()
            return {"online": data.get("online", False)}
    except Exception:
        return {"online": False}


@router.get("/health/vacaciones", tags=["Health"])
async def get_vacaciones_health():
    """Health check for Vacaciones service."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get("http://vacaciones-service:8003/health")
            data = r.json()
            return {"online": data.get("online", False)}
    except Exception:
        return {"online": False}


@router.get("/health/immich", tags=["Health"])
async def get_immich_health():
    """Health check for Immich photo server."""
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            r = await client.get("http://immich_server:2283/api/server/ping")
            return {"online": r.status_code == 200 and r.json().get("res") == "pong"}
    except Exception:
        return {"online": False}


@router.get("/health/casita", tags=["Health"])
async def get_casita_health():
    """Health check for Casita Sueños service."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get("http://casita-suenos:8001/health")
            data = resp.json()
            return {"online": data.get("online", False)}
    except Exception:
        return {"online": False}


@router.get("/health/passwords", tags=["Health"])
async def get_passwords_health():
    """Health check for Vaultwarden."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get("http://vaultwarden:80/")
            return {"online": resp.status_code == 200}
    except Exception:
        return {"online": False}


@router.get("/health/valheim", tags=["Health"])
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
                return {
                    "online": online,
                    "join_code": join_code,
                    "players": data.get("players", 0),
                }
    except Exception:
        pass

    # Container running but game not yet loaded (starting up)
    return {"online": False}


@router.get("/health/valheim-admin", tags=["Health"])
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


@router.get("/casita/status", tags=["Casita"])
async def get_casita_status():
    """Get full status of Casita Sueños property monitor."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get("http://casita-suenos:8001/status")
            return resp.json()
    except Exception as e:
        return {
            "online": False,
            "error": str(e),
            "total_properties": 0,
            "scraper_errors": [],
            "top_properties": [],
        }


@router.get("/casita/radar", tags=["Casita"])
async def get_casita_radar(request: Request):
    """Get properties above alert threshold (radar view)."""
    qs = str(request.url.query)
    url = "http://casita-suenos:8001/radar"
    if qs:
        url = f"{url}?{qs}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            return resp.json()
    except Exception as e:
        return {
            "items": [],
            "total": 0,
            "offset": 0,
            "limit": 20,
            "has_more": False,
            "error": str(e),
        }


@router.get("/casita/dismissed", tags=["Casita"])
async def get_casita_dismissed():
    """Get list of dismissed properties."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get("http://casita-suenos:8001/dismissed")
            return resp.json()
    except Exception as e:
        return {"properties": [], "error": str(e)}


@router.get("/casita/schedule", tags=["Casita"])
async def get_casita_schedule():
    """Get scraping schedule configuration."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get("http://casita-suenos:8001/schedule")
            return resp.json()
    except Exception as e:
        return {"error": str(e)}


@router.post("/casita/schedule", tags=["Casita"])
async def save_casita_schedule(request: Request):
    """Update scraping schedule configuration."""
    try:
        body = await request.json()
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post("http://casita-suenos:8001/schedule", json=body)
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/casita/dismiss", tags=["Casita"])
async def dismiss_casita_property(request: Request):
    """Dismiss a property from radar."""
    try:
        body = await request.json()
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post("http://casita-suenos:8001/dismiss", json=body)
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/casita/undismiss", tags=["Casita"])
async def undismiss_casita_property(request: Request):
    """Restore a dismissed property to radar."""
    try:
        body = await request.json()
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post("http://casita-suenos:8001/undismiss", json=body)
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/casita/mark-viewed", tags=["Casita"])
async def mark_casita_viewed(request: Request):
    """Mark a property as viewed."""
    try:
        body = await request.json()
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post("http://casita-suenos:8001/mark-viewed", json=body)
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/casita/save-comment", tags=["Casita"])
async def save_casita_comment(request: Request):
    """Save a comment on a property."""
    try:
        body = await request.json()
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "http://casita-suenos:8001/save-comment", json=body
            )
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/casita/summary", tags=["Casita"])
async def get_casita_summary():
    """Get AI-generated summary of interesting properties."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get("http://casita-suenos:8001/summary")
            return resp.json()
    except Exception as e:
        return {"content": None, "sent_at": None, "error": str(e)}


@router.post("/casita/run-scraping", tags=["Casita"])
async def run_casita_scraping():
    """Trigger manual property scraping."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post("http://casita-suenos:8001/run-scraping")
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/casita/run-summary", tags=["Casita"])
async def run_casita_summary():
    """Trigger AI summary generation."""
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
    "ac": ["ac-service"],
    "vacaciones": ["vacaciones-service"],
    "casita": ["casita-suenos"],
    "photos": ["immich_postgres", "immich_redis", "immich_server"],
    "passwords": ["vaultwarden"],
    "valheim": ["valheim-server"],
    "babygifts": ["baby-gifts-service"],
}

DOCKER_PROXY = "http://docker-socket-proxy:2375/v1.41"
# Seconds to wait before starting each container after the previous one.
# Needed for services where later containers depend on earlier ones being healthy.
CONTAINER_START_DELAYS: dict[str, int] = {
    "photos": 5,  # wait 5s between redis and immich_server (postgres cold-start)
}


def _require_super(request: Request) -> str:
    """Return username if caller is SUPER, raise 403 otherwise."""
    import auth as auth_core
    import user_profiles

    user = auth_core.get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    profile_key = user_profiles.get_profile_key(user)
    profile = user_profiles.PROFILES.get(profile_key, {})
    if not profile.get("show_config_apps", False):
        raise HTTPException(status_code=403, detail="SUPER profile required")
    return user


@router.get("/system/containers", tags=["Containers"])
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


@router.post("/system/containers/{app_key}/stop", tags=["Containers"])
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
                results[name] = (
                    "ok" if r.status_code in (204, 304) else f"http_{r.status_code}"
                )
            except Exception as e:
                results[name] = f"error: {e}"

    all_ok = all(v == "ok" or v == "http_304" for v in results.values())
    return {"status": "ok" if all_ok else "partial", "results": results}


@router.post("/system/containers/{app_key}/start", tags=["Containers"])
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
                results[name] = (
                    "ok" if r.status_code in (204, 304) else f"http_{r.status_code}"
                )
            except Exception as e:
                results[name] = f"error: {e}"

    all_ok = all(v == "ok" or v == "http_304" for v in results.values())
    return {"status": "ok" if all_ok else "partial", "results": results}


# ── System resource stats (SUPER only) ───────────────────────────────────────

import os as _os


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


@router.get("/system/stats", tags=["System"])
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
        total_kb = mem.get("MemTotal", 0)
        avail_kb = mem.get("MemAvailable", 0)
        free_kb = mem.get("MemFree", 0)
        buffers_kb = mem.get("Buffers", 0)
        cached_kb = (
            mem.get("Cached", 0) + mem.get("SReclaimable", 0) - mem.get("Shmem", 0)
        )
        used_kb = total_kb - free_kb - buffers_kb - max(0, cached_kb)
        stats["ram"] = {
            "total_mb": round(total_kb / 1024),
            "used_mb": round(used_kb / 1024),
            "available_mb": round(avail_kb / 1024),
            "cache_mb": round((buffers_kb + max(0, cached_kb)) / 1024),
            "percent": round(used_kb / total_kb * 100, 1) if total_kb else 0.0,
        }
        swap_total = mem.get("SwapTotal", 0)
        swap_free = mem.get("SwapFree", 0)
        swap_used = swap_total - swap_free
        stats["swap"] = {
            "total_mb": round(swap_total / 1024),
            "used_mb": round(swap_used / 1024),
            "percent": round(swap_used / swap_total * 100, 1) if swap_total else 0.0,
        }
    except Exception as e:
        stats["ram"] = {"error": str(e)}
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
        free_b = sv.f_frsize * sv.f_bavail
        used_b = total_b - free_b
        GB = 1024**3
        stats["disk"] = {
            "total_gb": round(total_b / GB, 1),
            "used_gb": round(used_b / GB, 1),
            "free_gb": round(free_b / GB, 1),
            "percent": round(used_b / total_b * 100, 1) if total_b else 0.0,
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


PI_MODES = {
    "gaming": {
        "stop": [
            "immich_postgres",
            "immich_redis",
            "immich_server",
            "casita-suenos",
            "vacaciones-service",
        ],
        "start": ["valheim-server"],
    },
    "photos": {
        "stop": ["valheim-server"],
        "start": [
            "immich_postgres",
            "immich_redis",
            "immich_server",
            "casita-suenos",
            "vacaciones-service",
        ],
    },
    "minimal": {
        "stop": [
            "valheim-server",
            "immich_postgres",
            "immich_redis",
            "immich_server",
            "casita-suenos",
            "vacaciones-service",
        ],
        "start": [],
    },
}


@router.get("/system/mode", tags=["System"])
async def get_system_mode(request: Request):
    """Return current Pi mode based on which heavy services are running.

    Returns: {"mode": "gaming"|"photos"|"minimal", "ram_available_mb": int}
    """
    _require_super(request)

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{DOCKER_PROXY}/containers/json?all=true")
            all_containers = r.json()
            running = {
                c["Names"][0].lstrip("/")
                for c in all_containers
                if c.get("State") == "running"
            }
            # Include restarting so mode stays "photos" while immich_server is starting up
            active = {
                c["Names"][0].lstrip("/")
                for c in all_containers
                if c.get("State") in ("running", "restarting")
            }
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Docker proxy unreachable: {e}")

    # Determine mode
    valheim_up = "valheim-server" in running
    immich_up = "immich_server" in active  # use active: includes restarting state

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


@router.post("/system/mode/{mode}", tags=["System"])
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
        raise HTTPException(
            status_code=400,
            detail=f"Invalid mode: {mode}. Valid: gaming, photos, minimal",
        )

    config = PI_MODES[mode]
    results = {"stopped": {}, "started": {}}

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Stop containers first
        for name in config["stop"]:
            try:
                r = await client.post(f"{DOCKER_PROXY}/containers/{name}/stop?t=10")
                results["stopped"][name] = (
                    "ok" if r.status_code in (204, 304) else f"http_{r.status_code}"
                )
            except Exception as e:
                results["stopped"][name] = f"error: {e}"

        # Small delay to let RAM free up
        await __import__("asyncio").sleep(2)

        # Start containers — apply same inter-container delays as start_service()
        mode_delay = CONTAINER_START_DELAYS.get(mode, 0)
        for i, name in enumerate(config["start"]):
            if i > 0 and mode_delay > 0:
                await __import__("asyncio").sleep(mode_delay)
            try:
                r = await client.post(f"{DOCKER_PROXY}/containers/{name}/start")
                results["started"][name] = (
                    "ok" if r.status_code in (204, 304) else f"http_{r.status_code}"
                )
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


# ── External API Proxies ─────────────────────────────────────────────────────


@router.get("/proxy/flood", tags=["Proxy"])
async def proxy_flood(lat: float, lon: float):
    """
    Riesgo de inundación multicapa para una coordenada.

    Fuente 1: SNCZI MITECO (oficial España) — peligrosidad fluvial T=10/100/500 años.
    Fuente 2: GloFAS via Open-Meteo Flood API — caudal diario del río más cercano.

    Respuesta:
      {
        snczi: { t10, t100, t500 } | null,
        glofas: { mean_m3s, max_hist_m3s, p95_m3s, p99_m3s } | null,
        risk_level: "muy_alto"|"alto"|"moderado"|"bajo"|"sin_datos",
        risk_source: "snczi"|"glofas"|"sin_datos",
        calado_m: float | null,
      }
    """
    import asyncio
    import re
    import statistics
    from datetime import date

    WMS_BASE = "https://servicios.idee.es/wms-inspire/riesgos-naturales/inundaciones"
    LAYERS = ["NZ.Flood.FluvialT10", "NZ.Flood.FluvialT100", "NZ.Flood.FluvialT500"]
    DELTAS = [0.0005, 0.001, 0.002, 0.005, 0.01, 0.02]
    FILL_VALS = {-9999.0, -3.0}

    def _is_fill(v: float) -> bool:
        if v is None:
            return True
        if v in FILL_VALS or v < -2:
            return True
        return abs(v - 3.4) < 0.1

    async def _wms_query(layer: str, delta: float) -> float | None:
        bbox = f"{lon - delta:.5f},{lat - delta:.5f},{lon + delta:.5f},{lat + delta:.5f}"
        url = (
            f"{WMS_BASE}?SERVICE=WMS&VERSION=1.1.1&REQUEST=GetFeatureInfo"
            f"&BBOX={bbox}&WIDTH=10&HEIGHT=10"
            f"&LAYERS={layer}&QUERY_LAYERS={layer}"
            f"&INFO_FORMAT=text/plain&X=5&Y=5&SRS=EPSG:4326"
        )
        try:
            async with httpx.AsyncClient(timeout=8) as c:
                r = await c.get(url)
            m = re.search(r"GRAY_INDEX\s*=\s*([-\d.]+)", r.text)
            return float(m.group(1)) if m else None
        except Exception:
            return None

    async def _snczi_with_progressive_bbox() -> dict | None:
        for delta in DELTAS:
            results = await asyncio.gather(*[_wms_query(l, delta) for l in LAYERS])
            t10_raw, t100_raw, t500_raw = results
            t10 = None if _is_fill(t10_raw) else round(t10_raw, 2)
            t100 = None if _is_fill(t100_raw) else round(t100_raw, 2)
            t500 = None if _is_fill(t500_raw) else round(t500_raw, 2)
            if t10 is not None and t100 is not None and t500 is not None and t10 == t100 == t500:
                t10 = t100 = t500 = None
            if any(v is not None for v in (t10, t100, t500)):
                return {"t10": t10, "t100": t100, "t500": t500, "bbox_delta_deg": delta, "bbox_radius_m": int(delta * 111000)}
        return None

    async def _glofas() -> dict | None:
        end_date = date.today().isoformat()
        start_date = f"{date.today().year - 30}-01-01"
        url = f"https://flood-api.open-meteo.com/v1/flood?latitude={lat}&longitude={lon}&daily=river_discharge&start_date={start_date}&end_date={end_date}&cell_selection=nearest"
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get(url)
            d = r.json()
            if not d.get("daily"):
                return None
            vals = [v for v in d["daily"]["river_discharge"] if v is not None]
            if len(vals) < 30:
                return None
            vals_sorted = sorted(vals)
            n = len(vals_sorted)
            return {
                "mean_m3s": round(statistics.mean(vals), 1),
                "max_hist_m3s": round(max(vals), 1),
                "p95_m3s": round(vals_sorted[int(n * 0.95)], 1),
                "p99_m3s": round(vals_sorted[int(n * 0.99)], 1),
                "lat_grid": d.get("latitude"),
                "lon_grid": d.get("longitude"),
                "years": 30,
            }
        except Exception:
            return None

    snczi_data, glofas_data = await asyncio.gather(_snczi_with_progressive_bbox(), _glofas())

    risk_level = "sin_datos"
    risk_source = "sin_datos"
    calado_m = None

    if snczi_data:
        t10, t100, t500 = snczi_data["t10"], snczi_data["t100"], snczi_data["t500"]
        if t10 is not None and t10 >= 0:
            risk_level, calado_m = "muy_alto", t10
        elif t100 is not None and t100 >= 0:
            risk_level, calado_m = "alto", t100
        elif t500 is not None and t500 >= 0:
            risk_level, calado_m = "moderado", t500
        else:
            risk_level = "bajo"
        risk_source = "snczi"
    elif glofas_data:
        p99, mx = glofas_data["p99_m3s"], glofas_data["max_hist_m3s"]
        if mx > 1500 or p99 > 500:
            risk_level = "muy_alto"
        elif mx > 500 or p99 > 150:
            risk_level = "alto"
        elif mx > 50 or p99 > 15:
            risk_level = "moderado"
        else:
            risk_level = "bajo"
        risk_source = "glofas"

    return {"snczi": snczi_data, "glofas": glofas_data, "risk_level": risk_level, "risk_source": risk_source, "calado_m": calado_m}


@router.get("/proxy/firms", tags=["Proxy"])
async def proxy_firms(lat: float, lon: float):
    """
    Proxy para NASA FIRMS — focos de calor VIIRS SNPP últimos 3 años.
    Consulta meses de riesgo alto (junio-octubre) en bloques de 5 días.
    """
    import asyncio
    from datetime import date

    if not FIRMS_MAP_KEY:
        return {"status": "no_key", "focos": None}

    delta = 0.27
    bbox = f"{lon - delta:.4f},{lat - delta:.4f},{lon + delta:.4f},{lat + delta:.4f}"
    base = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
    source = "VIIRS_SNPP_SP"

    today = date.today()
    windows: list[str] = []

    for years_back in range(1, 4):
        year = today.year - years_back
        for month in (6, 7, 8, 9, 10):
            for day_start in range(1, 29, 5):
                try:
                    d = date(year, month, day_start)
                    if d < date(2012, 1, 19) or d >= today:
                        continue
                    windows.append(d.strftime("%Y-%m-%d"))
                except ValueError:
                    pass

    if not windows:
        return {"status": "error", "focos": None, "error": "Sin ventanas disponibles"}

    async def _fetch_window(start_date: str) -> int:
        url = f"{base}/{FIRMS_MAP_KEY}/{source}/{bbox}/5/{start_date}"
        try:
            async with httpx.AsyncClient(timeout=12) as client:
                r = await client.get(url)
            if r.status_code != 200:
                return 0
            raw_lines = r.text.strip().split("\n")
            if not raw_lines or len(raw_lines) < 2:
                return 0
            header = raw_lines[0].split(",")
            try:
                ci = header.index("confidence")
            except ValueError:
                ci = None
            count = 0
            for line in raw_lines[1:]:
                if not line.strip():
                    continue
                if ci is not None:
                    parts = line.split(",")
                    if len(parts) > ci and parts[ci].strip().lower() == "l":
                        continue
                count += 1
            return count
        except Exception:
            return 0

    results = await asyncio.gather(*[_fetch_window(w) for w in windows])
    total_focos = sum(results)

    return {"status": "ok", "focos": total_focos, "radio_km": 30, "periodo": "jun-oct ultimos 3 anos", "peticiones": len(windows)}


# ══════════════════════════════════════════════════════════════════════════════
# AC Service Proxy Routes
# All AC endpoints are proxied to ac-service:8002
# ══════════════════════════════════════════════════════════════════════════════

AC_SERVICE_URL = "http://ac-service:8002"


@router.get("/ac/status", tags=["AC"])
async def get_ac_status():
    """Get current AC and sensor status."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{AC_SERVICE_URL}/api/ac/status")
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/ac/sensors", tags=["AC"])
async def get_ac_sensors():
    """Get all sensor readings."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{AC_SERVICE_URL}/api/ac/sensors")
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/ac/sensors/history", tags=["AC"])
async def get_ac_sensors_history(start: float | None = None, end: float | None = None, last: int | None = None):
    """Get sensor reading history."""
    try:
        params = {}
        if start is not None:
            params["start"] = start
        if end is not None:
            params["end"] = end
        if last is not None:
            params["last"] = last
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{AC_SERVICE_URL}/api/ac/sensors/history", params=params)
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/ac/history", tags=["AC"])
async def get_ac_history(limit: int = 100):
    """Get controller action history."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{AC_SERVICE_URL}/api/ac/history", params={"limit": limit})
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/ac/config", tags=["AC"])
async def get_ac_config():
    """Get controller configuration."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{AC_SERVICE_URL}/api/ac/config")
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/ac/config", tags=["AC"])
async def update_ac_config(request: Request):
    """Update controller configuration."""
    try:
        body = await request.json()
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(f"{AC_SERVICE_URL}/api/ac/config", json=body)
            if resp.status_code >= 400:
                raise HTTPException(status_code=resp.status_code, detail=resp.json().get("detail", "Error"))
            return resp.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/ac/control", tags=["AC"])
async def set_ac_control_mode(request: Request):
    """Set control mode (auto/manual/off)."""
    try:
        body = await request.json()
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(f"{AC_SERVICE_URL}/api/ac/control", json=body)
            if resp.status_code >= 400:
                raise HTTPException(status_code=resp.status_code, detail=resp.json().get("detail", "Error"))
            return resp.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/ac/manual", tags=["AC"])
async def set_ac_manual_params(request: Request):
    """Set manual control parameters."""
    try:
        body = await request.json()
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(f"{AC_SERVICE_URL}/api/ac/manual", json=body)
            if resp.status_code >= 400:
                raise HTTPException(status_code=resp.status_code, detail=resp.json().get("detail", "Error"))
            return resp.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/ac/manual/param", tags=["AC"])
async def update_ac_manual_param(param: str, value: str):
    """Update a single manual parameter."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(f"{AC_SERVICE_URL}/api/ac/manual/param", params={"param": param, "value": value})
            if resp.status_code >= 400:
                raise HTTPException(status_code=resp.status_code, detail=resp.json().get("detail", "Error"))
            return resp.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/ac/real", tags=["AC"])
async def get_ac_real():
    """Get real AC state from MELCloud."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{AC_SERVICE_URL}/api/ac/real")
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/ac/outdoor", tags=["AC"])
async def get_ac_outdoor():
    """Get outdoor temperature and air quality."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{AC_SERVICE_URL}/api/ac/outdoor")
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/ac/errors", tags=["AC"])
async def get_ac_errors():
    """Get active errors."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{AC_SERVICE_URL}/api/ac/errors")
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/ac/humidity/study", tags=["AC"])
async def get_ac_humidity_study():
    """Get humidity analysis summary."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{AC_SERVICE_URL}/api/ac/humidity/study")
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/ac/humidity/study/run", tags=["AC"])
async def trigger_ac_humidity_analysis():
    """Trigger manual humidity analysis."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(f"{AC_SERVICE_URL}/api/ac/humidity/study/run")
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/ac/energy/current", tags=["AC"])
async def get_ac_energy_current():
    """Get current energy consumption."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{AC_SERVICE_URL}/api/ac/energy/current")
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/ac/energy/hourly", tags=["AC"])
async def get_ac_energy_hourly():
    """Get hourly energy data."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{AC_SERVICE_URL}/api/ac/energy/hourly")
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/ac/energy/monthly", tags=["AC"])
async def get_ac_energy_monthly():
    """Get monthly energy data."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{AC_SERVICE_URL}/api/ac/energy/monthly")
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/ac/subscriptions/stats", tags=["AC"])
async def get_ac_subscriptions_stats():
    """Get subscription manager stats."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{AC_SERVICE_URL}/api/ac/subscriptions/stats")
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


# ══════════════════════════════════════════════════════════════════════════════
# Vacaciones Service Proxy Routes
# All Vacaciones endpoints are proxied to vacaciones-service:8003
# ══════════════════════════════════════════════════════════════════════════════

VACACIONES_SERVICE_URL = "http://vacaciones-service:8003"


@router.get("/vacaciones", tags=["Vacaciones"])
async def get_vacaciones():
    """Returns all vacaciones data including config and momentos."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{VACACIONES_SERVICE_URL}/api/vacaciones")
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/vacaciones/config", tags=["Vacaciones"])
async def get_vacaciones_config():
    """Returns vacaciones configuration (nucleos and personas)."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{VACACIONES_SERVICE_URL}/api/vacaciones/config")
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/vacaciones/config", tags=["Vacaciones"])
async def post_vacaciones_config(request: Request):
    """Save vacaciones configuration."""
    try:
        body = await request.json()
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(f"{VACACIONES_SERVICE_URL}/api/vacaciones/config", json=body)
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/vacaciones/year", tags=["Vacaciones"])
async def add_vacaciones_year():
    """Add a new year (next after highest existing)."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(f"{VACACIONES_SERVICE_URL}/api/vacaciones/year")
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/vacaciones/year/{year}", tags=["Vacaciones"])
async def post_vacaciones_year(year: int, request: Request):
    """Save a year's planning."""
    try:
        body = await request.json()
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(f"{VACACIONES_SERVICE_URL}/api/vacaciones/year/{year}", json=body)
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.delete("/vacaciones/year/{year}", tags=["Vacaciones"])
async def delete_vacaciones_year(year: int):
    """Delete a year."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.delete(f"{VACACIONES_SERVICE_URL}/api/vacaciones/year/{year}")
            if resp.status_code >= 400:
                raise HTTPException(status_code=resp.status_code, detail=resp.json().get("detail", "Error"))
            return resp.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


# ══════════════════════════════════════════════════════════════════════════════
# Baby Gifts Service Proxy Routes
# All Baby Gifts endpoints are proxied to baby-gifts-service:8004
# ══════════════════════════════════════════════════════════════════════════════

BABY_GIFTS_SERVICE_URL = "http://baby-gifts-service:8004"


# ── Admin endpoints ──────────────────────────────────────────────────────────


@router.get("/baby-gifts", tags=["Baby Gifts"])
async def get_all_baby_gifts():
    """Get all gifts with full reservation details (admin only)."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{BABY_GIFTS_SERVICE_URL}/api/baby-gifts")
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/baby-gifts", tags=["Baby Gifts"])
async def create_baby_gift(request: Request):
    """Add a new gift (admin only)."""
    try:
        body = await request.json()
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(f"{BABY_GIFTS_SERVICE_URL}/api/baby-gifts", json=body)
            if resp.status_code >= 400:
                raise HTTPException(status_code=resp.status_code, detail=resp.json().get("detail", "Error"))
            return resp.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.put("/baby-gifts/{gift_id}", tags=["Baby Gifts"])
async def update_baby_gift(gift_id: str, request: Request):
    """Update a gift (admin only)."""
    try:
        body = await request.json()
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.put(f"{BABY_GIFTS_SERVICE_URL}/api/baby-gifts/{gift_id}", json=body)
            if resp.status_code >= 400:
                raise HTTPException(status_code=resp.status_code, detail=resp.json().get("detail", "Error"))
            return resp.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.delete("/baby-gifts/{gift_id}", tags=["Baby Gifts"])
async def delete_baby_gift(gift_id: str):
    """Delete a gift (admin only)."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.delete(f"{BABY_GIFTS_SERVICE_URL}/api/baby-gifts/{gift_id}")
            if resp.status_code >= 400:
                raise HTTPException(status_code=resp.status_code, detail=resp.json().get("detail", "Error"))
            return resp.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/baby-gifts/{gift_id}/unreserve", tags=["Baby Gifts"])
async def admin_unreserve_baby_gift(gift_id: str):
    """Admin can unreserve any gift."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(f"{BABY_GIFTS_SERVICE_URL}/api/baby-gifts/{gift_id}/unreserve")
            if resp.status_code >= 400:
                raise HTTPException(status_code=resp.status_code, detail=resp.json().get("detail", "Error"))
            return resp.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.put("/baby-gifts/categories", tags=["Baby Gifts"])
async def update_baby_gifts_categories(request: Request):
    """Update gift categories (admin only)."""
    try:
        body = await request.json()
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.put(f"{BABY_GIFTS_SERVICE_URL}/api/baby-gifts/categories", json=body)
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


# ── Invitation management ────────────────────────────────────────────────────


@router.get("/baby-gifts/invitations", tags=["Baby Gifts"])
async def get_baby_gifts_invitations():
    """List all invitations (admin only)."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{BABY_GIFTS_SERVICE_URL}/api/baby-gifts/invitations")
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/baby-gifts/invitations", tags=["Baby Gifts"])
async def create_baby_gifts_invitation(request: Request):
    """Create a new invitation (admin only)."""
    try:
        body = await request.json()
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(f"{BABY_GIFTS_SERVICE_URL}/api/baby-gifts/invitations", json=body)
            if resp.status_code >= 400:
                raise HTTPException(status_code=resp.status_code, detail=resp.json().get("detail", "Error"))
            return resp.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.delete("/baby-gifts/invitations/{token}", tags=["Baby Gifts"])
async def delete_baby_gifts_invitation(token: str):
    """Delete an invitation (admin only)."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.delete(f"{BABY_GIFTS_SERVICE_URL}/api/baby-gifts/invitations/{token}")
            if resp.status_code >= 400:
                raise HTTPException(status_code=resp.status_code, detail=resp.json().get("detail", "Error"))
            return resp.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/baby-gifts/invitations/{token}/revoke", tags=["Baby Gifts"])
async def revoke_baby_gifts_invitation(token: str):
    """Revoke an invitation without deleting it (admin only)."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(f"{BABY_GIFTS_SERVICE_URL}/api/baby-gifts/invitations/{token}/revoke")
            if resp.status_code >= 400:
                raise HTTPException(status_code=resp.status_code, detail=resp.json().get("detail", "Error"))
            return resp.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


# ── Authenticated user endpoints ─────────────────────────────────────────────


@router.get("/baby-gifts/user", tags=["Baby Gifts"])
async def get_baby_gifts_for_user(request: Request):
    """Get gifts for an authenticated user."""
    try:
        # Forward auth header
        headers = {}
        if "X-Auth-User" in request.headers:
            headers["X-Auth-User"] = request.headers["X-Auth-User"]
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{BABY_GIFTS_SERVICE_URL}/api/baby-gifts/user", headers=headers)
            if resp.status_code >= 400:
                raise HTTPException(status_code=resp.status_code, detail=resp.json().get("detail", "Error"))
            return resp.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/baby-gifts/user/reserve/{gift_id}", tags=["Baby Gifts"])
async def user_reserve_baby_gift(gift_id: str, request: Request):
    """Reserve a gift as an authenticated user."""
    try:
        headers = {}
        if "X-Auth-User" in request.headers:
            headers["X-Auth-User"] = request.headers["X-Auth-User"]
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(f"{BABY_GIFTS_SERVICE_URL}/api/baby-gifts/user/reserve/{gift_id}", headers=headers)
            if resp.status_code >= 400:
                raise HTTPException(status_code=resp.status_code, detail=resp.json().get("detail", "Error"))
            return resp.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/baby-gifts/user/unreserve/{gift_id}", tags=["Baby Gifts"])
async def user_unreserve_baby_gift(gift_id: str, request: Request):
    """Cancel own reservation as an authenticated user."""
    try:
        headers = {}
        if "X-Auth-User" in request.headers:
            headers["X-Auth-User"] = request.headers["X-Auth-User"]
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(f"{BABY_GIFTS_SERVICE_URL}/api/baby-gifts/user/unreserve/{gift_id}", headers=headers)
            if resp.status_code >= 400:
                raise HTTPException(status_code=resp.status_code, detail=resp.json().get("detail", "Error"))
            return resp.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


# ── Guest endpoints (public, token-based) ────────────────────────────────────


@router.get("/baby-gifts/guest/{token}", tags=["Baby Gifts"])
async def get_baby_gifts_for_guest(token: str, request: Request):
    """Get gifts for a guest."""
    try:
        # Forward client IP for rate limiting
        headers = {}
        if "X-Forwarded-For" in request.headers:
            headers["X-Forwarded-For"] = request.headers["X-Forwarded-For"]
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{BABY_GIFTS_SERVICE_URL}/api/baby-gifts/guest/{token}", headers=headers)
            if resp.status_code >= 400:
                raise HTTPException(status_code=resp.status_code, detail=resp.json().get("detail", "Error"))
            return resp.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/baby-gifts/guest/{token}/reserve/{gift_id}", tags=["Baby Gifts"])
async def guest_reserve_baby_gift(token: str, gift_id: str, request: Request):
    """Reserve a gift as a guest."""
    try:
        headers = {}
        if "X-Forwarded-For" in request.headers:
            headers["X-Forwarded-For"] = request.headers["X-Forwarded-For"]
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(f"{BABY_GIFTS_SERVICE_URL}/api/baby-gifts/guest/{token}/reserve/{gift_id}", headers=headers)
            if resp.status_code >= 400:
                raise HTTPException(status_code=resp.status_code, detail=resp.json().get("detail", "Error"))
            return resp.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/baby-gifts/guest/{token}/unreserve/{gift_id}", tags=["Baby Gifts"])
async def guest_unreserve_baby_gift(token: str, gift_id: str, request: Request):
    """Cancel own reservation as a guest."""
    try:
        headers = {}
        if "X-Forwarded-For" in request.headers:
            headers["X-Forwarded-For"] = request.headers["X-Forwarded-For"]
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(f"{BABY_GIFTS_SERVICE_URL}/api/baby-gifts/guest/{token}/unreserve/{gift_id}", headers=headers)
            if resp.status_code >= 400:
                raise HTTPException(status_code=resp.status_code, detail=resp.json().get("detail", "Error"))
            return resp.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))
