"""REST API router aggregator.

This module combines all API routers into a single router for the main app.
Each service-specific router is in its own module for better organization.

Route modules:
- api/health.py: Health check endpoints for all services
- api/proxy/*.py: Proxy routes to external services (AC, Vacaciones, etc.)
- system/*.py: Container control and system stats
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from system.containers import router as containers_router
from system.stats import router as stats_router

from api.alerts import router as alerts_router
from api.deploy import router as deploy_router
from api.health import router as health_router
from api.metrics import router as metrics_router
from api.monitoring import router as monitoring_router
from api.proxy import external as _external_module
from api.proxy.ac import router as ac_router
from api.proxy.baby_gifts import router as baby_gifts_router
from api.proxy.casita import router as casita_router
from api.proxy.external import router as external_router
from api.proxy.pc import router as pc_router
from api.proxy.portfolio import router as portfolio_router
from api.proxy.vacaciones import router as vacaciones_router
from api.proxy.valheim import router as valheim_router
from api.ws import router as ws_router

# Main router that aggregates all sub-routers
router = APIRouter()

# Include all sub-routers
router.include_router(health_router)
router.include_router(casita_router)
router.include_router(ac_router)
router.include_router(vacaciones_router)
router.include_router(baby_gifts_router)
router.include_router(portfolio_router)
router.include_router(pc_router)
router.include_router(valheim_router)
router.include_router(external_router)
router.include_router(containers_router)
router.include_router(stats_router)
router.include_router(monitoring_router)
router.include_router(metrics_router)
router.include_router(ws_router)
router.include_router(deploy_router)
router.include_router(alerts_router)


# Legacy redirect: valheim-admin was removed, control is now via /api/valheim/*
@router.get("/valheim-admin", include_in_schema=False)
@router.get("/valheim-admin/", include_in_schema=False)
@router.get("/valheim-admin/{path:path}", include_in_schema=False)
async def valheim_admin_redirect():
    """Return info about the removed valheim-admin service."""
    return JSONResponse(
        status_code=410,
        content={
            "message": "valheim-admin service has been removed",
            "info": "Valheim control is now integrated into the dashboard via /api/valheim/*",
            "endpoints": {
                "status": "/api/valheim/status",
                "start": "POST /api/valheim/server/start",
                "stop": "POST /api/valheim/server/stop",
                "config": "/api/valheim/config",
                "worlds": "/api/valheim/worlds",
            },
        },
    )


# Module-level FIRMS_MAP_KEY, re-exported from the external module.
# main.py sets it via set_firms_key() during the lifespan startup.
FIRMS_MAP_KEY = ""  # Will be set by main.py


def set_firms_key(key: str):
    """Set the FIRMS API key. Called by main.py lifespan."""
    global FIRMS_MAP_KEY
    FIRMS_MAP_KEY = key
    _external_module.FIRMS_MAP_KEY = key


__all__ = ["router", "FIRMS_MAP_KEY", "set_firms_key"]
