"""Tests for smart_home_common/clients/melcloud.py.

Covers:
- MelCloudClient initialization and URL normalization
- login: success, auth failure, HTTP errors
- get_device_state: success and HTTP errors
- set_temperature: success, state retrieval failure, HTTP errors
- close method
"""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from smart_home_common.clients.melcloud import (
    AC_MODE_AUTO,
    AC_MODE_COOL,
    AC_MODE_DRY,
    AC_MODE_FAN,
    AC_MODE_HEAT,
    MODE_MAP,
    MelCloudClient,
)


class TestMelCloudClientInit:
    def test_base_url_normalization_adds_path(self):
        client = MelCloudClient(
            base_url="https://example.com",
            email="test@example.com",
            password="secret",
        )
        assert client.base_url == "https://example.com/Mitsubishi.Wifi.Client"
        client.close()

    def test_base_url_normalization_strips_trailing_slash(self):
        client = MelCloudClient(
            base_url="https://example.com/",
            email="test@example.com",
            password="secret",
        )
        assert client.base_url == "https://example.com/Mitsubishi.Wifi.Client"
        client.close()

    def test_base_url_keeps_existing_path(self):
        client = MelCloudClient(
            base_url="https://example.com/Mitsubishi.Wifi.Client",
            email="test@example.com",
            password="secret",
        )
        assert client.base_url == "https://example.com/Mitsubishi.Wifi.Client"
        client.close()

    def test_stores_credentials_and_defaults(self):
        client = MelCloudClient(
            base_url="https://example.com",
            email="test@example.com",
            password="secret",
            building_id=123,
            timeout=15.0,
            app_version="2.0.0",
        )
        assert client.email == "test@example.com"
        assert client.password == "secret"
        assert client._building_id == 123
        assert client._timeout == 15.0
        assert client._app_version == "2.0.0"
        assert client.context_key is None
        client.close()


class TestMelCloudClientHeaders:
    def test_headers_without_context_key(self):
        client = MelCloudClient(
            base_url="https://example.com",
            email="test@example.com",
            password="secret",
        )
        headers = client._headers()
        assert headers == {"Content-Type": "application/json"}
        assert "X-MitsContextKey" not in headers
        client.close()

    def test_headers_with_context_key(self):
        client = MelCloudClient(
            base_url="https://example.com",
            email="test@example.com",
            password="secret",
        )
        client.context_key = "abc123"
        headers = client._headers()
        assert headers == {
            "Content-Type": "application/json",
            "X-MitsContextKey": "abc123",
        }
        client.close()


class TestMelCloudClientLogin:
    def test_login_success(self):
        client = MelCloudClient(
            base_url="https://example.com",
            email="test@example.com",
            password="secret",
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "ErrorId": None,
            "LoginData": {"ContextKey": "ctx-key-123"},
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(client.client, "post", return_value=mock_response) as mock_post:
            result = client.login()

        assert result is True
        assert client.context_key == "ctx-key-123"
        assert not hasattr(client, "password")  # Password deleted after login
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert "/Login/ClientLogin" in call_args[0][0]
        client.close()

    def test_login_api_error(self):
        client = MelCloudClient(
            base_url="https://example.com",
            email="test@example.com",
            password="secret",
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
        client = MelCloudClient(
            base_url="https://example.com",
            email="test@example.com",
            password="secret",
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
        assert client.context_key is None
        client.close()

    def test_login_http_error(self):
        client = MelCloudClient(
            base_url="https://example.com",
            email="test@example.com",
            password="secret",
        )

        with patch.object(
            client.client,
            "post",
            side_effect=httpx.HTTPError("Connection failed"),
        ):
            result = client.login()

        assert result is False
        assert client.context_key is None
        client.close()


class TestMelCloudClientGetDeviceState:
    def test_get_device_state_success(self):
        client = MelCloudClient(
            base_url="https://example.com",
            email="test@example.com",
            password="secret",
        )
        client.context_key = "ctx-key-123"

        device_data = {
            "DeviceID": 12345,
            "Power": True,
            "SetTemperature": 22.0,
            "RoomTemperature": 24.5,
            "OperationMode": AC_MODE_COOL,
        }

        mock_response = MagicMock()
        mock_response.json.return_value = device_data
        mock_response.raise_for_status = MagicMock()

        with patch.object(client.client, "get", return_value=mock_response) as mock_get:
            result = client.get_device_state(device_id=12345, building_id=100)

        assert result == device_data
        mock_get.assert_called_once()
        call_args = mock_get.call_args
        assert "/Device/Get" in call_args[0][0]
        assert call_args[1]["params"] == {"id": 12345, "buildingID": 100}
        client.close()

    def test_get_device_state_http_error(self):
        client = MelCloudClient(
            base_url="https://example.com",
            email="test@example.com",
            password="secret",
        )
        client.context_key = "ctx-key-123"

        with patch.object(
            client.client,
            "get",
            side_effect=httpx.HTTPError("Server error"),
        ):
            result = client.get_device_state(device_id=12345, building_id=100)

        assert result is None
        client.close()


class TestMelCloudClientSetTemperature:
    def test_set_temperature_success(self):
        client = MelCloudClient(
            base_url="https://example.com",
            email="test@example.com",
            password="secret",
            building_id=100,
        )
        client.context_key = "ctx-key-123"

        device_state = {
            "DeviceID": 12345,
            "Power": False,
            "SetTemperature": 20.0,
            "RoomTemperature": 24.5,
            "OperationMode": AC_MODE_HEAT,
            "SetFanSpeed": 3,
        }

        mock_get_response = MagicMock()
        mock_get_response.json.return_value = device_state.copy()
        mock_get_response.raise_for_status = MagicMock()

        mock_post_response = MagicMock()
        mock_post_response.json.return_value = {"SetTemperature": 23.0}
        mock_post_response.raise_for_status = MagicMock()

        with (
            patch.object(client.client, "get", return_value=mock_get_response),
            patch.object(client.client, "post", return_value=mock_post_response) as mock_post,
        ):
            result = client.set_temperature(
                device_id=12345,
                setpoint=23.0,
                power=True,
                mode="cool",
                fan_speed=2,
            )

        assert result is True
        # Verify the POST was called with modified state
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert "/Device/SetAta" in call_args[0][0]
        posted_json = call_args[1]["json"]
        assert posted_json["Power"] is True
        assert posted_json["SetTemperature"] == 23.0
        assert posted_json["OperationMode"] == AC_MODE_COOL
        assert posted_json["SetFanSpeed"] == 2
        assert posted_json["EffectiveFlags"] == 0x1F
        assert posted_json["HasPendingCommand"] is True
        client.close()

    def test_set_temperature_clamps_values(self):
        client = MelCloudClient(
            base_url="https://example.com",
            email="test@example.com",
            password="secret",
            building_id=100,
        )
        client.context_key = "ctx-key-123"

        device_state = {"DeviceID": 12345}

        mock_get_response = MagicMock()
        mock_get_response.json.return_value = device_state.copy()
        mock_get_response.raise_for_status = MagicMock()

        mock_post_response = MagicMock()
        mock_post_response.json.return_value = {"SetTemperature": 16.0}
        mock_post_response.raise_for_status = MagicMock()

        with (
            patch.object(client.client, "get", return_value=mock_get_response),
            patch.object(client.client, "post", return_value=mock_post_response) as mock_post,
        ):
            # Test clamping below minimum
            result = client.set_temperature(device_id=12345, setpoint=10.0)

        assert result is True
        posted_json = mock_post.call_args[1]["json"]
        assert posted_json["SetTemperature"] == 16.0  # Clamped to min

        # Test clamping above maximum
        mock_post_response.json.return_value = {"SetTemperature": 31.0}
        with (
            patch.object(client.client, "get", return_value=mock_get_response),
            patch.object(client.client, "post", return_value=mock_post_response) as mock_post,
        ):
            result = client.set_temperature(device_id=12345, setpoint=40.0)

        assert result is True
        posted_json = mock_post.call_args[1]["json"]
        assert posted_json["SetTemperature"] == 31.0  # Clamped to max
        client.close()

    def test_set_temperature_state_retrieval_failure(self):
        client = MelCloudClient(
            base_url="https://example.com",
            email="test@example.com",
            password="secret",
            building_id=100,
        )
        client.context_key = "ctx-key-123"

        with patch.object(
            client.client,
            "get",
            side_effect=httpx.HTTPError("Server error"),
        ):
            result = client.set_temperature(device_id=12345, setpoint=23.0)

        assert result is False
        client.close()

    def test_set_temperature_post_http_error(self):
        client = MelCloudClient(
            base_url="https://example.com",
            email="test@example.com",
            password="secret",
            building_id=100,
        )
        client.context_key = "ctx-key-123"

        device_state = {"DeviceID": 12345}

        mock_get_response = MagicMock()
        mock_get_response.json.return_value = device_state.copy()
        mock_get_response.raise_for_status = MagicMock()

        with (
            patch.object(client.client, "get", return_value=mock_get_response),
            patch.object(
                client.client,
                "post",
                side_effect=httpx.HTTPError("Server error"),
            ),
        ):
            result = client.set_temperature(device_id=12345, setpoint=23.0)

        assert result is False
        client.close()

    def test_set_temperature_uses_custom_building_id(self):
        client = MelCloudClient(
            base_url="https://example.com",
            email="test@example.com",
            password="secret",
            building_id=100,
        )
        client.context_key = "ctx-key-123"

        mock_get_response = MagicMock()
        mock_get_response.json.return_value = {"DeviceID": 12345}
        mock_get_response.raise_for_status = MagicMock()

        mock_post_response = MagicMock()
        mock_post_response.json.return_value = {"SetTemperature": 23.0}
        mock_post_response.raise_for_status = MagicMock()

        with (
            patch.object(client.client, "get", return_value=mock_get_response) as mock_get,
            patch.object(client.client, "post", return_value=mock_post_response),
        ):
            client.set_temperature(device_id=12345, setpoint=23.0, building_id=999)

        # Verify custom building_id was used in GET
        call_args = mock_get.call_args
        assert call_args[1]["params"]["buildingID"] == 999
        client.close()


class TestMelCloudClientClose:
    def test_close_calls_client_close(self):
        client = MelCloudClient(
            base_url="https://example.com",
            email="test@example.com",
            password="secret",
        )

        with patch.object(client.client, "close") as mock_close:
            client.close()

        mock_close.assert_called_once()


class TestModeMap:
    def test_mode_map_values(self):
        assert MODE_MAP["heat"] == AC_MODE_HEAT
        assert MODE_MAP["dry"] == AC_MODE_DRY
        assert MODE_MAP["cool"] == AC_MODE_COOL
        assert MODE_MAP["fan"] == AC_MODE_FAN
        assert MODE_MAP["auto"] == AC_MODE_AUTO

    def test_mode_constants(self):
        assert AC_MODE_HEAT == 1
        assert AC_MODE_DRY == 2
        assert AC_MODE_COOL == 3
        assert AC_MODE_FAN == 7
        assert AC_MODE_AUTO == 8
