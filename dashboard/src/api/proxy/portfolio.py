"""Portfolio Monitor service proxy routes.

Proxies requests to the portfolio-monitor service.
"""

import httpx
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/portfolio", tags=["Portfolio"])

SERVICE_URL = "http://portfolio-monitor:8010"


@router.get("/summary")
async def get_portfolio_summary():
    """Get full portfolio summary (ETF + crypto)."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{SERVICE_URL}/api/portfolio/summary")
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/etf")
async def get_portfolio_etf():
    """Get ETF portfolio summary."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{SERVICE_URL}/api/portfolio/etf")
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/crypto")
async def get_portfolio_crypto():
    """Get crypto staking summary."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{SERVICE_URL}/api/portfolio/crypto")
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/refresh")
async def refresh_portfolio():
    """Trigger a refresh of all monitors."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(f"{SERVICE_URL}/api/portfolio/refresh")
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/refresh/{monitor_name}")
async def refresh_portfolio_monitor(monitor_name: str):
    """Trigger a refresh of a specific monitor (etf or crypto)."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{SERVICE_URL}/api/portfolio/refresh/{monitor_name}"
            )
            if resp.status_code >= 400:
                raise HTTPException(
                    status_code=resp.status_code,
                    detail=resp.json().get("detail", "Error"),
                )
            return resp.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/schedule")
async def get_portfolio_schedule():
    """Get the monitoring schedule."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{SERVICE_URL}/api/portfolio/schedule")
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/reload-config")
async def reload_portfolio_config():
    """Reload portfolio configuration from disk."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(f"{SERVICE_URL}/api/portfolio/reload-config")
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/notifications/status")
async def get_portfolio_notification_status():
    """Get the notification system status."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{SERVICE_URL}/api/portfolio/notifications/status")
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/notifications/test")
async def test_portfolio_notification():
    """Send a test notification to verify Telegram setup."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(f"{SERVICE_URL}/api/portfolio/notifications/test")
            if resp.status_code >= 400:
                raise HTTPException(
                    status_code=resp.status_code,
                    detail=resp.json().get("detail", "Error"),
                )
            return resp.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))
