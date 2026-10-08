"""
Portfolio Monitor — Health endpoints.

A basic liveness probe plus an aggregate external-dependency check that runs the
Yahoo Finance, CoinGecko, Fear & Greed and SMTP probes in parallel and reports a
combined status. SMTP is treated as optional and does not affect the overall
verdict.

The external check functions are resolved through the ``api.routes`` package
namespace at call time so tests patching e.g. ``api.routes.check_coingecko`` take
effect here.
"""

from datetime import datetime

from fastapi import APIRouter

from .helpers import _safe_json

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


@router.get("/health")
async def health_check():
    """Basic health check endpoint."""
    import api.routes as routes

    orch = routes.get_orchestrator()
    state = orch.get_state()

    return {
        "online": True,
        "service": "portfolio-monitor",
        "last_etf_run": state.last_etf_run.isoformat() if state.last_etf_run else None,
        "last_crypto_run": state.last_crypto_run.isoformat()
        if state.last_crypto_run
        else None,
    }


@router.get("/health/external")
async def health_check_external():
    """
    Health check for external service connectivity.

    Checks:
    - Yahoo Finance API
    - CoinGecko API
    - Fear & Greed Index API
    - SMTP server

    Returns detailed status for each service.
    """
    import asyncio

    import api.routes as routes

    # Run all checks in parallel
    results = await asyncio.gather(
        routes.check_yahoo_finance(),
        routes.check_coingecko(),
        routes.check_fear_greed(),
        routes.check_smtp(),
        return_exceptions=True,
    )

    yahoo_result = (
        results[0]
        if not isinstance(results[0], Exception)
        else {"status": "error", "message": str(results[0])}
    )
    coingecko_result = (
        results[1]
        if not isinstance(results[1], Exception)
        else {"status": "error", "message": str(results[1])}
    )
    fear_greed_result = (
        results[2]
        if not isinstance(results[2], Exception)
        else {"status": "error", "message": str(results[2])}
    )
    smtp_result = (
        results[3]
        if not isinstance(results[3], Exception)
        else {"status": "error", "message": str(results[3])}
    )

    # Determine overall status
    statuses = [
        yahoo_result.get("status"),
        coingecko_result.get("status"),
        fear_greed_result.get("status"),
    ]
    # SMTP is optional, don't count it for overall status

    all_ok = all(s == "ok" for s in statuses)
    any_error = any(s == "error" for s in statuses)

    overall = "ok" if all_ok else "degraded" if not any_error else "unhealthy"

    return _safe_json(
        {
            "overall": overall,
            "services": {
                "yahoo_finance": yahoo_result,
                "coingecko": coingecko_result,
                "fear_greed": fear_greed_result,
                "smtp": smtp_result,
            },
            "timestamp": datetime.now().isoformat(),
        }
    )
