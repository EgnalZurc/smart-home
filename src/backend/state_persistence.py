"""Controller state persistence module.

Saves and loads controller state to/from disk so the system
can continue from where it left off after restarts.

Goal: Minimize AC on/off cycles to protect the compressor.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from controllers.state_machine import ControllerState, ForceOnParams

logger = logging.getLogger(__name__)

# Persistence file (inside container, mounted as volume)
STATE_FILE = Path("/app/data/controller_state.json")


@dataclass
class PersistedState:
    """State to persist between sessions."""
    
    # Configuration
    target_temperature: float
    hysteresis_on: float
    hysteresis_off: float
    min_setpoint: float
    max_setpoint: float
    cooldown_seconds: int
    sensor_timeout: int
    
    # Manual mode
    override: str | None  # None=auto, "on", "off"
    force_on_temperature: float | None
    force_on_fan_speed: int | None
    
    # Internal state machine state
    current_sm_state: str  # ControllerState enum value
    last_off_timestamp: float
    last_modulating_setpoint: float
    
    def to_dict(self) -> dict:
        """Converts to dictionary for JSON serialization."""
        return {
            "target_temperature": self.target_temperature,
            "hysteresis_on": self.hysteresis_on,
            "hysteresis_off": self.hysteresis_off,
            "min_setpoint": self.min_setpoint,
            "max_setpoint": self.max_setpoint,
            "cooldown_seconds": self.cooldown_seconds,
            "sensor_timeout": self.sensor_timeout,
            "override": self.override,
            "force_on_temperature": self.force_on_temperature,
            "force_on_fan_speed": self.force_on_fan_speed,
            "current_sm_state": self.current_sm_state,
            "last_off_timestamp": self.last_off_timestamp,
            "last_modulating_setpoint": self.last_modulating_setpoint,
        }
    
    @staticmethod
    def from_dict(data: dict) -> "PersistedState":
        """Creates from dictionary loaded from JSON."""
        return PersistedState(
            target_temperature=data["target_temperature"],
            hysteresis_on=data["hysteresis_on"],
            hysteresis_off=data["hysteresis_off"],
            min_setpoint=data["min_setpoint"],
            max_setpoint=data["max_setpoint"],
            cooldown_seconds=data["cooldown_seconds"],
            sensor_timeout=data["sensor_timeout"],
            override=data.get("override"),
            force_on_temperature=data.get("force_on_temperature"),
            force_on_fan_speed=data.get("force_on_fan_speed"),
            current_sm_state=data.get("current_sm_state", "forced_off"),
            last_off_timestamp=data.get("last_off_timestamp", 0.0),
            last_modulating_setpoint=data.get("last_modulating_setpoint", 24.0),
        )


def save_state(state: PersistedState) -> bool:
    """Saves controller state to disk.
    
    Args:
        state: State to persist
        
    Returns:
        True if successful, False otherwise
    """
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = state.to_dict()
        STATE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Controller state saved to %s", STATE_FILE)
        return True
    except Exception as e:
        logger.error("Error saving controller state: %s", e, exc_info=True)
        return False


def load_state() -> PersistedState | None:
    """Loads controller state from disk.
    
    Returns:
        PersistedState if file exists and is valid, None otherwise
    """
    try:
        if not STATE_FILE.exists():
            logger.info("No persisted state found at %s (first boot)", STATE_FILE)
            return None
        
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        state = PersistedState.from_dict(data)
        logger.info("Controller state loaded from %s", STATE_FILE)
        logger.info("  - State: %s", state.current_sm_state)
        logger.info("  - Target: %.1f°C", state.target_temperature)
        logger.info("  - Override: %s", state.override)
        return state
    except Exception as e:
        logger.error("Error loading controller state: %s", e, exc_info=True)
        return None
