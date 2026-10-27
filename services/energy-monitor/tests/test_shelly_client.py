"""Unit tests for the Shelly EM client (shelly_client.py).

Uses ``httpx.MockTransport`` to simulate Gen1 (flat ``/status``) and Gen2
(``/rpc/Shelly.GetStatus``) devices without any hardware. Covers the happy
paths, offline handling and malformed payloads.
"""

from __future__ import annotations

import httpx
import pytest
from shelly_client import GEN1, GEN2, ShellyEMClient, _as_float, _rpc_index

# ── Fixture payloads ─────────────────────────────────────────────────────────
GEN1_STATUS = {
    "emeters": [
        {"power": 1234.5, "voltage": 230.1, "pf": 0.95, "total": 500000.0},
        {"power": 600.0, "voltage": 229.8, "pf": 0.9, "total": 120000.0},
    ],
}

GEN2_STATUS_3PHASE = {
    "em:0": {
        "a_act_power": 1000.0,
        "a_voltage": 231.0,
        "a_pf": 0.98,
        "b_act_power": 500.0,
        "b_voltage": 230.5,
        "b_pf": 0.97,
        "c_act_power": 250.0,
        "c_voltage": 230.0,
        "c_pf": 0.95,
    },
    "emdata:0": {
        "a_total_act_energy": 111.0,
        "b_total_act_energy": 222.0,
        "c_total_act_energy": 333.0,
    },
}

GEN2_STATUS_EM1 = {
    "em1:0": {"act_power": 800.0, "voltage": 230.0, "pf": 0.99},
    "em1:1": {"act_power": 150.0, "voltage": 230.0, "pf": 0.88},
    "em1data:0": {"total_act_energy": 4000.0},
    "em1data:1": {"total_act_energy": 900.0},
}


def _mock_client(handler) -> httpx.AsyncClient:
    """Build an AsyncClient backed by a MockTransport running ``handler``."""
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ── Gen1 ──────────────────────────────────────────────────────────────────────
async def test_gen1_get_status_online():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/status"
        return httpx.Response(200, json=GEN1_STATUS)

    dev = ShellyEMClient(
        "main",
        "192.168.1.50",
        gen=GEN1,
        channels={"ch0": "General"},
        client=_mock_client(handler),
    )
    status = await dev.get_status()
    assert status["online"] is True
    assert status["gen"] == GEN1
    assert status["power"]["ch0"]["power"] == 1234.5
    assert status["power"]["ch0"]["voltage"] == 230.1
    assert status["power"]["ch1"]["power"] == 600.0
    assert status["energy"]["ch0"] == 500000.0
    assert status["energy"]["ch1"] == 120000.0


async def test_gen1_get_power_and_energy_helpers():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=GEN1_STATUS)

    dev = ShellyEMClient("m", "1.2.3.4", gen=GEN1, client=_mock_client(handler))
    power = await dev.get_power()
    energy = await dev.get_energy()
    assert power["ch0"]["pf"] == 0.95
    assert energy["ch1"] == 120000.0


async def test_gen1_malformed_payload_marks_offline():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"not_emeters": []})

    dev = ShellyEMClient("m", "1.2.3.4", gen=GEN1, client=_mock_client(handler))
    status = await dev.get_status()
    assert status["online"] is False
    assert status["power"] == {}
    assert status["energy"] == {}


# ── Gen2 ──────────────────────────────────────────────────────────────────────
async def test_gen2_3phase_get_status():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/rpc/Shelly.GetStatus"
        return httpx.Response(200, json=GEN2_STATUS_3PHASE)

    dev = ShellyEMClient("pro", "192.168.1.60", gen=GEN2, client=_mock_client(handler))
    status = await dev.get_status()
    assert status["online"] is True
    assert status["power"]["ch0"]["power"] == 1000.0
    assert status["power"]["ch1"]["power"] == 500.0
    assert status["power"]["ch2"]["power"] == 250.0
    assert status["power"]["ch2"]["pf"] == 0.95
    assert status["energy"]["ch0"] == 111.0
    assert status["energy"]["ch2"] == 333.0


async def test_gen2_em1_two_meters():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=GEN2_STATUS_EM1)

    dev = ShellyEMClient("proem", "1.2.3.4", gen=GEN2, client=_mock_client(handler))
    status = await dev.get_status()
    assert status["power"]["ch0"]["power"] == 800.0
    assert status["power"]["ch1"]["power"] == 150.0
    assert status["energy"]["ch0"] == 4000.0
    assert status["energy"]["ch1"] == 900.0


async def test_gen2_no_em_component_marks_offline():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"sys": {}, "wifi": {}})

    dev = ShellyEMClient("x", "1.2.3.4", gen=GEN2, client=_mock_client(handler))
    status = await dev.get_status()
    assert status["online"] is False


# ── Error handling ──────────────────────────────────────────────────────────
async def test_http_error_marks_offline():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    dev = ShellyEMClient("x", "1.2.3.4", gen=GEN1, client=_mock_client(handler))
    status = await dev.get_status()
    assert status["online"] is False


async def test_connect_error_marks_offline():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unreachable")

    dev = ShellyEMClient("x", "1.2.3.4", gen=GEN1, client=_mock_client(handler))
    status = await dev.get_status()
    assert status["online"] is False
    assert await dev.get_power() == {}


# ── Auth selection ────────────────────────────────────────────────────────────
def test_auth_scheme_per_generation():
    gen1 = ShellyEMClient("a", "ip", gen=GEN1, username="u", password="p")
    gen2 = ShellyEMClient("b", "ip", gen=GEN2, username="u", password="p")
    assert isinstance(gen1._auth, httpx.BasicAuth)
    assert isinstance(gen2._auth, httpx.DigestAuth)
    no_creds = ShellyEMClient("c", "ip", gen=GEN1)
    assert no_creds._auth is None


def test_base_url():
    dev = ShellyEMClient("a", "192.168.1.50")
    assert dev.base_url == "http://192.168.1.50"


# ── aclose lifecycle ──────────────────────────────────────────────────────────
async def test_aclose_only_closes_owned_client():
    shared = _mock_client(lambda r: httpx.Response(200, json=GEN1_STATUS))
    dev = ShellyEMClient("a", "ip", client=shared)
    await dev.aclose()  # must NOT close the injected shared client
    assert shared.is_closed is False
    await shared.aclose()

    owner = ShellyEMClient("b", "ip")  # owns a private client
    await owner.aclose()
    assert owner._client.is_closed is True


# ── Helpers ────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "value,expected",
    [(1.5, 1.5), ("2.5", 2.5), (3, 3.0), (None, None), ("x", None), ([], None)],
)
def test_as_float(value, expected):
    assert _as_float(value) == expected


@pytest.mark.parametrize(
    "key,expected",
    [("em1:0", 0), ("em1:2", 2), ("emdata:5", 5), ("bad", None), ("em1:x", None)],
)
def test_rpc_index(key, expected):
    assert _rpc_index(key) == expected
