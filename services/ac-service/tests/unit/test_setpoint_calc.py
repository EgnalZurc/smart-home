"""Unit tests for setpoint_calc module.

Tests the setpoint calculation algorithms.
"""

from controllers.setpoint_calc import (
    SetpointConfig,
    calculate_adaptive_setpoint,
    calculate_outdoor_compensated_setpoint,
    calculate_proportional_setpoint,
    calculate_setpoint_simple,
    determine_zone,
    suggest_manual_setpoint,
)


class TestSetpointConfig:
    """Tests for SetpointConfig dataclass."""

    def test_default_values(self):
        """Should have sensible defaults."""
        config = SetpointConfig()

        assert config.min_setpoint == 19.0
        assert config.max_setpoint == 30.0
        assert config.hysteresis_on == 0.5
        assert config.hysteresis_off == 0.3

    def test_custom_values(self):
        """Should accept custom values."""
        config = SetpointConfig(
            min_setpoint=18.0,
            max_setpoint=28.0,
            hysteresis_on=1.0,
            hysteresis_off=0.5,
        )

        assert config.min_setpoint == 18.0
        assert config.max_setpoint == 28.0
        assert config.hysteresis_on == 1.0
        assert config.hysteresis_off == 0.5


class TestCalculateProportionalSetpoint:
    """Tests for calculate_proportional_setpoint function."""

    def test_at_hot_edge(self):
        """Should return min_setpoint at hot edge of band."""
        config = SetpointConfig(
            min_setpoint=19.0,
            max_setpoint=30.0,
            hysteresis_on=0.5,
            hysteresis_off=0.3,
        )

        # At hot edge: target + hysteresis_on = 26.5
        result = calculate_proportional_setpoint(26.5, 26.0, config)

        assert result.setpoint == 19.0
        assert result.position == 1.0
        # At exactly edge, position is clamped to 1.0
        assert result.clamped is True

    def test_at_cold_edge(self):
        """Should return max_setpoint at cold edge of band."""
        config = SetpointConfig(
            min_setpoint=19.0,
            max_setpoint=30.0,
            hysteresis_on=0.5,
            hysteresis_off=0.3,
        )

        # At cold edge: target - hysteresis_off = 25.7
        result = calculate_proportional_setpoint(25.7, 26.0, config)

        assert result.setpoint == 30.0
        assert result.position == 0.0
        assert result.clamped is False

    def test_at_target(self):
        """Should return mid-range setpoint at target."""
        config = SetpointConfig(
            min_setpoint=19.0,
            max_setpoint=30.0,
            hysteresis_on=0.5,
            hysteresis_off=0.3,
        )

        result = calculate_proportional_setpoint(26.0, 26.0, config)

        # Position should be 0.375 (0.3 / 0.8)
        # Setpoint should be 30 - (0.375 * 11) = 25.875 -> 25.9
        assert 25.0 <= result.setpoint <= 26.0
        assert 0.3 <= result.position <= 0.4

    def test_above_hot_edge(self):
        """Should clamp position and mark as clamped above hot edge."""
        config = SetpointConfig()

        # Well above hot edge
        result = calculate_proportional_setpoint(28.0, 26.0, config)

        assert result.setpoint == 19.0
        assert result.position == 1.0
        assert result.clamped is True

    def test_below_cold_edge(self):
        """Should clamp position and mark as clamped below cold edge."""
        config = SetpointConfig()

        # Well below cold edge
        result = calculate_proportional_setpoint(24.0, 26.0, config)

        assert result.setpoint == 30.0
        assert result.position == 0.0
        assert result.clamped is True

    def test_zero_range(self):
        """Should handle zero hysteresis range."""
        config = SetpointConfig(hysteresis_on=0.0, hysteresis_off=0.0)

        result = calculate_proportional_setpoint(26.0, 26.0, config)

        assert result.setpoint == config.min_setpoint
        assert result.position == 1.0


class TestCalculateSetpointSimple:
    """Tests for calculate_setpoint_simple function."""

    def test_returns_float(self):
        """Should return just the setpoint value."""
        setpoint = calculate_setpoint_simple(26.5, 26.0)

        assert isinstance(setpoint, float)
        assert setpoint == 19.0

    def test_accepts_custom_params(self):
        """Should accept custom parameters."""
        setpoint = calculate_setpoint_simple(
            average_temp=26.5,
            target_temp=26.0,
            min_setpoint=20.0,
            max_setpoint=28.0,
        )

        assert setpoint == 20.0


class TestCalculateOutdoorCompensatedSetpoint:
    """Tests for calculate_outdoor_compensated_setpoint function."""

    def test_no_compensation_at_reference(self):
        """Should not adjust when outdoor equals reference (25°C)."""
        config = SetpointConfig()

        result = calculate_outdoor_compensated_setpoint(
            indoor_temp=26.5,
            outdoor_temp=25.0,
            target_temp=26.0,
            config=config,
        )

        # Should be same as base proportional
        assert result.setpoint == 19.0

    def test_hot_outdoor_lowers_setpoint(self):
        """Should lower setpoint when outdoor is hot."""
        config = SetpointConfig()

        result = calculate_outdoor_compensated_setpoint(
            indoor_temp=26.0,
            outdoor_temp=35.0,  # 10°C above reference
            target_temp=26.0,
            config=config,
            outdoor_weight=0.1,
        )

        # Base setpoint ~25.9, adjustment: -10*0.1 = -1
        # Should be lower than base
        base = calculate_proportional_setpoint(26.0, 26.0, config)
        assert result.setpoint < base.setpoint

    def test_cold_outdoor_raises_setpoint(self):
        """Should raise setpoint when outdoor is cold."""
        config = SetpointConfig()

        result = calculate_outdoor_compensated_setpoint(
            indoor_temp=26.0,
            outdoor_temp=15.0,  # 10°C below reference
            target_temp=26.0,
            config=config,
            outdoor_weight=0.1,
        )

        # Should be higher than base
        base = calculate_proportional_setpoint(26.0, 26.0, config)
        assert result.setpoint > base.setpoint

    def test_clamps_adjustment(self):
        """Should clamp adjustment to ±2°C."""
        config = SetpointConfig()

        # Extreme outdoor temp
        result = calculate_outdoor_compensated_setpoint(
            indoor_temp=26.0,
            outdoor_temp=55.0,  # 30°C above reference
            target_temp=26.0,
            config=config,
            outdoor_weight=0.1,
        )

        # Max adjustment is -2°C (clamped)
        base = calculate_proportional_setpoint(26.0, 26.0, config)
        assert result.setpoint >= base.setpoint - 2.0

    def test_respects_min_setpoint(self):
        """Should not go below min_setpoint."""
        config = SetpointConfig(min_setpoint=19.0)

        # Already at min, hot outdoor
        result = calculate_outdoor_compensated_setpoint(
            indoor_temp=27.0,
            outdoor_temp=40.0,
            target_temp=26.0,
            config=config,
        )

        assert result.setpoint >= config.min_setpoint


class TestCalculateAdaptiveSetpoint:
    """Tests for calculate_adaptive_setpoint function."""

    def test_no_rate_data(self):
        """Should return base calculation without rate data."""
        config = SetpointConfig()

        result = calculate_adaptive_setpoint(26.0, 26.0, config)

        base = calculate_proportional_setpoint(26.0, 26.0, config)
        assert result.setpoint == base.setpoint

    def test_slow_cooling_lowers_setpoint(self):
        """Should lower setpoint when cooling is slow."""
        config = SetpointConfig()

        result = calculate_adaptive_setpoint(
            current_temp=26.0,
            target_temp=26.0,
            config=config,
            rate_c_per_min=-0.01,  # Very slow cooling (expected ~0.05)
        )

        base = calculate_proportional_setpoint(26.0, 26.0, config)
        assert result.setpoint < base.setpoint

    def test_fast_cooling_raises_setpoint(self):
        """Should raise setpoint when cooling is fast."""
        config = SetpointConfig()

        result = calculate_adaptive_setpoint(
            current_temp=26.0,
            target_temp=26.0,
            config=config,
            rate_c_per_min=-0.15,  # Fast cooling
        )

        base = calculate_proportional_setpoint(26.0, 26.0, config)
        assert result.setpoint > base.setpoint

    def test_normal_rate_no_adjustment(self):
        """Should not adjust at normal rate."""
        config = SetpointConfig()

        result = calculate_adaptive_setpoint(
            current_temp=26.0,
            target_temp=26.0,
            config=config,
            rate_c_per_min=-0.05,  # Expected rate
        )

        base = calculate_proportional_setpoint(26.0, 26.0, config)
        assert result.setpoint == base.setpoint

    def test_zero_rate_treated_as_slow(self):
        """Should treat zero rate as slow cooling."""
        config = SetpointConfig()

        result = calculate_adaptive_setpoint(
            current_temp=26.0,
            target_temp=26.0,
            config=config,
            rate_c_per_min=0.0,
        )

        base = calculate_proportional_setpoint(26.0, 26.0, config)
        # Zero rate gives efficiency 0.5, which is < 0.8, so adjustment
        assert result.setpoint <= base.setpoint


class TestDetermineZone:
    """Tests for determine_zone function."""

    def test_hot_zone(self):
        """Should detect hot zone above band."""
        zone = determine_zone(27.0, 26.0, 0.5, 0.3)

        assert zone == "hot"

    def test_cold_zone(self):
        """Should detect cold zone below band."""
        zone = determine_zone(25.5, 26.0, 0.5, 0.3)

        assert zone == "cold"

    def test_band_zone(self):
        """Should detect band zone within thresholds."""
        zone = determine_zone(26.2, 26.0, 0.5, 0.3)

        assert zone == "band"

    def test_at_hot_threshold(self):
        """Should be band at exactly hot threshold."""
        zone = determine_zone(26.5, 26.0, 0.5, 0.3)

        # At threshold is still within band
        assert zone == "band"

    def test_at_cold_threshold(self):
        """Should be band at exactly cold threshold."""
        zone = determine_zone(25.7, 26.0, 0.5, 0.3)

        # At threshold is still within band
        assert zone == "band"


class TestSuggestManualSetpoint:
    """Tests for suggest_manual_setpoint function."""

    def test_cool_aggressive(self):
        """Should suggest low setpoint for aggressive cooling."""
        setpoint = suggest_manual_setpoint(28.0, 26.0, "cool", "aggressive")

        assert setpoint == 19.0

    def test_cool_balanced(self):
        """Should suggest moderate setpoint for balanced cooling."""
        setpoint = suggest_manual_setpoint(28.0, 26.0, "cool", "balanced")

        # 26 - min(4, 2) = 24
        assert setpoint == 24.0

    def test_cool_efficient(self):
        """Should suggest conservative setpoint for efficient cooling."""
        setpoint = suggest_manual_setpoint(28.0, 26.0, "cool", "efficient")

        # 26 - min(2, 2*0.5) = 26 - 1 = 25
        assert setpoint == 25.0

    def test_heat_aggressive(self):
        """Should suggest high setpoint for aggressive heating."""
        setpoint = suggest_manual_setpoint(20.0, 24.0, "heat", "aggressive")

        assert setpoint == 28.0

    def test_heat_balanced(self):
        """Should suggest moderate setpoint for balanced heating."""
        setpoint = suggest_manual_setpoint(20.0, 24.0, "heat", "balanced")

        # 24 + min(3, 4) = 27
        assert setpoint == 27.0

    def test_heat_efficient(self):
        """Should suggest conservative setpoint for efficient heating."""
        setpoint = suggest_manual_setpoint(20.0, 24.0, "heat", "efficient")

        # 24 + min(2, 4*0.5) = 26
        assert setpoint == 26.0

    def test_clamps_cooling_range(self):
        """Should clamp to valid cooling range."""
        # Very aggressive cooling
        setpoint = suggest_manual_setpoint(30.0, 26.0, "cool", "aggressive")

        assert setpoint >= 17.0
        assert setpoint <= 26.0

    def test_clamps_heating_range(self):
        """Should clamp to valid heating range."""
        # Very aggressive heating
        setpoint = suggest_manual_setpoint(15.0, 24.0, "heat", "aggressive")

        assert setpoint >= 20.0
        assert setpoint <= 30.0
