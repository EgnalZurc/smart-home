"""AC service proxy routes.

Proxies requests to the ac-service for climate control.
"""

import httpx
from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/ac", tags=["AC"])

SERVICE_URL = "http://ac-service:8002"


@router.get("/status")
async def get_ac_status():
    """Get current AC and sensor status."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{SERVICE_URL}/api/ac/status")
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/sensors")
async def get_ac_sensors():
    """Get all sensor readings."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{SERVICE_URL}/api/ac/sensors")
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/sensors/history")
async def get_ac_sensors_history(
    start: float | None = None, end: float | None = None, last: int | None = None
):
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
            resp = await client.get(
                f"{SERVICE_URL}/api/ac/sensors/history", params=params
            )
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/history")
async def get_ac_history(limit: int = 100):
    """Get controller action history."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{SERVICE_URL}/api/ac/history", params={"limit": limit}
            )
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/config")
async def get_ac_config():
    """Get controller configuration."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{SERVICE_URL}/api/ac/config")
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/config")
async def update_ac_config(request: Request):
    """Update controller configuration."""
    try:
        body = await request.json()
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(f"{SERVICE_URL}/api/ac/config", json=body)
            if resp.status_code >= 400:
                raise HTTPException(
                    status_code=resp.status_code,
                    detail=resp.json().get("detail", "Error"),
                )
            return resp.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/control")
async def set_ac_control_mode(request: Request):
    """Set control mode (auto/manual/off)."""
    try:
        body = await request.json()
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(f"{SERVICE_URL}/api/ac/control", json=body)
            if resp.status_code >= 400:
                raise HTTPException(
                    status_code=resp.status_code,
                    detail=resp.json().get("detail", "Error"),
                )
            return resp.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/manual")
async def set_ac_manual_params(request: Request):
    """Set manual control parameters."""
    try:
        body = await request.json()
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(f"{SERVICE_URL}/api/ac/manual", json=body)
            if resp.status_code >= 400:
                raise HTTPException(
                    status_code=resp.status_code,
                    detail=resp.json().get("detail", "Error"),
                )
            return resp.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/manual/param")
async def update_ac_manual_param(param: str, value: str):
    """Update a single manual parameter."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{SERVICE_URL}/api/ac/manual/param",
                params={"param": param, "value": value},
            )
            if resp.status_code >= 400:
                raise HTTPException(
                    status_code=resp.status_code,
                    detail=resp.json().get("detail", "Error"),
                )
            return resp.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/real")
async def get_ac_real():
    """Get real AC state from MELCloud."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{SERVICE_URL}/api/ac/real")
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/outdoor")
async def get_ac_outdoor():
    """Get outdoor temperature and air quality."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{SERVICE_URL}/api/ac/outdoor")
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/errors")
async def get_ac_errors():
    """Get active errors."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{SERVICE_URL}/api/ac/errors")
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/energy/current")
async def get_ac_energy_current():
    """Get current energy consumption."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{SERVICE_URL}/api/ac/energy/current")
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/energy/hourly")
async def get_ac_energy_hourly():
    """Get hourly energy data."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{SERVICE_URL}/api/ac/energy/hourly")
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/energy/monthly")
async def get_ac_energy_monthly():
    """Get monthly energy data."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{SERVICE_URL}/api/ac/energy/monthly")
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/subscriptions/stats")
async def get_ac_subscriptions_stats():
    """Get subscription manager stats."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{SERVICE_URL}/api/ac/subscriptions/stats")
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))
