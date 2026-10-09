"""Portfolio Monitor service proxy routes.

Proxies requests to the portfolio-monitor service.
"""

from fastapi import APIRouter, Request

from api.auth_helpers import require_super

from .base import ServiceProxy

router = APIRouter(prefix="/api/portfolio", tags=["Portfolio"])

_proxy = ServiceProxy("http://portfolio-monitor:8010")


@router.get("/summary")
async def get_portfolio_summary():
    """Get full portfolio summary (ETF + crypto)."""
    return await _proxy.get("/api/portfolio/summary")


@router.get("/etf")
async def get_portfolio_etf():
    """Get ETF portfolio summary."""
    return await _proxy.get("/api/portfolio/etf")


@router.get("/crypto")
async def get_portfolio_crypto():
    """Get crypto staking summary."""
    return await _proxy.get("/api/portfolio/crypto")


@router.post("/refresh")
async def refresh_portfolio(request: Request):
    """Trigger a refresh of all monitors."""
    require_super(request)
    return await _proxy.post("/api/portfolio/refresh")


@router.post("/refresh/{monitor_name}")
async def refresh_portfolio_monitor(monitor_name: str, request: Request):
    """Trigger a refresh of a specific monitor (etf or crypto)."""
    require_super(request)
    return await _proxy.post(f"/api/portfolio/refresh/{monitor_name}")


@router.get("/schedule")
async def get_portfolio_schedule():
    """Get the monitoring schedule."""
    return await _proxy.get("/api/portfolio/schedule")


@router.post("/reload-config")
async def reload_portfolio_config(request: Request):
    """Reload portfolio configuration from disk."""
    require_super(request)
    return await _proxy.post("/api/portfolio/reload-config")


@router.get("/notifications/status")
async def get_portfolio_notification_status():
    """Get the notification system status."""
    return await _proxy.get("/api/portfolio/notifications/status")


@router.post("/notifications/test")
async def test_portfolio_notification(request: Request):
    """Send a test notification to verify Telegram setup."""
    require_super(request)
    return await _proxy.post("/api/portfolio/notifications/test")
