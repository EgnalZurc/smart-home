"""Integration tests for the energy-monitor HTTP API.

Exercises the FastAPI routes directly against the in-process app using
``httpx.ASGITransport`` WITHOUT triggering the lifespan (so the background poll
loops never start). The module-level ``collector`` is pointed at a temp DB and
has its ring buffer manipulated directly so tests never touch hardware or the
production path.
"""

from __future__ import annotations

import httpx
import main
import pytest
from collector import Collector
from database import EnergyStore


@pytest.fixture
def client(tmp_path, monkeypatch):
    test_collector = Collector(EnergyStore(str(tmp_path / "energy.db")))
    monkeypatch.setattr(main, "collector", test_collector)
    transport = httpx.ASGITransport(app=main.app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_health_reports_db_ok(client):
    async with client as c:
        resp = await c.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["online"] is True
    assert body["service"] == "energy-monitor"
    assert body["db_ok"] is True
    # Sensitive config (db_path) should not be exposed in responses.
    assert "db_path" not in body
    # No poll has run in-test, so collector/meter liveness is "no data yet".
    assert body["meter_online"] is None
    assert body["collector_last_tick_age_s"] is None


async def test_health_alias_matches(client):
    async with client as c:
        resp = await c.get("/api/health/energy")
    assert resp.status_code == 200
    body = resp.json()
    assert body["service"] == "energy-monitor"
    assert body["db_ok"] is True
    # Sensitive config should not be exposed.
    assert "db_path" not in body


async def test_health_db_ok_false_when_store_broken(client, monkeypatch):
    class BrokenStore:
        def count(self):
            raise RuntimeError("db gone")

    class BrokenCollector:
        store = BrokenStore()
        meter_online = None

        def last_tick_age_s(self):
            return None

    monkeypatch.setattr(main, "collector", BrokenCollector())
    async with client as c:
        resp = await c.get("/health")
    assert resp.status_code == 200
    assert resp.json()["db_ok"] is False


async def test_current_returns_empty_channels_when_no_data(client):
    async with client as c:
        resp = await c.get("/api/energy/current")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_w"] == 0.0
    assert body["channels"] == {}
    assert body["meter_online"] is None
    assert isinstance(body["ts"], int)


async def test_current_reflects_ring_buffer(client, monkeypatch):
    # Seed the collector's ring buffer with two live channels and mark online.
    monkeypatch.setitem(main.collector.labels, "main:ch0", "General")
    main.collector.ring["main:ch0"].append((1000, 1200.0, 230.0, 0.95))
    main.collector.ring["main:ch1"].append((1000, 300.0, 230.0, 0.9))
    main.collector.meter_online = True
    try:
        async with client as c:
            resp = await c.get("/api/energy/current")
        body = resp.json()
        assert body["meter_online"] is True
        assert body["total_w"] == pytest.approx(1500.0)
        assert body["channels"]["main:ch0"]["power"] == 1200.0
        assert body["channels"]["main:ch0"]["label"] == "General"
        # No inventory label for ch1 → key is used as the fallback label.
        assert body["channels"]["main:ch1"]["label"] == "main:ch1"
    finally:
        main.collector.ring.clear()
        main.collector.meter_online = None


async def test_db_ok_helper_true_and_false(monkeypatch, tmp_path):
    # Direct unit coverage of the _db_ok helper on both branches.
    test_collector = Collector(EnergyStore(str(tmp_path / "e.db")))
    monkeypatch.setattr(main, "collector", test_collector)
    assert main._db_ok() is True

    class Broken:
        def count(self):
            raise RuntimeError("boom")

    test_collector.store = Broken()  # type: ignore[assignment]
    assert main._db_ok() is False


# ── History endpoint ──────────────────────────────────────────────────────────
async def test_history_empty_defaults_to_day(client):
    async with client as c:
        resp = await c.get("/api/energy/history")
    assert resp.status_code == 200
    body = resp.json()
    assert body["period"] == "day"
    assert body["count"] == 24
    assert len(body["series"]) == 24
    assert all(p["consumption_wh"] is None for p in body["series"])


async def test_history_returns_deltas(client):
    import time as _time

    main.collector.store.write_energy(int(_time.time()) - 7200, [("ch0", 0.0)])
    main.collector.store.write_energy(int(_time.time()) - 3600, [("ch0", 1500.0)])
    async with client as c:
        resp = await c.get("/api/energy/history?period=hour&count=3&channel=ch0")
    assert resp.status_code == 200
    body = resp.json()
    assert body["period"] == "hour"
    assert body["channel"] == "ch0"
    values = [p["consumption_wh"] for p in body["series"] if p["consumption_wh"]]
    assert 1500.0 in values


async def test_history_invalid_period_422(client):
    async with client as c:
        resp = await c.get("/api/energy/history?period=decade")
    assert resp.status_code == 422


async def test_history_count_out_of_range_422(client):
    async with client as c:
        resp = await c.get("/api/energy/history?period=day&count=0")
    assert resp.status_code == 422


# ── Stats endpoint ────────────────────────────────────────────────────────────
async def test_stats_empty_shape(client):
    async with client as c:
        resp = await c.get("/api/energy/stats")
    assert resp.status_code == 200
    body = resp.json()
    for key in (
        "month_start",
        "days_elapsed",
        "total_kwh",
        "avg_daily_kwh",
        "peak_daily_kwh",
        "peak_power_w",
    ):
        assert key in body
    assert body["total_kwh"] is None


# ── Alerts endpoint ───────────────────────────────────────────────────────────
async def test_alerts_empty(client):
    async with client as c:
        resp = await c.get("/api/energy/alerts")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 0
    assert body["alerts"] == []


async def test_alerts_returns_recorded(client):
    main.collector.store.record_alert("daily_budget", "warning", "fired", value=25.0)
    async with client as c:
        resp = await c.get("/api/energy/alerts?limit=10")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["alerts"][0]["rule_key"] == "daily_budget"


# ── Channel validation ────────────────────────────────────────────────────────
async def test_history_channel_too_long_422(client):
    async with client as c:
        resp = await c.get(f"/api/energy/history?channel={'x' * 100}")
    assert resp.status_code == 422
    assert "64 characters" in resp.json()["detail"]


async def test_history_channel_invalid_chars_422(client):
    async with client as c:
        resp = await c.get("/api/energy/history?channel=test;DROP TABLE")
    assert resp.status_code == 422
    assert "alphanumeric" in resp.json()["detail"]


async def test_history_channel_valid_special_chars(client):
    async with client as c:
        resp = await c.get("/api/energy/history?channel=device_1:ch-0")
    assert resp.status_code == 200
    body = resp.json()
    assert body["channel"] == "device_1:ch-0"


async def test_history_empty_channel_treated_as_none(client):
    async with client as c:
        resp = await c.get("/api/energy/history?channel=")
    assert resp.status_code == 200
    body = resp.json()
    assert body["channel"] is None


async def test_history_whitespace_channel_treated_as_none(client):
    async with client as c:
        resp = await c.get("/api/energy/history?channel=   ")
    assert resp.status_code == 200
    body = resp.json()
    assert body["channel"] is None


# ── Security headers ──────────────────────────────────────────────────────────
async def test_security_headers_present(client):
    """Verify that security headers are added to all responses."""
    async with client as c:
        resp = await c.get("/health")
    assert resp.status_code == 200
    # Check all required security headers
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert resp.headers.get("Content-Security-Policy") == "default-src 'self'"
    assert resp.headers.get("X-XSS-Protection") == "1; mode=block"
    assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"


async def test_security_headers_on_api_endpoints(client):
    """Verify security headers on API endpoints, not just health."""
    async with client as c:
        resp = await c.get("/api/energy/current")
    assert resp.status_code == 200
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"


async def test_security_headers_on_error_responses(client):
    """Verify security headers are present even on error responses."""
    async with client as c:
        resp = await c.get("/api/energy/history?period=invalid")
    assert resp.status_code == 422
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"
