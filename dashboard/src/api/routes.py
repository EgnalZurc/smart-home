"""REST API router aggregator.

This module combines all API routers into a single router for the main app.
Each service-specific router is in its own module for better organization.

Route modules:
- api/health.py: Health check endpoints for all services
- api/proxy/*.py: Proxy routes to external services (AC, Vacaciones, etc.)
- system/*.py: Container control and system stats
"""

from fastapi import APIRouter
from system.containers import router as containers_router
from system.stats import router as stats_router

from api.health import router as health_router
from api.proxy import external as _external_module
from api.proxy.ac import router as ac_router
from api.proxy.baby_gifts import router as baby_gifts_router
from api.proxy.casita import router as casita_router
from api.proxy.external import router as external_router
from api.proxy.pc import router as pc_router
from api.proxy.portfolio import router as portfolio_router
from api.proxy.vacaciones import router as vacaciones_router

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
router.include_router(external_router)
router.include_router(containers_router)
router.include_router(stats_router)


# Module-level FIRMS_MAP_KEY that forwards to external module
# This allows main.py to do: routes.FIRMS_MAP_KEY = "value"
class _FirmsKeyProxy:
    """Proxy class to allow setting FIRMS_MAP_KEY on this module."""

    def __get__(self, obj, objtype=None):
        return _external_module.FIRMS_MAP_KEY

    def __set__(self, obj, value):
        _external_module.FIRMS_MAP_KEY = value


# Create instance at module level
# main.py can do: routes.FIRMS_MAP_KEY = "value"
# We use a simple approach: just re-export from external and update there
FIRMS_MAP_KEY = ""  # Will be set by main.py


def set_firms_key(key: str):
    """Set the FIRMS API key. Called by main.py lifespan."""
    global FIRMS_MAP_KEY
    FIRMS_MAP_KEY = key
    _external_module.FIRMS_MAP_KEY = key


__all__ = ["router", "FIRMS_MAP_KEY", "set_firms_key"]
