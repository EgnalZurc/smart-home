"""Unit tests for api/proxy/pc.py.

Tests cover:
- Existing PC status and power mode endpoints
- New sleep/wake power control endpoints with safety headers
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from httpx import Response

from api.proxy.pc import (
    router,
    get_pc_status,
    get_pc_mode,
    set_pc_mode,
    pc_sleep,
    pc_wake,
    EGNALPC_MAC,
    WOL_INTERFACE,
)


def make_mock_response(data, status_code=200):
    """Create a mock HTTP response."""
    resp = MagicMock(spec=Response)
    resp.status_code = status_code
    resp.json.return_value = data
    resp.text = str(data)
    return resp


def make_mock_request(headers=None, is_super=True):
    """Create a mock FastAPI request with optional headers."""
    mock_req = MagicMock()
    mock_req.headers = headers or {}

    # For require_super check
    mock_req.state = MagicMock()
    if is_super:
        mock_req.state.user = "admin"
    else:
        mock_req.state.user = "guest"

    return mock_req


HTTPX_PATCH = "api.proxy.pc.httpx.AsyncClient"


class TestPcStatus:
    """Tests for GET /api/pc/status endpoint."""

    @pytest.mark.asyncio
    async def test_get_status_success(self):
        """Returns PC health status."""
        data = {"online": True, "docker": True, "service": "pc-agent"}
        with patch(HTTPX_PATCH) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = make_mock_response(data)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await get_pc_status()
            assert result == data
            assert result["online"] is True

    @pytest.mark.asyncio
    async def test_get_status_offline_returns_default(self):
        """Returns offline status when PC unreachable."""
        with patch(HTTPX_PATCH) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.side_effect = Exception("Connection refused")
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await get_pc_status()
            assert result == {"online": False, "docker": False}


class TestPcMode:
    """Tests for power mode endpoints."""

    @pytest.mark.asyncio
    async def test_get_mode_success(self):
        """Returns current power mode."""
        data = {"mode": "gaming", "windows_name": "Gaming"}
        with patch(HTTPX_PATCH) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = make_mock_response(data)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await get_pc_mode()
            assert result["mode"] == "gaming"

    @pytest.mark.asyncio
    async def test_set_mode_requires_super(self):
        """Non-super users cannot set power mode."""
        request = make_mock_request(is_super=False)

        with patch("api.proxy.pc.require_super") as mock_super:
            mock_super.side_effect = HTTPException(403, "Admin access required")
            with pytest.raises(HTTPException) as exc_info:
                await set_pc_mode("gaming", request)
            assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_set_mode_invalid_mode_rejected(self):
        """Invalid power mode is rejected."""
        request = make_mock_request(is_super=True)

        with patch("api.proxy.pc.require_super"):
            with pytest.raises(HTTPException) as exc_info:
                await set_pc_mode("turbo", request)
            assert exc_info.value.status_code == 400
            assert "Invalid mode" in exc_info.value.detail


class TestPcSleep:
    """Tests for POST /api/pc/sleep endpoint."""

    @pytest.mark.asyncio
    async def test_sleep_requires_super(self):
        """Non-super users cannot put PC to sleep."""
        request = make_mock_request(is_super=False)

        with patch("api.proxy.pc.require_super") as mock_super:
            mock_super.side_effect = HTTPException(403, "Admin access required")
            with pytest.raises(HTTPException) as exc_info:
                await pc_sleep(request)
            assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_sleep_requires_confirmation_header(self):
        """Sleep endpoint requires X-Confirm-Action: SLEEP header."""
        request = make_mock_request(headers={}, is_super=True)

        with patch("api.proxy.pc.require_super"):
            with pytest.raises(HTTPException) as exc_info:
                await pc_sleep(request)
            assert exc_info.value.status_code == 400
            assert "Confirmation required" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_sleep_wrong_confirmation_rejected(self):
        """Wrong confirmation header value is rejected."""
        request = make_mock_request(
            headers={"X-Confirm-Action": "SHUTDOWN"}, is_super=True
        )

        with patch("api.proxy.pc.require_super"):
            with pytest.raises(HTTPException) as exc_info:
                await pc_sleep(request)
            assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_sleep_success_with_correct_confirmation(self):
        """Sleep succeeds with correct auth and confirmation."""
        request = make_mock_request(
            headers={"X-Confirm-Action": "SLEEP"}, is_super=True
        )
        data = {"status": "ok", "message": "Sleep command sent"}

        with patch("api.proxy.pc.require_super"):
            with patch(HTTPX_PATCH) as mock_client:
                mock_instance = AsyncMock()
                mock_instance.post.return_value = make_mock_response(data)
                mock_client.return_value.__aenter__.return_value = mock_instance

                result = await pc_sleep(request)
                assert result["status"] == "ok"

                # Verify confirmation header was forwarded to pc-agent
                call_kwargs = mock_instance.post.call_args
                assert call_kwargs[1]["headers"]["X-Confirm-Action"] == "SLEEP"


class TestPcWake:
    """Tests for POST /api/pc/wake endpoint."""

    @pytest.mark.asyncio
    async def test_wake_requires_super(self):
        """Non-super users cannot wake PC."""
        request = make_mock_request(is_super=False)

        with patch("api.proxy.pc.require_super") as mock_super:
            mock_super.side_effect = HTTPException(403, "Admin access required")
            with pytest.raises(HTTPException) as exc_info:
                await pc_wake(request)
            assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_wake_requires_confirmation_header(self):
        """Wake endpoint requires X-Confirm-Action: WAKE header."""
        request = make_mock_request(headers={}, is_super=True)

        with patch("api.proxy.pc.require_super"):
            with pytest.raises(HTTPException) as exc_info:
                await pc_wake(request)
            assert exc_info.value.status_code == 400
            assert "Confirmation required" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_wake_wrong_confirmation_rejected(self):
        """Wrong confirmation header value is rejected."""
        request = make_mock_request(
            headers={"X-Confirm-Action": "SLEEP"}, is_super=True
        )

        with patch("api.proxy.pc.require_super"):
            with pytest.raises(HTTPException) as exc_info:
                await pc_wake(request)
            assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_wake_success_with_correct_confirmation(self):
        """Wake succeeds with correct auth and confirmation."""
        request = make_mock_request(
            headers={"X-Confirm-Action": "WAKE"}, is_super=True
        )

        with patch("api.proxy.pc.require_super"):
            with patch("asyncio.create_subprocess_exec") as mock_exec:
                mock_proc = AsyncMock()
                mock_proc.returncode = 0
                mock_proc.communicate.return_value = (b"", b"")
                mock_exec.return_value = mock_proc

                result = await pc_wake(request)
                assert result["status"] == "ok"
                assert EGNALPC_MAC in result["message"]

                # Verify etherwake was called with correct args
                call_args = mock_exec.call_args[0]
                assert "sudo" in call_args
                assert "etherwake" in call_args
                assert "-i" in call_args
                assert WOL_INTERFACE in call_args
                assert EGNALPC_MAC in call_args

    @pytest.mark.asyncio
    async def test_wake_etherwake_not_found(self):
        """Returns 500 when etherwake is not installed."""
        request = make_mock_request(
            headers={"X-Confirm-Action": "WAKE"}, is_super=True
        )

        with patch("api.proxy.pc.require_super"):
            with patch("asyncio.create_subprocess_exec") as mock_exec:
                mock_exec.side_effect = FileNotFoundError("etherwake not found")

                with pytest.raises(HTTPException) as exc_info:
                    await pc_wake(request)
                assert exc_info.value.status_code == 500
                assert "etherwake not installed" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_wake_etherwake_fails(self):
        """Returns 500 when etherwake command fails."""
        request = make_mock_request(
            headers={"X-Confirm-Action": "WAKE"}, is_super=True
        )

        with patch("api.proxy.pc.require_super"):
            with patch("asyncio.create_subprocess_exec") as mock_exec:
                mock_proc = AsyncMock()
                mock_proc.returncode = 1
                mock_proc.communicate.return_value = (b"", b"Permission denied")
                mock_exec.return_value = mock_proc

                with pytest.raises(HTTPException) as exc_info:
                    await pc_wake(request)
                assert exc_info.value.status_code == 500
                assert "Permission denied" in exc_info.value.detail


class TestRouteRegistration:
    """Verify all routes are properly registered."""

    def test_router_has_expected_routes(self):
        """All PC control routes are registered."""
        paths = {route.path for route in router.routes}
        expected = [
            "/status",
            "/mode",
            "/mode/{mode}",
            "/sleep",
            "/wake",
        ]
        for path in expected:
            assert path in paths, f"Route {path} not found in router"

    def test_router_prefix(self):
        """Router has correct prefix."""
        assert router.prefix == "/api/pc"
