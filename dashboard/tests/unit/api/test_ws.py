"""Tests for the real-time health WebSocket (api.ws).

Covers both layers:
* The ``ConnectionManager`` logic directly (connect/disconnect bookkeeping,
  the shared broadcast loop lifecycle, dead-client pruning, message format).
* The ``/api/ws/health`` endpoint end-to-end via Starlette's TestClient
  (initial snapshot on connect, broadcast message shape, clean disconnect).

``api.health.get_all_health`` is patched throughout so no real HTTP requests
to backend services are issued.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.ws as ws


# The root conftest's autouse mock_require_super fixture patches proxy modules
# that aren't relevant here (and can fail under import isolation). This file
# exercises the WebSocket layer only, so override it with a no-op.
@pytest.fixture(autouse=True)
def mock_require_super():
    """No-op override of the root authorization fixture."""
    yield


SAMPLE_HEALTH = {
    "ac": {"online": True, "latency_ms": 12},
    "casita": {"online": False, "error": "Timeout"},
    "valheim": {"online": True},
}


@pytest.fixture
def app():
    """Minimal app mounting just the WebSocket router."""
    application = FastAPI()
    application.include_router(ws.router)
    return application


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture(autouse=True)
def fresh_manager():
    """Give each test a clean ConnectionManager singleton.

    The module exposes a process-wide ``manager``; reset it so broadcast tasks
    and client sets don't leak between tests.
    """
    ws.manager = ws.ConnectionManager()
    yield
    # Best-effort: cancel any lingering broadcast task.
    task = ws.manager._broadcast_task
    if task is not None:
        task.cancel()


# ── ConnectionManager unit tests ───────────────────────────────────────────────


class _FakeWebSocket:
    """Minimal WebSocket stand-in recording sent JSON payloads."""

    def __init__(self, *, fail_on_send: bool = False):
        self.accepted = False
        self.closed = False
        self.sent: list[dict] = []
        self.fail_on_send = fail_on_send

    async def accept(self):
        self.accepted = True

    async def send_json(self, data):
        if self.fail_on_send:
            raise RuntimeError("client gone")
        self.sent.append(data)

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_connect_accepts_and_sends_initial_snapshot():
    manager = ws.ConnectionManager()
    sock = _FakeWebSocket()

    with patch.object(ws, "get_all_health", AsyncMock(return_value=SAMPLE_HEALTH)):
        await manager.connect(sock)

    assert sock.accepted is True
    assert manager.client_count == 1
    # The first (and only) message is the current snapshot in standard shape.
    assert sock.sent == [{"type": "health", "data": SAMPLE_HEALTH}]

    await manager.disconnect(sock)


@pytest.mark.asyncio
async def test_connect_starts_broadcast_task_disconnect_stops_it():
    manager = ws.ConnectionManager()
    sock = _FakeWebSocket()

    with patch.object(ws, "get_all_health", AsyncMock(return_value=SAMPLE_HEALTH)):
        await manager.connect(sock)
        # A single shared broadcast loop is now running.
        assert manager._broadcast_task is not None
        assert not manager._broadcast_task.done()

        await manager.disconnect(sock)

    # Last client gone -> loop cancelled, bookkeeping cleared.
    assert manager.client_count == 0
    assert manager._broadcast_task is None


@pytest.mark.asyncio
async def test_broadcast_fans_out_to_all_clients():
    manager = ws.ConnectionManager()
    a, b = _FakeWebSocket(), _FakeWebSocket()

    with patch.object(ws, "get_all_health", AsyncMock(return_value=SAMPLE_HEALTH)):
        await manager.connect(a)
        await manager.connect(b)

    # Clear the initial-snapshot messages from connect().
    a.sent.clear()
    b.sent.clear()

    message = {"type": "health", "data": SAMPLE_HEALTH}
    await manager.broadcast(message)

    assert a.sent == [message]
    assert b.sent == [message]

    await manager.disconnect(a)
    await manager.disconnect(b)


@pytest.mark.asyncio
async def test_broadcast_prunes_dead_clients():
    manager = ws.ConnectionManager()
    good = _FakeWebSocket()
    bad = _FakeWebSocket(fail_on_send=True)

    with patch.object(ws, "get_all_health", AsyncMock(return_value=SAMPLE_HEALTH)):
        # Connect the good client normally; the initial snapshot send succeeds.
        await manager.connect(good)
        # Inject the failing client directly so connect()'s initial send doesn't
        # prune it before we test broadcast pruning.
        manager._clients.add(bad)

    good.sent.clear()
    await manager.broadcast({"type": "health", "data": {}})

    # The failing client was removed; the healthy one stayed and got the message.
    assert bad not in manager._clients
    assert good in manager._clients
    assert good.sent == [{"type": "health", "data": {}}]

    await manager.disconnect(good)


@pytest.mark.asyncio
async def test_build_message_format():
    manager = ws.ConnectionManager()
    with patch.object(ws, "get_all_health", AsyncMock(return_value=SAMPLE_HEALTH)):
        msg = await manager._build_message()

    assert msg == {"type": "health", "data": SAMPLE_HEALTH}


@pytest.mark.asyncio
async def test_disconnect_unknown_client_is_safe():
    """Disconnecting a client that was never tracked must not raise."""
    manager = ws.ConnectionManager()
    stray = _FakeWebSocket()
    # Should be a no-op, not a KeyError.
    await manager.disconnect(stray)
    assert manager.client_count == 0


# ── Endpoint tests via TestClient ──────────────────────────────────────────────


def test_websocket_connect_receives_initial_snapshot(client):
    with patch.object(ws, "get_all_health", AsyncMock(return_value=SAMPLE_HEALTH)):
        with client.websocket_connect("/api/ws/health") as websocket:
            msg = websocket.receive_json()
            assert msg["type"] == "health"
            assert msg["data"] == SAMPLE_HEALTH


def test_websocket_message_has_expected_shape(client):
    with patch.object(ws, "get_all_health", AsyncMock(return_value=SAMPLE_HEALTH)):
        with client.websocket_connect("/api/ws/health") as websocket:
            msg = websocket.receive_json()
            # Contract the frontend relies on: a 'type' discriminator and a
            # 'data' map of service-key -> health dict.
            assert set(msg.keys()) == {"type", "data"}
            assert isinstance(msg["data"], dict)
            assert msg["data"]["ac"]["online"] is True


def test_websocket_disconnect_is_handled(client):
    """Closing the socket must drop the client and stop the broadcast loop."""
    with patch.object(ws, "get_all_health", AsyncMock(return_value=SAMPLE_HEALTH)):
        with client.websocket_connect("/api/ws/health") as websocket:
            websocket.receive_json()  # initial snapshot
            assert ws.manager.client_count == 1
        # Context manager exit closes the socket; the server-side handler runs
        # manager.disconnect(), clearing the client and the broadcast task.
        assert ws.manager.client_count == 0
        assert ws.manager._broadcast_task is None


def test_multiple_clients_tracked_independently(client):
    with patch.object(ws, "get_all_health", AsyncMock(return_value=SAMPLE_HEALTH)):
        with client.websocket_connect("/api/ws/health") as w1:
            w1.receive_json()
            assert ws.manager.client_count == 1
            with client.websocket_connect("/api/ws/health") as w2:
                w2.receive_json()
                assert ws.manager.client_count == 2
            # w2 closed -> back to one client, loop still running.
            assert ws.manager.client_count == 1
            assert ws.manager._broadcast_task is not None
        assert ws.manager.client_count == 0
