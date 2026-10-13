"""Unit tests for the collector: docker/health parsing, rollup, and tick."""

from __future__ import annotations

import httpx
import pytest
from collector import (
    Collector,
    parse_container_stats,
    parse_health,
    sample_docker,
    sample_health,
)
from sqlite_store import SqliteStore
from storage import RingBuffer


# ── Docker stats parsing ──────────────────────────────────────────────────────
def _docker_stats(
    usage,
    limit,
    cache=0,
    cpu_total=200,
    precpu_total=100,
    sys_cpu=2000,
    presys_cpu=1000,
    online=4,
):
    return {
        "memory_stats": {
            "usage": usage,
            "limit": limit,
            "stats": {"inactive_file": cache},
        },
        "cpu_stats": {
            "cpu_usage": {"total_usage": cpu_total},
            "system_cpu_usage": sys_cpu,
            "online_cpus": online,
        },
        "precpu_stats": {
            "cpu_usage": {"total_usage": precpu_total},
            "system_cpu_usage": presys_cpu,
        },
    }


def test_parse_container_stats_mem_and_cpu():
    stats = _docker_stats(usage=100 * 1024 * 1024, limit=200 * 1024 * 1024, cache=0)
    out = dict((m, v) for (m, _lbl, v) in parse_container_stats("svc", stats))
    assert out["container.mem.used_mb"] == 100.0
    assert out["container.mem.percent"] == 50.0
    # cpu_delta=100, sys_delta=1000 -> (100/1000)*4*100 = 40%
    assert out["container.cpu.percent"] == 40.0


def test_parse_container_stats_subtracts_cache():
    stats = _docker_stats(
        usage=100 * 1024 * 1024, limit=200 * 1024 * 1024, cache=40 * 1024 * 1024
    )
    out = dict((m, v) for (m, _lbl, v) in parse_container_stats("svc", stats))
    assert out["container.mem.used_mb"] == 60.0
    assert out["container.mem.percent"] == 30.0


def test_parse_container_stats_handles_missing_cpu_fields():
    stats = {"memory_stats": {"usage": 1024 * 1024, "limit": 2 * 1024 * 1024}}
    out = dict((m, v) for (m, _lbl, v) in parse_container_stats("svc", stats))
    assert out["container.cpu.percent"] == 0.0


# ── Health parsing (discard cached) ───────────────────────────────────────────
def test_parse_health_online_and_latency():
    payload = {
        "ac": {"online": True, "latency_ms": 180, "cached": False},
        "casita": {"online": False, "latency_ms": 50, "cached": False},
    }
    out = {(m, lbl): v for (m, lbl, v) in parse_health(payload)}
    assert out[("service.ac.online", "ac")] == 1.0
    assert out[("service.ac.latency_ms", "ac")] == 180.0
    assert out[("service.casita.online", "casita")] == 0.0
    assert out[("service.casita.latency_ms", "casita")] == 50.0


def test_parse_health_discards_cached_latency():
    """CRITICAL: cached entries must not contribute a latency sample."""
    payload = {"ac": {"online": True, "latency_ms": 0, "cached": True}}
    samples = parse_health(payload)
    metrics = {m for (m, _lbl, _v) in samples}
    # online is still recorded, but latency is discarded for cached echoes.
    assert "service.ac.online" in metrics
    assert "service.ac.latency_ms" not in metrics


def test_parse_health_ignores_non_dict_entries():
    payload = {"ac": "oops", "ts": 123}
    assert parse_health(payload) == []


# ── Async samplers with mocked httpx ──────────────────────────────────────────
async def test_sample_docker_with_mock_transport():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/containers/json":
            return httpx.Response(200, json=[{"Id": "abc123", "Names": ["/svc"]}])
        if request.url.path == "/containers/abc123/stats":
            return httpx.Response(
                200,
                json=_docker_stats(50 * 1024 * 1024, 100 * 1024 * 1024),
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        samples = await sample_docker(client, proxy_url="http://proxy")
    out = {(m, lbl): v for (m, lbl, v) in samples}
    assert out[("container.mem.percent", "svc")] == 50.0


async def test_sample_docker_list_failure_returns_empty():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        assert await sample_docker(client, proxy_url="http://proxy") == []


async def test_sample_health_with_mock_transport():
    payload = {"ac": {"online": True, "latency_ms": 120, "cached": False}}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        samples = await sample_health(client, url="http://backend/api/health/all")
    out = {(m, lbl): v for (m, lbl, v) in samples}
    assert out[("service.ac.latency_ms", "ac")] == 120.0


async def test_sample_health_failure_returns_empty():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        assert await sample_health(client, url="http://backend/x") == []


# ── Rollup ────────────────────────────────────────────────────────────────────
@pytest.fixture
def collector(tmp_path):
    return Collector(
        ring=RingBuffer(maxlen=240), store=SqliteStore(str(tmp_path / "m.db"))
    )


def test_rollup_averages_window_into_sqlite(collector):
    # ROLLUP_INTERVAL_S defaults to 300. Put samples in the previous window.
    bucket = (6000 // 300) * 300  # 6000
    start = bucket - 300  # 5700
    for i, val in enumerate((10.0, 20.0, 60.0)):
        collector.ring.add("host.ram.percent", "", val, ts=start + i)
    written = collector.rollup(now=bucket)
    assert written == 1
    rows = collector.store.series("host.ram.percent")
    assert rows[0]["ts"] == start
    assert rows[0]["value"] == 30.0  # avg of 10,20,60
    assert rows[0]["value_max"] == 60.0


def test_rollup_empty_window_writes_nothing(collector):
    assert collector.rollup(now=600000) == 0


async def test_tick_populates_ring_without_client(collector, monkeypatch):
    # No HTTP client set -> only host samples. Stub host sampler to be fast.
    import collector as collector_mod

    monkeypatch.setattr(
        collector_mod,
        "sample_host",
        lambda: [("host.ram.percent", "", 55.0)],
    )
    collector._client = None
    samples = await collector.tick()
    assert ("host.ram.percent", "", 55.0) in samples
    assert collector.last_tick_age_s() is not None
    assert collector.ring.series("host.ram.percent")[-1][1] == 55.0


def test_last_tick_age_none_before_first_tick(collector):
    assert collector.last_tick_ts is None
    assert collector.last_tick_age_s() is None


async def test_tick_gathers_docker_and_health_with_client(collector, monkeypatch):
    import collector as collector_mod

    monkeypatch.setattr(
        collector_mod, "sample_host", lambda: [("host.cpu.percent", "", 1.0)]
    )

    async def fake_docker(_client, **_kw):
        return [("container.mem.percent", "svc", 42.0)]

    async def fake_health(_client, **_kw):
        return [("service.ac.online", "ac", 1.0)]

    monkeypatch.setattr(collector_mod, "sample_docker", fake_docker)
    monkeypatch.setattr(collector_mod, "sample_health", fake_health)

    collector._client = object()  # truthy; samplers are stubbed so it is unused
    samples = await collector.tick()
    metrics = {m for (m, _lbl, _v) in samples}
    assert {"host.cpu.percent", "container.mem.percent", "service.ac.online"} <= metrics


async def test_start_and_stop_lifecycle(collector, monkeypatch):
    # Make ticks a no-op so the loop spins harmlessly, then ensure stop() cancels.
    async def fast_tick():
        return []

    monkeypatch.setattr(collector, "tick", fast_tick)
    await collector.start()
    assert len(collector._tasks) == 3
    assert collector._client is not None
    await collector.stop()
    assert collector._tasks == []
    assert collector._client is None
