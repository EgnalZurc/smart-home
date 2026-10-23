"""Vacaciones service proxy routes.

Proxies requests to the vacaciones-service for Christmas planning.
"""

from typing import Any

from fastapi import APIRouter, Request

from api.auth_helpers import require_app_write

from .base import ServiceProxy

router = APIRouter(prefix="/api/vacaciones", tags=["Vacaciones"])

_proxy = ServiceProxy("http://vacaciones-service:8003")


@router.get("")
async def get_vacaciones() -> dict[str, Any]:
    """Returns all vacaciones data including config and momentos."""
    return await _proxy.get("/api/vacaciones")


@router.get("/config")
async def get_vacaciones_config() -> dict[str, Any]:
    """Returns vacaciones configuration (nucleos and personas)."""
    return await _proxy.get("/api/vacaciones/config")


@router.post("/config")
async def post_vacaciones_config(request: Request) -> dict[str, Any]:
    """Save vacaciones configuration."""
    require_app_write(request, "vacaciones")
    body = await request.json()
    return await _proxy.post("/api/vacaciones/config", json=body)


@router.post("/year")
async def add_vacaciones_year(request: Request) -> dict[str, Any]:
    """Add a new year (next after highest existing)."""
    require_app_write(request, "vacaciones")
    return await _proxy.post("/api/vacaciones/year")


@router.post("/year/{year}")
async def post_vacaciones_year(year: int, request: Request) -> dict[str, Any]:
    """Save a year's planning."""
    require_app_write(request, "vacaciones")
    body = await request.json()
    return await _proxy.post(f"/api/vacaciones/year/{year}", json=body)


@router.delete("/year/{year}")
async def delete_vacaciones_year(year: int, request: Request) -> dict[str, Any]:
    """Delete a year."""
    require_app_write(request, "vacaciones")
    return await _proxy.delete(f"/api/vacaciones/year/{year}")
