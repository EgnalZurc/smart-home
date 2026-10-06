"""Unit tests for FastAPI endpoints in main.py.

Tests the API endpoints without running the full lifespan
(MQTT, MELCloud connections, etc.)
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Mock the dependencies before importing main
with patch.dict(
    "os.environ",
    {
        "MELCLOUD_EMAIL": "test@test.com",
        "MELCLOUD_PASSWORD": "testpwd",
        "MELCLOUD_DEVICE_ID": "12345",
        "MELCLOUD_BUILDING_ID": "67890",
    },
):
    # We need to mock modules that connect to external services

    # Create mock modules for dependencies that require connections
    mock_mqtt = MagicMock()
    mock_mqtt_handler = MagicMock()
    mock_melcloud = MagicMock()
    mock_z2m = MagicMock()

    from main import app


@pytest.fixture
def client():
    """Create test client without lifespan."""
    # Override the lifespan to do nothing for tests
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def mock_components():
    """Mock all global components."""
    import main

    # Create mocks
    mock_mqtt_handler = MagicMock()
    mock_mqtt_handler.is_connected = True
    mock_mqtt_handler.sensor_names = ["sensor1", "sensor2"]
    mock_mqtt_handler.readings = {}
    mock_mqtt_handler.history = {}
    mock_mqtt_handler._lock = MagicMock()
    mock_mqtt_handler._lock.__enter__ = MagicMock()
    mock_mqtt_handler._lock.__exit__ = MagicMock()

    mock_melcloud = MagicMock()
    mock_melcloud.get_device_state.return_value = {
        "Power": True,
        "OperationMode": 3,
        "SetFanSpeed": 2,
        "SetTemperature": 23.0,
        "RoomTemperature": 25.0,
    }

    mock_controller = MagicMock()
    mock_state = MagicMock()
    mock_state.average_temp = 25.0
    mock_state.average_humidity = 55.0
    mock_state.state = "modulating"
    mock_state.setpoint = 22.0
    mock_state.ac_mode = "cool"
    mock_state.fan_speed = 0
    mock_state.active_sensors = 3
    mock_state.total_sensors = 5
    mock_state.control_mode = "auto"
    mock_state.sensor_alert = False
    mock_state.melcloud_error = False
    mock_state.manual_params = MagicMock()
    mock_state.manual_params.mode = "cool"
    mock_state.manual_params.fan_speed = 0
    mock_state.manual_params.temperature = 23.0
    mock_state.last_update = 1234567890.0
    mock_state.ac_real_power = True
    mock_state.ac_real_mode = "cool"
    mock_state.ac_real_fan_speed = 2
    mock_state.ac_real_setpoint = 23.0
    mock_state.ac_real_room_temp = 25.0
    mock_state.ac_real_last_update = 1234567890.0
    mock_controller.current_state = mock_state
    mock_controller.state = mock_state
    mock_controller.config = MagicMock()
    mock_controller.config.target_temperature = 25.0
    mock_controller.config.hysteresis_on = 0.5
    mock_controller.config.hysteresis_off = 0.3
    mock_controller.config.min_setpoint = 19.0
    mock_controller.config.max_setpoint = 30.0
    mock_controller.config.loop_interval = 45
    mock_controller.config.sensor_timeout = 600
    mock_controller.config.ac_mode = "cool"
    mock_controller.config.fan_speed_max = 3
    mock_controller.config.fan_speed_modulate = 0
    mock_controller.config.device_id = 12345
    mock_controller.config.building_id = 67890
    mock_controller.get_history.return_value = []
    mock_controller.melcloud = mock_melcloud

    mock_sub_manager = MagicMock()
    mock_sub_manager.get_cached.return_value = {
        "temperature": 28.0,
        "humidity": 40.0,
        "aqi": 35,
    }
    mock_sub_manager.cache = {"outdoor": MagicMock(timestamp=1234567890.0)}
    mock_sub_manager.get_stats.return_value = {
        "subscriptions": 2,
        "cached_services": 2,
        "total_cache_size_bytes": 1000,
        "total_cache_size_kb": 0.98,
        "services": [],
    }

    mock_error_tracker = MagicMock()
    mock_error_tracker.get_active.return_value = []

    # Inject mocks
    original_mqtt = main.mqtt_handler
    original_melcloud = main.melcloud_client
    original_controller = main.ac_controller
    original_sub = main.subscription_manager
    original_error = main.error_tracker

    main.mqtt_handler = mock_mqtt_handler
    main.melcloud_client = mock_melcloud
    main.ac_controller = mock_controller
    main.subscription_manager = mock_sub_manager
    main.error_tracker = mock_error_tracker

    yield {
        "mqtt_handler": mock_mqtt_handler,
        "melcloud_client": mock_melcloud,
        "ac_controller": mock_controller,
        "subscription_manager": mock_sub_manager,
        "error_tracker": mock_error_tracker,
    }

    # Restore originals
    main.mqtt_handler = original_mqtt
    main.melcloud_client = original_melcloud
    main.ac_controller = original_controller
    main.subscription_manager = original_sub
    main.error_tracker = original_error


class TestHealthEndpoints:
    """Tests for health check endpoints."""

    def test_health_endpoint(self, client):
        """GET /health should return online status."""
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["online"] is True
        assert data["service"] == "ac"

    def test_health_api_endpoint(self, client):
        """GET /api/health/ac should return online status."""
        response = client.get("/api/health/ac")

        assert response.status_code == 200
        data = response.json()
        assert data["online"] is True


class TestStatusEndpoint:
    """Tests for /api/ac/status endpoint."""

    def test_get_status(self, client, mock_components):
        """GET /api/ac/status should return full status."""
        response = client.get("/api/ac/status")

        assert response.status_code == 200
        data = response.json()

        assert data["average_temperature"] == 25.0
        assert data["average_humidity"] == 55.0
        assert data["target_temperature"] == 25.0
        assert "ac_state" in data
        assert "ac_real" in data
        assert "manual_params" in data


class TestSensorsEndpoint:
    """Tests for /api/ac/sensors endpoint."""

    def test_get_sensors_empty(self, client, mock_components):
        """GET /api/ac/sensors should return sensor list."""
        response = client.get("/api/ac/sensors")

        assert response.status_code == 200
        data = response.json()
        assert "sensors" in data


class TestConfigEndpoints:
    """Tests for config endpoints."""

    def test_get_config(self, client, mock_components):
        """GET /api/ac/config should return configuration."""
        response = client.get("/api/ac/config")

        assert response.status_code == 200
        data = response.json()

        assert data["target_temperature"] == 25.0
        assert data["hysteresis_on"] == 0.5
        assert data["hysteresis_off"] == 0.3

    def test_post_config_updates_values(self, client, mock_components):
        """POST /api/ac/config should update configuration."""
        response = client.post("/api/ac/config", json={"target_temperature": 24.0})

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "updated"
        assert "target_temperature" in data["changes"]

    def test_post_config_no_changes_returns_400(self, client, mock_components):
        """POST /api/ac/config with no changes should return 400."""
        response = client.post("/api/ac/config", json={})

        assert response.status_code == 400


class TestControlEndpoints:
    """Tests for control mode endpoints."""

    def test_set_control_mode_auto(self, client, mock_components):
        """POST /api/ac/control with mode=auto should succeed."""
        response = client.post("/api/ac/control", json={"mode": "auto"})

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["control_mode"] == "auto"

    def test_set_control_mode_manual(self, client, mock_components):
        """POST /api/ac/control with mode=manual should succeed."""
        response = client.post("/api/ac/control", json={"mode": "manual"})

        assert response.status_code == 200
        data = response.json()
        assert data["control_mode"] == "manual"

    def test_set_control_mode_off(self, client, mock_components):
        """POST /api/ac/control with mode=off should succeed."""
        response = client.post("/api/ac/control", json={"mode": "off"})

        assert response.status_code == 200
        data = response.json()
        assert data["control_mode"] == "off"

    def test_set_control_mode_invalid(self, client, mock_components):
        """POST /api/ac/control with invalid mode should return 400."""
        response = client.post("/api/ac/control", json={"mode": "invalid"})

        assert response.status_code == 400


class TestManualParamsEndpoints:
    """Tests for manual parameters endpoints."""

    def test_set_manual_params(self, client, mock_components):
        """POST /api/ac/manual should set parameters."""
        mock_components["ac_controller"].melcloud.set_temperature.return_value = True

        response = client.post(
            "/api/ac/manual", json={"mode": "cool", "fan_speed": 2, "temperature": 22.0}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

    def test_set_manual_params_invalid_temperature(self, client, mock_components):
        """POST /api/ac/manual with invalid temp should return 400."""
        response = client.post(
            "/api/ac/manual",
            json={
                "mode": "cool",
                "fan_speed": 0,
                "temperature": 15.0,  # Below min_setpoint
            },
        )

        assert response.status_code == 400

    def test_set_manual_params_invalid_fan_speed(self, client, mock_components):
        """POST /api/ac/manual with invalid fan speed should return 400."""
        response = client.post(
            "/api/ac/manual",
            json={
                "mode": "cool",
                "fan_speed": 5,  # Invalid
                "temperature": 23.0,
            },
        )

        assert response.status_code == 400

    def test_set_manual_params_invalid_mode(self, client, mock_components):
        """POST /api/ac/manual with invalid mode should return 400."""
        response = client.post(
            "/api/ac/manual",
            json={
                "mode": "turbo",  # Invalid
                "fan_speed": 0,
                "temperature": 23.0,
            },
        )

        assert response.status_code == 400


class TestOutdoorEndpoint:
    """Tests for outdoor temperature endpoint."""

    def test_get_outdoor(self, client, mock_components):
        """GET /api/ac/outdoor should return outdoor data."""
        response = client.get("/api/ac/outdoor")

        assert response.status_code == 200
        data = response.json()
        assert data["temperature"] == 28.0
        assert data["humidity"] == 40.0
        assert data["aqi"] == 35


class TestErrorsEndpoint:
    """Tests for errors endpoint."""

    def test_get_errors_empty(self, client, mock_components):
        """GET /api/ac/errors should return error list."""
        response = client.get("/api/ac/errors")

        assert response.status_code == 200
        data = response.json()
        assert data["errors"] == []
        assert data["has_errors"] is False

    def test_get_errors_with_errors(self, client, mock_components):
        """GET /api/ac/errors should return errors when present."""
        mock_components["error_tracker"].get_active.return_value = [
            {
                "id": "test_error",
                "severity": "error",
                "message": "Test",
                "source": "test",
            }
        ]

        response = client.get("/api/ac/errors")

        assert response.status_code == 200
        data = response.json()
        assert data["has_errors"] is True
        assert len(data["errors"]) == 1


class TestHistoryEndpoint:
    """Tests for history endpoint."""

    def test_get_history(self, client, mock_components):
        """GET /api/ac/history should return history."""
        mock_components["ac_controller"].get_history.return_value = [
            {"timestamp": 1000.0, "state": "off", "average_temp": 25.0}
        ]

        response = client.get("/api/ac/history")

        assert response.status_code == 200
        data = response.json()
        assert "history" in data


class TestSubscriptionStatsEndpoint:
    """Tests for subscription stats endpoint."""

    def test_get_subscription_stats(self, client, mock_components):
        """GET /api/ac/subscriptions/stats should return stats."""
        response = client.get("/api/ac/subscriptions/stats")

        assert response.status_code == 200
        data = response.json()
        assert data["subscriptions"] == 2


class TestZigbeeHealthEndpoint:
    """Tests for Zigbee health endpoint."""

    def test_get_zigbee_health(self, client, mock_components):
        """GET /api/ac/health/zigbee should return health status."""
        mock_components["mqtt_handler"].get_active_readings.return_value = {
            "sensor1": MagicMock(),
            "sensor2": MagicMock(),
        }

        response = client.get("/api/ac/health/zigbee")

        assert response.status_code == 200
        data = response.json()
        assert data["online"] is True
        assert data["mqtt_connected"] is True
        assert data["active_sensors"] == 2


class TestEnergyEndpoints:
    """Tests for energy endpoints."""

    def test_get_energy_current(self, client, mock_components):
        """GET /api/ac/energy/current should return placeholder."""
        response = client.get("/api/ac/energy/current")

        assert response.status_code == 200
        data = response.json()
        assert "kwh" in data

    def test_get_energy_hourly(self, client, mock_components):
        """GET /api/ac/energy/hourly should return empty data."""
        response = client.get("/api/ac/energy/hourly")

        assert response.status_code == 200
        data = response.json()
        assert data["data"] == {}

    def test_get_energy_monthly(self, client, mock_components):
        """GET /api/ac/energy/monthly should return empty data."""
        response = client.get("/api/ac/energy/monthly")

        assert response.status_code == 200
        data = response.json()
        assert data["data"] == {}


class TestAcRealEndpoint:
    """Tests for AC real state endpoint."""

    def test_get_ac_real(self, client, mock_components):
        """GET /api/ac/real should return real AC state."""
        response = client.get("/api/ac/real")

        assert response.status_code == 200
        data = response.json()
        assert data["power"] is True
        assert data["mode"] == "COLD"  # Mode 3 maps to COLD
        assert data["set_temp"] == 23.0
        assert data["room_temp"] == 25.0

    def test_get_ac_real_with_null_state(self, client, mock_components):
        """GET /api/ac/real should handle null state."""
        mock_components["ac_controller"].melcloud.get_device_state.return_value = None

        response = client.get("/api/ac/real")

        assert response.status_code == 200
        data = response.json()
        assert data["power"] is None


class TestSensorsHistoryEndpoint:
    """Tests for sensors history endpoint."""

    def test_get_sensors_history(self, client, mock_components):
        """GET /api/ac/sensors/history should return history."""
        response = client.get("/api/ac/sensors/history")

        assert response.status_code == 200

    def test_get_sensors_history_with_last_param(self, client, mock_components):
        """GET /api/ac/sensors/history with last param should limit results."""
        response = client.get("/api/ac/sensors/history?last=10")

        assert response.status_code == 200


class TestManualParamEndpoint:
    """Tests for single manual param update endpoint."""

    def test_update_manual_param_temperature(self, client, mock_components):
        """POST /api/ac/manual/param should update temperature."""
        mock_components["ac_controller"].state.control_mode = "manual"
        mock_components["ac_controller"].melcloud.set_temperature.return_value = True

        response = client.post("/api/ac/manual/param?param=temperature&value=24.0")

        assert response.status_code == 200

    def test_update_manual_param_not_in_manual_mode(self, client, mock_components):
        """POST /api/ac/manual/param should fail when not in manual mode."""
        mock_components["ac_controller"].state.control_mode = "auto"

        response = client.post("/api/ac/manual/param?param=temperature&value=24.0")

        assert response.status_code == 400

    def test_update_manual_param_invalid_param(self, client, mock_components):
        """POST /api/ac/manual/param with invalid param should fail."""
        mock_components["ac_controller"].state.control_mode = "manual"

        response = client.post("/api/ac/manual/param?param=invalid&value=24.0")

        assert response.status_code == 400

    def test_update_manual_param_invalid_temperature(self, client, mock_components):
        """POST /api/ac/manual/param with invalid temp value should fail."""
        mock_components["ac_controller"].state.control_mode = "manual"

        response = client.post(
            "/api/ac/manual/param?param=temperature&value=not_a_number"
        )

        assert response.status_code == 400

    def test_update_manual_param_temperature_out_of_range(
        self, client, mock_components
    ):
        """POST /api/ac/manual/param with out of range temp should fail."""
        mock_components["ac_controller"].state.control_mode = "manual"

        response = client.post("/api/ac/manual/param?param=temperature&value=15.0")

        assert response.status_code == 400

    def test_update_manual_param_fan_speed(self, client, mock_components):
        """POST /api/ac/manual/param should update fan speed."""
        mock_components["ac_controller"].state.control_mode = "manual"
        mock_components["ac_controller"].melcloud.set_temperature.return_value = True

        response = client.post("/api/ac/manual/param?param=fan_speed&value=2")

        assert response.status_code == 200

    def test_update_manual_param_invalid_fan_speed(self, client, mock_components):
        """POST /api/ac/manual/param with invalid fan speed should fail."""
        mock_components["ac_controller"].state.control_mode = "manual"

        response = client.post(
            "/api/ac/manual/param?param=fan_speed&value=not_a_number"
        )

        assert response.status_code == 400

    def test_update_manual_param_fan_speed_out_of_range(self, client, mock_components):
        """POST /api/ac/manual/param with out of range fan speed should fail."""
        mock_components["ac_controller"].state.control_mode = "manual"

        response = client.post("/api/ac/manual/param?param=fan_speed&value=5")

        assert response.status_code == 400

    def test_update_manual_param_mode(self, client, mock_components):
        """POST /api/ac/manual/param should update mode."""
        mock_components["ac_controller"].state.control_mode = "manual"
        mock_components["ac_controller"].melcloud.set_temperature.return_value = True

        response = client.post("/api/ac/manual/param?param=mode&value=heat")

        assert response.status_code == 200

    def test_update_manual_param_invalid_mode(self, client, mock_components):
        """POST /api/ac/manual/param with invalid mode should fail."""
        mock_components["ac_controller"].state.control_mode = "manual"

        response = client.post("/api/ac/manual/param?param=mode&value=turbo")

        assert response.status_code == 400


class TestConfigValidation:
    """Tests for config validation."""

    def test_post_config_temperature_out_of_range(self, client, mock_components):
        """POST /api/ac/config with out of range temp should fail."""
        response = client.post(
            "/api/ac/config",
            json={"target_temperature": 15.0},  # Below min_setpoint
        )

        assert response.status_code == 400


class TestErrorTrackerNone:
    """Tests when error tracker is None."""

    def test_get_errors_when_tracker_none(self, client):
        """GET /api/ac/errors should handle None tracker."""
        import main

        original = main.error_tracker
        main.error_tracker = None

        response = client.get("/api/ac/errors")

        main.error_tracker = original

        assert response.status_code == 200
        data = response.json()
        assert data["errors"] == []


class TestSubscriptionManagerNone:
    """Tests when subscription manager is None."""

    def test_get_subscription_stats_when_none(self, client):
        """GET /api/ac/subscriptions/stats should handle None manager."""
        import main

        original = main.subscription_manager
        main.subscription_manager = None

        response = client.get("/api/ac/subscriptions/stats")

        main.subscription_manager = original

        assert response.status_code == 200
        data = response.json()
        assert "error" in data
