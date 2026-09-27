"""Shared fixtures for all tests.

pytest.ini sets pythonpath = src/backend so all imports work directly.
"""
import pytest
from unittest.mock import MagicMock


# ── Backend component fixtures ────────────────────────────────────────────────

@pytest.fixture
def error_tracker():
    from error_tracker import ErrorTracker
    return ErrorTracker()


@pytest.fixture
def sm_config():
    from controllers.state_machine import StateMachineConfig
    return StateMachineConfig(
        hysteresis_on=0.5,
        hysteresis_off=0.3,
        min_setpoint=19.0,
        max_setpoint=30.0,
        cooldown_seconds=180,
        sensor_alert_seconds=3600,
        melcloud_max_failures=100,
    )


@pytest.fixture
def mock_mqtt():
    """Minimal MqttHandler mock."""
    m = MagicMock()
    m.sensor_names = ["Salon", "Despacho"]
    m.readings = {}
    m.history = {"Salon": [], "Despacho": []}
    m.is_connected = True
    return m


@pytest.fixture
def mock_melcloud():
    """MelCloudClient mock that succeeds by default."""
    m = MagicMock()
    m.login.return_value = True
    m.get_device_state.return_value = {
        "Power": True,
        "OperationMode": 3,
        "SetTemperature": 24.0,
        "SetFanSpeed": 0,
        "RoomTemperature": 25.0,
    }
    m.set_temperature.return_value = True
    return m


@pytest.fixture
def ac_controller(mock_mqtt, mock_melcloud, error_tracker):
    """ACController wired with mocks, error tracker injected."""
    from controllers.ac_controller import ACController, ControlConfig
    config = ControlConfig(
        target_temperature=26.0,
        hysteresis_on=0.5,
        hysteresis_off=0.3,
        loop_interval=10,
        device_id=123,
        building_id=456,
    )
    ctrl = ACController(mock_mqtt, mock_melcloud, config)
    ctrl.set_error_tracker(error_tracker)
    return ctrl


@pytest.fixture
def fastapi_client(ac_controller, mock_mqtt, mock_melcloud, error_tracker):
    """FastAPI TestClient with all route dependencies injected."""
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from api import routes
    from subscription_manager import SubscriptionManager, SubscriptionConfig

    sub = SubscriptionManager(SubscriptionConfig())

    routes.mqtt_handler = mock_mqtt
    routes.ac_controller = ac_controller
    routes.subscription_manager = sub
    routes.error_tracker = error_tracker
    routes.energy_tracker = None

    app = FastAPI()
    app.include_router(routes.router)

    return TestClient(app)
