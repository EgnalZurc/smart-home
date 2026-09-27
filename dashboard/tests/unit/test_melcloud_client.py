"""Unit tests for melcloud_client.py"""
import pytest
from unittest.mock import patch, MagicMock
from melcloud_client import MelCloudClient


@pytest.fixture
def client():
    return MelCloudClient("https://app.melcloud.com", "test@test.com", "pass123", 456, timeout=5.0)


class TestLogin:
    def test_login_success(self, client):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"ErrorId": None, "LoginData": {"ContextKey": "abc123"}}
        with patch.object(client.client, "post", return_value=resp):
            assert client.login() is True
            assert client.context_key == "abc123"

    def test_login_failure_error_id(self, client):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"ErrorId": 1, "LoginData": None}
        with patch.object(client.client, "post", return_value=resp):
            assert client.login() is False

    def test_login_http_error(self, client):
        import httpx
        with patch.object(client.client, "post", side_effect=httpx.HTTPError("fail")):
            assert client.login() is False

    def test_login_deletes_password_on_success(self, client):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"ErrorId": None, "LoginData": {"ContextKey": "key"}}
        with patch.object(client.client, "post", return_value=resp):
            client.login()
        assert not hasattr(client, "password") or client.password is None


class TestGetDeviceState:
    def test_success(self, client):
        client.context_key = "key"
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"Power": True, "RoomTemperature": 25.0}
        with patch.object(client.client, "get", return_value=resp):
            state = client.get_device_state(123, 456)
            assert state["Power"] is True

    def test_http_error_returns_none(self, client):
        client.context_key = "key"
        import httpx
        with patch.object(client.client, "get", side_effect=httpx.HTTPError("fail")):
            assert client.get_device_state(123, 456) is None


class TestSetTemperature:
    def test_success(self, client):
        client.context_key = "key"
        current = {
            "Power": False, "OperationMode": 3, "SetTemperature": 24.0,
            "SetFanSpeed": 0, "RoomTemperature": 25.0,
        }
        get_resp = MagicMock()
        get_resp.status_code = 200
        get_resp.json.return_value = current
        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.json.return_value = {"SetTemperature": 22.0, **current}
        with patch.object(client.client, "get", return_value=get_resp):
            with patch.object(client.client, "post", return_value=post_resp):
                result = client.set_temperature(123, 22.0, power=True, mode="cool", fan_speed=2)
                assert result is True

    def test_clamps_setpoint_to_valid_range(self, client):
        """Setpoint must be clamped to [16, 31]."""
        client.context_key = "key"
        called_with = {}
        current = {"Power": False, "OperationMode": 3, "SetTemperature": 24.0, "SetFanSpeed": 0}
        get_resp = MagicMock()
        get_resp.status_code = 200
        get_resp.json.return_value = current

        def capture_post(url, json=None, headers=None, timeout=None):
            called_with["SetTemperature"] = json.get("SetTemperature")
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {**current, "SetTemperature": json.get("SetTemperature")}
            return resp

        with patch.object(client.client, "get", return_value=get_resp):
            with patch.object(client.client, "post", side_effect=capture_post):
                client.set_temperature(123, 5.0, power=True)   # below 16 ? clamped to 16
                assert called_with["SetTemperature"] >= 16.0

    def test_get_state_failure_returns_false(self, client):
        client.context_key = "key"
        with patch.object(client, "get_device_state", return_value=None):
            result = client.set_temperature(123, 22.0, power=True)
            assert result is False
