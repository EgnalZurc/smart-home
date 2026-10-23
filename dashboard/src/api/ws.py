"""WebSocket endpoint for real-time health status push updates.

The dashboard historically polled ``/api/health/*`` on a timer to refresh the
status dots next to each service. That means every open tab issues N HTTP
requests every few seconds. This module replaces the polling with a single
WebSocket push: the server runs ONE background task that snapshots all service
health every ``BROADCAST_INTERVAL`` seconds and fans the result out to every
connected client.

Design notes
------------
* Health data comes from ``api.health.get_all_health()``, which already sits
  behind the 5s TTL cache (see ``_cached_health_check``). We broadcast on the
  same cadence so a push always reflects a freshly-refreshed cache entry
  without issuing extra backend requests.
* A single shared broadcast loop is started lazily when the first client
  connects and cancelled when the last client disconnects, so N clients never
  spawn N loops.
* On connect the client immediately receives the current snapshot so the UI
  can paint without waiting for the next broadcast tick.
* Disconnects (clean or abrupt) are handled gracefully: a send failure prunes
  the dead connection instead of crashing the loop.

Message format (JSON)::

    {
      "type": "health",
      "data": { "<service-key>": { "online": bool, ... }, ... }
    }

Security
--------
WebSocket connections require a valid session cookie (``smh_session`` JWT).
The HTTP auth middleware does not cover WebSocket upgrades, so validation
happens during the handshake via ``_validate_session()``.

If the JWT is expired or missing, the WebSocket handler falls back to device
token authentication (``smh_device`` cookie). This allows trusted devices to
maintain real-time connections without requiring a fresh JWT. Device token
auth is only accepted if the client IP matches the IP stored when the device
was registered.

Unauthenticated requests are rejected with close code 4001 (Unauthorized).
"""

import asyncio
import contextlib
import logging

import auth as auth_core
import auth_devices
import httpx
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from api.health import get_all_health

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ws", tags=["WebSocket"])

# Broadcast cadence in seconds. Matches HEALTH_CACHE_TTL so each push reflects a
# fresh cache refresh without triggering extra backend requests between ticks.
from api.constants import WS_BROADCAST_INTERVAL_SECONDS

BROADCAST_INTERVAL = WS_BROADCAST_INTERVAL_SECONDS

# WebSocket close codes for authentication errors (4000-4999 = application-defined)
WS_CLOSE_UNAUTHORIZED = 4001


class ConnectionManager:
    """Tracks connected WebSocket clients and the shared broadcast task.

    The manager owns a single background task that periodically snapshots the
    aggregated health status and pushes it to every connected client. The task
    is started on the first connection and stopped once the last client leaves,
    so idle periods consume no resources.
    """

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._broadcast_task: asyncio.Task | None = None
        # Guards mutations of the client set / task so concurrent connect and
        # disconnect handlers don't race on starting/stopping the loop.
        self._lock = asyncio.Lock()

    @property
    def client_count(self) -> int:
        """Number of currently connected clients."""
        return len(self._clients)

    async def connect(self, websocket: WebSocket) -> None:
        """Accept a new client, send it the current snapshot, and ensure the
        broadcast loop is running.
        """
        await websocket.accept()
        async with self._lock:
            self._clients.add(websocket)
            self._ensure_broadcast_task()

        # Send the current status immediately so the UI paints without waiting
        # for the next broadcast tick. A failure here is non-fatal; the regular
        # disconnect path will clean up.
        try:
            await websocket.send_json(await self._build_message())
        except (WebSocketDisconnect, asyncio.CancelledError, OSError, RuntimeError):
            logger.debug("Initial health push failed for a client", exc_info=True)

    async def disconnect(self, websocket: WebSocket) -> None:
        """Remove a client and stop the broadcast loop if none remain."""
        async with self._lock:
            self._clients.discard(websocket)
            if not self._clients:
                self._stop_broadcast_task()

    async def broadcast(self, message: dict) -> None:
        """Send ``message`` as JSON to every connected client.

        Clients whose send fails (disconnected mid-flight) are pruned so a dead
        connection never breaks the loop or leaks.
        """
        dead: list[WebSocket] = []
        # Iterate over a snapshot: a client may disconnect while we send.
        for client in list(self._clients):
            try:
                await client.send_json(message)
            except (WebSocketDisconnect, asyncio.CancelledError, OSError, RuntimeError):
                dead.append(client)

        if dead:
            async with self._lock:
                for client in dead:
                    self._clients.discard(client)
                if not self._clients:
                    self._stop_broadcast_task()

    async def _build_message(self) -> dict:
        """Build the standard health message from the aggregated health check."""
        data = await get_all_health()
        return {"type": "health", "data": data}

    def _ensure_broadcast_task(self) -> None:
        """Start the broadcast loop if it isn't already running.

        Caller must hold ``self._lock``.
        """
        if self._broadcast_task is None or self._broadcast_task.done():
            self._broadcast_task = asyncio.create_task(self._broadcast_loop())

    def _stop_broadcast_task(self) -> None:
        """Cancel the broadcast loop. Caller must hold ``self._lock``."""
        if self._broadcast_task is not None:
            self._broadcast_task.cancel()
            self._broadcast_task = None

    async def _broadcast_loop(self) -> None:
        """Periodically push the current health snapshot to all clients."""
        try:
            while self._clients:
                await asyncio.sleep(BROADCAST_INTERVAL)
                if not self._clients:
                    break
                try:
                    message = await self._build_message()
                except (httpx.HTTPError, OSError, RuntimeError):
                    logger.warning("Health broadcast build failed", exc_info=True)
                    continue
                await self.broadcast(message)
        except asyncio.CancelledError:
            # Normal shutdown when the last client disconnects.
            raise


# Module-level singleton: one manager (and thus one broadcast loop) per process.
manager = ConnectionManager()


def _get_client_ip(websocket: WebSocket) -> str:
    """Extract client IP from WebSocket connection.

    Returns the client host address, or 'unknown' if not available.
    """
    if websocket.client:
        return websocket.client.host
    return "unknown"


def _validate_session(websocket: WebSocket) -> str | None:
    """Validate the session cookie from a WebSocket handshake request.

    WebSocket connections start as HTTP upgrade requests and carry cookies in
    the initial handshake headers. We reuse the existing JWT validation logic
    from auth_core.

    Returns:
        The authenticated username if valid, None otherwise.
    """
    # WebSocket.cookies is a dict-like populated from the handshake headers.
    token = websocket.cookies.get(auth_core.COOKIE_NAME)
    if not token:
        return None
    payload = auth_core.decode_token(token)
    if payload is None:
        return None
    return payload.get("sub")


def _validate_device_token(websocket: WebSocket) -> str | None:
    """Validate device token from WebSocket handshake as fallback auth.

    When JWT auth fails (expired/missing), this function attempts to authenticate
    using the device token cookie (smh_device). The device token is validated
    using the same Jaspan pattern as HTTP requests.

    Security: Device token auth is only accepted if the client IP matches an IP
    address associated with device tokens for the user. This prevents a stolen
    device token from being used from an unrecognized location.

    Returns:
        The authenticated username if valid, None otherwise.
    """
    device_cookie = websocket.cookies.get(auth_devices.DEVICE_COOKIE_NAME)
    if not device_cookie:
        return None

    result = auth_devices.verify_and_rotate(device_cookie)

    # Token theft detected — don't authenticate
    if result.theft_detected:
        client_ip = _get_client_ip(websocket)
        logger.warning(
            "Device token theft detected during WebSocket auth for user %r from IP %s",
            result.username,
            client_ip,
        )
        return None

    if not result.ok:
        return None

    # Verify client IP matches a known device IP for this user
    client_ip = _get_client_ip(websocket)
    if not _is_recognized_device_ip(result.username, client_ip):
        logger.warning(
            "Device token auth rejected for user %r: IP %s not recognized",
            result.username,
            client_ip,
        )
        return None

    logger.debug(
        "WebSocket authenticated via device token for user %r (IP: %s)",
        result.username,
        client_ip,
    )
    return result.username


def _is_recognized_device_ip(username: str, client_ip: str) -> bool:
    """Check if the client IP is associated with any device token for this user.

    This provides an additional security layer for device token auth on WebSocket
    connections. A valid device token from an unrecognized IP is rejected.

    Args:
        username: The authenticated user from the device token.
        client_ip: The client's IP address.

    Returns:
        True if the IP is associated with any device token for this user.
    """
    if client_ip == "unknown":
        # Can't verify IP — reject for safety
        return False

    devices = auth_devices.list_devices(username)
    recognized_ips = {d.get("ip_address") for d in devices}
    return client_ip in recognized_ips


@router.websocket("/health")
async def health_websocket(websocket: WebSocket) -> None:
    """Stream real-time health status to the dashboard.

    Requires authentication via one of:
    1. Valid session cookie (smh_session JWT) — preferred
    2. Valid device token cookie (smh_device) — fallback when JWT expires

    Device token fallback is only accepted from recognized device IPs (IPs that
    have previously been associated with a device token for the user).

    Unauthenticated requests are rejected with close code 4001 (Unauthorized).

    On connect the client receives the current health snapshot immediately,
    then a fresh snapshot every ``BROADCAST_INTERVAL`` seconds. The server does
    not expect any messages from the client; incoming frames are drained so the
    connection stays open and disconnects are detected promptly.
    """
    # Validate session before accepting the WebSocket connection.
    # The HTTP middleware doesn't cover WebSocket upgrades, so we check manually.
    user = _validate_session(websocket)

    # Fallback to device token if JWT auth failed
    if not user:
        user = _validate_device_token(websocket)

    if not user:
        # Reject unauthenticated connections. Must call accept() first to send
        # a close frame with a custom code — calling close() on an unaccepted
        # WebSocket is a protocol error in some implementations.
        await websocket.accept()
        await websocket.close(code=WS_CLOSE_UNAUTHORIZED, reason="Unauthorized")
        logger.debug("WebSocket connection rejected: no valid session or device token")
        return

    logger.debug("WebSocket connection accepted for user %r", user)
    await manager.connect(websocket)
    try:
        # We don't need client messages, but we must keep receiving so Starlette
        # surfaces the disconnect. receive_text() raises WebSocketDisconnect
        # when the client goes away.
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
    except (asyncio.CancelledError, OSError, RuntimeError):
        logger.debug("WebSocket connection ended with error", exc_info=True)
        await manager.disconnect(websocket)
        with contextlib.suppress(OSError, RuntimeError):
            await websocket.close()
