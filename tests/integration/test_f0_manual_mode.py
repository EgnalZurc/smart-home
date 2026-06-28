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


class TestNoOptimisticUI:
    """Actions send requests and show toast; UI updates only via next poll (AC-MANUAL.5)."""

    def test_manual_param_response_has_applied_values(self):
        """API response must include applied values so the queue can track acknowledged state."""
        client, ac, _ = _setup("manual")
        ac.current_state.manual_params = ManualParams(temperature=22.0, fan_speed=1, mode="cool")
        r = client.post("/api/manual_param?param=fan_speed&value=2")
        assert r.status_code == 200
        data = r.json()
        # Response must include 'applied' so ManualControlQueue can update lastAcknowledged
        assert "applied" in data

    def test_manual_param_applied_contains_all_fields(self):
        client, ac, _ = _setup("manual")
        r = client.post("/api/manual_param?param=mode&value=heat")
        assert r.status_code == 200
        applied = r.json()["applied"]
        assert "mode" in applied
        assert "fan_speed" in applied
        assert "temperature" in applied

    def test_status_reflects_server_state_not_local(self):
        """After a param change, /api/status reflects server state (controller state machine)."""
        client, ac, _ = _setup("manual")
        # Simulate server applying temperature=20.0
        ac.current_state.manual_params = ManualParams(temperature=20.0, fan_speed=0, mode="cool")
        client.post("/api/manual_param?param=temperature&value=20.0")
        status = client.get("/api/status").json()
        assert status["manual_params"]["temperature"] == 20.0

    def test_control_mode_change_response_200(self):
        """Switching control mode returns 200 - UI updates from next /api/status poll."""
        client, ac, _ = _setup("auto")
        r = client.post("/api/control_mode", json={"mode": "manual"})
        assert r.status_code == 200

    def test_target_temp_change_persists_to_config(self):
        """Changing target temperature via /api/config persists to controller config."""
        client, ac, _ = _setup("auto")
        r = client.post("/api/config", json={"target_temperature": 24.0})
        assert r.status_code == 200
        ac.update_config.assert_called_once()


class TestPendingStateFeedback:
    """Pending state: API contract for manualQueue.onPollUpdate (AC-MANUAL.7)."""

    def test_manual_param_response_applied_mode_matches_sent(self):
        """Queue uses applied.mode to decide when to clear pending state."""
        client, ac, _ = _setup("manual")
        ac.current_state.manual_params = ManualParams(temperature=22.0, fan_speed=0, mode="heat")
        r = client.post("/api/manual_param?param=mode&value=heat")
        assert r.status_code == 200
        assert r.json()["applied"]["mode"] == "heat"

    def test_manual_param_response_applied_fan_matches_sent(self):
        client, ac, _ = _setup("manual")
        ac.current_state.manual_params = ManualParams(temperature=22.0, fan_speed=2, mode="cool")
        r = client.post("/api/manual_param?param=fan_speed&value=2")
        assert r.status_code == 200
        assert r.json()["applied"]["fan_speed"] == 2

    def test_manual_param_response_applied_temperature_matches_sent(self):
        client, ac, _ = _setup("manual")
        ac.current_state.manual_params = ManualParams(temperature=20.5, fan_speed=0, mode="cool")
        r = client.post("/api/manual_param?param=temperature&value=20.5")
        assert r.status_code == 200
        assert abs(r.json()["applied"]["temperature"] - 20.5) < 0.15

    def test_status_manual_params_has_all_fields_for_pending_clear(self):
        """After any change, /api/status must expose manual_params with all 3 fields
        so onPollUpdate can check mode, fan_speed, and temperature."""
        client, ac, _ = _setup("manual")
        status = client.get("/api/status").json()
        mp = status["manual_params"]
        assert "mode" in mp
        assert "fan_speed" in mp
        assert "temperature" in mp

    def test_pending_cleared_when_server_confirms_temperature(self):
        """Simulate: send temp=20.0, server later returns temp=20.0 in status -> matches."""
        client, ac, _ = _setup("manual")
        ac.current_state.manual_params = ManualParams(temperature=20.0, fan_speed=0, mode="cool")
        client.post("/api/manual_param?param=temperature&value=20.0")
        # Next poll returns manual_params.temperature=20.0 -> onPollUpdate clears pending
        status = client.get("/api/status").json()
        assert abs(status["manual_params"]["temperature"] - 20.0) < 0.15
