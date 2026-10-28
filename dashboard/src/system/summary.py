"""Unified system summary endpoint.

Provides a single ``GET /api/system/summary`` call that bundles everything the
dashboard home view needs into one response, so the frontend does not have to
fan out to four separate endpoints on every refresh:

- ``containers``: running state of every controllable service
  (from :func:`system.containers.get_containers`)
- ``stats``: host resource usage — RAM, CPU, disk, temperature
  (from :func:`system.stats.get_system_stats`)
- ``alerts``: the unified alert feed
  (from :func:`api.alerts.get_unified_alerts`)
- ``services_health``: per-service health
  (from :func:`api.health.get_all_health`)

The four sources are gathered concurrently in-process (direct coroutine calls,
not self-HTTP through nginx) so the summary costs roughly one slow source, not
the sum of all four. A failing source degrades gracefully: its slot carries an
``{"error": ...}`` payload instead of taking the whole response down.

Caching
-------
The dashboard polls this view frequently. To avoid hammering Docker, ``/proc``
and every downstream service on each poll, the assembled payload is cached for
``SUMMARY_CACHE_TTL`` seconds (30s) and reused for repeated calls within the
window. Because ``alerts`` is per-user (read-state is scoped to the caller), the
cache is keyed by username so one user's read-state never leaks into another's
response.

Authorization
-------------
SUPER (level 0) only, matching ``system/stats.py`` and ``system/containers.py``:
the payload exposes host internals (container states, CPU/RAM/disk/temp) that
only the admin should see.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from api.auth_helpers import require_super
from fastapi import APIRouter, Query, Request

router = APIRouter(prefix="/api/system", tags=["System"])

__all__ = ["router", "get_system_summary", "SUMMARY_CACHE_TTL"]

# ── Summary cache ─────────────────────────────────────────────────────────────
#
# The assembled summary is cached per (user, days) key for a short TTL. The key
# includes the username because the alerts section embeds per-user read-state,
# and ``days`` because it changes the alerts look-back window.

SUMMARY_CACHE_TTL: float = 30.0  # seconds

# Maps a cache key -> (timestamp, payload) of the last assembled summary.
_summary_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _error_slot(exc: BaseException) -> dict[str, Any]:
    """Normalise a failed source into an ``{"error": ...}`` slot."""
    return {"error": f"{type(exc).__name__}: {exc}"}


@router.get("/summary")
async def get_system_summary(
    request: Request,
    days: int = Query(
        1, ge=1, le=30, description="Look-back window for memory alerts (days)"
    ),
) -> dict[str, Any]:
    """Return a unified snapshot of the whole system in a single call.

    Aggregates containers, host stats, unified alerts and per-service health.
    SUPER-only. The result is cached for ``SUMMARY_CACHE_TTL`` seconds per user
    so frequent dashboard polls do not re-run every underlying check.

    Response shape::

        {
          "cached": bool,            # true when served from the TTL cache
          "timestamp": float,        # epoch seconds when assembled
          "containers": {...},       # or {"error": ...}
          "stats": {...},            # or {"error": ...}
          "alerts": {...},           # or {"error": ...}
          "services_health": {...},  # or {"error": ...}
        }

    A failing source never fails the whole endpoint: its slot carries an
    ``error`` string instead.
    """
    user: str = require_super(request)

    cache_key: str = f"{user}:{days}"
    now: float = time.monotonic()
    cached: tuple[float, dict[str, Any]] | None = _summary_cache.get(cache_key)
    if cached is not None:
        timestamp, payload = cached
        if now - timestamp < SUMMARY_CACHE_TTL:
            return {**payload, "cached": True}

    # Import here (not at module load) so the router registers even if an
    # optional source module is unavailable, and to avoid import cycles.
    from api.alerts import get_unified_alerts
    from api.health import get_all_health

    from system.containers import get_containers
    from system.stats import get_system_stats

    results: tuple[Any, ...] = await asyncio.gather(
        get_containers(request),
        get_system_stats(request),
        get_unified_alerts(request, days=days),
        get_all_health(),
        return_exceptions=True,
    )

    containers, stats, alerts, services_health = results

    payload: dict[str, Any] = {
        "cached": False,
        "timestamp": time.time(),
        "containers": _error_slot(containers)
        if isinstance(containers, BaseException)
        else containers,
        "stats": _error_slot(stats) if isinstance(stats, BaseException) else stats,
        "alerts": _error_slot(alerts) if isinstance(alerts, BaseException) else alerts,
        "services_health": _error_slot(services_health)
        if isinstance(services_health, BaseException)
        else services_health,
    }

    _summary_cache[cache_key] = (time.monotonic(), payload)
    return payload
