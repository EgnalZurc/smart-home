"""Service contract tests verifying health endpoint schemas.

These tests validate that each service's health endpoint returns the expected
response schema. This catches:
- Missing required fields in health responses
- Type mismatches in response data
- Breaking changes to health endpoint contracts

The contracts are derived from the actual health.py implementation and
document the expected response structure for each service.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


# ══════════════════════════════════════════════════════════════════════════════
# CONTRACT DEFINITIONS
#
# Each service has a defined contract specifying:
# - required_fields: Fields that MUST be present in the response
# - optional_fields: Fields that MAY be present
# - field_types: Expected types for each field
# ══════════════════════════════════════════════════════════════════════════════

SERVICE_CONTRACTS = {
    "backend": {
        "required_fields": {"online"},
        "optional_fields": {"db_accessible", "static_files", "db_error", "static_error", "latency_ms", "cached"},
        "field_types": {
            "online": bool,
            "db_accessible": bool,
            "static_files": bool,
            "db_error": str,
            "static_error": str,
            "latency_ms": int,
            "cached": bool,
        },
    },
    "zigbee": {
        "required_fields": {"online", "mqtt_connected", "active_sensors"},
        "optional_fields": {"error", "latency_ms", "cached"},
        "field_types": {
            "online": bool,
            "mqtt_connected": bool,
            "active_sensors": int,
            "error": str,
            "latency_ms": int,
            "cached": bool,
        },
    },
    "ac": {
        "required_fields": {"online"},
        "optional_fields": {"melcloud_connected", "error", "latency_ms", "cached"},
        "field_types": {
            "online": bool,
            "melcloud_connected": bool,
            "error": str,
            "latency_ms": int,
            "cached": bool,
        },
    },
    "vacaciones": {
        "required_fields": {"online"},
        "optional_fields": {"error", "latency_ms", "cached"},
        "field_types": {
            "online": bool,
            "error": str,
            "latency_ms": int,
            "cached": bool,
        },
    },
    "immich": {
        "required_fields": {"online"},
        "optional_fields": {"error", "latency_ms", "cached"},
        "field_types": {
            "online": bool,
            "error": str,
            "latency_ms": int,
            "cached": bool,
        },
    },
    "casita": {
        "required_fields": {"online"},
        "optional_fields": {"telegram_connected", "error", "latency_ms", "cached"},
        "field_types": {
            "online": bool,
            "telegram_connected": bool,
            "error": str,
            "latency_ms": int,
            "cached": bool,
        },
    },
    "baby-gifts": {
        "required_fields": {"online"},
        "optional_fields": {"error", "latency_ms", "cached"},
        "field_types": {
            "online": bool,
            "error": str,
            "latency_ms": int,
            "cached": bool,
        },
    },
    "portfolio": {
        "required_fields": {"online"},
        "optional_fields": {"last_update", "error", "latency_ms", "cached"},
        "field_types": {
            "online": bool,
            "last_update": (str, type(None)),  # Can be null
            "error": str,
            "latency_ms": int,
            "cached": bool,
        },
    },
    "passwords": {
        "required_fields": {"online"},
        "optional_fields": {"error", "latency_ms", "cached"},
        "field_types": {
            "online": bool,
            "error": str,
            "latency_ms": int,
            "cached": bool,
        },
    },

    "metrics": {
        "required_fields": {"online"},
        "optional_fields": {"db_ok", "collector_last_tick_age_s", "error", "latency_ms", "cached"},
        "field_types": {
            "online": bool,
            "db_ok": bool,
            "collector_last_tick_age_s": (int, float, type(None)),
            "error": str,
            "latency_ms": int,
            "cached": bool,
        },
    },
    "energy": {
        "required_fields": {"online"},
        "optional_fields": {"db_ok", "meter_online", "collector_last_tick_age_s", "error", "latency_ms", "cached"},
        "field_types": {
            "online": bool,
            "db_ok": bool,
            "meter_online": (bool, type(None)),
            "collector_last_tick_age_s": (int, float, type(None)),
            "error": str,
            "latency_ms": int,
            "cached": bool,
        },
    },
    "presence": {
        "required_fields": {"online"},
        "optional_fields": {
            "db_ok",
            "router_online",
            "mqtt_online",
            "last_tick_age_s",
            "error",
            "latency_ms",
            "cached",
        },
        "field_types": {
            "online": bool,
            "db_ok": bool,
            "router_online": (bool, type(None)),
            "mqtt_online": (bool, type(None)),
            "last_tick_age_s": (int, float, type(None)),
            "error": str,
            "latency_ms": int,
            "cached": bool,
        },
    },
    "calendar": {
        "required_fields": {"online"},
        "optional_fields": {
            "db_ok",
            "google_auth_ok",
            "last_sync_ok",
            "last_sync_age_s",
            "reminder_tick_age_s",
            "error",
            "latency_ms",
            "cached",
        },
        "field_types": {
            "online": bool,
            "db_ok": bool,
            "google_auth_ok": (bool, type(None)),
            "last_sync_ok": (bool, type(None)),
            "last_sync_age_s": (int, float, type(None)),
            "reminder_tick_age_s": (int, float, type(None)),
            "error": str,
            "latency_ms": int,
            "cached": bool,
        },
    },
}


def _validate_contract(response: dict[str, Any], contract: dict, service_name: str) -> list[str]:
    """Validate a response against its contract definition.

    Returns a list of validation errors (empty if valid).
    """
    errors = []

    # Check required fields
    for field in contract["required_fields"]:
        if field not in response:
            errors.append(f"{service_name}: missing required field '{field}'")

    # Check field types for all present fields
    for field, value in response.items():
        if field in contract["field_types"]:
            expected_type = contract["field_types"][field]
            # Handle tuple of types (e.g., (str, type(None)))
            if isinstance(expected_type, tuple):
                if not isinstance(value, expected_type):
                    errors.append(
                        f"{service_name}.{field}: expected one of {expected_type}, got {type(value).__name__}"
                    )
            elif not isinstance(value, expected_type):
                errors.append(
                    f"{service_name}.{field}: expected {expected_type.__name__}, got {type(value).__name__}"
                )

    # Check for unknown fields (not required or optional)
    all_known_fields = contract["required_fields"] | contract["optional_fields"]
    for field in response:
        if field not in all_known_fields:
            errors.append(f"{service_name}: unknown field '{field}' (consider adding to contract)")

    return errors


# ══════════════════════════════════════════════════════════════════════════════
# MOCK RESPONSE FACTORY
# ══════════════════════════════════════════════════════════════════════════════


def _create_mock_service_response(service_key: str, online: bool = True) -> dict:
    """Create a mock response matching the expected contract for a service.

    This helps test that the health check functions correctly transform
    upstream responses into the expected contract format.
    """
    base = {"online": online}

    if service_key == "zigbee":
        return {"mqtt_connected": online, "active_sensors": 5 if online else 0}
    elif service_key == "ac":
        return {"online": online, "melcloud_connected": online}
    elif service_key == "casita":
        return {"online": online, "telegram_connected": online}
    elif service_key == "portfolio":
        return {"online": online, "last_update": "2024-01-01T00:00:00Z" if online else None}
    elif service_key == "metrics":
        return {"online": online, "db_ok": online, "collector_last_tick_age_s": 30 if online else None}
    elif service_key == "energy":
        return {
            "online": online,
            "db_ok": online,
            "meter_online": online,
            "collector_last_tick_age_s": 60 if online else None,
        }
    elif service_key == "presence":
        return {
            "online": online,
            "db_ok": online,
            "router_online": online,
            "mqtt_online": online,
            "last_tick_age_s": 15 if online else None,
        }
    elif service_key == "calendar":
        return {
            "online": online,
            "db_ok": online,
            "google_auth_ok": online,
            "last_sync_ok": online,
            "last_sync_age_s": 120 if online else None,
            "reminder_tick_age_s": 45 if online else None,
        }
    elif service_key == "immich":
        # Immich returns {res: "pong"} for success
        return {"res": "pong"} if online else {}

    return base


# ══════════════════════════════════════════════════════════════════════════════
# CONTRACT TESTS
# ══════════════════════════════════════════════════════════════════════════════


class TestServiceContracts:
    """Tests verifying health endpoint response schemas match contracts."""

    @pytest.mark.asyncio
    async def test_backend_health_contract(self):
        """Backend health response matches its contract."""
        from api.health import get_backend_health

        result = await get_backend_health()
        errors = _validate_contract(result, SERVICE_CONTRACTS["backend"], "backend")
        assert not errors, f"Contract violations: {errors}"

    @pytest.mark.asyncio
    async def test_zigbee_health_contract_online(self):
        """Zigbee health response matches contract when service is online."""
        from api.health import get_zigbee_health

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = _create_mock_service_response("zigbee", online=True)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await get_zigbee_health()

        errors = _validate_contract(result, SERVICE_CONTRACTS["zigbee"], "zigbee")
        assert not errors, f"Contract violations: {errors}"

    @pytest.mark.asyncio
    async def test_zigbee_health_contract_offline(self):
        """Zigbee health response matches contract when service is offline."""
        from api.health import get_zigbee_health

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await get_zigbee_health()

        errors = _validate_contract(result, SERVICE_CONTRACTS["zigbee"], "zigbee")
        assert not errors, f"Contract violations: {errors}"
        assert result["online"] is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_ac_health_contract_online(self):
        """AC health response matches contract when service is online."""
        from api.health import get_ac_health

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = _create_mock_service_response("ac", online=True)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await get_ac_health()

        errors = _validate_contract(result, SERVICE_CONTRACTS["ac"], "ac")
        assert not errors, f"Contract violations: {errors}"

    @pytest.mark.asyncio
    async def test_ac_health_contract_offline(self):
        """AC health response matches contract when service is offline."""
        from api.health import get_ac_health

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await get_ac_health()

        errors = _validate_contract(result, SERVICE_CONTRACTS["ac"], "ac")
        assert not errors, f"Contract violations: {errors}"
        assert result["online"] is False

    @pytest.mark.asyncio
    async def test_vacaciones_health_contract_online(self):
        """Vacaciones health response matches contract when online."""
        from api.health import get_vacaciones_health

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"online": True}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await get_vacaciones_health()

        errors = _validate_contract(result, SERVICE_CONTRACTS["vacaciones"], "vacaciones")
        assert not errors, f"Contract violations: {errors}"

    @pytest.mark.asyncio
    async def test_immich_health_contract_online(self):
        """Immich health response matches contract when online."""
        from api.health import get_immich_health

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"res": "pong"}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await get_immich_health()

        errors = _validate_contract(result, SERVICE_CONTRACTS["immich"], "immich")
        assert not errors, f"Contract violations: {errors}"
        assert result["online"] is True

    @pytest.mark.asyncio
    async def test_casita_health_contract_online(self):
        """Casita health response matches contract when online."""
        from api.health import get_casita_health

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = _create_mock_service_response("casita", online=True)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await get_casita_health()

        errors = _validate_contract(result, SERVICE_CONTRACTS["casita"], "casita")
        assert not errors, f"Contract violations: {errors}"

    @pytest.mark.asyncio
    async def test_baby_gifts_health_contract_online(self):
        """Baby-gifts health response matches contract when online."""
        from api.health import get_baby_gifts_health

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"online": True}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await get_baby_gifts_health()

        errors = _validate_contract(result, SERVICE_CONTRACTS["baby-gifts"], "baby-gifts")
        assert not errors, f"Contract violations: {errors}"

    @pytest.mark.asyncio
    async def test_portfolio_health_contract_online(self):
        """Portfolio health response matches contract when online."""
        from api.health import get_portfolio_health

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = _create_mock_service_response("portfolio", online=True)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await get_portfolio_health()

        errors = _validate_contract(result, SERVICE_CONTRACTS["portfolio"], "portfolio")
        assert not errors, f"Contract violations: {errors}"

    @pytest.mark.asyncio
    async def test_passwords_health_contract_online(self):
        """Passwords (vaultwarden) health response matches contract when online."""
        from api.health import get_passwords_health

        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await get_passwords_health()

        errors = _validate_contract(result, SERVICE_CONTRACTS["passwords"], "passwords")
        assert not errors, f"Contract violations: {errors}"

    @pytest.mark.asyncio
    async def test_metrics_health_contract_online(self):
        """Metrics health response matches contract when online."""
        from api.health import get_metrics_health

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = _create_mock_service_response("metrics", online=True)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await get_metrics_health()

        errors = _validate_contract(result, SERVICE_CONTRACTS["metrics"], "metrics")
        assert not errors, f"Contract violations: {errors}"

    @pytest.mark.asyncio
    async def test_energy_health_contract_online(self):
        """Energy health response matches contract when online."""
        from api.health import get_energy_health

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = _create_mock_service_response("energy", online=True)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await get_energy_health()

        errors = _validate_contract(result, SERVICE_CONTRACTS["energy"], "energy")
        assert not errors, f"Contract violations: {errors}"

    @pytest.mark.asyncio
    async def test_presence_health_contract_online(self):
        """Presence health response matches contract when online."""
        from api.health import get_presence_health

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = _create_mock_service_response("presence", online=True)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await get_presence_health()

        errors = _validate_contract(result, SERVICE_CONTRACTS["presence"], "presence")
        assert not errors, f"Contract violations: {errors}"

    @pytest.mark.asyncio
    async def test_calendar_health_contract_online(self):
        """Calendar health response matches contract when online."""
        from api.health import get_calendar_health

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = _create_mock_service_response("calendar", online=True)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await get_calendar_health()

        errors = _validate_contract(result, SERVICE_CONTRACTS["calendar"], "calendar")
        assert not errors, f"Contract violations: {errors}"


class TestContractCompleteness:
    """Tests verifying contract definitions are complete."""

    def test_all_health_functions_have_contracts(self):
        """Every health check function has a defined contract."""
        from api import health

        # Get all health check functions
        health_functions = [
            name for name in dir(health) if name.startswith("get_") and name.endswith("_health")
        ]

        # Map function names to contract keys
        func_to_contract = {
            "get_backend_health": "backend",
            "get_zigbee_health": "zigbee",
            "get_ac_health": "ac",
            "get_vacaciones_health": "vacaciones",
            "get_immich_health": "immich",
            "get_casita_health": "casita",
            "get_baby_gifts_health": "baby-gifts",
            "get_portfolio_health": "portfolio",
            "get_passwords_health": "passwords",
            "get_metrics_health": "metrics",
            "get_energy_health": "energy",
            "get_presence_health": "presence",
            "get_calendar_health": "calendar",
            "get_health": None,  # Base health endpoint, not a service
            "get_all_health": None,  # Aggregation endpoint
        }

        missing = []
        for func_name in health_functions:
            if func_name not in func_to_contract:
                missing.append(f"{func_name} (no mapping)")
            elif func_to_contract[func_name] is not None:
                contract_key = func_to_contract[func_name]
                if contract_key not in SERVICE_CONTRACTS:
                    missing.append(f"{func_name} -> {contract_key} (no contract)")

        assert not missing, f"Health functions without contracts: {missing}"

    def test_contracts_have_required_structure(self):
        """All contracts have required_fields, optional_fields, and field_types."""
        for service, contract in SERVICE_CONTRACTS.items():
            assert "required_fields" in contract, f"{service}: missing required_fields"
            assert "optional_fields" in contract, f"{service}: missing optional_fields"
            assert "field_types" in contract, f"{service}: missing field_types"

            # All required and optional fields should have type definitions
            all_fields = contract["required_fields"] | contract["optional_fields"]
            for field in all_fields:
                assert field in contract["field_types"], (
                    f"{service}.{field}: no type definition"
                )

    def test_all_contracts_require_online_field(self):
        """Every service contract requires the 'online' field."""
        for service, contract in SERVICE_CONTRACTS.items():
            assert "online" in contract["required_fields"], (
                f"{service}: 'online' should be a required field"
            )


class TestErrorResponses:
    """Tests verifying error responses still match contracts."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "service,health_func",
        [
            ("zigbee", "get_zigbee_health"),
            ("ac", "get_ac_health"),
            ("vacaciones", "get_vacaciones_health"),
            ("immich", "get_immich_health"),
            ("casita", "get_casita_health"),
            ("baby-gifts", "get_baby_gifts_health"),
            ("portfolio", "get_portfolio_health"),
            ("passwords", "get_passwords_health"),
            ("metrics", "get_metrics_health"),
            ("energy", "get_energy_health"),
            ("presence", "get_presence_health"),
            ("calendar", "get_calendar_health"),
        ],
    )
    async def test_connection_error_matches_contract(self, service: str, health_func: str):
        """Connection errors produce valid contract-compliant responses."""
        from api import health

        func = getattr(health, health_func)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await func()

        errors = _validate_contract(result, SERVICE_CONTRACTS[service], service)
        assert not errors, f"Contract violations on error: {errors}"
        assert result["online"] is False
        assert "error" in result

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "service,health_func",
        [
            ("zigbee", "get_zigbee_health"),
            ("ac", "get_ac_health"),
            ("vacaciones", "get_vacaciones_health"),
            ("immich", "get_immich_health"),
            ("casita", "get_casita_health"),
            ("baby-gifts", "get_baby_gifts_health"),
            ("portfolio", "get_portfolio_health"),
            ("passwords", "get_passwords_health"),
            ("metrics", "get_metrics_health"),
            ("energy", "get_energy_health"),
            ("presence", "get_presence_health"),
            ("calendar", "get_calendar_health"),
        ],
    )
    async def test_timeout_error_matches_contract(self, service: str, health_func: str):
        """Timeout errors produce valid contract-compliant responses."""
        from api import health

        func = getattr(health, health_func)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("Timeout"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await func()

        errors = _validate_contract(result, SERVICE_CONTRACTS[service], service)
        assert not errors, f"Contract violations on timeout: {errors}"
        assert result["online"] is False
        assert "error" in result
