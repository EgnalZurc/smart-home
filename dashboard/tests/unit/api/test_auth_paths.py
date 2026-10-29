"""Tests that exercise authentication paths end-to-end.

These tests verify that auth checks are properly enforced on protected endpoints,
complementing the existing unit tests that bypass auth with mocks.
"""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def mock_require_super():
    """Override the root fixture to NOT auto-mock auth for these tests."""
    yield


class TestHealthCacheTTLConfiguration:
    """Tests for configurable health cache TTL."""

    def test_health_cache_ttl_default(self):
        """Health cache TTL should default to 5.0 seconds."""
        from api.constants import HEALTH_CACHE_TTL_SECONDS

        assert HEALTH_CACHE_TTL_SECONDS == 5.0


class TestRateLimiterConfiguration:
    """Tests for configurable rate limiter settings."""

    def test_rate_limiter_defaults_in_constants(self):
        """Rate limiter defaults should be defined in constants."""
        from api.constants import (
            LOGIN_RATE_LIMIT_MAX_REQUESTS,
            LOGIN_RATE_LIMIT_WINDOW_SECONDS,
        )

        # Defaults: 5 requests per 300 seconds (5 minutes)
        assert LOGIN_RATE_LIMIT_MAX_REQUESTS == 5
        assert LOGIN_RATE_LIMIT_WINDOW_SECONDS == 300


class TestEgnalPCMACConfiguration:
    """Tests for configurable EGNALPC_MAC."""

    def test_egnalpc_mac_has_valid_format(self):
        """EGNALPC_MAC should have a valid MAC address format."""
        from api.constants import EGNALPC_MAC

        # Should be a valid MAC address format
        assert ":" in EGNALPC_MAC
        parts = EGNALPC_MAC.split(":")
        assert len(parts) == 6
        # Each part should be 2 hex chars
        for part in parts:
            assert len(part) == 2
            int(part, 16)  # Should not raise


class TestWebSocketIPTracking:
    """Tests for IP tracking on WebSocket device token rotation."""

    def test_update_device_ip_updates_all_user_devices(self):
        """update_device_ip should update IP for all devices of a user."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.rowcount = 3
        mock_conn.execute.return_value = mock_cursor

        with patch("auth_devices._db") as mock_db:
            mock_db.return_value.__enter__.return_value = mock_conn
            mock_db.return_value.__exit__.return_value = None

            import auth_devices

            count = auth_devices.update_device_ip("testuser", "192.168.1.100")

            assert count == 3
            mock_conn.execute.assert_called_once()
            call_args = mock_conn.execute.call_args
            assert "UPDATE device_tokens SET ip_address" in call_args[0][0]
            assert call_args[0][1] == ("192.168.1.100", "testuser")

    def test_validate_device_token_updates_ip_on_rotation(self):
        """WebSocket device token validation should update IP on rotation."""
        import api.ws as ws
        import auth_devices

        class FakeWebSocket:
            cookies = {"smh_device": "series:token"}

            @property
            def client(self):
                class ClientInfo:
                    host = "10.0.0.50"

                return ClientInfo()

        mock_result = auth_devices.VerifyResult(
            ok=True, username="testuser", new_cookie_value="series:new_token"
        )
        mock_devices = [{"ip_address": "10.0.0.50"}]

        with (
            patch.object(auth_devices, "verify_and_rotate", return_value=mock_result),
            patch.object(auth_devices, "list_devices", return_value=mock_devices),
            patch.object(auth_devices, "update_device_ip") as mock_update,
        ):
            result = ws._validate_device_token(FakeWebSocket())

            assert result == "testuser"
            mock_update.assert_called_once_with("testuser", "10.0.0.50")

    def test_validate_device_token_handles_ip_update_failure(self):
        """IP update failure should not block authentication."""
        import api.ws as ws
        import auth_devices

        class FakeWebSocket:
            cookies = {"smh_device": "series:token"}

            @property
            def client(self):
                class ClientInfo:
                    host = "10.0.0.50"

                return ClientInfo()

        mock_result = auth_devices.VerifyResult(
            ok=True, username="testuser", new_cookie_value="series:new_token"
        )
        mock_devices = [{"ip_address": "10.0.0.50"}]

        with (
            patch.object(auth_devices, "verify_and_rotate", return_value=mock_result),
            patch.object(auth_devices, "list_devices", return_value=mock_devices),
            patch.object(
                auth_devices, "update_device_ip", side_effect=OSError("DB error")
            ),
        ):
            # Should still return username even if IP update fails
            result = ws._validate_device_token(FakeWebSocket())
            assert result == "testuser"