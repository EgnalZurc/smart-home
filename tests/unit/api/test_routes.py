"""Unit tests for api/routes.py"""
import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from fastapi import FastAPI
from api import routes
from subscription_manager import SubscriptionManager, SubscriptionConfig
from error_tracker import ErrorTracker


def _mock_ac_state(control_mode="auto", action="off"):
    state = MagicMock()
    state.state = action
    state.average_temp = 26.5
    state.average_humidity = 40.0
    state.active_sensors = 5
    state.total_sensors = 5
    state.control_mode = control_mode
    state.sensor_alert = False
    state.melcloud_error = False
    state.setpoint = 24.0
    state.ac_mode = "cool"
    state.fan_speed = 0
    state.ac_real_power = False
    state.ac_real_mode = "cool"
    state.ac_real_fan_speed = 0
    state.ac_real_setpoint = 24.0
    state.ac_real_room_temp = 25.0
    state.ac_real_last_update = 1000.0
    state.manual_params = MagicMock(mode="cool", fan_speed=0, temperature=23.0)
    state.last_update = 1000.0
    return state


@pytest.fixture
def client(error_tracker):
    # Use full MagicMock for ac_controller so we control current_state
    ac = MagicMock()
    ac.current_state = _mock_ac_state()
    ac.config.target_temperature = 26.0
    ac.config.min_setpoint = 19.0
    ac.config.max_setpoint = 30.0
    ac.config.sensor_timeout = 3600
    ac.config.hysteresis_on = 0.5
    ac.config.hysteresis_off = 0.3
    ac.config.loop_interval = 10
    ac.config.ac_mode = "cool"
    ac.config.fan_speed_max = 3
    ac.config.fan_speed_modulate = 0
    ac.get_history.return_value = []

    mqtt = MagicMock()
    mqtt.sensor_names = ["Salon"]
    mqtt.readings = {}
    mqtt.is_connected = True

    sub = SubscriptionManager(SubscriptionConfig())
    routes.mqtt_handler = mqtt
    routes.ac_controller = ac
    routes.subscription_manager = sub
    routes.error_tracker = error_tracker
    routes.energy_tracker = None

    app = FastAPI()
    app.include_router(routes.router)
    return TestClient(app)


class TestGetStatus:
    def test_status_200(self, client):
        r = client.get("/api/status")
        assert r.status_code == 200

    def test_status_has_required_fields(self, client):
        d = client.get("/api/status").json()
        for field in ("average_temperature", "ac_state", "ac_real", "manual_params", "mqtt_connected"):
            assert field in d, f"Missing field: {field}"

    def test_manual_params_always_present(self, client):
        assert client.get("/api/status").json()["manual_params"] is not None


class TestGetSensors:
    def test_sensors_200(self, client):
        r = client.get("/api/sensors")
        assert r.status_code == 200
        assert "sensors" in r.json()

    def test_sensors_offline_when_no_reading(self, client):
        sensors = client.get("/api/sensors").json()["sensors"]
        assert sensors[0]["online"] is False
        assert sensors[0]["temperature"] is None


class TestPostConfig:
    def test_no_changes_returns_400(self, client):
        assert client.post("/api/config", json={}).status_code == 400

    def test_temp_out_of_range_returns_400(self, client):
        assert client.post("/api/config", json={"target_temperature": 5.0}).status_code == 400

    def test_valid_update_returns_200(self, client):
        r = client.post("/api/config", json={"target_temperature": 25.0})
        assert r.status_code == 200


class TestPostControlMode:
    def test_invalid_mode_returns_400(self, client):
        assert client.post("/api/control_mode", json={"mode": "invalid"}).status_code == 400

    def test_valid_mode_off_returns_200(self, client):
        r = client.post("/api/control_mode", json={"mode": "off"})
        assert r.status_code == 200

    def test_switching_to_manual_calls_set_manual_params(self, client):
        r = client.post("/api/control_mode", json={"mode": "manual"})
        assert r.status_code == 200
        # set_manual_params should have been called
        routes.ac_controller.set_manual_params.assert_called_once()


class TestGetErrors:
    def test_no_errors_returns_empty(self, client, error_tracker):
        r = client.get("/api/errors")
        assert r.status_code == 200
        assert r.json() == {"errors": [], "has_errors": False}

    def test_with_errors_returns_list(self, client, error_tracker):
        error_tracker.register("test_err", "error", "Test", "test")
        r = client.get("/api/errors")
        assert r.json()["has_errors"] is True
        assert len(r.json()["errors"]) == 1
