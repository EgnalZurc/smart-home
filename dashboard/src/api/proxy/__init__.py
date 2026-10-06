"""Proxy routers for external services.

Each module contains routes that proxy requests to a specific service.
"""

from .ac import router as ac_router
from .baby_gifts import router as baby_gifts_router
from .casita import router as casita_router
from .external import router as external_router
from .pc import router as pc_router
from .portfolio import router as portfolio_router
from .vacaciones import router as vacaciones_router

__all__ = [
    "ac_router",
    "baby_gifts_router",
    "casita_router",
    "external_router",
    "pc_router",
    "portfolio_router",
    "vacaciones_router",
]
