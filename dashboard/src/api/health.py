"""Health check endpoints for all services.

These endpoints are used by the dashboard UI to show service status
and by external monitoring tools.
"""

import asyncio

import httpx
from fastapi import APIRouter

router = APIRouter(prefix="/api/health", tags=["Health"])


@router.get("/all")
async def get_all_health():
    """Batch health check for all services in parallel.

    Returns status of all services in a single request, checking them
    concurrently using asyncio.gather(). This reduces total latency from
    O(n * timeout) to O(max_timeout) where n is the number of services.

    Used by the Services modal to load all statuses quickly.
    """
    # Run all health checks in parallel
    results = await asyncio.gather(
        get_backend_health(),
        get_zigbee_health(),
        get_ac_health(),
        get_vacaciones_health(),
        get_immich_health(),
        get_casita_health(),
        get_baby_gifts_health(),
        get_portfolio_health(),
        get_passwords_health(),
        get_ai_health(),
        get_valheim_health(),
        return_exceptions=True,
    )

    # Map results to service keys, handling exceptions gracefully
    keys = [
        "backend",
        "zigbee",
        "ac",
        "vacaciones",
        "immich",
        "casita",
        "baby-gifts",
        "portfolio",
        "passwords",
        "ai",
        "valheim",
    ]

    response = {}
    for key, result in zip(keys, results):
        if isinstance(result, Exception):
            response[key] = {"online": False, "error": str(type(result).__name__)}
        else:
            response[key] = result

    return response


@router.get("")
async def get_health():
    """Health check for the dashboard API."""
    return {"status": "ok", "service": "dashboard"}


@router.get("/backend")
async def get_backend_health():
    """Health check for the backend itself.

    Returns JSON (unlike nginx /health which returns plain text).
    Used by the dashboard infrastructure bar to check backend status.
    """
    return {"online": True}


@router.get("/zigbee")
async def get_zigbee_health():
    """Proxy health check to ac-service (which manages Zigbee/MQTT)."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get("http://ac-service:8002/api/ac/health/zigbee")
            return r.json()
    except Exception:
        return {"online": False, "mqtt_connected": False, "active_sensors": 0}


@router.get("/ac")
async def get_ac_health():
    """Health check for AC service."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get("http://ac-service:8002/api/health/ac")
            data = r.json()
            return {"online": data.get("online", False)}
    except Exception:
        return {"online": False}


@router.get("/vacaciones")
async def get_vacaciones_health():
    """Health check for Vacaciones service."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get("http://vacaciones-service:8003/health")
            data = r.json()
            return {"online": data.get("online", False)}
    except Exception:
        return {"online": False}


@router.get("/immich")
async def get_immich_health():
    """Health check for Immich photo server."""
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            r = await client.get("http://immich_server:2283/api/server/ping")
            return {"online": r.status_code == 200 and r.json().get("res") == "pong"}
    except Exception:
        return {"online": False}


@router.get("/casita")
async def get_casita_health():
    """Health check for Casita Sueños service."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get("http://casita-suenos:8001/health")
            data = resp.json()
            return {"online": data.get("online", False)}
    except Exception:
        return {"online": False}


@router.get("/baby-gifts")
async def get_baby_gifts_health():
    """Health check for Baby Gifts service."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get("http://baby-gifts-service:8004/health")
            data = resp.json()
            return {"online": data.get("online", False)}
    except Exception:
        return {"online": False}


@router.get("/portfolio")
async def get_portfolio_health():
    """Health check for Portfolio Monitor service."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get("http://portfolio-monitor:8010/health")
            data = resp.json()
            return {"online": data.get("online", False)}
    except Exception:
        return {"online": False}


@router.get("/passwords")
async def get_passwords_health():
    """Health check for Vaultwarden."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get("http://vaultwarden:80/passwords/")
            return {"online": resp.status_code == 200}
    except Exception:
        return {"online": False}


@router.get("/ai")
async def get_ai_health():
    """Health check for Local AI (Open WebUI on EgnalPC)."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get("http://192.168.1.164:3000/health")
            data = r.json()
            return {"online": data.get("status", False) is True}
    except Exception:
        return {"online": False}


@router.get("/valheim")
async def get_valheim_health():
    """Health check for Valheim Admin service."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get("http://valheim-admin:8080/health")
            data = r.json()
            return {"online": data.get("online", False)}
    except Exception:
        return {"online": False}


@router.get("/valheim-server")
async def get_valheim_server_health():
    """Health check for the actual Valheim game server.

    Queries valheim-admin to get the status of valheim-server container
    and whether the game has fully loaded (join code available).
    """
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get("http://valheim-admin:8080/api/status")
            if r.status_code == 200:
                data = r.json()
                running = data.get("running", False)
                join_code = data.get("join_code")
                online = running and join_code is not None
                return {
                    "online": online,
                    "running": running,
                    "join_code": join_code,
                    "players": data.get("players", 0),
                }
    except Exception:
        pass
    return {"online": False, "running": False}
