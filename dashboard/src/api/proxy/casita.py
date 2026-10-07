"""Casita Sueños service proxy routes.

Proxies requests to the casita-suenos property search service.
"""

from fastapi import APIRouter, Request

from .base import ServiceProxy

router = APIRouter(prefix="/api/casita", tags=["Casita"])

_proxy = ServiceProxy("http://casita-suenos:8001")


@router.get("/status")
async def get_casita_status():
    """Get full status of Casita Sueños property monitor."""
    return await _proxy.get(
        "/status",
        raise_on_error=False,
        default_on_error={
            "online": False,
            "error": "Service unavailable",
            "total_properties": 0,
            "scraper_errors": [],
            "top_properties": [],
        },
    )


@router.get("/radar")
async def get_casita_radar(request: Request):
    """Get properties above alert threshold (radar view)."""
    # Forward query string for pagination
    params = dict(request.query_params)
    return await _proxy.get(
        "/radar",
        params=params if params else None,
        raise_on_error=False,
        default_on_error={
            "items": [],
            "total": 0,
            "offset": 0,
            "limit": 20,
            "has_more": False,
            "error": "Service unavailable",
        },
    )


@router.get("/dismissed")
async def get_casita_dismissed():
    """Get list of dismissed properties."""
    return await _proxy.get(
        "/dismissed",
        raise_on_error=False,
        default_on_error={"properties": [], "error": "Service unavailable"},
    )


@router.get("/schedule")
async def get_casita_schedule():
    """Get scraping schedule configuration."""
    return await _proxy.get(
        "/schedule",
        raise_on_error=False,
        default_on_error={"error": "Service unavailable"},
    )


@router.post("/schedule")
async def save_casita_schedule(request: Request):
    """Update scraping schedule configuration."""
    body = await request.json()
    return await _proxy.post("/schedule", json=body)


@router.post("/dismiss")
async def dismiss_casita_property(request: Request):
    """Dismiss a property from radar."""
    body = await request.json()
    return await _proxy.post("/dismiss", json=body)


@router.post("/undismiss")
async def undismiss_casita_property(request: Request):
    """Restore a dismissed property to radar."""
    body = await request.json()
    return await _proxy.post("/undismiss", json=body)


@router.post("/mark-viewed")
async def mark_casita_viewed(request: Request):
    """Mark a property as viewed."""
    body = await request.json()
    return await _proxy.post("/mark-viewed", json=body)


@router.post("/save-comment")
async def save_casita_comment(request: Request):
    """Save a comment on a property."""
    body = await request.json()
    # Longer timeout for AI operations
    return await _proxy.post("/save-comment", json=body)


@router.get("/summary")
async def get_casita_summary():
    """Get AI-generated summary of interesting properties."""
    return await _proxy.get(
        "/summary",
        raise_on_error=False,
        default_on_error={
            "content": None,
            "sent_at": None,
            "error": "Service unavailable",
        },
    )


@router.post("/run-scraping")
async def run_casita_scraping():
    """Trigger manual property scraping."""
    return await _proxy.post("/run-scraping")


@router.post("/run-summary")
async def run_casita_summary():
    """Trigger AI summary generation."""
    return await _proxy.post("/run-summary")
