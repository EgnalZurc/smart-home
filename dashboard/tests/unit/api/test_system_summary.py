"""Unit tests for GET /api/system/summary.

Tests cover:
  - SUPER profile gets 200 with all four sections (containers, stats, alerts,
    services_health)
  - FAMILIA_PRINCIPAL gets 403, unauthenticated gets 401
  - A failing source degrades to an {"error": ...} slot instead of 500
  - The response is cached for the TTL window (second call does not re-run the
    underlying sources and is marked cached=True)
  - The cache is keyed per user so one user's result is not served to another
  - The ``days`` query param is validated and forwarded to the alerts source
"""

import sys
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Mock passlib before any auth import (mirrors test_system_stats.py).
_mock_passlib = MagicMock()
_mock_passlib.hash.apr_md5_crypt.verify.return_value = True
sys.modules.setdefault("passlib", _mock_passlib)
sys.modules.setdefault("passlib.hash", _mock_passlib.hash)

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

# ── Fixtures / helpers ──────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def clear_summary_cache():
    """Reset the module-level summary cache before and after each test."""
    import system.summary as summary

    summary._summary_cache.clear()
    yield
    summary._summary_cache.clear()


def _make_client():
    """TestClient for the aggregated router without auth middleware."""
    from api import routes

    app = FastAPI()
    app.include_router(routes.router)
    return TestClient(app, raise_server_exceptions=True)


def _patch_super(username="egnal"):
    """Patch require_super (as referenced inside system.summary) to allow."""
    return patch("system.summary.require_super", side_effect=lambda request: username)


def _patch_familia():
    """Patch require_super to reject as FAMILIA_PRINCIPAL (403)."""

    def fake(request):
        raise HTTPException(status_code=403, detail="SUPER profile required")

    return patch("system.summary.require_super", side_effect=fake)


def _patch_unauthenticated():
    """Patch require_super to reject as unauthenticated (401)."""

    def fake(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    return patch("system.summary.require_super", side_effect=fake)


# Representative source payloads.
_CONTAINERS = {"ac": {"containers": ["ac-service"], "running": True}}
_STATS = {
    "ram": {"total_mb": 4096, "used_mb": 1500, "percent": 36.6},
    "cpu": {"percent": 12.3},
    "disk": {"total_gb": 128.0, "used_gb": 40.0, "percent": 31.2},
    "temp": {"celsius": 48.5},
}
_ALERTS = {"count": 2, "unread_count": 1, "alerts": [{"source": "ac"}]}
_HEALTH = {"backend": {"online": True}, "ac": {"online": True}}


def _patch_sources(containers=None, stats=None, alerts=None, health=None):
    """Patch the four source coroutines imported inside get_system_summary.

    They are imported lazily inside the handler, so patching the names on their
    defining modules is what the import binds to.
    """
    containers = _CONTAINERS if containers is None else containers
    stats = _STATS if stats is None else stats
    alerts = _ALERTS if alerts is None else alerts
    health = _HEALTH if health is None else health

    return [
        patch(
            "system.containers.get_containers", new=AsyncMock(return_value=containers)
        ),
        patch("system.stats.get_system_stats", new=AsyncMock(return_value=stats)),
        patch("api.alerts.get_unified_alerts", new=AsyncMock(return_value=alerts)),
        patch("api.health.get_all_health", new=AsyncMock(return_value=health)),
    ]


# ── Authorization ─────────────────────────────────────────────────────────────


def test_summary_super_gets_all_sections():
    client = _make_client()
    with ExitStack() as stack:
        stack.enter_context(_patch_super())
        for p in _patch_sources():
            stack.enter_context(p)
        resp = client.get("/api/system/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["containers"] == _CONTAINERS
    assert body["stats"] == _STATS
    assert body["alerts"] == _ALERTS
    assert body["services_health"] == _HEALTH
    assert body["cached"] is False
    assert "timestamp" in body


def test_summary_familia_gets_403():
    client = _make_client()
    with ExitStack() as stack:
        stack.enter_context(_patch_familia())
        for p in _patch_sources():
            stack.enter_context(p)
        resp = client.get("/api/system/summary")
    assert resp.status_code == 403


def test_summary_unauthenticated_gets_401():
    client = _make_client()
    with ExitStack() as stack:
        stack.enter_context(_patch_unauthenticated())
        for p in _patch_sources():
            stack.enter_context(p)
        resp = client.get("/api/system/summary")
    assert resp.status_code == 401


# ── Graceful degradation ────────────────────────────────────────────────────


def test_summary_failing_source_degrades_to_error_slot():
    """One source raising must not 500 the whole summary."""
    client = _make_client()
    patches = [
        patch(
            "system.containers.get_containers",
            new=AsyncMock(side_effect=RuntimeError("docker down")),
        ),
        patch("system.stats.get_system_stats", new=AsyncMock(return_value=_STATS)),
        patch("api.alerts.get_unified_alerts", new=AsyncMock(return_value=_ALERTS)),
        patch("api.health.get_all_health", new=AsyncMock(return_value=_HEALTH)),
    ]
    with _patch_super(), patches[0], patches[1], patches[2], patches[3]:
        resp = client.get("/api/system/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert "error" in body["containers"]
    assert "docker down" in body["containers"]["error"]
    # Healthy sources are still present.
    assert body["stats"] == _STATS
    assert body["alerts"] == _ALERTS


# ── Caching ───────────────────────────────────────────────────────────────────


def test_summary_second_call_is_cached():
    """A second call within the TTL returns cached data without re-running sources."""
    client = _make_client()
    containers_mock = AsyncMock(return_value=_CONTAINERS)
    stats_mock = AsyncMock(return_value=_STATS)
    alerts_mock = AsyncMock(return_value=_ALERTS)
    health_mock = AsyncMock(return_value=_HEALTH)

    with (
        _patch_super(),
        patch("system.containers.get_containers", new=containers_mock),
        patch("system.stats.get_system_stats", new=stats_mock),
        patch("api.alerts.get_unified_alerts", new=alerts_mock),
        patch("api.health.get_all_health", new=health_mock),
    ):
        first = client.get("/api/system/summary")
        second = client.get("/api/system/summary")

    assert first.status_code == second.status_code == 200
    assert first.json()["cached"] is False
    assert second.json()["cached"] is True
    # Sources ran exactly once (first call); the second call hit the cache.
    assert containers_mock.await_count == 1
    assert stats_mock.await_count == 1
    assert alerts_mock.await_count == 1
    assert health_mock.await_count == 1


def test_summary_cache_is_per_user():
    """Different users must not share a cached summary."""
    client = _make_client()
    containers_mock = AsyncMock(return_value=_CONTAINERS)

    with (
        patch("system.summary.require_super", side_effect=["alice", "bob"]),
        patch("system.containers.get_containers", new=containers_mock),
        patch("system.stats.get_system_stats", new=AsyncMock(return_value=_STATS)),
        patch("api.alerts.get_unified_alerts", new=AsyncMock(return_value=_ALERTS)),
        patch("api.health.get_all_health", new=AsyncMock(return_value=_HEALTH)),
    ):
        first = client.get("/api/system/summary")
        second = client.get("/api/system/summary")

    assert first.json()["cached"] is False
    # bob has no cache entry, so his call is a fresh (not cached) build.
    assert second.json()["cached"] is False
    assert containers_mock.await_count == 2


# ── Query param ─────────────────────────────────────────────────────────────


def test_summary_days_param_forwarded_to_alerts():
    client = _make_client()
    alerts_mock = AsyncMock(return_value=_ALERTS)
    with (
        _patch_super(),
        patch(
            "system.containers.get_containers", new=AsyncMock(return_value=_CONTAINERS)
        ),
        patch("system.stats.get_system_stats", new=AsyncMock(return_value=_STATS)),
        patch("api.alerts.get_unified_alerts", new=alerts_mock),
        patch("api.health.get_all_health", new=AsyncMock(return_value=_HEALTH)),
    ):
        resp = client.get("/api/system/summary?days=7")
    assert resp.status_code == 200
    # days is forwarded as a keyword argument to the alerts source.
    _, kwargs = alerts_mock.await_args
    assert kwargs.get("days") == 7


def test_summary_days_param_out_of_range_rejected():
    client = _make_client()
    with ExitStack() as stack:
        stack.enter_context(_patch_super())
        for p in _patch_sources():
            stack.enter_context(p)
        resp = client.get("/api/system/summary?days=99")
    assert resp.status_code == 422
