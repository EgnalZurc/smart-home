"""Portfolio Monitor service proxy routes.

Proxies requests to the portfolio-monitor service.
"""

from fastapi import APIRouter

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
async def refresh_portfolio():
    """Trigger a refresh of all monitors."""
    return await _proxy.post("/api/portfolio/refresh")


@router.post("/refresh/{monitor_name}")
async def refresh_portfolio_monitor(monitor_name: str):
    """Trigger a refresh of a specific monitor (etf or crypto)."""
    return await _proxy.post(f"/api/portfolio/refresh/{monitor_name}")


@router.get("/schedule")
async def get_portfolio_schedule():
    """Get the monitoring schedule."""
    return await _proxy.get("/api/portfolio/schedule")


@router.post("/reload-config")
async def reload_portfolio_config():
    """Reload portfolio configuration from disk."""
    return await _proxy.post("/api/portfolio/reload-config")


@router.get("/notifications/status")
async def get_portfolio_notification_status():
    """Get the notification system status."""
    return await _proxy.get("/api/portfolio/notifications/status")


@router.post("/notifications/test")
async def test_portfolio_notification():
    """Send a test notification to verify Telegram setup."""
    return await _proxy.post("/api/portfolio/notifications/test")
