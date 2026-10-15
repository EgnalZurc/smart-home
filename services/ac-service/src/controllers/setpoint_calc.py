"""Setpoint calculation algorithms.

This module provides setpoint calculation strategies for the AC controller:
1. Proportional setpoint calculation within hysteresis band
2. Adaptive setpoint based on thermal analysis
3. Outdoor temperature compensation

These functions are pure calculations with no side effects, making them
easy to unit test and compose.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class SetpointConfig:
    """Configuration for setpoint calculations.

    Attributes:
        min_setpoint: Minimum allowable setpoint (°C).
        max_setpoint: Maximum allowable setpoint (°C).
        hysteresis_on: Temperature above target to trigger cooling (°C).
        hysteresis_off: Temperature below target to stop cooling (°C).
    """

    min_setpoint: float = 19.0
    max_setpoint: float = 30.0
    hysteresis_on: float = 0.5
    hysteresis_off: float = 0.3


@dataclass(frozen=True)
class SetpointResult:
    """Result of a setpoint calculation.

    Attributes:
        setpoint: Calculated setpoint temperature (°C).
        position: Position within hysteresis band (0.0-1.0).
        clamped: Whether the setpoint was clamped to limits.
    """

    setpoint: float
    position: float
    clamped: bool


def calculate_proportional_setpoint(
    average_temp: float,
    target_temp: float,
    config: SetpointConfig,
) -> SetpointResult:
    """Calculate proportional setpoint for modulating control.

    Maps the current temperature within the hysteresis band to a setpoint
    using linear interpolation:
    - At hot edge (target + hysteresis_on): returns min_setpoint (max cooling)
    - At cold edge (target - hysteresis_off): returns max_setpoint (min cooling)

    Args:
        average_temp: Current average temperature from sensors (°C).
        target_temp: Desired target temperature (°C).
        config: Setpoint configuration with limits and hysteresis.

    Returns:
        SetpointResult with calculated setpoint and metadata.

    Example:
        >>> config = SetpointConfig(min_setpoint=19.0, max_setpoint=30.0)
        >>> result = calculate_proportional_setpoint(26.5, 26.0, config)
        >>> result.setpoint  # Temperature is hot, setpoint is low
        19.0
    """
    range_size = config.hysteresis_on + config.hysteresis_off
    if range_size == 0:
        return SetpointResult(
            setpoint=config.min_setpoint,
            position=1.0,
            clamped=False,
        )

    # Calculate position within the hysteresis band
    cold_edge = target_temp - config.hysteresis_off
    position = (average_temp - cold_edge) / range_size

    # Clamp position to [0, 1]
    clamped = position < 0.0 or position > 1.0
    position = max(0.0, min(1.0, position))

    # Interpolate setpoint: high position -> low setpoint (more cooling)
    setpoint_range = config.max_setpoint - config.min_setpoint
    setpoint = config.max_setpoint - (position * setpoint_range)
    setpoint = round(max(config.min_setpoint, min(config.max_setpoint, setpoint)), 1)

    return SetpointResult(
        setpoint=setpoint,
        position=round(position, 3),
        clamped=clamped,
    )


def calculate_setpoint_simple(
    average_temp: float,
    target_temp: float,
    min_setpoint: float = 19.0,
    max_setpoint: float = 30.0,
    hysteresis_on: float = 0.5,
    hysteresis_off: float = 0.3,
) -> float:
    """Simplified setpoint calculation returning just the value.

    Convenience wrapper around calculate_proportional_setpoint for
    cases where only the setpoint value is needed.

    Args:
        average_temp: Current average temperature (°C).
        target_temp: Desired target temperature (°C).
        min_setpoint: Minimum setpoint (°C).
        max_setpoint: Maximum setpoint (°C).
        hysteresis_on: Hot threshold offset (°C).
        hysteresis_off: Cold threshold offset (°C).

    Returns:
        Calculated setpoint temperature (°C).
    """
    config = SetpointConfig(
        min_setpoint=min_setpoint,
        max_setpoint=max_setpoint,
        hysteresis_on=hysteresis_on,
        hysteresis_off=hysteresis_off,
    )
    return calculate_proportional_setpoint(average_temp, target_temp, config).setpoint


def calculate_outdoor_compensated_setpoint(
    indoor_temp: float,
    outdoor_temp: float,
    target_temp: float,
    config: SetpointConfig,
    outdoor_weight: float = 0.1,
) -> SetpointResult:
    """Calculate setpoint with outdoor temperature compensation.

    Adjusts the base proportional setpoint based on outdoor temperature:
    - Higher outdoor temp → slightly lower setpoint (more aggressive cooling)
    - Lower outdoor temp → slightly higher setpoint (less aggressive cooling)

    The adjustment is bounded to prevent extreme values.

    Args:
        indoor_temp: Current indoor temperature (°C).
        outdoor_temp: Current outdoor temperature (°C).
        target_temp: Desired target temperature (°C).
        config: Setpoint configuration.
        outdoor_weight: Weight of outdoor temp influence (0.0-0.3 typical).

    Returns:
        SetpointResult with compensated setpoint.

    Example:
        >>> config = SetpointConfig()
        >>> # Hot outdoor temp pushes setpoint lower
        >>> result = calculate_outdoor_compensated_setpoint(
        ...     indoor_temp=27.0, outdoor_temp=35.0, target_temp=26.0, config=config
        ... )
    """
    # Get base proportional setpoint
    base_result = calculate_proportional_setpoint(indoor_temp, target_temp, config)

    # Calculate outdoor compensation
    # Reference outdoor temp where no compensation is applied
    reference_outdoor = 25.0

    # Deviation from reference (positive = hotter outside)
    outdoor_deviation = outdoor_temp - reference_outdoor

    # Adjustment: hotter outside -> lower setpoint
    # Clamp weight to reasonable range
    weight = max(0.0, min(0.3, outdoor_weight))
    adjustment = -outdoor_deviation * weight

    # Apply adjustment with limits (max ±2°C from base)
    adjustment = max(-2.0, min(2.0, adjustment))
    compensated = base_result.setpoint + adjustment

    # Ensure within bounds
    clamped = compensated < config.min_setpoint or compensated > config.max_setpoint
    compensated = max(config.min_setpoint, min(config.max_setpoint, compensated))

    return SetpointResult(
        setpoint=round(compensated, 1),
        position=base_result.position,
        clamped=clamped or base_result.clamped,
    )


def calculate_adaptive_setpoint(
    current_temp: float,
    target_temp: float,
    config: SetpointConfig,
    rate_c_per_min: float | None = None,
    minutes_to_target: float | None = None,
) -> SetpointResult:
    """Calculate setpoint adapting to thermal performance.

    Adjusts the base setpoint based on observed cooling/heating rate:
    - If cooling is slower than expected, be more aggressive (lower setpoint)
    - If cooling is faster than expected, be more conservative (higher setpoint)

    Args:
        current_temp: Current temperature (°C).
        target_temp: Desired target temperature (°C).
        config: Setpoint configuration.
        rate_c_per_min: Observed temperature change rate (°C/min).
            Negative for cooling, positive for heating.
        minutes_to_target: Optional user-specified time to reach target.

    Returns:
        SetpointResult with adaptive setpoint.
    """
    base_result = calculate_proportional_setpoint(current_temp, target_temp, config)

    # Without rate data, return base calculation
    if rate_c_per_min is None:
        return base_result

    # Expected rate for proportional control: ~0.05°C/min at mid-band
    expected_rate = 0.05

    # Calculate rate efficiency (1.0 = expected, <1.0 = slower, >1.0 = faster)
    actual_rate = abs(rate_c_per_min)
    efficiency = 0.5 if actual_rate == 0 else min(2.0, actual_rate / expected_rate)

    # Adjust setpoint based on efficiency
    # Slower cooling -> lower setpoint (more aggressive)
    # Faster cooling -> higher setpoint (more conservative)
    if efficiency < 0.8:
        # Slow cooling: reduce setpoint by up to 1.5°C
        adjustment = (0.8 - efficiency) * 3.0
        adjustment = min(1.5, adjustment)
        adjusted = base_result.setpoint - adjustment
    elif efficiency > 1.2:
        # Fast cooling: increase setpoint by up to 1.0°C
        adjustment = (efficiency - 1.2) * 2.0
        adjustment = min(1.0, adjustment)
        adjusted = base_result.setpoint + adjustment
    else:
        # Normal range: no adjustment
        adjusted = base_result.setpoint

    # Clamp to limits
    clamped = adjusted < config.min_setpoint or adjusted > config.max_setpoint
    adjusted = max(config.min_setpoint, min(config.max_setpoint, adjusted))

    return SetpointResult(
        setpoint=round(adjusted, 1),
        position=base_result.position,
        clamped=clamped or base_result.clamped,
    )


def determine_zone(
    temperature: float,
    target_temp: float,
    hysteresis_on: float,
    hysteresis_off: float,
) -> str:
    """Determine which temperature zone the current reading is in.

    Args:
        temperature: Current temperature (°C).
        target_temp: Target temperature (°C).
        hysteresis_on: Hot threshold offset (°C).
        hysteresis_off: Cold threshold offset (°C).

    Returns:
        Zone name: "hot" (above band), "cold" (below band), or "band" (within).

    Example:
        >>> determine_zone(27.0, 26.0, 0.5, 0.3)
        'hot'
        >>> determine_zone(25.5, 26.0, 0.5, 0.3)
        'cold'
        >>> determine_zone(26.2, 26.0, 0.5, 0.3)
        'band'
    """
    hot_threshold = target_temp + hysteresis_on
    cold_threshold = target_temp - hysteresis_off

    if temperature > hot_threshold:
        return "hot"
    elif temperature < cold_threshold:
        return "cold"
    else:
        return "band"


def suggest_manual_setpoint(
    current_temp: float,
    target_temp: float,
    mode: str = "cool",
    comfort_priority: str = "balanced",
) -> float:
    """Suggest a manual setpoint based on current conditions and preferences.

    Args:
        current_temp: Current room temperature (°C).
        target_temp: User's target temperature (°C).
        mode: AC mode ("cool" or "heat").
        comfort_priority: User preference:
            - "aggressive": Reach target quickly (more extreme setpoint)
            - "balanced": Normal operation
            - "efficient": Energy efficient (conservative setpoint)

    Returns:
        Suggested setpoint temperature (°C).

    Example:
        >>> suggest_manual_setpoint(28.0, 26.0, "cool", "aggressive")
        19.0
        >>> suggest_manual_setpoint(28.0, 26.0, "cool", "efficient")
        24.0
    """
    delta = abs(current_temp - target_temp)

    if mode == "cool":
        if comfort_priority == "aggressive":
            # Set much lower to cool quickly
            setpoint = target_temp - 7.0
        elif comfort_priority == "efficient":
            # Set just below target
            setpoint = target_temp - min(2.0, delta * 0.5)
        else:  # balanced
            # Moderate offset
            setpoint = target_temp - min(4.0, delta)

        # Clamp to reasonable cooling range
        return round(max(17.0, min(26.0, setpoint)), 1)
    else:  # heat
        if comfort_priority == "aggressive":
            setpoint = target_temp + 4.0
        elif comfort_priority == "efficient":
            setpoint = target_temp + min(2.0, delta * 0.5)
        else:
            setpoint = target_temp + min(3.0, delta)

        # Clamp to reasonable heating range
        return round(max(20.0, min(30.0, setpoint)), 1)
