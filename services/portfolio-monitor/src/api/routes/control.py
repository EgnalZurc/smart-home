"""
Portfolio Monitor — Control endpoints.

Write/trigger operations: refresh all or a single monitor, reload config from
disk, and read the monitoring schedule. The refresh and reload endpoints are
rate limited to protect the upstream data sources.

``get_orchestrator`` is resolved through the ``api.routes`` package namespace at
call time so tests patching ``api.routes.get_orchestrator`` take effect here.
"""

import logging
from enum import Enum

from fastapi import APIRouter, BackgroundTasks, Depends, Request

from .auth import require_auth
from .helpers import _config_limiter, _enforce_rate_limit, _refresh_limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


class MonitorName(str, Enum):
    """Valid monitor names for refresh endpoints.

    Using an Enum ensures that only valid monitor names are accepted,
    providing type safety and preventing injection of arbitrary strings
    into log messages and orchestrator calls.
    """

    ETF = "etf"
    CRYPTO = "crypto"
    SAVINGS = "savings"


@router.post("/refresh", dependencies=[Depends(require_auth)])
async def refresh_all(request: Request, background_tasks: BackgroundTasks):
    """Trigger a refresh of all monitors. Rate limited: 5 req/min."""
    import api.routes as routes

    # Manual rate limit check (can't use decorator easily with BackgroundTasks)
    _enforce_rate_limit(_refresh_limiter, request)

    orch = routes.get_orchestrator()

    async def run_refresh():
        try:
            await orch.run_all_monitors()
            logger.info("All monitors refresh completed")
        except (OSError, ValueError, TypeError, RuntimeError, ConnectionError) as e:
            logger.error(f"Error during refresh all monitors: {type(e).__name__}: {e}")

    background_tasks.add_task(run_refresh)
    logger.info("Refresh all monitors triggered")

    return {"status": "refresh_started", "monitors": ["etf", "crypto", "savings"]}


@router.post("/refresh/{monitor_name}", dependencies=[Depends(require_auth)])
async def refresh_monitor(
    monitor_name: MonitorName, request: Request, background_tasks: BackgroundTasks
):
    """Trigger a refresh of a specific monitor. Rate limited: 5 req/min.

    Args:
        monitor_name: The monitor to refresh (etf, crypto, or savings).
            Using MonitorName enum ensures type-safe validation and prevents
            arbitrary string injection into logs.
        request: The incoming HTTP request (for rate limiting).
        background_tasks: FastAPI background tasks for async execution.

    Returns:
        JSON with status and monitor name.

    Raises:
        HTTPException 429: If rate limit exceeded.
    """
    import api.routes as routes

    _enforce_rate_limit(_refresh_limiter, request)

    orch = routes.get_orchestrator()

    async def run_refresh():
        try:
            await orch.run_monitor(monitor_name.value)
            logger.info("Monitor %s refresh completed", monitor_name.value)
        except (OSError, ValueError, TypeError, RuntimeError, ConnectionError) as e:
            logger.error(
                "Error during refresh of %s: %s: %s",
                monitor_name.value,
                type(e).__name__,
                e,
            )

    background_tasks.add_task(run_refresh)
    logger.info("Refresh %s monitor triggered", monitor_name.value)

    return {"status": "refresh_started", "monitor": monitor_name.value}


@router.post("/reload-config", dependencies=[Depends(require_auth)])
async def reload_config(request: Request):
    """Reload configuration from disk. Rate limited: 2 req/min."""
    import api.routes as routes

    _enforce_rate_limit(_config_limiter, request)

    orch = routes.get_orchestrator()
    orch.reload_config()
    logger.info("Configuration reloaded from disk")
    return {"status": "config_reloaded"}


@router.get("/schedule")
async def get_schedule(request: Request):
    """Get the monitoring schedule. Rate limited: 30 req/min.

    Returns the configured schedule for each monitor and the next scheduled
    run times. This is a read-only endpoint but rate limited to prevent
    abuse (e.g., polling loops that hammer the endpoint).

    Args:
        request: The incoming HTTP request (for rate limiting).

    Returns:
        JSON with schedule configuration and next_runs timestamps.

    Raises:
        HTTPException 429: If rate limit exceeded.
    """
    import api.routes as routes

    from .helpers import _enforce_rate_limit, _public_read_limiter

    _enforce_rate_limit(_public_read_limiter, request)

    orch = routes.get_orchestrator()
    schedule = orch.get_schedule()
    next_runs = orch.get_next_run_times()

    return {
        "schedule": schedule,
        "next_runs": {
            name: ts.isoformat() if ts else None for name, ts in next_runs.items()
        },
    }
