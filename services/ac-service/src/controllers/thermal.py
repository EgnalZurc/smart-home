"""Thermal comfort calculations and energy tracking.

This module provides:
1. Thermal sample recording for analysis (ThermalSampleRecorder)
2. Energy consumption tracking by controller state (EnergyTracker)

These classes are injected into ACController to separate thermal/energy
concerns from the main control logic.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from thermal_analysis import ThermalBuffer

logger = logging.getLogger(__name__)


@dataclass
class EnergyConfig:
    """Power consumption parameters for each AC state.

    Attributes:
        ac_power_cooling_max: Power consumption in cooling_max state (kW).
        ac_power_cooling_mid: Power consumption in cooling_mid state (kW).
        ac_power_modulating: Power consumption in modulating state (kW).
        ac_power_forced_on: Power consumption in manual/forced_on state (kW).
    """

    ac_power_cooling_max: float = 2.5
    ac_power_cooling_mid: float = 1.75
    ac_power_modulating: float = 1.25
    ac_power_forced_on: float = 2.5


@dataclass
class EnergyState:
    """Internal state for energy tracking.

    Attributes:
        last_state: The previous AC state for duration calculation.
        last_transition: Timestamp of the last state transition.
        kwh_session: Accumulated kWh since last reset.
    """

    last_state: str = "off"
    last_transition: float = field(default_factory=time.time)
    kwh_session: float = 0.0


class EnergyTracker:
    """Tracks energy consumption based on AC state transitions.

    Calculates estimated kWh consumed by mapping controller states to
    power consumption values and tracking time spent in each state.

    Example:
        >>> config = EnergyConfig(ac_power_cooling_max=2.5)
        >>> tracker = EnergyTracker(config)
        >>> tracker.record_transition("cooling_max")
        >>> # ... time passes ...
        >>> tracker.record_transition("off")
        >>> print(f"Consumed: {tracker.get_session_kwh():.4f} kWh")
    """

    # Map of state names to power consumption attributes
    STATE_POWER_MAP: dict[str, str] = {
        "cooling_max": "ac_power_cooling_max",
        "cooling_mid": "ac_power_cooling_mid",
        "modulating": "ac_power_modulating",
        "forced_on": "ac_power_forced_on",
        "manual": "ac_power_forced_on",  # Manual uses same as forced_on
    }

    _config: EnergyConfig
    _state: EnergyState

    def __init__(self, config: EnergyConfig | None = None) -> None:
        """Initialize energy tracker.

        Args:
            config: Power consumption parameters. Uses defaults if None.
        """
        self._config = config or EnergyConfig()
        self._state = EnergyState()

    def get_power_for_state(self, state: str) -> float:
        """Return power consumption in kW for a given state.

        Args:
            state: Controller state name (e.g., "cooling_max", "off").

        Returns:
            Power consumption in kW, or 0.0 for off/unknown states.
        """
        attr_name = self.STATE_POWER_MAP.get(state)
        if attr_name is None:
            return 0.0
        return getattr(self._config, attr_name, 0.0)

    def record_transition(self, new_state: str) -> float:
        """Record a state transition and calculate energy consumed.

        Args:
            new_state: The new controller state name.

        Returns:
            kWh consumed in the previous state since last transition.
        """
        now = time.time()
        elapsed_hours = (now - self._state.last_transition) / 3600

        power_kw = self.get_power_for_state(self._state.last_state)
        kwh_consumed = power_kw * elapsed_hours
        self._state.kwh_session += kwh_consumed

        if kwh_consumed > 0:
            logger.debug(
                "Energy: state %s for %.2fh consumed %.4f kWh (session: %.4f kWh)",
                self._state.last_state,
                elapsed_hours,
                kwh_consumed,
                self._state.kwh_session,
            )

        self._state.last_state = new_state
        self._state.last_transition = now

        return kwh_consumed

    def get_session_kwh(self) -> float:
        """Return kWh consumed in current session including time in current state.

        Returns:
            Total kWh consumed since last reset.
        """
        now = time.time()
        elapsed_hours = (now - self._state.last_transition) / 3600
        power_kw = self.get_power_for_state(self._state.last_state)
        current_kwh = power_kw * elapsed_hours
        return self._state.kwh_session + current_kwh

    def reset_session(self) -> float:
        """Reset session energy counter.

        Typically called after logging hourly consumption.

        Returns:
            The accumulated kWh before reset.
        """
        accumulated = self._state.kwh_session
        logger.info("Resetting energy session (accumulated: %.4f kWh)", accumulated)
        self._state.kwh_session = 0.0
        self._state.last_transition = time.time()
        return accumulated

    def update_config(self, **kwargs: Any) -> None:
        """Update power configuration parameters.

        Args:
            **kwargs: Power parameters to update (e.g., ac_power_cooling_max=3.0).
        """
        for key, value in kwargs.items():
            if hasattr(self._config, key):
                setattr(self._config, key, value)


class ThermalSampleRecorder:
    """Records thermal samples for analysis.

    Bridges the control loop to the ThermalBuffer in thermal_analysis.py.
    Handles optional outdoor temperature provider and defensive error handling.

    Example:
        >>> from thermal_analysis import ThermalBuffer, ThermalSample
        >>> buffer = ThermalBuffer()
        >>> recorder = ThermalSampleRecorder(buffer)
        >>> recorder.set_outdoor_provider(lambda: 32.5)
        >>> recorder.record(
        ...     timestamp=time.time(),
        ...     average_temp=25.0,
        ...     setpoint=23.0,
        ...     state="modulating",
        ...     mode="cool",
        ... )
    """

    _buffer: ThermalBuffer | None
    _outdoor_provider: Callable[[], float | None] | None

    def __init__(self, buffer: ThermalBuffer | None = None) -> None:
        """Initialize thermal sample recorder.

        Args:
            buffer: ThermalBuffer instance for sample storage.
                Can be set later via set_buffer().
        """
        self._buffer = buffer
        self._outdoor_provider = None

    def set_buffer(self, buffer: ThermalBuffer) -> None:
        """Set or replace the thermal buffer.

        Args:
            buffer: ThermalBuffer instance for sample storage.
        """
        self._buffer = buffer

    def set_outdoor_provider(self, provider: Callable[[], float | None]) -> None:
        """Set the outdoor temperature provider.

        Args:
            provider: Zero-arg callable returning outdoor temp (°C) or None.
        """
        self._outdoor_provider = provider

    def record(
        self,
        timestamp: float,
        average_temp: float | None,
        setpoint: float,
        state: str,
        mode: str,
    ) -> bool:
        """Record a thermal sample.

        Args:
            timestamp: Unix timestamp of the sample.
            average_temp: Average indoor temperature (°C), or None.
            setpoint: Current AC setpoint (°C).
            state: Controller state name.
            mode: AC mode ("cool" or "heat").

        Returns:
            True if sample was recorded, False if no buffer configured.
        """
        if self._buffer is None:
            return False

        outdoor_temp = self._get_outdoor_temp()

        # Import here to avoid circular dependency
        from thermal_analysis import ThermalSample

        sample = ThermalSample(
            timestamp=timestamp,
            average_temp=round(average_temp, 2) if average_temp else None,
            setpoint=setpoint,
            state=state,
            mode=mode,
            outdoor_temp=outdoor_temp,
        )
        self._buffer.add(sample)
        return True

    def _get_outdoor_temp(self) -> float | None:
        """Safely get outdoor temperature from provider.

        Returns:
            Outdoor temperature in °C, or None if unavailable/error.
        """
        if self._outdoor_provider is None:
            return None

        try:
            return self._outdoor_provider()
        except Exception:
            logger.debug("Outdoor temp provider failed for thermal sample")
            return None

    @property
    def is_configured(self) -> bool:
        """Check if the recorder has a buffer configured."""
        return self._buffer is not None


def calculate_thermal_comfort_index(
    temperature: float,
    humidity: float,
    target_temp: float = 26.0,
) -> float:
    """Calculate a thermal comfort index (0-100).

    Combines temperature deviation from target with humidity effects.
    Higher values indicate better comfort.

    The formula uses:
    - Temperature penalty: abs deviation from target
    - Humidity penalty: deviation from 45% optimal humidity
    - Combined into 0-100 scale

    Args:
        temperature: Current temperature in °C.
        humidity: Current relative humidity in %.
        target_temp: Target temperature in °C.

    Returns:
        Comfort index from 0 (very uncomfortable) to 100 (perfect).

    Example:
        >>> calculate_thermal_comfort_index(26.0, 45.0, 26.0)
        100.0
        >>> calculate_thermal_comfort_index(28.0, 70.0, 26.0)
        62.5
    """
    # Optimal humidity is around 45%
    optimal_humidity = 45.0

    # Temperature component: 100 at target, decreasing with deviation
    # Lose 10 points per degree away from target
    temp_deviation = abs(temperature - target_temp)
    temp_score = max(0.0, 100.0 - temp_deviation * 10.0)

    # Humidity component: optimal at 45%, penalty for deviation
    # Lose 1 point per 2% away from optimal
    humidity_deviation = abs(humidity - optimal_humidity)
    humidity_score = max(0.0, 100.0 - humidity_deviation * 0.5)

    # Combined score (70% temperature, 30% humidity)
    comfort = temp_score * 0.7 + humidity_score * 0.3
    return round(max(0.0, min(100.0, comfort)), 1)


def estimate_time_to_target(
    current_temp: float,
    target_temp: float,
    rate_c_per_min: float,
) -> float | None:
    """Estimate minutes to reach target temperature.

    Args:
        current_temp: Current temperature in °C.
        target_temp: Target temperature in °C.
        rate_c_per_min: Temperature change rate in °C per minute
            (negative for cooling, positive for heating).

    Returns:
        Estimated minutes to reach target, or None if unreachable
        (rate is zero or moving away from target).

    Example:
        >>> estimate_time_to_target(28.0, 26.0, -0.1)  # Cooling
        20.0
    """
    if rate_c_per_min == 0:
        return None

    delta = target_temp - current_temp

    # Check if we're moving toward or away from target
    if delta > 0 and rate_c_per_min <= 0:
        return None  # Need to heat but cooling
    if delta < 0 and rate_c_per_min >= 0:
        return None  # Need to cool but heating

    minutes = abs(delta / rate_c_per_min)
    return round(minutes, 1)
