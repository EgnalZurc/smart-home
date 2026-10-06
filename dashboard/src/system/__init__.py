"""System management modules.

Container control and system statistics.
"""

from .containers import router as containers_router
from .stats import router as stats_router

__all__ = ["containers_router", "stats_router"]
