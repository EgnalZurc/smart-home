"""Unit tests for ETF monitor module."""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta


class TestTaxCalculation:
    """Tests for IRPF tax calculation."""

    def test_zero_gain_zero_tax(self):
        """Zero or negative gain should result in zero tax."""
        from monitors.etf_monitor import calculate_tax
        
        assert calculate_tax(0) == 0.0
        assert calculate_tax(-1000) == 0.0

    def test_tax_with_brackets(self):
        """Tax calculation should use brackets when configured."""
        from monitors.etf_monitor import calculate_tax
        from config import ETF_PLAN
        
        # Only test if brackets are configured
        brackets = ETF_PLAN.get("tax_brackets", [])
        if brackets:
            gain = 5000
            tax = calculate_tax(gain)
            # Should produce some tax if brackets exist
            assert tax >= 0

    def test_tax_impact_with_gain_and_loss(self):
        """Tax impact calculation for gains and losses."""
        from monitors.etf_monitor import calculate_tax_impact
        
        # Test with gain
        result_gain = calculate_tax_impact(100, 50.0, 60.0)
        assert result_gain is not None
        assert result_gain["gain"] == 1000  # (60 - 50) * 100
        
        # Test with loss
        result_loss = calculate_tax_impact(100, 60.0, 50.0)
        assert result_loss["gain"] < 0
        assert result_loss["tax"] == 0


class TestPlanHelpers:
    """Tests for ETF plan helper functions."""

    def test_current_contribution(self):
        """current_contribution should return configured value."""
        from monitors.etf_monitor import current_contribution
        
        # This depends on config, just verify it returns a number
        contrib = current_contribution("IE00B4L5Y983")
        assert isinstance(contrib, (int, float))

    def test_years_since_start(self):
        """years_since_start should return positive integer."""
        from monitors.etf_monitor import years_since_start
        
        years = years_since_start()
        assert isinstance(years, int)
        assert years >= 1


class TestSignalCalculation:
    """Tests for technical signal calculation."""

    def test_calculate_signals_empty_dataframe(self):
        """Should handle empty dataframe gracefully."""
        from monitors.etf_monitor import calculate_signals
        
        empty_df = pd.DataFrame()
        result = calculate_signals(empty_df, None)
        
        assert result["price"] == 0
        assert result["signals"] == []

    def test_calculate_signals_with_data(self):
        """Should calculate signals from price data."""
        from monitors.etf_monitor import calculate_signals
        
        # Create sample price data (1 year of daily prices)
        dates = pd.date_range(end=datetime.now(), periods=252, freq='D')
        prices = np.random.uniform(90, 110, 252)  # Random walk around 100
        
        df = pd.DataFrame({
            'Open': prices,
            'High': prices * 1.02,
            'Low': prices * 0.98,
            'Close': prices,
            'Volume': np.random.randint(1000, 10000, 252)
        }, index=dates)
        
        result = calculate_signals(df, avg_cost=100.0)
        
        assert result["price"] > 0
        assert "ma50" in result
        assert "ma200" in result
        assert "drawdown" in result
        assert "signals" in result

    def test_drawdown_calculation(self):
        """Drawdown should be calculated correctly."""
        from monitors.etf_monitor import calculate_signals
        
        # Create data where current price is 10% below 52-week high
        dates = pd.date_range(end=datetime.now(), periods=252, freq='D')
        prices = [100] * 200 + [90] * 52  # Dropped from 100 to 90
        
        df = pd.DataFrame({
            'Open': prices,
            'High': [105] * 200 + [95] * 52,  # High was 105
            'Low': prices,
            'Close': prices,
            'Volume': [1000] * 252
        }, index=dates)
        
        result = calculate_signals(df, None)
        
        # Drawdown should be negative (price below high)
        assert result["drawdown"] < 0


class TestMovingAverageAnalysis:
    """Tests for moving average signal analysis."""

    def test_golden_cross_detection(self):
        """Should detect golden cross (MA50 crosses above MA200)."""
        from monitors.etf_monitor import _analyse_moving_averages
        from models import AlertLevel
        
        # Create data where MA50 just crossed above MA200
        dates = pd.date_range(end=datetime.now(), periods=252, freq='D')
        
        # Prices that would create a recent golden cross
        prices = list(range(80, 332))  # Steadily increasing
        df = pd.DataFrame({
            'Close': prices,
        }, index=dates)
        
        price = prices[-1]
        ma50 = np.mean(prices[-50:])
        ma200 = np.mean(prices[-200:])
        
        signals, level = _analyse_moving_averages(df, price, ma50, ma200)
        
        # Should produce some signals
        assert len(signals) >= 1


class TestRecommendations:
    """Tests for recommendation generation."""

    def test_danger_recommendation(self):
        """Danger level should produce danger recommendation."""
        from monitors.etf_monitor import get_recommendation
        from models import AlertLevel
        
        rec = get_recommendation(AlertLevel.DANGER, "Test Fund")
        
        assert rec.level == "DANGER"
        assert "Test Fund" in rec.body

    def test_ok_recommendation(self):
        """OK level should produce OK recommendation."""
        from monitors.etf_monitor import get_recommendation
        from models import AlertLevel
        
        rec = get_recommendation(AlertLevel.OK, "Test Fund")
        
        assert rec.level == "OK"
