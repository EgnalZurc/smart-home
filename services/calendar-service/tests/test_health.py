"""Tests for the calendar-service HTTP API scaffold.

These exercise the FastAPI routes directly against the in-process app using
``httpx.ASGITransport`` WITHOUT triggering the lifespan (so no background loops
run). The module-level ``store`` singleton is swapped for a temp-file store per
test so no test touches the production DB path.
"""

from __future__ import annotations

import httpx
import main
import pytest
from database import CalendarStore


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Swap the module-level store for a test-local one on a temp DB.
    monkeypatch.setattr(main, "store", CalendarStore(str(tmp_path / "calendar.db")))
    # Point the token path at a non-existent file so google_auth_ok is False by
    # default; individual tests override it to simulate an authorized service.
    monkeypatch.setattr(main, "TOKEN_PATH", str(tmp_path / "token.json"))
    transport = httpx.ASGITransport(app=main.app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_health_reports_db_ok(client):
    async with client as c:
        resp = await c.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["online"] is True
    assert body["service"] == "calendar-service"
    assert body["db_ok"] is True


async def test_health_alias_matches(client):
    async with client as c:
        resp = await c.get("/api/health/calendar")
    assert resp.status_code == 200
    body = resp.json()
    assert body["service"] == "calendar-service"
    assert body["db_ok"] is True


async def test_health_reports_loop_liveness_fields(client):
    async with client as c:
        resp = await c.get("/health")
    body = resp.json()
    # No sync / tick has run yet in the scaffold → honestly reported as null.
    assert body["last_sync_ok"] is None
    assert body["last_sync_age_s"] is None
    assert body["reminder_tick_age_s"] is None


async def test_health_google_auth_false_without_token(client):
    async with client as c:
        resp = await c.get("/health")
    assert resp.json()["google_auth_ok"] is False


async def test_health_google_auth_true_with_token(client, tmp_path, monkeypatch):
    # google_auth_ok is now based on google_client being not None
    monkeypatch.setattr(main, "google_client", object())  # Mock a truthy client
    async with client as c:
        resp = await c.get("/health")
    assert resp.json()["google_auth_ok"] is True


async def test_health_db_ok_false_when_store_broken(client, monkeypatch):
    class BrokenStore:
        def count(self):
            raise RuntimeError("db gone")

    monkeypatch.setattr(main, "store", BrokenStore())
    async with client as c:
        resp = await c.get("/health")
    assert resp.json()["db_ok"] is False


async def test_upcoming_empty_on_fresh_store(client):
    async with client as c:
        resp = await c.get("/api/calendar/upcoming")
    assert resp.status_code == 200
    body = resp.json()
    assert body["events"] == []
    assert "ts" in body


async def test_upcoming_returns_cached_events_ordered(client):
    import time

    # Use timestamps comfortably in the future so the endpoint's real-clock
    # ``start_ts >= now`` filter keeps both events regardless of when the test runs.
    base = int(time.time()) + 86400
    main.store.upsert_event(
        {
            "uid": "fam:b:200",
            "calendar_id": "fam@g",
            "google_id": "b",
            "title": "Later",
            "start_ts": base + 7200,
            "end_ts": base + 10800,
            "updated_ts": base,
        }
    )
    main.store.upsert_event(
        {
            "uid": "fam:a:100",
            "calendar_id": "fam@g",
            "google_id": "a",
            "title": "Sooner",
            "start_ts": base + 3600,
            "end_ts": base + 7200,
            "updated_ts": base,
        }
    )
    async with client as c:
        resp = await c.get("/api/calendar/upcoming", params={"limit": 5})
    titles = [e["title"] for e in resp.json()["events"]]
    assert titles == ["Sooner", "Later"]


async def test_upcoming_limit_validation(client):
    async with client as c:
        resp = await c.get("/api/calendar/upcoming", params={"limit": 999})
    assert resp.status_code == 422


async def test_today_endpoint_responds(client):
    async with client as c:
        resp = await c.get("/api/calendar/today")
    assert resp.status_code == 200
    assert "events" in resp.json()


def test_store_prune_removes_old_rows(tmp_path):
    store = CalendarStore(str(tmp_path / "p.db"))
    now = 1_760_000_000
    # An event that ended well beyond the retention window.
    store.upsert_event(
        {
            "uid": "old:1",
            "calendar_id": "c",
            "google_id": "g",
            "title": "Old",
            "start_ts": now - 40 * 86400,
            "end_ts": now - 39 * 86400,
            "updated_ts": now - 39 * 86400,
        }
    )
    deleted = store.prune(now=now)
    assert deleted["events"] == 1
    assert store.count() == 0
