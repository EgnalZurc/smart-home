"""Integration tests for error tracking system (F0.30)."""
import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI
from unittest.mock import MagicMock
from api import routes
from subscription_manager import SubscriptionManager, SubscriptionConfig
from error_tracker import ErrorTracker


def _setup():
    tracker = ErrorTracker()
    ac = MagicMock()
    state = MagicMock()
    state.state = "off"
    state.control_mode = "auto"
    state.average_temp = 25.0
    state.average_humidity = 40.0
    state.active_sensors = 5
    state.total_sensors = 5
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
    ac.current_state = state
    ac.config.min_setpoint = 19.0
    ac.config.max_setpoint = 30.0

    mqtt = MagicMock()
    mqtt.sensor_names = []
    mqtt.is_connected = True

    sub = SubscriptionManager(SubscriptionConfig())
    routes.mqtt_handler = mqtt
    routes.ac_controller = ac
    routes.subscription_manager = sub
    routes.error_tracker = tracker
    routes.energy_tracker = None

    app = FastAPI()
    app.include_router(routes.router)
    return TestClient(app), tracker


class TestF0ErrorTrackingAPI:
    def test_get_errors_empty(self):
        client, _ = _setup()
        r = client.get("/api/errors")
        assert r.status_code == 200
        assert r.json() == {"errors": [], "has_errors": False}

    def test_get_errors_with_active_error(self):
        client, tracker = _setup()
        tracker.register("melcloud_error", "error", "MELCloud unreachable", "melcloud")
        r = client.get("/api/errors")
        data = r.json()
        assert data["has_errors"] is True
        assert data["errors"][0]["severity"] == "error"

    def test_errors_cleared_after_resolution(self):
        client, tracker = _setup()
        tracker.register("sensor_alert", "warning", "Sensor offline", "sensors")
        tracker.clear("sensor_alert")
        assert client.get("/api/errors").json()["has_errors"] is False

    def test_multiple_errors_returned(self):
        client, tracker = _setup()
        tracker.register("err1", "error", "E1", "s1")
        tracker.register("err2", "warning", "E2", "s2")
        assert len(client.get("/api/errors").json()["errors"]) == 2

    def test_error_has_required_fields(self):
        client, tracker = _setup()
        tracker.register("test", "error", "Test message", "test_source")
        error = client.get("/api/errors").json()["errors"][0]
        for field in ("id", "severity", "message", "source", "timestamp"):
            assert field in error
