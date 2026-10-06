"""Vacaciones service proxy routes.

Proxies requests to the vacaciones-service for Christmas planning.
"""

import httpx
from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/vacaciones", tags=["Vacaciones"])

SERVICE_URL = "http://vacaciones-service:8003"


@router.get("")
async def get_vacaciones():
    """Returns all vacaciones data including config and momentos."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{SERVICE_URL}/api/vacaciones")
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/config")
async def get_vacaciones_config():
    """Returns vacaciones configuration (nucleos and personas)."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{SERVICE_URL}/api/vacaciones/config")
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/config")
async def post_vacaciones_config(request: Request):
    """Save vacaciones configuration."""
    try:
        body = await request.json()
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(f"{SERVICE_URL}/api/vacaciones/config", json=body)
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/year")
async def add_vacaciones_year():
    """Add a new year (next after highest existing)."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(f"{SERVICE_URL}/api/vacaciones/year")
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/year/{year}")
async def post_vacaciones_year(year: int, request: Request):
    """Save a year's planning."""
    try:
        body = await request.json()
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{SERVICE_URL}/api/vacaciones/year/{year}", json=body
            )
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.delete("/year/{year}")
async def delete_vacaciones_year(year: int):
    """Delete a year."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.delete(f"{SERVICE_URL}/api/vacaciones/year/{year}")
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
