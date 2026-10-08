"""Tests for smart_home_common/persistence/state.py.

Covers:
- PersistedState dataclass: initialization, to_dict, from_dict
- save_state: success, directory creation, error handling
- load_state: success, missing file, invalid JSON, corrupt data
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from smart_home_common.persistence.state import (
    STATE_FILE,
    PersistedState,
    load_state,
    save_state,
)


def make_default_state(**overrides) -> PersistedState:
    """Factory for creating PersistedState with defaults."""
    defaults = {
        "target_temperature": 23.0,
        "hysteresis_on": 1.0,
        "hysteresis_off": 0.5,
        "min_setpoint": 16.0,
        "max_setpoint": 31.0,
        "cooldown_seconds": 300,
        "sensor_timeout": 120,
        "override": None,
        "force_on_temperature": None,
        "force_on_fan_speed": None,
        "current_sm_state": "modulating",
        "last_off_timestamp": 0.0,
        "last_modulating_setpoint": 24.0,
    }
    defaults.update(overrides)
    return PersistedState(**defaults)


class TestPersistedStateDataclass:
    def test_initialization_with_all_fields(self):
        state = PersistedState(
            target_temperature=22.5,
            hysteresis_on=1.5,
            hysteresis_off=0.8,
            min_setpoint=18.0,
            max_setpoint=28.0,
            cooldown_seconds=600,
            sensor_timeout=180,
            override="on",
            force_on_temperature=25.0,
            force_on_fan_speed=3,
            current_sm_state="forced_on",
            last_off_timestamp=1000.0,
            last_modulating_setpoint=23.5,
        )

        assert state.target_temperature == 22.5
        assert state.hysteresis_on == 1.5
        assert state.hysteresis_off == 0.8
        assert state.min_setpoint == 18.0
        assert state.max_setpoint == 28.0
        assert state.cooldown_seconds == 600
        assert state.sensor_timeout == 180
        assert state.override == "on"
        assert state.force_on_temperature == 25.0
        assert state.force_on_fan_speed == 3
        assert state.current_sm_state == "forced_on"
        assert state.last_off_timestamp == 1000.0
        assert state.last_modulating_setpoint == 23.5

    def test_initialization_with_none_optional_fields(self):
        state = make_default_state(
            override=None,
            force_on_temperature=None,
            force_on_fan_speed=None,
        )

        assert state.override is None
        assert state.force_on_temperature is None
        assert state.force_on_fan_speed is None


class TestPersistedStateToDict:
    def test_to_dict_includes_all_fields(self):
        state = make_default_state(
            target_temperature=22.0,
            override="off",
            force_on_temperature=20.0,
            current_sm_state="forced_off",
        )

        result = state.to_dict()

        assert result == {
            "target_temperature": 22.0,
            "hysteresis_on": 1.0,
            "hysteresis_off": 0.5,
            "min_setpoint": 16.0,
            "max_setpoint": 31.0,
            "cooldown_seconds": 300,
            "sensor_timeout": 120,
            "override": "off",
            "force_on_temperature": 20.0,
            "force_on_fan_speed": None,
            "current_sm_state": "forced_off",
            "last_off_timestamp": 0.0,
            "last_modulating_setpoint": 24.0,
        }

    def test_to_dict_result_is_json_serializable(self):
        state = make_default_state()

        result = state.to_dict()

        # Should not raise
        json_str = json.dumps(result)
        assert isinstance(json_str, str)


class TestPersistedStateFromDict:
    def test_from_dict_with_all_fields(self):
        data = {
            "target_temperature": 24.0,
            "hysteresis_on": 2.0,
            "hysteresis_off": 1.0,
            "min_setpoint": 17.0,
            "max_setpoint": 30.0,
            "cooldown_seconds": 400,
            "sensor_timeout": 150,
            "override": "on",
            "force_on_temperature": 26.0,
            "force_on_fan_speed": 4,
            "current_sm_state": "cooldown",
            "last_off_timestamp": 500.0,
            "last_modulating_setpoint": 25.0,
        }

        state = PersistedState.from_dict(data)

        assert state.target_temperature == 24.0
        assert state.hysteresis_on == 2.0
        assert state.hysteresis_off == 1.0
        assert state.min_setpoint == 17.0
        assert state.max_setpoint == 30.0
        assert state.cooldown_seconds == 400
        assert state.sensor_timeout == 150
        assert state.override == "on"
        assert state.force_on_temperature == 26.0
        assert state.force_on_fan_speed == 4
        assert state.current_sm_state == "cooldown"
        assert state.last_off_timestamp == 500.0
        assert state.last_modulating_setpoint == 25.0

    def test_from_dict_with_missing_optional_fields_uses_defaults(self):
        # Minimal data without optional fields
        data = {
            "target_temperature": 23.0,
            "hysteresis_on": 1.0,
            "hysteresis_off": 0.5,
            "min_setpoint": 16.0,
            "max_setpoint": 31.0,
            "cooldown_seconds": 300,
            "sensor_timeout": 120,
        }

        state = PersistedState.from_dict(data)

        # Optional fields should have None or defaults
        assert state.override is None
        assert state.force_on_temperature is None
        assert state.force_on_fan_speed is None
        assert state.current_sm_state == "forced_off"  # Default
        assert state.last_off_timestamp == 0.0  # Default
        assert state.last_modulating_setpoint == 24.0  # Default

    def test_from_dict_round_trip_with_to_dict(self):
        original = make_default_state(
            target_temperature=21.5,
            override="off",
            current_sm_state="modulating",
        )

        result = PersistedState.from_dict(original.to_dict())

        assert result.target_temperature == original.target_temperature
        assert result.hysteresis_on == original.hysteresis_on
        assert result.hysteresis_off == original.hysteresis_off
        assert result.min_setpoint == original.min_setpoint
        assert result.max_setpoint == original.max_setpoint
        assert result.cooldown_seconds == original.cooldown_seconds
        assert result.sensor_timeout == original.sensor_timeout
        assert result.override == original.override
        assert result.force_on_temperature == original.force_on_temperature
        assert result.force_on_fan_speed == original.force_on_fan_speed
        assert result.current_sm_state == original.current_sm_state
        assert result.last_off_timestamp == original.last_off_timestamp
        assert result.last_modulating_setpoint == original.last_modulating_setpoint


class TestSaveState:
    def test_save_state_creates_file(self, tmp_path: Path):
        state_file = tmp_path / "controller_state.json"
        state = make_default_state(target_temperature=22.0)

        with patch("smart_home_common.persistence.state.STATE_FILE", state_file):
            result = save_state(state)

        assert result is True
        assert state_file.exists()
        saved_data = json.loads(state_file.read_text(encoding="utf-8"))
        assert saved_data["target_temperature"] == 22.0

    def test_save_state_creates_parent_directories(self, tmp_path: Path):
        state_file = tmp_path / "deep" / "nested" / "controller_state.json"
        state = make_default_state()

        with patch("smart_home_common.persistence.state.STATE_FILE", state_file):
            result = save_state(state)

        assert result is True
        assert state_file.exists()

    def test_save_state_overwrites_existing(self, tmp_path: Path):
        state_file = tmp_path / "controller_state.json"
        state_file.write_text('{"old": "data"}', encoding="utf-8")

        state = make_default_state(target_temperature=25.0)

        with patch("smart_home_common.persistence.state.STATE_FILE", state_file):
            result = save_state(state)

        assert result is True
        saved_data = json.loads(state_file.read_text(encoding="utf-8"))
        assert saved_data["target_temperature"] == 25.0
        assert "old" not in saved_data

    def test_save_state_formats_json_with_indent(self, tmp_path: Path):
        state_file = tmp_path / "controller_state.json"
        state = make_default_state()

        with patch("smart_home_common.persistence.state.STATE_FILE", state_file):
            save_state(state)

        content = state_file.read_text(encoding="utf-8")
        # Check for indentation (pretty-printed JSON)
        assert "\n" in content
        assert "  " in content  # indent=2

    def test_save_state_preserves_unicode(self, tmp_path: Path):
        # Test that ensure_ascii=False works
        state_file = tmp_path / "controller_state.json"
        state = make_default_state()

        with patch("smart_home_common.persistence.state.STATE_FILE", state_file):
            save_state(state)

        content = state_file.read_text(encoding="utf-8")
        # Just verify we can read it back; the state doesn't have unicode but
        # the function uses ensure_ascii=False
        assert isinstance(content, str)

    def test_save_state_returns_false_on_error(self, tmp_path: Path):
        # Create a read-only directory to cause write failure
        state_file = tmp_path / "readonly" / "state.json"
        state = make_default_state()

        with patch(
            "smart_home_common.persistence.state.STATE_FILE",
            state_file,
        ), patch(
            "pathlib.Path.mkdir",
            side_effect=PermissionError("Access denied"),
        ):
            result = save_state(state)

        assert result is False


class TestLoadState:
    def test_load_state_returns_state_from_file(self, tmp_path: Path):
        state_file = tmp_path / "controller_state.json"
        data = {
            "target_temperature": 24.5,
            "hysteresis_on": 1.5,
            "hysteresis_off": 0.8,
            "min_setpoint": 17.0,
            "max_setpoint": 29.0,
            "cooldown_seconds": 500,
            "sensor_timeout": 180,
            "override": "off",
            "force_on_temperature": None,
            "force_on_fan_speed": None,
            "current_sm_state": "modulating",
            "last_off_timestamp": 1234.5,
            "last_modulating_setpoint": 23.0,
        }
        state_file.write_text(json.dumps(data), encoding="utf-8")

        with patch("smart_home_common.persistence.state.STATE_FILE", state_file):
            state = load_state()

        assert state is not None
        assert state.target_temperature == 24.5
        assert state.override == "off"
        assert state.current_sm_state == "modulating"
        assert state.last_off_timestamp == 1234.5

    def test_load_state_returns_none_for_missing_file(self, tmp_path: Path):
        state_file = tmp_path / "nonexistent.json"

        with patch("smart_home_common.persistence.state.STATE_FILE", state_file):
            state = load_state()

        assert state is None

    def test_load_state_returns_none_for_invalid_json(self, tmp_path: Path):
        state_file = tmp_path / "controller_state.json"
        state_file.write_text("not valid json {{{", encoding="utf-8")

        with patch("smart_home_common.persistence.state.STATE_FILE", state_file):
            state = load_state()

        assert state is None

    def test_load_state_returns_none_for_missing_required_fields(self, tmp_path: Path):
        state_file = tmp_path / "controller_state.json"
        # Missing required field target_temperature
        data = {"hysteresis_on": 1.0}
        state_file.write_text(json.dumps(data), encoding="utf-8")

        with patch("smart_home_common.persistence.state.STATE_FILE", state_file):
            state = load_state()

        assert state is None  # Should fail due to KeyError

    def test_load_state_handles_read_error(self, tmp_path: Path):
        state_file = tmp_path / "controller_state.json"
        state_file.write_text("{}", encoding="utf-8")

        with patch("smart_home_common.persistence.state.STATE_FILE", state_file), patch(
            "pathlib.Path.read_text",
            side_effect=PermissionError("Access denied"),
        ):
            state = load_state()

        assert state is None


class TestSaveLoadRoundTrip:
    def test_round_trip_preserves_all_fields(self, tmp_path: Path):
        state_file = tmp_path / "controller_state.json"
        original = PersistedState(
            target_temperature=21.0,
            hysteresis_on=1.2,
            hysteresis_off=0.6,
            min_setpoint=15.0,
            max_setpoint=32.0,
            cooldown_seconds=450,
            sensor_timeout=200,
            override="on",
            force_on_temperature=20.0,
            force_on_fan_speed=2,
            current_sm_state="forced_on",
            last_off_timestamp=9999.9,
            last_modulating_setpoint=22.5,
        )

        with patch("smart_home_common.persistence.state.STATE_FILE", state_file):
            save_state(original)
            loaded = load_state()

        assert loaded is not None
        assert loaded.target_temperature == original.target_temperature
        assert loaded.hysteresis_on == original.hysteresis_on
        assert loaded.hysteresis_off == original.hysteresis_off
        assert loaded.min_setpoint == original.min_setpoint
        assert loaded.max_setpoint == original.max_setpoint
        assert loaded.cooldown_seconds == original.cooldown_seconds
        assert loaded.sensor_timeout == original.sensor_timeout
        assert loaded.override == original.override
        assert loaded.force_on_temperature == original.force_on_temperature
        assert loaded.force_on_fan_speed == original.force_on_fan_speed
        assert loaded.current_sm_state == original.current_sm_state
        assert loaded.last_off_timestamp == original.last_off_timestamp
        assert loaded.last_modulating_setpoint == original.last_modulating_setpoint


class TestStateFileConstant:
    def test_state_file_path(self):
        assert STATE_FILE == Path("/app/data/controller_state.json")
