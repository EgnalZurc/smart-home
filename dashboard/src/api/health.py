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
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from fastapi import APIRouter

router = APIRouter(prefix="/api/health", tags=["Health"])

# ── Configuration ─────────────────────────────────────────────────────────────

PC_AGENT_URL = os.environ.get("PC_AGENT_URL", "http://192.168.1.164:8090")
PC_AGENT_TOKEN = os.environ.get("PC_AGENT_TOKEN", "")


def _pc_agent_headers() -> dict[str, str]:
    """Get authentication headers for pc-agent requests."""
    return {"X-Api-Token": PC_AGENT_TOKEN} if PC_AGENT_TOKEN else {}


# ── Health Check Cache ────────────────────────────────────────────────────────
#
# The dashboard UI polls service status frequently (and the /all endpoint fans
# out to every service in parallel). Without caching, each poll triggers N real
# HTTP requests to the backend services, which is wasteful and can hammer slow
# services. We cache each service's result for a short TTL so repeated polls
# within the window reuse the last known result instead of issuing a new request.

HEALTH_CACHE_TTL = 5.0  # seconds

# Maps a service key -> (timestamp, data) of the last successful check.
_health_cache: dict[str, tuple[float, dict]] = {}


async def _cached_health_check(
    key: str, check_fn: Callable[[], Awaitable[dict]]
) -> dict:
    """Return a cached health result for ``key`` or run ``check_fn`` to refresh it.

    If a cached entry exists for ``key`` and is younger than ``HEALTH_CACHE_TTL``
    seconds, the cached data is returned without calling ``check_fn``. Otherwise
    ``check_fn`` is awaited, its result stored with the current timestamp, and
    returned.

    The result always includes a ``latency_ms`` field: for cache hits this is 0
    (no real request was made), for fresh checks it is the actual request time
    in milliseconds.

    Args:
        key: Unique cache key identifying the service (e.g. ``"ac"``).
        check_fn: Zero-argument coroutine function that performs the real check
            and returns the health dict.

    Returns:
        The health dict, either from cache or freshly computed, with latency_ms.
    """
    now = time.monotonic()
    cached = _health_cache.get(key)
    if cached is not None:
        timestamp, data = cached
        if now - timestamp < HEALTH_CACHE_TTL:
            # Return cached data with latency=0 to indicate cache hit
            return {**data, "latency_ms": 0, "cached": True}

    start = time.monotonic()
    data = await check_fn()
    latency_ms = int((time.monotonic() - start) * 1000)
    _health_cache[key] = (time.monotonic(), data)
    return {**data, "latency_ms": latency_ms}


# ── Batch Health Check ────────────────────────────────────────────────────────


@router.get("/all")
async def get_all_health() -> dict[str, Any]:
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
        get_valheim_health(),
        get_metrics_health(),
        get_energy_health(),
        get_presence_health(),
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
        "valheim",
        "metrics",
        "energy",
        "presence",
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
async def get_health() -> dict[str, Any]:
    """Health check for the dashboard API."""
    return {"status": "ok", "service": "dashboard"}


@router.get("/backend")
async def get_backend_health() -> dict[str, Any]:
    """Health check for the backend itself with self-tests.

    Validates that critical components are functional:
    - Database connection (auth.db)
    - Required environment variables
    - Static files accessibility
    """

    async def _check() -> dict:
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
            if db_path.exists() or db_path.parent.exists():
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

    return await _cached_health_check("backend", _check)


# ── Zigbee / MQTT ─────────────────────────────────────────────────────────────


@router.get("/zigbee")
async def get_zigbee_health() -> dict[str, Any]:
    """Health check for Zigbee2MQTT via ac-service.

    Returns:
    - online: whether the MQTT broker is connected
    - mqtt_connected: explicit MQTT connection status
    - active_sensors: number of sensors currently reporting
    - error: connection error message if any
    """

    async def _check() -> dict:
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

    return await _cached_health_check("zigbee", _check)


# ── AC Service ────────────────────────────────────────────────────────────────


@router.get("/ac")
async def get_ac_health() -> dict[str, Any]:
    """Health check for AC service.

    Returns:
    - online: whether the service is running and responsive
    - melcloud_connected: whether MELCloud API is accessible (if applicable)
    - error: connection error message if any
    """

    async def _check() -> dict:
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

    return await _cached_health_check("ac", _check)


# ── Vacaciones Service ────────────────────────────────────────────────────────


@router.get("/vacaciones")
async def get_vacaciones_health() -> dict[str, Any]:
    """Health check for Vacaciones service.

    Returns:
    - online: whether the service is running
    - error: connection error message if any
    """

    async def _check() -> dict:
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

    return await _cached_health_check("vacaciones", _check)


# ── Immich ────────────────────────────────────────────────────────────────────


@router.get("/immich")
async def get_immich_health() -> dict[str, Any]:
    """Health check for Immich photo server.

    Returns:
    - online: whether Immich is running and responsive
    - error: connection error message if any
    """

    async def _check() -> dict:
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

    return await _cached_health_check("immich", _check)


# ── Casita Sueños ─────────────────────────────────────────────────────────────


@router.get("/casita")
async def get_casita_health() -> dict[str, Any]:
    """Health check for Casita Sueños service.

    Returns:
    - online: whether the service is running
    - telegram_connected: whether Telegram bot is connected (if available)
    - error: connection error message if any
    """

    async def _check() -> dict:
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

    return await _cached_health_check("casita", _check)


# ── Baby Gifts ────────────────────────────────────────────────────────────────


@router.get("/baby-gifts")
async def get_baby_gifts_health() -> dict[str, Any]:
    """Health check for Baby Gifts service.

    Returns:
    - online: whether the service is running
    - error: connection error message if any
    """

    async def _check() -> dict:
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

    return await _cached_health_check("baby-gifts", _check)


# ── Portfolio Monitor ─────────────────────────────────────────────────────────


@router.get("/portfolio")
async def get_portfolio_health() -> dict[str, Any]:
    """Health check for Portfolio Monitor service.

    Returns:
    - online: whether the service is running
    - last_update: timestamp of last portfolio update (if available)
    - error: connection error message if any
    """

    async def _check() -> dict:
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

    return await _cached_health_check("portfolio", _check)


# ── Vaultwarden (Passwords) ───────────────────────────────────────────────────


@router.get("/passwords")
async def get_passwords_health() -> dict[str, Any]:
    """Health check for Vaultwarden.

    Returns:
    - online: whether Vaultwarden is running and accessible
    - error: connection error message if any
    """

    async def _check() -> dict:
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

    return await _cached_health_check("passwords", _check)


# ── Valheim Control (pc-agent) ────────────────────────────────────────────────


@router.get("/valheim")
async def get_valheim_health() -> dict[str, Any]:
    """Health check for valheim-admin service.

    Checks if the valheim-admin container (running on Pi) is healthy.
    valheim-admin provides the web UI for managing the Valheim server
    that runs on EgnalPC via pc-agent.

    Returns:
    - online: whether valheim-admin is running and responsive
    - error: connection error message if any
    """

    async def _check() -> dict:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                r = await client.get("http://valheim-admin:8080/health")
                if r.status_code == 200:
                    data = r.json()
                    return {"online": data.get("online", False)}
                return {"online": False, "error": f"HTTP {r.status_code}"}
        except httpx.ConnectError:
            return {"online": False, "error": "Cannot connect to valheim-admin"}
        except httpx.TimeoutException:
            return {"online": False, "error": "Timeout"}
        except Exception as e:
            return {"online": False, "error": str(e)}

    return await _cached_health_check("valheim", _check)


# ── Metrics Service (infrastructure) ──────────────────────────────────────────


@router.get("/metrics")
async def get_metrics_health() -> dict[str, Any]:
    """Health check for the metrics-service (infrastructure collector).

    Exercises the service's own DB-aware /health, which reports:
    - online: whether metrics-service is running
    - db_ok: whether its SQLite store answers a query
    - collector_last_tick_age_s: seconds since the last collection tick

    Public (like all /api/health/*) so the dashboard status view and CI verify
    step can reach it without a session; the data endpoints under /api/metrics/*
    remain SUPER-gated via the proxy router.
    """

    async def _check() -> dict:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                r = await client.get("http://metrics-service:8011/health")
                if r.status_code == 200:
                    data = r.json()
                    return {
                        "online": data.get("online", False),
                        "db_ok": data.get("db_ok"),
                        "collector_last_tick_age_s": data.get(
                            "collector_last_tick_age_s"
                        ),
                    }
                return {"online": False, "error": f"HTTP {r.status_code}"}
        except httpx.ConnectError:
            return {"online": False, "error": "Cannot connect to metrics-service"}
        except httpx.TimeoutException:
            return {"online": False, "error": "Timeout"}
        except Exception as e:
            return {"online": False, "error": str(e)}

    return await _cached_health_check("metrics", _check)


# ── Energy Monitor (infrastructure) ───────────────────────────────────────────


@router.get("/energy")
async def get_energy_health() -> dict[str, Any]:
    """Health check for the energy-monitor (infrastructure collector).

    Exercises the service's own DB-aware /health, which reports:
    - online: whether energy-monitor is running
    - db_ok: whether its SQLite store answers a query
    - meter_online: whether the last Shelly device poll succeeded (None until
      the collector task lands)
    - collector_last_tick_age_s: seconds since the last collection tick

    Public (like all /api/health/*) so the dashboard status view and CI verify
    step can reach it without a session; the data endpoints under /api/energy/*
    remain SUPER-gated via the proxy router.
    """

    async def _check() -> dict:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                r = await client.get("http://energy-monitor:8012/health")
                if r.status_code == 200:
                    data = r.json()
                    return {
                        "online": data.get("online", False),
                        "db_ok": data.get("db_ok"),
                        "meter_online": data.get("meter_online"),
                        "collector_last_tick_age_s": data.get(
                            "collector_last_tick_age_s"
                        ),
                    }
                return {"online": False, "error": f"HTTP {r.status_code}"}
        except httpx.ConnectError:
            return {"online": False, "error": "Cannot connect to energy-monitor"}
        except httpx.TimeoutException:
            return {"online": False, "error": "Timeout"}
        except Exception as e:
            return {"online": False, "error": str(e)}

    return await _cached_health_check("energy", _check)


# ── Presence Service (infrastructure) ─────────────────────────────────────────


@router.get("/presence")
async def get_presence_health() -> dict[str, Any]:
    """Health check for the presence-service (multi-signal presence detection).

    Exercises the service's own DB-aware /health, which reports:
    - online: whether presence-service is running
    - db_ok: whether its SQLite store answers a query
    - router_online: whether the router poll succeeded (None until the collector
      task lands)
    - mqtt_online: whether the broker connection is up (None until the MQTT
      handler lands)
    - last_tick_age_s: seconds since the last engine tick

    Public (like all /api/health/*) so the dashboard status view and CI verify
    step can reach it without a session; the data endpoints under /api/presence/*
    remain SUPER-gated via the proxy router.
    """

    async def _check() -> dict:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                r = await client.get("http://presence-service:8013/health")
                if r.status_code == 200:
                    data = r.json()
                    return {
                        "online": data.get("online", False),
                        "db_ok": data.get("db_ok"),
                        "router_online": data.get("router_online"),
                        "mqtt_online": data.get("mqtt_online"),
                        "last_tick_age_s": data.get("last_tick_age_s"),
                    }
                return {"online": False, "error": f"HTTP {r.status_code}"}
        except httpx.ConnectError:
            return {"online": False, "error": "Cannot connect to presence-service"}
        except httpx.TimeoutException:
            return {"online": False, "error": "Timeout"}
        except Exception as e:
            return {"online": False, "error": str(e)}

    return await _cached_health_check("presence", _check)
