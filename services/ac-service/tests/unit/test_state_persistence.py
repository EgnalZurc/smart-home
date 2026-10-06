"""Unit tests for state_persistence module.

Tests the persistence layer that saves/loads controller state
to/from disk for session continuity.
"""

import json
from pathlib import Path
from unittest.mock import patch

from state_persistence import (
    STATE_FILE,
    PersistedState,
    load_state,
    save_state,
)


class TestPersistedState:
    """Tests for PersistedState dataclass."""

    def test_to_dict_contains_all_fields(self):
        """to_dict should include all state fields."""
        state = PersistedState(
            target_temperature=25.0,
            hysteresis_on=0.5,
            hysteresis_off=0.3,
            min_setpoint=19.0,
            max_setpoint=30.0,
            cooldown_seconds=180,
            sensor_timeout=3600,
            override="on",
            force_on_temperature=22.0,
            force_on_fan_speed=2,
            current_sm_state="modulating",
            last_off_timestamp=1234567890.0,
            last_modulating_setpoint=23.5,
        )

        data = state.to_dict()

        assert data["target_temperature"] == 25.0
        assert data["hysteresis_on"] == 0.5
        assert data["hysteresis_off"] == 0.3
        assert data["min_setpoint"] == 19.0
        assert data["max_setpoint"] == 30.0
        assert data["cooldown_seconds"] == 180
        assert data["sensor_timeout"] == 3600
        assert data["override"] == "on"
        assert data["force_on_temperature"] == 22.0
        assert data["force_on_fan_speed"] == 2
        assert data["current_sm_state"] == "modulating"
        assert data["last_off_timestamp"] == 1234567890.0
        assert data["last_modulating_setpoint"] == 23.5

    def test_from_dict_creates_state(self):
        """from_dict should create PersistedState from dict."""
        data = {
            "target_temperature": 26.0,
            "hysteresis_on": 0.6,
            "hysteresis_off": 0.4,
            "min_setpoint": 18.0,
            "max_setpoint": 31.0,
            "cooldown_seconds": 200,
            "sensor_timeout": 4000,
            "override": "off",
            "force_on_temperature": 24.0,
            "force_on_fan_speed": 1,
            "current_sm_state": "cooling_max",
            "last_off_timestamp": 1111111111.0,
            "last_modulating_setpoint": 22.0,
        }

        state = PersistedState.from_dict(data)

        assert state.target_temperature == 26.0
        assert state.hysteresis_on == 0.6
        assert state.hysteresis_off == 0.4
        assert state.min_setpoint == 18.0
        assert state.max_setpoint == 31.0
        assert state.cooldown_seconds == 200
        assert state.sensor_timeout == 4000
        assert state.override == "off"
        assert state.force_on_temperature == 24.0
        assert state.force_on_fan_speed == 1
        assert state.current_sm_state == "cooling_max"
        assert state.last_off_timestamp == 1111111111.0
        assert state.last_modulating_setpoint == 22.0

    def test_from_dict_handles_missing_optional_fields(self):
        """from_dict should handle missing optional fields with defaults."""
        data = {
            "target_temperature": 25.0,
            "hysteresis_on": 0.5,
            "hysteresis_off": 0.3,
            "min_setpoint": 19.0,
            "max_setpoint": 30.0,
            "cooldown_seconds": 180,
            "sensor_timeout": 3600,
            # Missing: override, force_on_temperature, force_on_fan_speed
            # Missing: current_sm_state, last_off_timestamp, last_modulating_setpoint
        }

        state = PersistedState.from_dict(data)

        assert state.override is None
        assert state.force_on_temperature is None
        assert state.force_on_fan_speed is None
        assert state.current_sm_state == "forced_off"  # Default
        assert state.last_off_timestamp == 0.0
        assert state.last_modulating_setpoint == 24.0

    def test_roundtrip_to_dict_from_dict(self):
        """to_dict and from_dict should be reversible."""
        original = PersistedState(
            target_temperature=24.5,
            hysteresis_on=0.4,
            hysteresis_off=0.2,
            min_setpoint=20.0,
            max_setpoint=28.0,
            cooldown_seconds=120,
            sensor_timeout=1800,
            override=None,
            force_on_temperature=None,
            force_on_fan_speed=None,
            current_sm_state="off",
            last_off_timestamp=9876543210.0,
            last_modulating_setpoint=25.0,
        )

        data = original.to_dict()
        restored = PersistedState.from_dict(data)

        assert restored.target_temperature == original.target_temperature
        assert restored.hysteresis_on == original.hysteresis_on
        assert restored.hysteresis_off == original.hysteresis_off
        assert restored.current_sm_state == original.current_sm_state
        assert restored.last_off_timestamp == original.last_off_timestamp


class TestSaveState:
    """Tests for save_state function."""

    def test_save_state_creates_file(self, tmp_path):
        """save_state should create state file."""
        test_file = tmp_path / "state.json"

        state = PersistedState(
            target_temperature=25.0,
            hysteresis_on=0.5,
            hysteresis_off=0.3,
            min_setpoint=19.0,
            max_setpoint=30.0,
            cooldown_seconds=180,
            sensor_timeout=3600,
            override=None,
            force_on_temperature=None,
            force_on_fan_speed=None,
            current_sm_state="off",
            last_off_timestamp=0.0,
            last_modulating_setpoint=24.0,
        )

        with patch("state_persistence.STATE_FILE", test_file):
            result = save_state(state)

        assert result is True
        assert test_file.exists()

        # Verify content
        content = json.loads(test_file.read_text(encoding="utf-8"))
        assert content["target_temperature"] == 25.0

    def test_save_state_creates_parent_dirs(self, tmp_path):
        """save_state should create parent directories if missing."""
        test_file = tmp_path / "subdir" / "deep" / "state.json"

        state = PersistedState(
            target_temperature=25.0,
            hysteresis_on=0.5,
            hysteresis_off=0.3,
            min_setpoint=19.0,
            max_setpoint=30.0,
            cooldown_seconds=180,
            sensor_timeout=3600,
            override=None,
            force_on_temperature=None,
            force_on_fan_speed=None,
            current_sm_state="off",
            last_off_timestamp=0.0,
            last_modulating_setpoint=24.0,
        )

        with patch("state_persistence.STATE_FILE", test_file):
            result = save_state(state)

        assert result is True
        assert test_file.exists()

    def test_save_state_handles_write_error(self, tmp_path):
        """save_state should return False on write error."""
        # Create a directory where file should be (will cause write error)
        test_file = tmp_path / "state.json"
        test_file.mkdir()  # Make it a directory so write fails

        state = PersistedState(
            target_temperature=25.0,
            hysteresis_on=0.5,
            hysteresis_off=0.3,
            min_setpoint=19.0,
            max_setpoint=30.0,
            cooldown_seconds=180,
            sensor_timeout=3600,
            override=None,
            force_on_temperature=None,
            force_on_fan_speed=None,
            current_sm_state="off",
            last_off_timestamp=0.0,
            last_modulating_setpoint=24.0,
        )

        with patch("state_persistence.STATE_FILE", test_file):
            result = save_state(state)

        assert result is False


class TestLoadState:
    """Tests for load_state function."""

    def test_load_state_reads_file(self, tmp_path):
        """load_state should read and parse state file."""
        test_file = tmp_path / "state.json"

        data = {
            "target_temperature": 26.0,
            "hysteresis_on": 0.6,
            "hysteresis_off": 0.4,
            "min_setpoint": 18.0,
            "max_setpoint": 31.0,
            "cooldown_seconds": 200,
            "sensor_timeout": 4000,
            "override": "on",
            "force_on_temperature": 23.0,
            "force_on_fan_speed": 3,
            "current_sm_state": "modulating",
            "last_off_timestamp": 1234567890.0,
            "last_modulating_setpoint": 22.5,
        }
        test_file.write_text(json.dumps(data), encoding="utf-8")

        with patch("state_persistence.STATE_FILE", test_file):
            state = load_state()

        assert state is not None
        assert state.target_temperature == 26.0
        assert state.override == "on"
        assert state.current_sm_state == "modulating"

    def test_load_state_returns_none_if_missing(self, tmp_path):
        """load_state should return None if file doesn't exist."""
        test_file = tmp_path / "nonexistent.json"

        with patch("state_persistence.STATE_FILE", test_file):
            state = load_state()

        assert state is None

    def test_load_state_returns_none_on_invalid_json(self, tmp_path):
        """load_state should return None on invalid JSON."""
        test_file = tmp_path / "state.json"
        test_file.write_text("not valid json {{{", encoding="utf-8")

        with patch("state_persistence.STATE_FILE", test_file):
            state = load_state()

        assert state is None

    def test_load_state_returns_none_on_missing_fields(self, tmp_path):
        """load_state should return None if required fields missing."""
        test_file = tmp_path / "state.json"
        # Missing required fields like target_temperature
        test_file.write_text('{"some_field": 123}', encoding="utf-8")

        with patch("state_persistence.STATE_FILE", test_file):
            state = load_state()

        assert state is None


class TestStateFileConstant:
    """Tests for STATE_FILE constant."""

    def test_state_file_is_path(self):
        """STATE_FILE should be a Path object."""
        assert isinstance(STATE_FILE, Path)

    def test_state_file_in_app_data(self):
        """STATE_FILE should be in /app/data directory."""
        assert "data" in STATE_FILE.parts
        assert STATE_FILE.name == "controller_state.json"
