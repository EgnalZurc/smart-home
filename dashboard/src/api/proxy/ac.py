"""AC service proxy routes.

Proxies requests to the ac-service for climate control.
"""

from typing import Any

from fastapi import APIRouter, Request

from api.auth_helpers import require_app_write

from .base import ServiceProxy

router = APIRouter(prefix="/api/ac", tags=["AC"])

SERVICE_URL = "http://ac-service:8002"

_proxy = ServiceProxy(SERVICE_URL)
# Dedicated longer-timeout proxy for endpoints that hit MELCloud / history.
_proxy_slow = ServiceProxy(SERVICE_URL, timeout=10.0)


@router.get("/status")
async def get_ac_status():
    """Get current AC and sensor status."""
    return await _proxy.get("/api/ac/status")


@router.get("/sensors")
async def get_ac_sensors():
    """Get all sensor readings."""
    return await _proxy.get("/api/ac/sensors")


@router.get("/sensors/history")
async def get_ac_sensors_history(
    start: float | None = None, end: float | None = None, last: int | None = None
) -> dict[str, Any]:
    """Get sensor reading history."""
    params: dict[str, float | int] = {}
    if start is not None:
        params["start"] = start
    if end is not None:
        params["end"] = end
    if last is not None:
        params["last"] = last
    return await _proxy_slow.get(
        "/api/ac/sensors/history", params=params if params else None
    )


@router.get("/history")
async def get_ac_history(limit: int = 100) -> dict[str, Any]:
    """Get controller action history."""
    return await _proxy.get("/api/ac/history", params={"limit": limit})


@router.get("/config")
async def get_ac_config() -> dict[str, Any]:
    """Get controller configuration."""
    return await _proxy.get("/api/ac/config")


@router.post("/config")
async def update_ac_config(request: Request) -> dict[str, Any]:
    """Update controller configuration."""
    require_app_write(request, "ac")
    body = await request.json()
    return await _proxy.post("/api/ac/config", json=body)


@router.post("/control")
async def set_ac_control_mode(request: Request) -> dict[str, Any]:
    """Set control mode (auto/manual/off)."""
    require_app_write(request, "ac")
    body = await request.json()
    return await _proxy.post("/api/ac/control", json=body)


@router.post("/manual")
async def set_ac_manual_params(request: Request) -> dict[str, Any]:
    """Set manual control parameters."""
    require_app_write(request, "ac")
    body = await request.json()
    return await _proxy.post("/api/ac/manual", json=body)


@router.post("/manual/param")
async def update_ac_manual_param(
    param: str, value: str, request: Request
) -> dict[str, Any]:
    """Update a single manual parameter."""
    require_app_write(request, "ac")
    # ac-service reads these as query params; forward them in the path.
    return await _proxy.post(f"/api/ac/manual/param?param={param}&value={value}")


@router.get("/real")
async def get_ac_real() -> dict[str, Any]:
    """Get real AC state from MELCloud."""
    return await _proxy_slow.get("/api/ac/real")


@router.get("/outdoor")
async def get_ac_outdoor() -> dict[str, Any]:
    """Get outdoor temperature and air quality."""
    return await _proxy.get("/api/ac/outdoor")


@router.get("/errors")
async def get_ac_errors() -> dict[str, Any]:
    """Get active errors."""
    return await _proxy.get("/api/ac/errors")


@router.get("/energy/current")
async def get_ac_energy_current() -> dict[str, Any]:
    """Get current energy consumption."""
    return await _proxy.get("/api/ac/energy/current")


@router.get("/energy/hourly")
async def get_ac_energy_hourly() -> dict[str, Any]:
    """Get hourly energy data."""
    return await _proxy.get("/api/ac/energy/hourly")


@router.get("/energy/monthly")
async def get_ac_energy_monthly() -> dict[str, Any]:
    """Get monthly energy data."""
    return await _proxy.get("/api/ac/energy/monthly")


@router.get("/subscriptions/stats")
async def get_ac_subscriptions_stats() -> dict[str, Any]:
    """Get subscription manager stats."""
    return await _proxy.get("/api/ac/subscriptions/stats")
