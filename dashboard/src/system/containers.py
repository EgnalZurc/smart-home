"""Container control endpoints.

Only SUPER profile can call these endpoints.
Uses docker-socket-proxy:2375 (CONTAINERS=1, POST=1 — read + start/stop).
"""

import asyncio

import httpx
from api.auth_helpers import require_super
from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/system", tags=["Containers"])

# Mapping: app key → list of container names to stop/start together.
CONTROLLABLE_CONTAINERS: dict[str, list[str]] = {
    "ac": ["ac-service"],
    "vacaciones": ["vacaciones-service"],
    "casita": ["casita-suenos"],
    "photos": ["immich_postgres", "immich_redis", "immich_server"],
    "passwords": ["vaultwarden"],
    "valheim": ["valheim-admin"],
    "babygifts": ["baby-gifts-service"],
    "portfolio": ["portfolio-monitor"],
}

DOCKER_PROXY = "http://docker-socket-proxy:2375/v1.41"

# Seconds to wait before starting each container after the previous one.
CONTAINER_START_DELAYS: dict[str, int] = {
    "photos": 5,  # wait 5s between redis and immich_server (postgres cold-start)
}


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
    require_super(request)
    result = {}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{DOCKER_PROXY}/containers/json?all=true")
            all_containers = r.json()
            state_by_name: dict[str, str] = {}
            for c in all_containers:
                for name in c.get("Names", []):
                    clean = name.lstrip("/")
                    state_by_name[clean] = c.get("State", "unknown")
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Docker proxy unreachable: {e}")

    for key, container_names in CONTROLLABLE_CONTAINERS.items():
        states = [state_by_name.get(n, "unknown") for n in container_names]
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
    require_super(request)
    containers = CONTROLLABLE_CONTAINERS.get(app_key)
    if not containers:
        raise HTTPException(status_code=404, detail=f"Unknown service: {app_key}")

    results = {}
    async with httpx.AsyncClient(timeout=20.0) as client:
        for name in containers:
            try:
                r = await client.post(f"{DOCKER_PROXY}/containers/{name}/stop?t=10")
                results[name] = (
                    "ok" if r.status_code in (204, 304) else f"http_{r.status_code}"
                )
            except Exception as e:
                results[name] = f"error: {e}"

    all_ok = all(v == "ok" or v == "http_304" for v in results.values())
    return {"status": "ok" if all_ok else "partial", "results": results}


@router.post("/containers/{app_key}/start")
async def start_service(app_key: str, request: Request):
    """Start all containers for the given service app key.

    Only accessible to SUPER profile.
    """
    require_super(request)
    containers = CONTROLLABLE_CONTAINERS.get(app_key)
    if not containers:
        raise HTTPException(status_code=404, detail=f"Unknown service: {app_key}")

    results = {}
    delay = CONTAINER_START_DELAYS.get(app_key, 0)
    async with httpx.AsyncClient(timeout=20.0) as client:
        for i, name in enumerate(containers):
            if i > 0 and delay > 0:
                await asyncio.sleep(delay)
            try:
                r = await client.post(f"{DOCKER_PROXY}/containers/{name}/start")
                results[name] = (
                    "ok" if r.status_code in (204, 304) else f"http_{r.status_code}"
                )
            except Exception as e:
                results[name] = f"error: {e}"

    all_ok = all(v == "ok" or v == "http_304" for v in results.values())
    return {"status": "ok" if all_ok else "partial", "results": results}
