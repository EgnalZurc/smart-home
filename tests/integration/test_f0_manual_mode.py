"""Integration tests for manual mode (F0.34, F0.36)."""
import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from fastapi import FastAPI
from api import routes
from subscription_manager import SubscriptionManager, SubscriptionConfig
from error_tracker import ErrorTracker
from controllers.state_machine import ManualParams


def _setup(control_mode="manual"):
    tracker = ErrorTracker()
    ac = MagicMock()
    state = MagicMock()
    state.state = "manual"
    state.control_mode = control_mode
    state.setpoint = 22.0
    state.fan_speed = 2
    state.ac_mode = "cool"
    state.average_temp = 26.0
    state.average_humidity = 40.0
    state.active_sensors = 5
    state.total_sensors = 5
    state.sensor_alert = False
    state.melcloud_error = False
    state.ac_real_power = True
    state.ac_real_mode = "cool"
    state.ac_real_fan_speed = 2
    state.ac_real_setpoint = 22.0
    state.ac_real_room_temp = 24.0
    state.ac_real_last_update = 1000.0
    state.manual_params = ManualParams(temperature=22.0, fan_speed=2, mode="cool")
    state.last_update = 1000.0
    ac.current_state = state
    ac.config.target_temperature = 26.0
    ac.config.min_setpoint = 19.0
    ac.config.max_setpoint = 30.0
    ac.config.sensor_timeout = 3600
    ac.config.device_id = 123
    ac.config.building_id = 456

    mqtt = MagicMock()
    mqtt.sensor_names = ["Salon"]
    mqtt.readings = {}
    mqtt.is_connected = True

    mc = MagicMock()
    mc.set_temperature.return_value = True
    ac.melcloud = mc

    sub = SubscriptionManager(SubscriptionConfig())
    routes.mqtt_handler = mqtt
    routes.ac_controller = ac
    routes.subscription_manager = sub
    routes.error_tracker = tracker
    routes.energy_tracker = None

    app = FastAPI()
    app.include_router(routes.router)
    return TestClient(app), ac, tracker


class TestF0ManualMode:
    def test_switching_to_manual_pre_populates_params(self):
        client, ac, _ = _setup("auto")
        ac.current_state.setpoint = 21.0
        ac.current_state.fan_speed = 3
        ac.current_state.ac_mode = "cool"
        r = client.post("/api/control_mode", json={"mode": "manual"})
        assert r.status_code == 200
        ac.set_manual_params.assert_called_once_with(
            temperature=21.0, fan_speed=3, mode="cool"
        )

    def test_manual_param_update_calls_melcloud(self):
        client, ac, _ = _setup("manual")
        r = client.post("/api/manual_param?param=temperature&value=20.0")
        assert r.status_code == 200
        ac.melcloud.set_temperature.assert_called_once()

    def test_manual_param_invalid_returns_400(self):
        client, _, _ = _setup("manual")
        assert client.post("/api/manual_param?param=unknown&value=22.0").status_code == 400

    def test_manual_param_temp_out_of_range_returns_400(self):
        client, _, _ = _setup("manual")
        assert client.post("/api/manual_param?param=temperature&value=5.0").status_code == 400

    def test_manual_param_not_in_manual_mode_returns_400(self):
        client, ac, _ = _setup("auto")
        r = client.post("/api/manual_param?param=temperature&value=22.0")
        assert r.status_code == 400

    def test_system_off_mode_calls_set_control_mode(self):
        client, ac, _ = _setup("auto")
        r = client.post("/api/control_mode", json={"mode": "off"})
        assert r.status_code == 200
        ac.set_control_mode.assert_called_with("off")
