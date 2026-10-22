"""
Portfolio Monitor — Control endpoints.

Write/trigger operations: refresh all or a single monitor, reload config from
disk, and read the monitoring schedule. The refresh and reload endpoints are
rate limited to protect the upstream data sources.

``get_orchestrator`` is resolved through the ``api.routes`` package namespace at
call time so tests patching ``api.routes.get_orchestrator`` take effect here.
"""

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from .auth import require_auth
from .helpers import _config_limiter, _enforce_rate_limit, _refresh_limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


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
    monitor_name: str, request: Request, background_tasks: BackgroundTasks
):
    """Trigger a refresh of a specific monitor. Rate limited: 5 req/min."""
    import api.routes as routes

    if monitor_name not in ["etf", "crypto", "savings"]:
        logger.warning(f"Unknown monitor requested: {monitor_name}")
        raise HTTPException(status_code=404, detail=f"Unknown monitor: {monitor_name}")

    _enforce_rate_limit(_refresh_limiter, request)

    orch = routes.get_orchestrator()

    async def run_refresh():
        try:
            await orch.run_monitor(monitor_name)
            logger.info(f"Monitor {monitor_name} refresh completed")
        except (OSError, ValueError, TypeError, RuntimeError, ConnectionError) as e:
            logger.error(
                f"Error during refresh of {monitor_name}: {type(e).__name__}: {e}"
            )

    background_tasks.add_task(run_refresh)
    logger.info(f"Refresh {monitor_name} monitor triggered")

    return {"status": "refresh_started", "monitor": monitor_name}


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
async def get_schedule():
    """Get the monitoring schedule."""
    import api.routes as routes

    orch = routes.get_orchestrator()
    schedule = orch.get_schedule()
    next_runs = orch.get_next_run_times()

    return {
        "schedule": schedule,
        "next_runs": {
            name: ts.isoformat() if ts else None for name, ts in next_runs.items()
        },
    }
