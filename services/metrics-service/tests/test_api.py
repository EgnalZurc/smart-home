"""Integration tests for the metrics-service HTTP API.

These exercise the FastAPI routes directly against the in-process app using
``httpx.ASGITransport`` WITHOUT triggering the lifespan (so the real collector
background tasks are not started). The module-level ``collector`` singleton's
ring buffer / store are populated manually per test.
"""

from __future__ import annotations

import time

import httpx
import main
import pytest
from alert_store import AlertStore
from alerts import AlertEngine
from sqlite_store import SqliteStore
from storage import RingBuffer


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Swap the module-level collector's storage for test-local instances so
    # tests do not touch the production DB path or share ring state.
    ring = RingBuffer(maxlen=240)
    monkeypatch.setattr(main.collector, "ring", ring)
    monkeypatch.setattr(main.collector, "store", SqliteStore(str(tmp_path / "m.db")))
    # Fresh alert engine on a temp store so alert endpoints are isolated too.
    engine = AlertEngine(ring, AlertStore(str(tmp_path / "m.db")))
    engine.load_state()
    monkeypatch.setattr(main.collector, "alert_engine", engine)
    monkeypatch.setattr(main.collector, "last_tick_ts", time.monotonic())
    transport = httpx.ASGITransport(app=main.app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_health_reports_db_ok_and_tick_age(client):
    async with client as c:
        resp = await c.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["online"] is True
    assert body["service"] == "metrics-service"
    assert body["db_ok"] is True
    assert body["collector_last_tick_age_s"] is not None


async def test_health_alias_matches(client):
    async with client as c:
        resp = await c.get("/api/health/metrics")
    assert resp.status_code == 200
    assert resp.json()["service"] == "metrics-service"


async def test_health_db_ok_false_when_store_broken(client, monkeypatch):
    class BrokenStore:
        def count(self):
            raise RuntimeError("db gone")

    monkeypatch.setattr(main.collector, "store", BrokenStore())
    async with client as c:
        resp = await c.get("/health")
    assert resp.json()["db_ok"] is False


async def test_latest_returns_ring_contents(client):
    main.collector.ring.add("host.ram.percent", "", 61.2, ts=1000)
    async with client as c:
        resp = await c.get("/api/metrics/latest")
    assert resp.status_code == 200
    series = resp.json()["series"]
    assert series["host.ram.percent|"]["value"] == 61.2


async def test_series_hi_from_ring(client):
    for i in range(3):
        main.collector.ring.add("host.cpu.percent", "", float(i), ts=100 + i)
    async with client as c:
        resp = await c.get(
            "/api/metrics/series",
            params={"metric": "host.cpu.percent", "resolution": "hi"},
        )
    body = resp.json()
    assert body["resolution"] == "hi"
    assert body["points"] == [
        {"ts": 100, "value": 0.0},
        {"ts": 101, "value": 1.0},
        {"ts": 102, "value": 2.0},
    ]


async def test_series_rollup_from_sqlite(client):
    main.collector.store.write_rollup(5000, [("host.ram.percent", "", 60.0, 72.0)])
    async with client as c:
        resp = await c.get(
            "/api/metrics/series",
            params={"metric": "host.ram.percent", "resolution": "rollup"},
        )
    body = resp.json()
    assert body["resolution"] == "rollup"
    assert body["points"][0]["ts"] == 5000
    assert body["points"][0]["value"] == 60.0
    assert body["points"][0]["value_max"] == 72.0


async def test_series_relative_since(client):
    now = int(time.time())
    main.collector.ring.add("m", "", 1.0, ts=now - 7200)  # 2h ago (excluded)
    main.collector.ring.add("m", "", 2.0, ts=now - 60)  # 1m ago (included)
    async with client as c:
        resp = await c.get(
            "/api/metrics/series",
            params={"metric": "m", "since": "-1h"},
        )
    pts = resp.json()["points"]
    assert [p["value"] for p in pts] == [2.0]


async def test_series_invalid_since_returns_400(client):
    async with client as c:
        resp = await c.get(
            "/api/metrics/series", params={"metric": "m", "since": "-5x"}
        )
    assert resp.status_code == 400


async def test_series_invalid_resolution_rejected(client):
    async with client as c:
        resp = await c.get(
            "/api/metrics/series", params={"metric": "m", "resolution": "weekly"}
        )
    assert resp.status_code == 422


async def test_summary_aggregates(client):
    now = int(time.time())
    main.collector.store.write_rollup(now - 100, [("host.ram.percent", "", 60.0, 70.0)])
    main.collector.store.write_rollup(now - 50, [("host.ram.percent", "", 80.0, 90.0)])
    async with client as c:
        resp = await c.get("/api/metrics/summary", params={"window": "24h"})
    body = resp.json()
    assert body["window"] == "24h"
    row = next(r for r in body["metrics"] if r["metric"] == "host.ram.percent")
    assert row["min"] == 60.0
    assert row["avg"] == 70.0
    assert row["max"] == 90.0


async def test_summary_invalid_window_rejected(client):
    async with client as c:
        resp = await c.get("/api/metrics/summary", params={"window": "99y"})
    assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════════
# Alerts + thresholds endpoints (Wave 3.3)
# ═══════════════════════════════════════════════════════════════════════════════
async def test_alerts_endpoint_reports_active(client):
    # Drive one firing alert through the engine, then read it back via the API.
    main.collector.ring.add("host.disk.percent", "", 95.0, ts=1000)
    main.collector.alert_engine.evaluate_tick(now=1000)
    async with client as c:
        resp = await c.get("/api/metrics/alerts")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["active"]) == 1
    assert body["active"][0]["rule_key"] == "host_disk"


async def test_alerts_history_endpoint(client):
    # Use a near-now timestamp: the history endpoint filters by real wall-clock
    # (now - days), so an epoch-1970 ts would be pruned out of the window.
    now = int(time.time())
    main.collector.ring.add("host.disk.percent", "", 95.0, ts=now)
    main.collector.alert_engine.evaluate_tick(now=now)
    async with client as c:
        resp = await c.get("/api/metrics/alerts/history", params={"days": 30})
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] >= 1
    assert body["events"][0]["event"] == "fired"


async def test_alerts_history_rejects_out_of_range_days(client):
    async with client as c:
        resp = await c.get("/api/metrics/alerts/history", params={"days": 999})
    assert resp.status_code == 422


async def test_get_thresholds_endpoint(client):
    async with client as c:
        resp = await c.get("/api/metrics/thresholds")
    assert resp.status_code == 200
    rules = resp.json()["thresholds"]
    assert any(r["key"] == "host_ram" for r in rules)


async def test_put_thresholds_updates_value(client):
    async with client as c:
        resp = await c.put(
            "/api/metrics/thresholds",
            json={"updates": {"host_disk": {"value": 42.0}}},
        )
    assert resp.status_code == 200
    rule = next(r for r in resp.json()["thresholds"] if r["key"] == "host_disk")
    assert rule["value"] == 42.0


async def test_put_thresholds_unknown_key_returns_400(client):
    async with client as c:
        resp = await c.put(
            "/api/metrics/thresholds",
            json={"updates": {"ghost": {"value": 1}}},
        )
    assert resp.status_code == 400


# ═══════════════════════════════════════════════════════════════════════════════
# Input validation tests (M-7)
# ═══════════════════════════════════════════════════════════════════════════════
async def test_series_rejects_invalid_label(client):
    """Invalid container/label names should be rejected (M-7)."""
    async with client as c:
        # SQL injection attempt
        resp = await c.get(
            "/api/metrics/series",
            params={"metric": "host.cpu.percent", "label": "'; DROP TABLE--"},
        )
    assert resp.status_code == 400
    assert "Invalid label" in resp.json()["detail"]


async def test_series_rejects_too_long_label(client):
    """Label exceeding 64 chars should be rejected."""
    async with client as c:
        resp = await c.get(
            "/api/metrics/series",
            params={"metric": "host.cpu.percent", "label": "a" * 65},
        )
    assert resp.status_code == 400


async def test_series_accepts_valid_label(client):
    """Valid container names should pass validation."""
    main.collector.ring.add("host.cpu.percent", "my-container_1", 42.0, ts=1000)
    async with client as c:
        resp = await c.get(
            "/api/metrics/series",
            params={"metric": "host.cpu.percent", "label": "my-container_1"},
        )
    assert resp.status_code == 200


async def test_series_rejects_invalid_metric(client):
    """Invalid metric names should be rejected."""
    async with client as c:
        resp = await c.get(
            "/api/metrics/series",
            params={"metric": "metric<script>alert(1)</script>"},
        )
    assert resp.status_code == 400
    assert "Invalid metric" in resp.json()["detail"]


async def test_series_rejects_too_long_metric(client):
    """Metric exceeding 128 chars should be rejected."""
    async with client as c:
        resp = await c.get(
            "/api/metrics/series",
            params={"metric": "m" * 129},
        )
    assert resp.status_code == 400


# ═══════════════════════════════════════════════════════════════════════════════
# Rate limiting tests (M-8)
# ═══════════════════════════════════════════════════════════════════════════════
async def test_rate_limit_allows_under_threshold(client, monkeypatch):
    """Requests under the rate limit should succeed (M-8)."""
    # Clear rate limit state
    main.rate_limiter._data.clear()
    async with client as c:
        for _ in range(5):
            resp = await c.get("/api/metrics/latest")
            assert resp.status_code == 200


async def test_rate_limit_blocks_over_threshold(client, monkeypatch):
    """Requests exceeding rate limit should get 429 (M-8)."""
    # Use X-Forwarded-For to have a known, consistent IP for the test
    from datetime import datetime

    main.rate_limiter._data.clear()
    # Pre-fill the rate limiter to exceed the limit
    main.rate_limiter._data["192.168.1.100"] = {
        "count": 60,  # Exceeds MAX_REQUESTS_PER_MINUTE
        "window_start": datetime.now(),
    }

    async with client as c:
        resp = await c.get(
            "/api/metrics/latest",
            headers={"X-Forwarded-For": "192.168.1.100"},
        )
    assert resp.status_code == 429
    assert "Rate limit" in resp.json()["detail"]


async def test_rate_limit_skips_health_endpoints(client, monkeypatch):
    """Health endpoints should bypass rate limiting."""
    from datetime import datetime

    main.rate_limiter._data.clear()
    # Pre-fill rate limiter to exceed limit
    main.rate_limiter._data["unknown"] = {
        "count": 100,
        "window_start": datetime.now(),
    }

    async with client as c:
        resp = await c.get("/health")
        assert resp.status_code == 200
        resp = await c.get("/api/health/metrics")
        assert resp.status_code == 200


async def test_rate_limit_respects_x_forwarded_for(client, monkeypatch):
    """Rate limiting should use X-Forwarded-For header when present."""
    from datetime import datetime

    main.rate_limiter._data.clear()
    # Fill bucket for the forwarded IP
    main.rate_limiter._data["10.0.0.1"] = {
        "count": 60,
        "window_start": datetime.now(),
    }

    async with client as c:
        resp = await c.get(
            "/api/metrics/latest",
            headers={"X-Forwarded-For": "10.0.0.1, 172.18.0.1"},
        )
    assert resp.status_code == 429


async def test_rate_limiter_reset_clears_key(client, monkeypatch):
    """reset() should clear rate limit for a specific key."""
    from datetime import datetime

    main.rate_limiter._data.clear()
    main.rate_limiter._data["test-ip"] = {
        "count": 50,
        "window_start": datetime.now(),
    }

    main.rate_limiter.reset("test-ip")

    assert "test-ip" not in main.rate_limiter._data



# ═══════════════════════════════════════════════════════════════════════════════
# Security headers tests (MEDIUM fixes)
# ═══════════════════════════════════════════════════════════════════════════════
async def test_security_headers_present(client):
    """All responses should include security headers."""
    async with client as c:
        resp = await c.get("/health")
    assert resp.status_code == 200
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert resp.headers.get("Content-Security-Policy") == "default-src 'self'"
    assert resp.headers.get("X-XSS-Protection") == "1; mode=block"
    assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"


async def test_security_headers_on_api_endpoints(client):
    """Security headers should be present on data endpoints too."""
    async with client as c:
        resp = await c.get("/api/metrics/latest")
    assert resp.status_code == 200
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"