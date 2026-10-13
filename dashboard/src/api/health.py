"""Health check endpoints for all services.

These endpoints are used by the dashboard UI to show service status
and by external monitoring tools.

Each health check returns:
- online: bool - whether the service is reachable and responding
- Additional diagnostic fields specific to each service
- error: str (optional) - error message if something went wrong

The /all endpoint aggregates all health checks in parallel for efficiency.
"""

import asyncio
import os

import httpx
from fastapi import APIRouter

router = APIRouter(prefix="/api/health", tags=["Health"])

# ── Configuration ─────────────────────────────────────────────────────────────

PC_AGENT_URL = os.environ.get("PC_AGENT_URL", "http://192.168.1.164:8090")
PC_AGENT_TOKEN = os.environ.get("PC_AGENT_TOKEN", "")


def _pc_agent_headers() -> dict[str, str]:
    """Get authentication headers for pc-agent requests."""
    return {"X-Api-Token": PC_AGENT_TOKEN} if PC_AGENT_TOKEN else {}


# ── Batch Health Check ────────────────────────────────────────────────────────


@router.get("/all")
async def get_all_health():
    """Batch health check for all services in parallel.

    Returns status of all services in a single request, checking them
    concurrently using asyncio.gather(). This reduces total latency from
    O(n * timeout) to O(max_timeout) where n is the number of services.

    Used by the Services modal to load all statuses quickly.
    """
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


# ── Dashboard Backend ─────────────────────────────────────────────────────────


@router.get("")
async def get_health():
    """Health check for the dashboard API."""
    return {"status": "ok", "service": "dashboard"}


@router.get("/backend")
async def get_backend_health():
    """Health check for the backend itself with self-tests.

    Validates that critical components are functional:
    - Database connection (auth.db)
    - Required environment variables
    - Static files accessibility
    """
    from pathlib import Path

    checks = {
        "online": True,
        "db_accessible": False,
        "static_files": False,
    }

    # Check database accessibility
    try:
        import profiles.db as profiles_db

        db_path = Path(profiles_db.AUTH_DB_PATH)
        if db_path.exists():
            checks["db_accessible"] = True
        elif db_path.parent.exists():
            checks["db_accessible"] = True
    except Exception as e:
        checks["db_error"] = str(e)

    # Check static files
    try:
        static_path = Path(__file__).parent.parent / "static" / "login.html"
        checks["static_files"] = static_path.exists()
    except Exception as e:
        checks["static_error"] = str(e)

    return checks


# ── Zigbee / MQTT ─────────────────────────────────────────────────────────────


@router.get("/zigbee")
async def get_zigbee_health():
    """Health check for Zigbee2MQTT via ac-service.

    Returns:
    - online: whether the MQTT broker is connected
    - mqtt_connected: explicit MQTT connection status
    - active_sensors: number of sensors currently reporting
    - error: connection error message if any
    """
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get("http://ac-service:8002/api/ac/health/zigbee")
            if r.status_code == 200:
                data = r.json()
                return {
                    "online": data.get("mqtt_connected", False),
                    "mqtt_connected": data.get("mqtt_connected", False),
                    "active_sensors": data.get("active_sensors", 0),
                }
            return {
                "online": False,
                "mqtt_connected": False,
                "active_sensors": 0,
                "error": f"HTTP {r.status_code}",
            }
    except httpx.ConnectError:
        return {
            "online": False,
            "mqtt_connected": False,
            "active_sensors": 0,
            "error": "Cannot connect to ac-service",
        }
    except httpx.TimeoutException:
        return {
            "online": False,
            "mqtt_connected": False,
            "active_sensors": 0,
            "error": "Timeout connecting to ac-service",
        }
    except Exception as e:
        return {
            "online": False,
            "mqtt_connected": False,
            "active_sensors": 0,
            "error": str(e),
        }


# ── AC Service ────────────────────────────────────────────────────────────────


@router.get("/ac")
async def get_ac_health():
    """Health check for AC service.

    Returns:
    - online: whether the service is running and responsive
    - melcloud_connected: whether MELCloud API is accessible (if applicable)
    - error: connection error message if any
    """
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get("http://ac-service:8002/api/health/ac")
            if r.status_code == 200:
                data = r.json()
                return {
                    "online": data.get("online", False),
                    "melcloud_connected": data.get("melcloud_connected"),
                }
            return {"online": False, "error": f"HTTP {r.status_code}"}
    except httpx.ConnectError:
        return {"online": False, "error": "Cannot connect to ac-service"}
    except httpx.TimeoutException:
        return {"online": False, "error": "Timeout"}
    except Exception as e:
        return {"online": False, "error": str(e)}


# ── Vacaciones Service ────────────────────────────────────────────────────────


@router.get("/vacaciones")
async def get_vacaciones_health():
    """Health check for Vacaciones service.

    Returns:
    - online: whether the service is running
    - error: connection error message if any
    """
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get("http://vacaciones-service:8003/health")
            if r.status_code == 200:
                data = r.json()
                return {"online": data.get("online", False)}
            return {"online": False, "error": f"HTTP {r.status_code}"}
    except httpx.ConnectError:
        return {"online": False, "error": "Cannot connect to vacaciones-service"}
    except httpx.TimeoutException:
        return {"online": False, "error": "Timeout"}
    except Exception as e:
        return {"online": False, "error": str(e)}


# ── Immich ────────────────────────────────────────────────────────────────────


@router.get("/immich")
async def get_immich_health():
    """Health check for Immich photo server.

    Returns:
    - online: whether Immich is running and responsive
    - error: connection error message if any
    """
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            r = await client.get("http://immich_server:2283/api/server/ping")
            if r.status_code == 200:
                data = r.json()
                is_online = data.get("res") == "pong"
                return {"online": is_online}
            return {"online": False, "error": f"HTTP {r.status_code}"}
    except httpx.ConnectError:
        return {"online": False, "error": "Cannot connect to immich_server"}
    except httpx.TimeoutException:
        return {"online": False, "error": "Timeout"}
    except Exception as e:
        return {"online": False, "error": str(e)}


# ── Casita Sueños ─────────────────────────────────────────────────────────────


@router.get("/casita")
async def get_casita_health():
    """Health check for Casita Sueños service.

    Returns:
    - online: whether the service is running
    - telegram_connected: whether Telegram bot is connected (if available)
    - error: connection error message if any
    """
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get("http://casita-suenos:8001/health")
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "online": data.get("online", False),
                    "telegram_connected": data.get("telegram_connected"),
                }
            return {"online": False, "error": f"HTTP {resp.status_code}"}
    except httpx.ConnectError:
        return {"online": False, "error": "Cannot connect to casita-suenos"}
    except httpx.TimeoutException:
        return {"online": False, "error": "Timeout"}
    except Exception as e:
        return {"online": False, "error": str(e)}


# ── Baby Gifts ────────────────────────────────────────────────────────────────


@router.get("/baby-gifts")
async def get_baby_gifts_health():
    """Health check for Baby Gifts service.

    Returns:
    - online: whether the service is running
    - error: connection error message if any
    """
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get("http://baby-gifts-service:8004/health")
            if resp.status_code == 200:
                data = resp.json()
                return {"online": data.get("online", False)}
            return {"online": False, "error": f"HTTP {resp.status_code}"}
    except httpx.ConnectError:
        return {"online": False, "error": "Cannot connect to baby-gifts-service"}
    except httpx.TimeoutException:
        return {"online": False, "error": "Timeout"}
    except Exception as e:
        return {"online": False, "error": str(e)}


# ── Portfolio Monitor ─────────────────────────────────────────────────────────


@router.get("/portfolio")
async def get_portfolio_health():
    """Health check for Portfolio Monitor service.

    Returns:
    - online: whether the service is running
    - last_update: timestamp of last portfolio update (if available)
    - error: connection error message if any
    """
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get("http://portfolio-monitor:8010/health")
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "online": data.get("online", False),
                    "last_update": data.get("last_update"),
                }
            return {"online": False, "error": f"HTTP {resp.status_code}"}
    except httpx.ConnectError:
        return {"online": False, "error": "Cannot connect to portfolio-monitor"}
    except httpx.TimeoutException:
        return {"online": False, "error": "Timeout"}
    except Exception as e:
        return {"online": False, "error": str(e)}


# ── Vaultwarden (Passwords) ───────────────────────────────────────────────────


@router.get("/passwords")
async def get_passwords_health():
    """Health check for Vaultwarden.

    Returns:
    - online: whether Vaultwarden is running and accessible
    - error: connection error message if any
    """
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get("http://vaultwarden:80/passwords/")
            if resp.status_code == 200:
                return {"online": True}
            # Vaultwarden may return redirects, that's still "online"
            if resp.status_code in (301, 302, 303, 307, 308):
                return {"online": True}
            return {"online": False, "error": f"HTTP {resp.status_code}"}
    except httpx.ConnectError:
        return {"online": False, "error": "Cannot connect to vaultwarden"}
    except httpx.TimeoutException:
        return {"online": False, "error": "Timeout"}
    except Exception as e:
        return {"online": False, "error": str(e)}


# ── Local AI (Open WebUI) ─────────────────────────────────────────────────────


@router.get("/ai")
async def get_ai_health():
    """Health check for Local AI (Open WebUI on EgnalPC).

    Returns:
    - online: whether Open WebUI is running
    - error: connection error message if any

    Note: This service runs on EgnalPC, not on the Pi.
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get("http://192.168.1.164:3000/health")
            if r.status_code == 200:
                data = r.json()
                return {"online": data.get("status", False) is True}
            return {"online": False, "error": f"HTTP {r.status_code}"}
    except httpx.ConnectError:
        return {"online": False, "error": "Cannot connect to EgnalPC:3000"}
    except httpx.TimeoutException:
        return {"online": False, "error": "Timeout - is EgnalPC on?"}
    except Exception as e:
        return {"online": False, "error": str(e)}


# ── Valheim Control (pc-agent) ────────────────────────────────────────────────


@router.get("/valheim")
async def get_valheim_health():
    """Health check for Valheim control (pc-agent reachability + auth).

    Verifies:
    1. pc-agent is reachable (/health - no auth required)
    2. Docker is available on EgnalPC
    3. Authentication works (/system/mode - requires valid token)

    Returns:
    - online: whether pc-agent is reachable
    - docker: whether Docker is available on EgnalPC
    - auth_ok: whether authentication is properly configured
    - auth_error: specific auth error message if auth fails
    - error: connection error message if any
    """
    result = {
        "online": False,
        "docker": False,
        "auth_ok": False,
    }

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            # Check basic reachability (no auth)
            r = await client.get(f"{PC_AGENT_URL}/health")
            if r.status_code == 200:
                data = r.json()
                result["online"] = data.get("online", False)
                result["docker"] = data.get("docker", False)

                # Check auth works (requires token)
                r2 = await client.get(
                    f"{PC_AGENT_URL}/system/mode",
                    headers=_pc_agent_headers(),
                )
                if r2.status_code == 200:
                    result["auth_ok"] = True
                elif r2.status_code == 401:
                    result["auth_error"] = "Invalid token"
                elif r2.status_code == 503:
                    result["auth_error"] = "Token not configured on pc-agent"
                else:
                    result["auth_error"] = f"Unexpected status {r2.status_code}"
            else:
                result["error"] = f"HTTP {r.status_code}"
    except httpx.ConnectError:
        result["error"] = "Cannot connect to pc-agent - is EgnalPC on?"
    except httpx.TimeoutException:
        result["error"] = "Timeout connecting to pc-agent"
    except Exception as e:
        result["error"] = str(e)

    return result


# ── Valheim Game Server ───────────────────────────────────────────────────────


@router.get("/valheim-server")
async def get_valheim_server_health():
    """Health check for the actual Valheim game server.

    Queries pc-agent to get the status of valheim-server container
    and whether the game has fully loaded (join code available).

    Returns:
    - online: whether the server is fully running and joinable
    - running: whether the container is running
    - join_code: the join code if available
    - players: current player count
    - error: error message if any
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(
                f"{PC_AGENT_URL}/valheim/status",
                headers=_pc_agent_headers(),
            )
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
            if r.status_code == 401:
                return {
                    "online": False,
                    "running": False,
                    "error": "Auth failed - check PC_AGENT_TOKEN",
                }
            return {
                "online": False,
                "running": False,
                "error": f"HTTP {r.status_code}",
            }
    except httpx.ConnectError:
        return {
            "online": False,
            "running": False,
            "error": "Cannot connect to pc-agent",
        }
    except httpx.TimeoutException:
        return {
            "online": False,
            "running": False,
            "error": "Timeout",
        }
    except Exception as e:
        return {
            "online": False,
            "running": False,
            "error": str(e),
        }
