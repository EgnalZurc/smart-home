"""Unit tests for MelCloudClient.

Tests the HTTP client that communicates with the MELCloud API
for controlling the air conditioning unit.
"""

from unittest.mock import MagicMock, patch

import httpx
from melcloud_client import MODE_MAP, MelCloudClient


class TestMelCloudClientInit:
    """Tests for MelCloudClient initialization."""

    def test_base_url_normalization(self):
        """Should normalize base URL correctly."""
        client = MelCloudClient(
            base_url="https://app.melcloud.com",
            email="test@test.com",
            password="password",
            building_id=123,
        )

        assert client.base_url == "https://app.melcloud.com/Mitsubishi.Wifi.Client"
        client.close()

    def test_base_url_already_has_path(self):
        """Should not duplicate path if already present."""
        client = MelCloudClient(
            base_url="https://app.melcloud.com/Mitsubishi.Wifi.Client",
            email="test@test.com",
            password="password",
            building_id=123,
        )

        assert client.base_url == "https://app.melcloud.com/Mitsubishi.Wifi.Client"
        client.close()

    def test_timeout_configuration(self):
        """Should accept custom timeout."""
        client = MelCloudClient(
            base_url="https://app.melcloud.com",
            email="test@test.com",
            password="password",
            building_id=123,
            timeout=60.0,
        )

        assert client._timeout == 60.0
        client.close()


class TestMelCloudClientHeaders:
    """Tests for header generation."""

    def test_headers_without_context_key(self):
        """Headers should only have Content-Type when not logged in."""
        client = MelCloudClient(
            base_url="https://app.melcloud.com",
            email="test@test.com",
            password="password",
            building_id=123,
        )

        headers = client._headers()

        assert headers["Content-Type"] == "application/json"
        assert "X-MitsContextKey" not in headers
        client.close()

    def test_headers_with_context_key(self):
        """Headers should include context key when logged in."""
        client = MelCloudClient(
            base_url="https://app.melcloud.com",
            email="test@test.com",
            password="password",
            building_id=123,
        )
        client.context_key = "test-context-key-123"

        headers = client._headers()

        assert headers["X-MitsContextKey"] == "test-context-key-123"
        client.close()


class TestMelCloudClientLogin:
    """Tests for login functionality."""

    def test_login_success(self):
        """Should return True and set context_key on success."""
        client = MelCloudClient(
            base_url="https://app.melcloud.com",
            email="test@test.com",
            password="password",
            building_id=123,
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "ErrorId": None,
            "LoginData": {"ContextKey": "abc123"},
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(client.client, "post", return_value=mock_response):
            result = client.login()

        assert result is True
        assert client.context_key == "abc123"
        # Password should be deleted after successful login
        assert not hasattr(client, "password")
        client.close()

    def test_login_api_error(self):
        """Should return False when API returns error."""
        client = MelCloudClient(
            base_url="https://app.melcloud.com",
            email="test@test.com",
            password="password",
            building_id=123,
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "ErrorId": 1,
            "ErrorMessage": "Invalid credentials",
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(client.client, "post", return_value=mock_response):
            result = client.login()

        assert result is False
        assert client.context_key is None
        client.close()

    def test_login_no_context_key(self):
        """Should return False when no context key in response."""
        client = MelCloudClient(
            base_url="https://app.melcloud.com",
            email="test@test.com",
            password="password",
            building_id=123,
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "ErrorId": None,
            "LoginData": {},  # No ContextKey
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(client.client, "post", return_value=mock_response):
            result = client.login()

        assert result is False
        client.close()

    def test_login_http_error(self):
        """Should return False on HTTP error."""
        client = MelCloudClient(
            base_url="https://app.melcloud.com",
            email="test@test.com",
            password="password",
            building_id=123,
        )

        with patch.object(
            client.client, "post", side_effect=httpx.HTTPError("Connection failed")
        ):
            result = client.login()

        assert result is False
        client.close()


class TestMelCloudClientGetDeviceState:
    """Tests for get_device_state functionality."""

    def test_get_device_state_success(self):
        """Should return device state dict on success."""
        client = MelCloudClient(
            base_url="https://app.melcloud.com",
            email="test@test.com",
            password="password",
            building_id=123,
        )
        client.context_key = "test-key"

        expected_state = {
            "Power": True,
            "OperationMode": 3,
            "SetTemperature": 24.0,
            "RoomTemperature": 26.5,
        }

        mock_response = MagicMock()
        mock_response.json.return_value = expected_state
        mock_response.raise_for_status = MagicMock()

        with patch.object(client.client, "get", return_value=mock_response):
            result = client.get_device_state(device_id=123, building_id=456)

        assert result == expected_state
        client.close()

    def test_get_device_state_http_error(self):
        """Should return None on HTTP error."""
        client = MelCloudClient(
            base_url="https://app.melcloud.com",
            email="test@test.com",
            password="password",
            building_id=123,
        )
        client.context_key = "test-key"

        with patch.object(
            client.client, "get", side_effect=httpx.HTTPError("Server error")
        ):
            result = client.get_device_state(device_id=123, building_id=456)

        assert result is None
        client.close()


class TestMelCloudClientSetTemperature:
    """Tests for set_temperature functionality."""

    def test_set_temperature_success(self):
        """Should return True on successful temperature set."""
        client = MelCloudClient(
            base_url="https://app.melcloud.com",
            email="test@test.com",
            password="password",
            building_id=123,
        )
        client.context_key = "test-key"

        current_state = {
            "Power": False,
            "OperationMode": 3,
            "SetTemperature": 22.0,
            "SetFanSpeed": 0,
        }

        post_response = MagicMock()
        post_response.json.return_value = {"SetTemperature": 24.0}
        post_response.raise_for_status = MagicMock()

        with patch.object(client, "get_device_state", return_value=current_state):
            with patch.object(client.client, "post", return_value=post_response):
                result = client.set_temperature(
                    device_id=123,
                    setpoint=24.0,
                    power=True,
                    mode="cool",
                    fan_speed=2,
                )

        assert result is True
        client.close()

    def test_set_temperature_clamps_values(self):
        """Should clamp setpoint to valid range (16-31)."""
        client = MelCloudClient(
            base_url="https://app.melcloud.com",
            email="test@test.com",
            password="password",
            building_id=123,
        )
        client.context_key = "test-key"

        current_state = {"Power": False, "SetTemperature": 22.0}
        post_response = MagicMock()
        post_response.json.return_value = {"SetTemperature": 16.0}
        post_response.raise_for_status = MagicMock()

        posted_data = None

        def capture_post(*args, **kwargs):
            nonlocal posted_data
            posted_data = kwargs.get("json")
            return post_response

        with patch.object(client, "get_device_state", return_value=current_state):
            with patch.object(client.client, "post", side_effect=capture_post):
                # Try to set temperature below minimum
                client.set_temperature(device_id=123, setpoint=10.0)

        assert posted_data["SetTemperature"] == 16.0
        client.close()

    def test_set_temperature_no_current_state(self):
        """Should return False if can't get current state."""
        client = MelCloudClient(
            base_url="https://app.melcloud.com",
            email="test@test.com",
            password="password",
            building_id=123,
        )
        client.context_key = "test-key"

        with patch.object(client, "get_device_state", return_value=None):
            result = client.set_temperature(device_id=123, setpoint=24.0)

        assert result is False
        client.close()

    def test_set_temperature_http_error(self):
        """Should return False on HTTP error."""
        client = MelCloudClient(
            base_url="https://app.melcloud.com",
            email="test@test.com",
            password="password",
            building_id=123,
        )
        client.context_key = "test-key"

        current_state = {"Power": False, "SetTemperature": 22.0}

        with patch.object(client, "get_device_state", return_value=current_state):
            with patch.object(
                client.client, "post", side_effect=httpx.HTTPError("Server error")
            ):
                result = client.set_temperature(device_id=123, setpoint=24.0)

        assert result is False
        client.close()


class TestModeMapping:
    """Tests for AC mode mapping."""

    def test_mode_map_contains_all_modes(self):
        """MODE_MAP should contain all expected modes."""
        assert "cool" in MODE_MAP
        assert "heat" in MODE_MAP
        assert "dry" in MODE_MAP
        assert "fan" in MODE_MAP
        assert "auto" in MODE_MAP

    def test_mode_values(self):
        """Mode values should match MELCloud API constants."""
        assert MODE_MAP["heat"] == 1
        assert MODE_MAP["dry"] == 2
        assert MODE_MAP["cool"] == 3
        assert MODE_MAP["fan"] == 7
        assert MODE_MAP["auto"] == 8
