"""Metrics service proxy routes (SUPER-gated).

Proxies the read API of the infrastructure ``metrics-service`` (:8011) under the
unified backend gateway so it appears in Swagger and is protected by the backend
AuthMiddleware + nginx ``auth_request``. The browser never talks to :8011
directly.

All routes require SUPER (level 0), matching ``system/stats.py`` and
``system/containers.py``: metrics expose host/container internals that only the
admin should see.

Defense-in-depth: POST/PUT requests include X-Internal-Request header that
metrics-service validates, ensuring requests only come through the dashboard proxy.
"""

from fastapi import APIRouter, Query, Request

from api.auth_helpers import require_super
from api.proxy.base import ServiceProxy

router = APIRouter(prefix="/api/metrics", tags=["Metrics"])

__all__ = [
    "router",
    "get_metrics_latest",
    "get_metrics_series",
    "get_metrics_summary",
    "get_metrics_alerts",
    "get_metrics_alerts_history",
    "dismiss_metrics_alert",
    "get_metrics_thresholds",
    "put_metrics_thresholds",
]

_proxy = ServiceProxy("http://metrics-service:8011")

# Header sent to metrics-service for defense-in-depth validation on write endpoints
_INTERNAL_HEADERS = {"X-Internal-Request": "dashboard"}


@router.get("/latest")
async def get_metrics_latest(request: Request):
    """Newest sample for every series (powers status widgets)."""
    require_super(request)
    return await _proxy.get("/api/metrics/latest")


@router.get("/series")
async def get_metrics_series(
    request: Request,
    metric: str = Query(..., description="Metric name, e.g. host.ram.percent"),
    label: str = Query("", description="Series label (container/service key)"),
    since: str | None = Query(None, description="Unix ts or relative, e.g. -1h"),
    until: str | None = Query(None, description="Unix ts upper bound"),
    resolution: str = Query("hi", pattern="^(hi|rollup)$"),
):
    """One time-ranged series (hi = ring buffer, rollup = SQLite)."""
    require_super(request)
    params = {"metric": metric, "label": label, "resolution": resolution}
    if since is not None:
        params["since"] = since
    if until is not None:
        params["until"] = until
    return await _proxy.get("/api/metrics/series", params=params)


@router.get("/summary")
async def get_metrics_summary(
    request: Request,
    window: str = Query("24h", pattern="^(1h|24h|7d|30d)$"),
):
    """min/avg/max per metric over a window."""
    require_super(request)
    return await _proxy.get("/api/metrics/summary", params={"window": window})


@router.get("/alerts")
async def get_metrics_alerts(request: Request):
    """Currently-firing alerts (anti-flap active set)."""
    require_super(request)
    return await _proxy.get("/api/metrics/alerts")


@router.get("/alerts/history")
async def get_metrics_alerts_history(
    request: Request,
    days: int = Query(7, ge=1, le=90, description="Look-back window in days"),
):
    """Alert audit trail (fired/resolved events) for the last N days."""
    require_super(request)
    return await _proxy.get("/api/metrics/alerts/history", params={"days": days})


@router.post("/alerts/dismiss")
async def dismiss_metrics_alert(request: Request):
    """Manually dismiss an active alert by fingerprint (SUPER).

    The alert is resolved as if the condition cleared. If the condition still
    breaches, the alert will re-fire on the next collector tick.
    """
    require_super(request)
    body = await request.json()
    return await _proxy.post(
        "/api/metrics/alerts/dismiss", json=body, headers=_INTERNAL_HEADERS
    )


@router.get("/thresholds")
async def get_metrics_thresholds(request: Request):
    """Current alert threshold rule set."""
    require_super(request)
    return await _proxy.get("/api/metrics/thresholds")


@router.put("/thresholds")
async def put_metrics_thresholds(request: Request):
    """Patch alert thresholds at runtime (SUPER)."""
    require_super(request)
    body = await request.json()
    return await _proxy.put(
        "/api/metrics/thresholds", json=body, headers=_INTERNAL_HEADERS
    )
