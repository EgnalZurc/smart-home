"""Unified alerts aggregator.

Collects alerts from every service that exposes an alerts feed into a single
endpoint the dashboard can poll. Each source is normalised into a common shape
and tagged with its ``source`` so the frontend can render one coherent list.

Design notes
------------
* The ``memory`` source lives in THIS service (``api.monitoring``) and reads a
  local JSON file, so it is called in-process rather than over HTTP. This avoids
  a fragile self-call through nginx/AuthMiddleware and keeps it fast.
* Remote sources are fetched through the shared :class:`ServiceProxy` (the same
  helper every other proxy module uses) via their Docker DNS names. Each fetch
  degrades gracefully: a failing source contributes an empty list and never
  takes the whole endpoint down.
* Wave 1 standardised the remote feeds to ``{"alerts": [...]}``; the pre-existing
  ``metrics-service`` feed uses ``{"ts": ..., "active": [...]}``. Both shapes are
  handled by :func:`_extract_alerts`.
"""

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from api import alert_reads_db
from api.auth_helpers import require_authenticated
from api.proxy.base import ServiceProxy

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/alerts", tags=["Alerts"])


class MarkReadRequest(BaseModel):
    """Body for ``POST /api/alerts/mark-read``."""

    alert_key: str = Field(
        ..., min_length=1, description="Stable identifier of the alert to mark read"
    )


# Remote sources: name -> (ServiceProxy, upstream path).
# These are fetched concurrently over the internal Docker network.
_REMOTE_SOURCES: dict[str, tuple[ServiceProxy, str]] = {
    "metrics": (ServiceProxy("http://metrics-service:8011"), "/api/metrics/alerts"),
    "ac": (ServiceProxy("http://ac-service:8002"), "/api/ac/alerts"),
    "portfolio": (
        ServiceProxy("http://portfolio-monitor:8010"),
        "/api/portfolio/alerts/active",
    ),
    "casita": (ServiceProxy("http://casita-suenos:8001"), "/api/casita/alerts"),
}

# Severity ordering for the sorted output (lower sorts first).
_SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}


def _extract_alerts(data: dict, source: str) -> list[dict]:
    """Pull the alert list out of a source payload and tag each entry.

    Handles both the Wave 1 ``{"alerts": [...]}`` shape and the metrics-service
    ``{"active": [...]}`` shape. Non-dict payloads yield an empty list.
    """
    if not isinstance(data, dict):
        return []

    raw = data.get("alerts")
    if raw is None:
        raw = data.get("active")
    if not isinstance(raw, list):
        return []

    alerts: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        item.setdefault("source", source)
        alerts.append(item)
    return alerts


async def _fetch_remote(name: str, proxy: ServiceProxy, path: str) -> list[dict]:
    """Fetch alerts from a remote service, returning [] on any failure."""
    try:
        data = await proxy.get(
            path,
            raise_on_error=False,
            default_on_error={"alerts": []},
        )
        return _extract_alerts(data, name)
    except Exception as exc:  # noqa: BLE001 - a bad source must not break the feed
        logger.warning("Failed to fetch alerts from %s: %s", name, exc)
        return []


async def _fetch_memory(days: int) -> list[dict]:
    """Fetch memory alerts in-process from the monitoring module."""
    try:
        import api.monitoring as monitoring

        data = await monitoring.get_memory_alerts(days=days)
        return _extract_alerts(data, "memory")
    except Exception as exc:  # noqa: BLE001 - keep the feed resilient
        logger.warning("Failed to collect memory alerts: %s", exc)
        return []


def _sort_key(alert: dict) -> tuple[int, str]:
    """Sort by severity (critical first), then timestamp ascending."""
    severity = alert.get("severity", "info")
    severity_rank = _SEVERITY_ORDER.get(severity, _SEVERITY_ORDER["info"])
    timestamp = alert.get("timestamp") or ""
    return (severity_rank, str(timestamp))


@router.get("/unified")
async def get_unified_alerts(
    request: Request,
    days: int = Query(
        1, ge=1, le=30, description="Look-back window for memory alerts (days)"
    ),
):
    """Aggregate alerts from every source into a single unified list.

    Visible to any authenticated family member. Sources are queried
    concurrently; a failing source contributes no alerts rather than erroring
    the whole response.
    """
    require_authenticated(request)

    tasks = [_fetch_memory(days)]
    tasks += [
        _fetch_remote(name, proxy, path)
        for name, (proxy, path) in _REMOTE_SOURCES.items()
    ]
    results = await asyncio.gather(*tasks)

    all_alerts: list[dict] = []
    for alerts in results:
        all_alerts.extend(alerts)

    all_alerts.sort(key=_sort_key)

    return {
        "count": len(all_alerts),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "alerts": all_alerts,
    }


@router.post("/mark-read")
async def mark_alert_read(request: Request, body: MarkReadRequest):
    """Mark an alert as read for the current user.

    Visible to any authenticated family member; the read state is scoped to the
    calling user (``user_id`` is the authenticated username). Idempotent:
    re-marking an already-read alert just refreshes its timestamp.
    """
    user = require_authenticated(request)
    alert_reads_db.mark_alert_read(user, body.alert_key)
    return {"status": "ok", "alert_key": body.alert_key}


@router.get("/read-status")
async def get_read_status(request: Request):
    """Return the alert keys the current user has marked as read.

    Visible to any authenticated family member; results are scoped to the
    calling user.
    """
    user = require_authenticated(request)
    read_keys = alert_reads_db.get_read_alerts(user)
    return {"count": len(read_keys), "read": read_keys}
