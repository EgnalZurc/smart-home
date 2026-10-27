"""Unit tests for the energy-monitor collector (collector.py).

Shelly devices are replaced by ``FakeClient`` instances returning canned
``get_status`` payloads, so the collector logic (ring buffer, rollup, energy
snapshot, current) is tested without hardware or HTTP.
"""

from __future__ import annotations

import pytest
from collector import Collector, parse_devices
from database import EnergyStore


class FakeClient:
    """Stand-in for ShellyEMClient returning a fixed status."""

    def __init__(self, device_id: str, status: dict) -> None:
        self.device_id = device_id
        self._status = status
        self.closed = False

    async def get_status(self) -> dict:
        return self._status

    async def aclose(self) -> None:
        self.closed = True


def _status(device_id, power, energy, online=True):
    return {
        "device_id": device_id,
        "gen": 1,
        "online": online,
        "power": power,
        "energy": energy,
    }


@pytest.fixture
def store(tmp_path):
    return EnergyStore(str(tmp_path / "energy.db"))


# ── parse_devices ─────────────────────────────────────────────────────────────
def test_parse_devices_valid():
    raw = (
        '[{"id":"main","ip":"192.168.1.50","gen":1,'
        '"channels":{"ch0":"General","ch1":"AC"}}]'
    )
    devices = parse_devices(raw)
    assert len(devices) == 1
    assert devices[0]["id"] == "main"
    assert devices[0]["gen"] == 1
    assert devices[0]["channels"] == {"ch0": "General", "ch1": "AC"}


def test_parse_devices_defaults_gen_and_channels():
    devices = parse_devices('[{"id":"d","ip":"1.2.3.4"}]')
    assert devices[0]["gen"] == 1
    assert devices[0]["channels"] == {}


def test_parse_devices_skips_malformed_entries():
    raw = '[{"ip":"1.2.3.4"}, {"id":"ok","ip":"5.6.7.8"}, "garbage", 42]'
    devices = parse_devices(raw)
    assert [d["id"] for d in devices] == ["ok"]


def test_parse_devices_invalid_json():
    assert parse_devices("not json") == []
    assert parse_devices("") == []


def test_parse_devices_not_a_list():
    assert parse_devices('{"id":"x","ip":"y"}') == []


# ── tick ──────────────────────────────────────────────────────────────────────
async def test_tick_fills_ring_and_marks_online(store):
    col = Collector(store=store, devices=[])
    col.clients = {
        "main": FakeClient(
            "main",
            _status(
                "main",
                {
                    "ch0": {"power": 1200.0, "voltage": 230.0, "pf": 0.95},
                    "ch1": {"power": 300.0, "voltage": 230.0, "pf": 0.9},
                },
                {"ch0": 500000.0, "ch1": 10000.0},
            ),
        )
    }
    seen = await col.tick()
    assert seen == 2
    assert col.meter_online is True
    assert col.last_tick_age_s() is not None
    assert len(col.ring["main:ch0"]) == 1
    assert col.latest_energy["main:ch0"] == 500000.0


async def test_tick_offline_device_not_recorded(store):
    col = Collector(store=store, devices=[])
    col.clients = {"x": FakeClient("x", _status("x", {}, {}, online=False))}
    seen = await col.tick()
    assert seen == 0
    assert col.meter_online is False
    assert "x:ch0" not in col.ring


async def test_tick_no_clients_is_noop(store):
    col = Collector(store=store, devices=[])
    assert await col.tick() == 0
    assert col.meter_online is None
    assert col.last_tick_age_s() is not None


async def test_tick_tolerates_client_exception(store):
    class Boom:
        device_id = "boom"

        async def get_status(self):
            raise RuntimeError("device blew up")

    col = Collector(store=store, devices=[])
    col.clients = {"boom": Boom()}
    seen = await col.tick()  # must not raise
    assert seen == 0
    assert col.meter_online is False


async def test_tick_skips_channel_with_none_power(store):
    col = Collector(store=store, devices=[])
    col.clients = {
        "d": FakeClient(
            "d",
            _status("d", {"ch0": {"power": None, "voltage": 230.0, "pf": 0.9}}, {}),
        )
    }
    seen = await col.tick()
    assert seen == 0
    assert "d:ch0" not in col.ring


# ── rollup ──────────────────────────────────────────────────────────────────
def test_rollup_averages_window(store):
    col = Collector(store=store, devices=[])
    # Three samples inside the previous 60-s bucket [60, 120).
    col.ring["d:ch0"].extend(
        [
            (60, 1000.0, 230.0, 0.9),
            (90, 2000.0, 232.0, 0.95),
            (119, 3000.0, 231.0, 0.92),
        ]
    )
    written = col.rollup(now=120)
    assert written == 1
    rows = store.power_series("d:ch0")
    assert len(rows) == 1
    assert rows[0]["ts"] == 60
    assert rows[0]["power_avg"] == 2000.0  # mean of 1000/2000/3000
    assert rows[0]["power_max"] == 3000.0
    assert rows[0]["voltage"] == pytest.approx(231.0)


def test_rollup_ignores_points_outside_window(store):
    col = Collector(store=store, devices=[])
    col.ring["d:ch0"].extend([(10, 500.0, None, None), (200, 999.0, None, None)])
    # Bucket for now=120 is [60, 120); neither point falls inside.
    assert col.rollup(now=120) == 0


def test_rollup_handles_missing_voltage_pf(store):
    col = Collector(store=store, devices=[])
    col.ring["d:ch0"].append((60, 800.0, None, None))
    assert col.rollup(now=120) == 1
    row = store.power_series("d:ch0")[0]
    assert row["voltage"] is None
    assert row["pf"] is None


# ── energy snapshot ───────────────────────────────────────────────────────────
def test_snapshot_energy_writes_counters(store):
    col = Collector(store=store, devices=[])
    col.latest_energy = {"d:ch0": 123456.0, "d:ch1": 789.0}
    written = col.snapshot_energy(now=3600)
    assert written == 2
    assert store.energy_series("d:ch0")[0]["energy_wh"] == 123456.0


def test_snapshot_energy_noop_when_empty(store):
    col = Collector(store=store, devices=[])
    assert col.snapshot_energy(now=3600) == 0


# ── current ───────────────────────────────────────────────────────────────────
def test_current_reports_latest_per_channel(store):
    col = Collector(store=store, devices=[])
    col.labels = {"d:ch0": "General"}
    col.ring["d:ch0"].extend([(10, 100.0, 230.0, 0.9), (20, 500.0, 231.0, 0.95)])
    col.ring["d:ch1"].append((20, 250.0, 230.0, 0.9))
    col.meter_online = True
    out = col.current()
    assert out["total_w"] == pytest.approx(750.0)  # 500 + 250 (latest each)
    assert out["channels"]["d:ch0"]["power"] == 500.0
    assert out["channels"]["d:ch0"]["label"] == "General"
    assert out["channels"]["d:ch1"]["label"] == "d:ch1"
    assert out["meter_online"] is True


def test_current_empty_when_no_samples(store):
    col = Collector(store=store, devices=[])
    out = col.current()
    assert out["channels"] == {}
    assert out["total_w"] == 0.0
    assert out["meter_online"] is None


# ── build_clients + start/stop ────────────────────────────────────────────────
async def test_start_builds_clients_and_labels(store, monkeypatch):
    devices = [
        {
            "id": "main",
            "ip": "1.2.3.4",
            "gen": 1,
            "channels": {"ch0": "General"},
            "username": None,
            "password": None,
        }
    ]
    col = Collector(store=store, devices=devices)
    await col.start()
    try:
        assert "main" in col.clients
        assert col.labels["main:ch0"] == "General"
        assert len(col._tasks) == 4
    finally:
        await col.stop()
    assert col._tasks == []


async def test_stop_closes_clients(store):
    col = Collector(store=store, devices=[])
    fake = FakeClient("d", _status("d", {}, {}))
    col.clients = {"d": fake}
    await col.start()
    await col.stop()
    assert fake.closed is True


# ══════════════════════════════════════════════════════════════════════════════
# Defensive branch coverage (LOW severity audit findings)
# ══════════════════════════════════════════════════════════════════════════════


async def test_stop_logs_client_close_failure(store, caplog):
    """LOW#4: Client close failure is logged but doesn't raise (collector.py:259-260)."""
    import logging

    import httpx

    class FailingCloseClient:
        device_id = "fail"

        async def get_status(self):
            return _status("fail", {}, {})

        async def aclose(self):
            raise httpx.HTTPError("connection reset")

    col = Collector(store=store, devices=[])
    col.clients = {"fail": FailingCloseClient()}
    await col.start()

    with caplog.at_level(logging.WARNING):
        await col.stop()  # Should not raise

    assert any("failed to close client" in r.message for r in caplog.records)
