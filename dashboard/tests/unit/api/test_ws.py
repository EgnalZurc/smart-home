"""Tests for the real-time health WebSocket (api.ws).

Covers both layers:
* The ``ConnectionManager`` logic directly (connect/disconnect bookkeeping,
  the shared broadcast loop lifecycle, dead-client pruning, message format).
* The ``/api/ws/health`` endpoint end-to-end via Starlette's TestClient
  (initial snapshot on connect, broadcast message shape, clean disconnect).
* **Authentication** (H-3 fix): WebSocket rejects unauthenticated connections
  with close code 4001.
* **Device token fallback**: When JWT auth fails, WebSocket accepts valid
  device tokens from recognized IPs.

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


@pytest.fixture
def mock_auth():
    """Bypass WebSocket authentication for non-auth-specific endpoint tests.

    The auth behavior is thoroughly tested in the dedicated auth tests below.
    Non-auth tests just need a valid session to exercise the data-push logic.
    """
    with patch.object(ws, "_validate_session", return_value="test_user"):
        yield


def test_websocket_connect_receives_initial_snapshot(client, mock_auth):
    with patch.object(ws, "get_all_health", AsyncMock(return_value=SAMPLE_HEALTH)):
        with client.websocket_connect("/api/ws/health") as websocket:
            msg = websocket.receive_json()
            assert msg["type"] == "health"
            assert msg["data"] == SAMPLE_HEALTH


def test_websocket_message_has_expected_shape(client, mock_auth):
    with patch.object(ws, "get_all_health", AsyncMock(return_value=SAMPLE_HEALTH)):
        with client.websocket_connect("/api/ws/health") as websocket:
            msg = websocket.receive_json()
            # Contract the frontend relies on: a 'type' discriminator and a
            # 'data' map of service-key -> health dict.
            assert set(msg.keys()) == {"type", "data"}
            assert isinstance(msg["data"], dict)
            assert msg["data"]["ac"]["online"] is True


def test_websocket_disconnect_is_handled(client, mock_auth):
    """Closing the socket must drop the client and stop the broadcast loop."""
    with patch.object(ws, "get_all_health", AsyncMock(return_value=SAMPLE_HEALTH)):
        with client.websocket_connect("/api/ws/health") as websocket:
            websocket.receive_json()  # initial snapshot
            assert ws.manager.client_count == 1
        # Context manager exit closes the socket; the server-side handler runs
        # manager.disconnect(), clearing the client and the broadcast task.
        assert ws.manager.client_count == 0
        assert ws.manager._broadcast_task is None


def test_multiple_clients_tracked_independently(client, mock_auth):
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


# ── WebSocket authentication tests (H-3 fix) ───────────────────────────────────


def test_websocket_rejects_unauthenticated_connection(client):
    """WebSocket must reject connections without a valid session cookie."""
    with patch.object(ws, "get_all_health", AsyncMock(return_value=SAMPLE_HEALTH)):
        # Patch _validate_session to return None (no valid session)
        with patch.object(ws, "_validate_session", return_value=None):
            # Patch _validate_device_token to also return None
            with patch.object(ws, "_validate_device_token", return_value=None):
                # Connect without valid auth — should be rejected with code 4001
                with pytest.raises(Exception) as exc_info:
                    with client.websocket_connect("/api/ws/health") as websocket:
                        websocket.receive_json()

                # WebSocketDisconnect is raised with our custom code
                assert exc_info.value.code == ws.WS_CLOSE_UNAUTHORIZED


def test_websocket_accepts_valid_session(client):
    """WebSocket must accept connections with a valid session cookie."""
    with patch.object(ws, "get_all_health", AsyncMock(return_value=SAMPLE_HEALTH)):
        # Patch _validate_session to return a username (valid session)
        with patch.object(ws, "_validate_session", return_value="authenticated_user"):
            with client.websocket_connect("/api/ws/health") as websocket:
                msg = websocket.receive_json()
                # Successfully received data means auth passed
                assert msg["type"] == "health"
                assert msg["data"] == SAMPLE_HEALTH


def test_websocket_authenticated_client_tracked(client):
    """Authenticated WebSocket client should be tracked in ConnectionManager."""
    with patch.object(ws, "get_all_health", AsyncMock(return_value=SAMPLE_HEALTH)):
        with patch.object(ws, "_validate_session", return_value="test_user"):
            with client.websocket_connect("/api/ws/health") as websocket:
                websocket.receive_json()
                # Client should be tracked
                assert ws.manager.client_count == 1

            # After disconnect, client should be removed
            assert ws.manager.client_count == 0


def test_websocket_unauthenticated_client_not_tracked(client):
    """Rejected unauthenticated connections must not be tracked."""
    with patch.object(ws, "get_all_health", AsyncMock(return_value=SAMPLE_HEALTH)):
        with patch.object(ws, "_validate_session", return_value=None):
            with patch.object(ws, "_validate_device_token", return_value=None):
                try:
                    with client.websocket_connect("/api/ws/health"):
                        pass
                except Exception:
                    pass

                # No client should remain tracked after rejection
                assert ws.manager.client_count == 0
                assert ws.manager._broadcast_task is None


def test_validate_session_called_with_websocket(client):
    """Verify _validate_session is called during handshake."""
    with patch.object(ws, "get_all_health", AsyncMock(return_value=SAMPLE_HEALTH)):
        mock_validate = patch.object(ws, "_validate_session", return_value="user")
        with mock_validate as m:
            with client.websocket_connect("/api/ws/health") as websocket:
                websocket.receive_json()
            # _validate_session should have been called once with the WebSocket
            assert m.call_count == 1


# ── WebSocket device token fallback tests ──────────────────────────────────────


def test_websocket_device_token_fallback_when_jwt_expired(client):
    """WebSocket accepts device token when JWT auth fails."""
    with patch.object(ws, "get_all_health", AsyncMock(return_value=SAMPLE_HEALTH)):
        # JWT auth fails
        with patch.object(ws, "_validate_session", return_value=None):
            # Device token auth succeeds
            with patch.object(ws, "_validate_device_token", return_value="device_user"):
                with client.websocket_connect("/api/ws/health") as websocket:
                    msg = websocket.receive_json()
                    assert msg["type"] == "health"
                    assert msg["data"] == SAMPLE_HEALTH


def test_websocket_rejects_when_both_auth_methods_fail(client):
    """WebSocket rejects when both JWT and device token auth fail."""
    with patch.object(ws, "get_all_health", AsyncMock(return_value=SAMPLE_HEALTH)):
        with patch.object(ws, "_validate_session", return_value=None):
            with patch.object(ws, "_validate_device_token", return_value=None):
                with pytest.raises(Exception) as exc_info:
                    with client.websocket_connect("/api/ws/health") as websocket:
                        websocket.receive_json()
                assert exc_info.value.code == ws.WS_CLOSE_UNAUTHORIZED


def test_websocket_prefers_jwt_over_device_token(client):
    """WebSocket uses JWT auth when available, doesn't call device token fallback."""
    with patch.object(ws, "get_all_health", AsyncMock(return_value=SAMPLE_HEALTH)):
        with patch.object(ws, "_validate_session", return_value="jwt_user"):
            mock_device = patch.object(
                ws, "_validate_device_token", return_value="device_user"
            )
            with mock_device as m:
                with client.websocket_connect("/api/ws/health") as websocket:
                    websocket.receive_json()
                # Device token validation should NOT be called when JWT succeeds
                assert m.call_count == 0


def test_websocket_device_token_fallback_client_tracked(client):
    """Device token authenticated client should be tracked in ConnectionManager."""
    with patch.object(ws, "get_all_health", AsyncMock(return_value=SAMPLE_HEALTH)):
        with patch.object(ws, "_validate_session", return_value=None):
            with patch.object(ws, "_validate_device_token", return_value="device_user"):
                with client.websocket_connect("/api/ws/health") as websocket:
                    websocket.receive_json()
                    assert ws.manager.client_count == 1
                assert ws.manager.client_count == 0


# ── Device token validation unit tests ─────────────────────────────────────────


class _FakeWebSocketWithCookies:
    """WebSocket mock with configurable cookies and client IP."""

    def __init__(
        self, cookies: dict | None = None, client_ip: str | None = "192.168.1.100"
    ):
        self.cookies = cookies or {}
        self._client_ip = client_ip

    @property
    def client(self):
        """Mock client property with host attribute.

        Returns None if _client_ip is None, simulating an unknown client.
        """
        if self._client_ip is None:
            return None

        class ClientInfo:
            def __init__(self, ip):
                self.host = ip

        return ClientInfo(self._client_ip)


def test_validate_device_token_no_cookie():
    """Returns None when device cookie is missing."""
    ws_mock = _FakeWebSocketWithCookies(cookies={})
    result = ws._validate_device_token(ws_mock)
    assert result is None


def test_validate_device_token_invalid_token():
    """Returns None when device token verification fails."""
    ws_mock = _FakeWebSocketWithCookies(cookies={"smh_device": "invalid:token"})

    mock_result = ws.auth_devices.VerifyResult(ok=False)
    with patch.object(ws.auth_devices, "verify_and_rotate", return_value=mock_result):
        result = ws._validate_device_token(ws_mock)
    assert result is None


def test_validate_device_token_theft_detected():
    """Returns None when token theft is detected."""
    ws_mock = _FakeWebSocketWithCookies(cookies={"smh_device": "series:token"})

    mock_result = ws.auth_devices.VerifyResult(
        ok=False, theft_detected=True, username="victim"
    )
    with patch.object(ws.auth_devices, "verify_and_rotate", return_value=mock_result):
        result = ws._validate_device_token(ws_mock)
    assert result is None


def test_validate_device_token_unrecognized_ip():
    """Returns None when client IP doesn't match any device IP."""
    ws_mock = _FakeWebSocketWithCookies(
        cookies={"smh_device": "series:token"}, client_ip="10.0.0.99"  # Unrecognized IP
    )

    mock_result = ws.auth_devices.VerifyResult(
        ok=True, username="testuser", new_cookie_value="series:new_token"
    )
    # list_devices returns devices with different IPs
    mock_devices = [
        {"ip_address": "192.168.1.1"},
        {"ip_address": "192.168.1.2"},
    ]
    with patch.object(ws.auth_devices, "verify_and_rotate", return_value=mock_result):
        with patch.object(ws.auth_devices, "list_devices", return_value=mock_devices):
            result = ws._validate_device_token(ws_mock)
    assert result is None


def test_validate_device_token_recognized_ip():
    """Returns username when device token is valid and IP matches."""
    ws_mock = _FakeWebSocketWithCookies(
        cookies={"smh_device": "series:token"}, client_ip="192.168.1.100"  # Matching IP
    )

    mock_result = ws.auth_devices.VerifyResult(
        ok=True, username="testuser", new_cookie_value="series:new_token"
    )
    mock_devices = [
        {"ip_address": "192.168.1.100"},  # Matches client IP
        {"ip_address": "192.168.1.2"},
    ]
    with patch.object(ws.auth_devices, "verify_and_rotate", return_value=mock_result):
        with patch.object(ws.auth_devices, "list_devices", return_value=mock_devices):
            result = ws._validate_device_token(ws_mock)
    assert result == "testuser"


def test_validate_device_token_unknown_ip_rejected():
    """Returns None when client IP cannot be determined."""
    ws_mock = _FakeWebSocketWithCookies(
        cookies={"smh_device": "series:token"}, client_ip=None  # No client info
    )

    mock_result = ws.auth_devices.VerifyResult(
        ok=True, username="testuser", new_cookie_value="series:new_token"
    )
    with patch.object(ws.auth_devices, "verify_and_rotate", return_value=mock_result):
        result = ws._validate_device_token(ws_mock)
    assert result is None


def test_get_client_ip_with_client():
    """Returns client host when available."""
    ws_mock = _FakeWebSocketWithCookies(client_ip="10.20.30.40")
    result = ws._get_client_ip(ws_mock)
    assert result == "10.20.30.40"


def test_get_client_ip_without_client():
    """Returns 'unknown' when client info not available."""
    ws_mock = _FakeWebSocketWithCookies(client_ip=None)
    result = ws._get_client_ip(ws_mock)
    assert result == "unknown"


def test_is_recognized_device_ip_returns_true_for_match():
    """_is_recognized_device_ip returns True when IP matches a device."""
    mock_devices = [
        {"ip_address": "192.168.1.1"},
        {"ip_address": "192.168.1.100"},
    ]
    with patch.object(ws.auth_devices, "list_devices", return_value=mock_devices):
        result = ws._is_recognized_device_ip("testuser", "192.168.1.100")
    assert result is True


def test_is_recognized_device_ip_returns_false_for_mismatch():
    """_is_recognized_device_ip returns False when IP doesn't match any device."""
    mock_devices = [
        {"ip_address": "192.168.1.1"},
        {"ip_address": "192.168.1.2"},
    ]
    with patch.object(ws.auth_devices, "list_devices", return_value=mock_devices):
        result = ws._is_recognized_device_ip("testuser", "10.0.0.99")
    assert result is False


def test_is_recognized_device_ip_returns_false_for_unknown():
    """_is_recognized_device_ip returns False for 'unknown' IP."""
    mock_devices = [{"ip_address": "192.168.1.1"}]
    with patch.object(ws.auth_devices, "list_devices", return_value=mock_devices):
        result = ws._is_recognized_device_ip("testuser", "unknown")
    assert result is False


def test_is_recognized_device_ip_empty_devices():
    """_is_recognized_device_ip returns False when user has no devices."""
    with patch.object(ws.auth_devices, "list_devices", return_value=[]):
        result = ws._is_recognized_device_ip("testuser", "192.168.1.100")
    assert result is False
