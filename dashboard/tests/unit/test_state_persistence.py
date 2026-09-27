"""Unit tests for state_persistence.py"""
import os, tempfile
from pathlib import Path
from unittest.mock import patch
from state_persistence import PersistedState, save_state, load_state


def _make_state(**kwargs):
    defaults = dict(
        target_temperature=26.0, hysteresis_on=0.5, hysteresis_off=0.3,
        min_setpoint=19.0, max_setpoint=30.0, cooldown_seconds=180,
        sensor_timeout=3600, override="auto", force_on_temperature=24.0,
        force_on_fan_speed=0, current_sm_state="off",
        last_off_timestamp=0.0, last_modulating_setpoint=24.0,
    )
    defaults.update(kwargs)
    return PersistedState(**defaults)


class TestPersistedState:
    def test_to_dict_has_required_keys(self):
        s = _make_state()
        d = s.to_dict()
        assert "target_temperature" in d
        assert "current_sm_state" in d

    def test_from_dict_round_trip(self):
        s = _make_state(target_temperature=24.5, current_sm_state="cooldown")
        d = s.to_dict()
        s2 = PersistedState.from_dict(d)
        assert s2.target_temperature == 24.5
        assert s2.current_sm_state == "cooldown"


class TestSaveAndLoadState:
    def test_save_then_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "state.json"
            s = _make_state(target_temperature=24.0, current_sm_state="off")
            with patch("state_persistence.STATE_FILE", state_file):
                result = save_state(s)
                assert result is True
                loaded = load_state()
                assert loaded is not None
                assert loaded.target_temperature == 24.0

    def test_load_missing_file_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "nonexistent.json"
            with patch("state_persistence.STATE_FILE", missing):
                assert load_state() is None

    def test_load_corrupt_file_returns_none(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not valid json }{")
            name = f.name
        try:
            with patch("state_persistence.STATE_FILE", Path(name)):
                assert load_state() is None
        finally:
            os.unlink(name)
