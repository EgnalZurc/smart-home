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
import hashlib
import logging
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from api import alert_reads_db
from api.auth_helpers import require_authenticated
from api.proxy.base import ServiceProxy

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/alerts", tags=["Alerts"])

__all__ = [
    "router",
    "get_unified_alerts",
    "mark_alert_read",
    "get_read_status",
    "MarkReadRequest",
]

# Length of the SHA1-based fingerprint used for alert identification
FINGERPRINT_LENGTH: int = 12


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


def _alert_identifier(alert: dict) -> str:
    """Derive a stable per-alert identifier within its source.

    Prefers an explicit unique field (``id``/``alert_id``/``fingerprint``/
    ``container``). When none is present, falls back to a short hash of the
    alert's title and/or URL so the same alert maps to the same key across
    polls. As a last resort the full alert payload is hashed.
    """
    for field in ("id", "alert_id", "fingerprint", "container"):
        value = alert.get(field)
        if value not in (None, ""):
            return str(value)

    title = str(alert.get("title") or "")
    url = str(alert.get("url") or "")
    basis = f"{title}|{url}" if (title or url) else repr(sorted(alert.items()))
    # Not a security control: this is a short, stable content fingerprint used
    # only to key read-state, so SHA1 (fast, compact) is fine.
    return hashlib.sha1(basis.encode("utf-8"), usedforsecurity=False).hexdigest()[
        :FINGERPRINT_LENGTH
    ]


def _alert_key(alert: dict) -> str:
    """Build the stable ``"{source}:{identifier}"`` key for an alert."""
    source = alert.get("source", "unknown")
    return f"{source}:{_alert_identifier(alert)}"


async def _fetch_remote(name: str, proxy: ServiceProxy, path: str) -> list[dict]:
    """Fetch alerts from a remote service, returning [] on any failure."""
    try:
        data = await proxy.get(
            path,
            raise_on_error=False,
            default_on_error={"alerts": []},
        )
        return _extract_alerts(data, name)
    except (httpx.HTTPError, httpx.TimeoutException, OSError) as exc:
        logger.warning("Failed to fetch alerts from %s: %s", name, exc)
        return []


async def _fetch_memory(days: int) -> list[dict]:
    """Fetch memory alerts in-process from the monitoring module."""
    try:
        import api.monitoring as monitoring

        data = await monitoring.get_memory_alerts(days=days)
        return _extract_alerts(data, "memory")
    except (
        OSError,
        ValueError,
        KeyError,
        RuntimeError,
        TypeError,
        AttributeError,
    ) as exc:
        # Specific exceptions: monitoring module may raise various errors (file I/O, JSON parsing, missing attributes)
        # and we must not break the aggregated feed.
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
    unread_only: bool = Query(
        False, description="When true, return only alerts the user has not read"
    ),
):
    """Aggregate alerts from every source into a single unified list.

    Visible to any authenticated family member. Sources are queried
    concurrently; a failing source contributes no alerts rather than erroring
    the whole response.

    Each alert is tagged with a stable ``key`` (``"{source}:{identifier}"``) and
    a per-user ``read`` flag derived from the caller's read records. The response
    also carries ``unread_count``. Pass ``unread_only=true`` to filter the list
    down to the alerts the current user has not yet read.
    """
    user = require_authenticated(request)

    # ``unread_only`` is a bool when resolved by FastAPI, but unit tests call
    # this coroutine directly, in which case it is still the ``Query(...)``
    # default sentinel. Coerce to a real bool so the sentinel (truthy) does not
    # accidentally enable filtering.
    unread_only = unread_only is True

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

    read_keys = set(alert_reads_db.get_read_alerts(user))

    unread_count = 0
    enriched: list[dict] = []
    for alert in all_alerts:
        key = _alert_key(alert)
        is_read = key in read_keys
        if not is_read:
            unread_count += 1
        if unread_only and is_read:
            continue
        alert["key"] = key
        alert["read"] = is_read
        enriched.append(alert)

    return {
        "count": len(enriched),
        "unread_count": unread_count,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "alerts": enriched,
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
