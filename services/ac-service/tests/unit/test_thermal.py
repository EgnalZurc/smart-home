"""Unit tests for thermal module.

Tests the EnergyTracker, ThermalSampleRecorder, and thermal comfort functions.
"""

import time
from unittest.mock import MagicMock

from controllers.thermal import (
    EnergyConfig,
    EnergyTracker,
    ThermalSampleRecorder,
    calculate_thermal_comfort_index,
    estimate_time_to_target,
)


class TestEnergyConfig:
    """Tests for EnergyConfig dataclass."""

    def test_default_values(self):
        """Should have sensible defaults."""
        config = EnergyConfig()

        assert config.ac_power_cooling_max == 2.5
        assert config.ac_power_cooling_mid == 1.75
        assert config.ac_power_modulating == 1.25
        assert config.ac_power_forced_on == 2.5

    def test_custom_values(self):
        """Should accept custom power values."""
        config = EnergyConfig(
            ac_power_cooling_max=3.0,
            ac_power_modulating=1.0,
        )

        assert config.ac_power_cooling_max == 3.0
        assert config.ac_power_modulating == 1.0


class TestEnergyTracker:
    """Tests for EnergyTracker class."""

    def test_init_default_config(self):
        """Should initialize with default config."""
        tracker = EnergyTracker()

        assert tracker.get_power_for_state("cooling_max") == 2.5
        assert tracker.get_power_for_state("off") == 0.0

    def test_init_custom_config(self):
        """Should use custom config."""
        config = EnergyConfig(ac_power_cooling_max=3.0)
        tracker = EnergyTracker(config)

        assert tracker.get_power_for_state("cooling_max") == 3.0

    def test_get_power_for_state_known(self):
        """Should return correct power for known states."""
        tracker = EnergyTracker()

        assert tracker.get_power_for_state("cooling_max") == 2.5
        assert tracker.get_power_for_state("cooling_mid") == 1.75
        assert tracker.get_power_for_state("modulating") == 1.25
        assert tracker.get_power_for_state("forced_on") == 2.5
        assert tracker.get_power_for_state("manual") == 2.5

    def test_get_power_for_state_unknown(self):
        """Should return 0.0 for unknown states."""
        tracker = EnergyTracker()

        assert tracker.get_power_for_state("off") == 0.0
        assert tracker.get_power_for_state("cooldown") == 0.0
        assert tracker.get_power_for_state("system_off") == 0.0
        assert tracker.get_power_for_state("unknown") == 0.0

    def test_record_transition_returns_kwh(self):
        """Should return consumed kWh on transition."""
        tracker = EnergyTracker()

        # First transition starts tracking
        tracker.record_transition("cooling_max")

        # Simulate time passing (mock internal state)
        tracker._state.last_transition = time.time() - 3600  # 1 hour ago

        # Transition to off after 1 hour at 2.5kW
        kwh = tracker.record_transition("off")

        # Should be approximately 2.5 kWh (1 hour * 2.5 kW)
        assert 2.4 <= kwh <= 2.6

    def test_get_session_kwh_includes_current(self):
        """Should include energy from current state."""
        tracker = EnergyTracker()
        tracker.record_transition("cooling_max")

        # Set transition time to 30 minutes ago
        tracker._state.last_transition = time.time() - 1800

        # Should include ~1.25 kWh (0.5h * 2.5kW)
        session_kwh = tracker.get_session_kwh()
        assert 1.2 <= session_kwh <= 1.3

    def test_reset_session(self):
        """Should reset accumulated kWh."""
        tracker = EnergyTracker()
        tracker._state.kwh_session = 10.0

        accumulated = tracker.reset_session()

        assert accumulated == 10.0
        assert tracker._state.kwh_session == 0.0

    def test_update_config(self):
        """Should update power configuration."""
        tracker = EnergyTracker()

        tracker.update_config(ac_power_cooling_max=3.5)

        assert tracker.get_power_for_state("cooling_max") == 3.5


class TestThermalSampleRecorder:
    """Tests for ThermalSampleRecorder class."""

    def test_init_without_buffer(self):
        """Should initialize without buffer."""
        recorder = ThermalSampleRecorder()

        assert not recorder.is_configured

    def test_init_with_buffer(self):
        """Should initialize with buffer."""
        buffer = MagicMock()
        recorder = ThermalSampleRecorder(buffer)

        assert recorder.is_configured

    def test_set_buffer(self):
        """Should allow setting buffer later."""
        recorder = ThermalSampleRecorder()
        buffer = MagicMock()

        recorder.set_buffer(buffer)

        assert recorder.is_configured

    def test_record_without_buffer(self):
        """Should return False when no buffer configured."""
        recorder = ThermalSampleRecorder()

        result = recorder.record(
            timestamp=time.time(),
            average_temp=25.0,
            setpoint=23.0,
            state="modulating",
            mode="cool",
        )

        assert result is False

    def test_record_with_buffer(self):
        """Should add sample to buffer."""
        buffer = MagicMock()
        recorder = ThermalSampleRecorder(buffer)

        result = recorder.record(
            timestamp=time.time(),
            average_temp=25.0,
            setpoint=23.0,
            state="modulating",
            mode="cool",
        )

        assert result is True
        buffer.add.assert_called_once()

    def test_record_with_outdoor_provider(self):
        """Should include outdoor temp from provider."""
        buffer = MagicMock()
        recorder = ThermalSampleRecorder(buffer)
        recorder.set_outdoor_provider(lambda: 32.5)

        recorder.record(
            timestamp=time.time(),
            average_temp=25.0,
            setpoint=23.0,
            state="modulating",
            mode="cool",
        )

        # Verify sample was added with outdoor temp
        call_args = buffer.add.call_args[0][0]
        assert call_args.outdoor_temp == 32.5

    def test_record_handles_provider_exception(self):
        """Should handle provider exceptions gracefully."""
        buffer = MagicMock()
        recorder = ThermalSampleRecorder(buffer)
        recorder.set_outdoor_provider(lambda: 1 / 0)  # Will raise

        # Should not raise
        result = recorder.record(
            timestamp=time.time(),
            average_temp=25.0,
            setpoint=23.0,
            state="modulating",
            mode="cool",
        )

        assert result is True
        call_args = buffer.add.call_args[0][0]
        assert call_args.outdoor_temp is None


class TestThermalComfortIndex:
    """Tests for calculate_thermal_comfort_index function."""

    def test_perfect_comfort(self):
        """Should return 100 at target temp and optimal humidity."""
        comfort = calculate_thermal_comfort_index(26.0, 45.0, 26.0)

        assert comfort == 100.0

    def test_temperature_penalty(self):
        """Should reduce comfort with temperature deviation."""
        # 2°C above target
        comfort = calculate_thermal_comfort_index(28.0, 45.0, 26.0)

        # 2°C * 10 points/°C = 20 points off temp component
        # Temp score: 80, Humidity: 100
        # Combined: 80*0.7 + 100*0.3 = 56 + 30 = 86
        assert comfort == 86.0

    def test_humidity_penalty(self):
        """Should reduce comfort with humidity deviation."""
        # 25% above optimal humidity
        comfort = calculate_thermal_comfort_index(26.0, 70.0, 26.0)

        # Humidity deviation: 25, penalty: 25*0.5 = 12.5
        # Humidity score: 87.5
        # Combined: 100*0.7 + 87.5*0.3 = 70 + 26.25 = 96.25 -> 96.2
        assert comfort == 96.2

    def test_combined_penalties(self):
        """Should combine temp and humidity penalties."""
        comfort = calculate_thermal_comfort_index(28.0, 70.0, 26.0)

        # Temp: 80, Humidity: 87.5
        # Combined: 80*0.7 + 87.5*0.3 = 56 + 26.25 = 82.25 -> 82.2
        assert comfort == 82.2

    def test_clamps_to_zero(self):
        """Should not go below zero."""
        # Extreme deviation
        comfort = calculate_thermal_comfort_index(40.0, 100.0, 26.0)

        assert comfort >= 0.0

    def test_clamps_to_hundred(self):
        """Should not exceed 100."""
        comfort = calculate_thermal_comfort_index(26.0, 45.0, 26.0)

        assert comfort <= 100.0


class TestEstimateTimeToTarget:
    """Tests for estimate_time_to_target function."""

    def test_cooling_to_target(self):
        """Should estimate time for cooling."""
        # 28°C -> 26°C at -0.1°C/min
        minutes = estimate_time_to_target(28.0, 26.0, -0.1)

        assert minutes == 20.0

    def test_heating_to_target(self):
        """Should estimate time for heating."""
        # 20°C -> 24°C at 0.2°C/min
        minutes = estimate_time_to_target(20.0, 24.0, 0.2)

        assert minutes == 20.0

    def test_zero_rate(self):
        """Should return None when rate is zero."""
        minutes = estimate_time_to_target(28.0, 26.0, 0.0)

        assert minutes is None

    def test_wrong_direction_cooling(self):
        """Should return None when cooling but need to heat."""
        # Need to heat (target > current) but rate is negative (cooling)
        minutes = estimate_time_to_target(24.0, 26.0, -0.1)

        assert minutes is None

    def test_wrong_direction_heating(self):
        """Should return None when heating but need to cool."""
        # Need to cool (target < current) but rate is positive (heating)
        minutes = estimate_time_to_target(28.0, 26.0, 0.1)

        assert minutes is None

    def test_already_at_target(self):
        """Should return 0 when already at target."""
        minutes = estimate_time_to_target(26.0, 26.0, -0.1)

        # 0 delta / 0.1 rate = 0 minutes
        assert minutes == 0.0
