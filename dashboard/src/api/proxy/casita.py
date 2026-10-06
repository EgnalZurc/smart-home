"""Casita Sueños service proxy routes.

Proxies requests to the casita-suenos property search service.
"""

import httpx
from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/casita", tags=["Casita"])

SERVICE_URL = "http://casita-suenos:8001"


@router.get("/status")
async def get_casita_status():
    """Get full status of Casita Sueños property monitor."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{SERVICE_URL}/status")
            return resp.json()
    except Exception as e:
        return {
            "online": False,
            "error": str(e),
            "total_properties": 0,
            "scraper_errors": [],
            "top_properties": [],
        }


@router.get("/radar")
async def get_casita_radar(request: Request):
    """Get properties above alert threshold (radar view)."""
    qs = str(request.url.query)
    url = f"{SERVICE_URL}/radar"
    if qs:
        url = f"{url}?{qs}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            return resp.json()
    except Exception as e:
        return {
            "items": [],
            "total": 0,
            "offset": 0,
            "limit": 20,
            "has_more": False,
            "error": str(e),
        }


@router.get("/dismissed")
async def get_casita_dismissed():
    """Get list of dismissed properties."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{SERVICE_URL}/dismissed")
            return resp.json()
    except Exception as e:
        return {"properties": [], "error": str(e)}


@router.get("/schedule")
async def get_casita_schedule():
    """Get scraping schedule configuration."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{SERVICE_URL}/schedule")
            return resp.json()
    except Exception as e:
        return {"error": str(e)}


@router.post("/schedule")
async def save_casita_schedule(request: Request):
    """Update scraping schedule configuration."""
    try:
        body = await request.json()
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(f"{SERVICE_URL}/schedule", json=body)
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/dismiss")
async def dismiss_casita_property(request: Request):
    """Dismiss a property from radar."""
    try:
        body = await request.json()
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(f"{SERVICE_URL}/dismiss", json=body)
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/undismiss")
async def undismiss_casita_property(request: Request):
    """Restore a dismissed property to radar."""
    try:
        body = await request.json()
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(f"{SERVICE_URL}/undismiss", json=body)
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/mark-viewed")
async def mark_casita_viewed(request: Request):
    """Mark a property as viewed."""
    try:
        body = await request.json()
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(f"{SERVICE_URL}/mark-viewed", json=body)
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/save-comment")
async def save_casita_comment(request: Request):
    """Save a comment on a property."""
    try:
        body = await request.json()
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(f"{SERVICE_URL}/save-comment", json=body)
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/summary")
async def get_casita_summary():
    """Get AI-generated summary of interesting properties."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{SERVICE_URL}/summary")
            return resp.json()
    except Exception as e:
        return {"content": None, "sent_at": None, "error": str(e)}


@router.post("/run-scraping")
async def run_casita_scraping():
    """Trigger manual property scraping."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(f"{SERVICE_URL}/run-scraping")
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/run-summary")
async def run_casita_summary():
    """Trigger AI summary generation."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(f"{SERVICE_URL}/run-summary")
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))
