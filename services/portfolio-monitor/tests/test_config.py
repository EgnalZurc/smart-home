"""
Test configuration loading and defaults.

Ensures configuration is loaded correctly and sensible defaults are applied.
"""

import pytest


class TestDefaultConfiguration:
    """Tests for default configuration values."""

    def test_default_tax_brackets_exist(self):
        """Default IRPF 2025 brackets should be defined."""
        from config import _DEFAULT_TAX_BRACKETS

        assert len(_DEFAULT_TAX_BRACKETS) == 5, "Should have 5 IRPF 2025 brackets"

        # Verify brackets are in correct order and format
        limits = [b[0] for b in _DEFAULT_TAX_BRACKETS]
        rates = [b[1] for b in _DEFAULT_TAX_BRACKETS]

        # Limits should be ascending
        for i in range(len(limits) - 1):
            assert limits[i] < limits[i + 1], "Bracket limits should be ascending"

        # Last bracket should be infinity
        assert limits[-1] == float("inf"), "Last bracket should be infinity"

        # Rates should be ascending (progressive tax)
        for i in range(len(rates) - 1):
            assert rates[i] < rates[i + 1], "Tax rates should be progressive"

    def test_irpf_2025_bracket_values(self):
        """Verify IRPF 2025 bracket values match Ley 7/2024."""
        from config import _DEFAULT_TAX_BRACKETS

        expected = [
            (6_000, 0.19),
            (50_000, 0.21),
            (200_000, 0.23),
            (300_000, 0.27),
            (float("inf"), 0.30),
        ]

        for actual, exp in zip(_DEFAULT_TAX_BRACKETS, expected):
            assert actual[0] == exp[0], f"Limit mismatch: {actual[0]} != {exp[0]}"
            assert abs(actual[1] - exp[1]) < 0.001, f"Rate mismatch: {actual[1]} != {exp[1]}"

    def test_default_crypto_thresholds(self):
        """Test default crypto thresholds are sensible."""
        from config import CRYPTO_THRESHOLDS

        # Fear & Greed thresholds
        assert 70 <= CRYPTO_THRESHOLDS["fg_extreme_greed"] <= 80
        assert 55 <= CRYPTO_THRESHOLDS["fg_high_greed"] <= 70
        assert 20 <= CRYPTO_THRESHOLDS["fg_extreme_fear"] <= 30

        # Change thresholds
        assert CRYPTO_THRESHOLDS["change_24h_danger"] < CRYPTO_THRESHOLDS["change_24h_warn"] < 0
        assert CRYPTO_THRESHOLDS["change_24h_pump"] > 0

    def test_default_etf_thresholds(self):
        """Test default ETF thresholds are sensible."""
        from config import ETF_THRESHOLDS

        # Moving averages
        assert ETF_THRESHOLDS["ma_short"] == 50
        assert ETF_THRESHOLDS["ma_long"] == 200

        # Loss thresholds should be negative
        assert ETF_THRESHOLDS["drop_from_high_warn"] < 0
        assert ETF_THRESHOLDS["loss_vs_cost_warn"] < 0
        assert ETF_THRESHOLDS["critical_threshold"] < 0

        # Critical should be more severe than warning
        assert ETF_THRESHOLDS["critical_threshold"] < ETF_THRESHOLDS["drop_from_high_warn"]


class TestConfigReload:
    """Tests for configuration reload functionality."""

    def test_reload_returns_dict(self):
        """reload_config should return a dictionary."""
        from config import reload_config

        result = reload_config()
        assert isinstance(result, dict)


class TestScheduleConfig:
    """Tests for schedule configuration."""

    def test_schedule_has_required_keys(self):
        """Schedule config should have etf_time and crypto_time."""
        from config import SCHEDULE

        assert "etf_time" in SCHEDULE
        assert "crypto_time" in SCHEDULE

    def test_schedule_times_are_valid_format(self):
        """Schedule times should be in HH:MM format."""
        from config import SCHEDULE
        import re

        time_pattern = re.compile(r"^\d{2}:\d{2}$")

        assert time_pattern.match(SCHEDULE["etf_time"]), f"Invalid etf_time format: {SCHEDULE['etf_time']}"
        assert time_pattern.match(SCHEDULE["crypto_time"]), f"Invalid crypto_time format: {SCHEDULE['crypto_time']}"
