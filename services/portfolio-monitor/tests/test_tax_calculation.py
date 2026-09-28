"""
Test IRPF tax calculation for capital gains.

These tests verify the progressive bracket calculation is correct
according to Spanish tax law (Ley 7/2024, vigente desde 1 enero 2025).
"""

import pytest


class TestIRPFCalculation:
    """Tests for IRPF capital gains tax calculation."""

    def test_small_gain_first_bracket(self, irpf_2025_brackets):
        """5.000€ gain should be taxed at 19% = 950€."""
        from monitors import etf_monitor

        original = etf_monitor.ETF_PLAN.get("tax_brackets")
        etf_monitor.ETF_PLAN["tax_brackets"] = irpf_2025_brackets

        try:
            tax = etf_monitor.calculate_tax(5_000)
            assert abs(tax - 950) < 0.01
        finally:
            etf_monitor.ETF_PLAN["tax_brackets"] = original

    def test_exactly_first_bracket_limit(self, irpf_2025_brackets):
        """6.000€ at 19% = 1.140€."""
        from monitors import etf_monitor

        original = etf_monitor.ETF_PLAN.get("tax_brackets")
        etf_monitor.ETF_PLAN["tax_brackets"] = irpf_2025_brackets

        try:
            tax = etf_monitor.calculate_tax(6_000)
            assert abs(tax - 1_140) < 0.01
        finally:
            etf_monitor.ETF_PLAN["tax_brackets"] = original

    def test_second_bracket(self, irpf_2025_brackets):
        """20.000€ = 6.000 × 19% + 14.000 × 21% = 4.080€."""
        from monitors import etf_monitor

        original = etf_monitor.ETF_PLAN.get("tax_brackets")
        etf_monitor.ETF_PLAN["tax_brackets"] = irpf_2025_brackets

        try:
            tax = etf_monitor.calculate_tax(20_000)
            assert abs(tax - 4_080) < 0.01
        finally:
            etf_monitor.ETF_PLAN["tax_brackets"] = original

    def test_at_second_bracket_limit(self, irpf_2025_brackets):
        """50.000€ = 6.000 × 19% + 44.000 × 21% = 10.380€."""
        from monitors import etf_monitor

        original = etf_monitor.ETF_PLAN.get("tax_brackets")
        etf_monitor.ETF_PLAN["tax_brackets"] = irpf_2025_brackets

        try:
            tax = etf_monitor.calculate_tax(50_000)
            assert abs(tax - 10_380) < 0.01
        finally:
            etf_monitor.ETF_PLAN["tax_brackets"] = original

    def test_third_bracket(self, irpf_2025_brackets):
        """100.000€ = 6k×19% + 44k×21% + 50k×23% = 21.880€."""
        from monitors import etf_monitor

        original = etf_monitor.ETF_PLAN.get("tax_brackets")
        etf_monitor.ETF_PLAN["tax_brackets"] = irpf_2025_brackets

        try:
            tax = etf_monitor.calculate_tax(100_000)
            assert abs(tax - 21_880) < 0.01
        finally:
            etf_monitor.ETF_PLAN["tax_brackets"] = original

    def test_all_brackets_large_gain(self, irpf_2025_brackets):
        """
        400.000€ spans all 5 brackets:
        6k×19% + 44k×21% + 150k×23% + 100k×27% + 100k×30% = 101.880€
        """
        from monitors import etf_monitor

        original = etf_monitor.ETF_PLAN.get("tax_brackets")
        etf_monitor.ETF_PLAN["tax_brackets"] = irpf_2025_brackets

        try:
            tax = etf_monitor.calculate_tax(400_000)
            assert abs(tax - 101_880) < 0.01
        finally:
            etf_monitor.ETF_PLAN["tax_brackets"] = original

    def test_zero_gain(self, irpf_2025_brackets):
        """Zero gain = zero tax."""
        from monitors import etf_monitor

        original = etf_monitor.ETF_PLAN.get("tax_brackets")
        etf_monitor.ETF_PLAN["tax_brackets"] = irpf_2025_brackets

        try:
            assert etf_monitor.calculate_tax(0) == 0
        finally:
            etf_monitor.ETF_PLAN["tax_brackets"] = original

    def test_negative_gain_loss(self, irpf_2025_brackets):
        """Losses should result in zero tax."""
        from monitors import etf_monitor

        original = etf_monitor.ETF_PLAN.get("tax_brackets")
        etf_monitor.ETF_PLAN["tax_brackets"] = irpf_2025_brackets

        try:
            assert etf_monitor.calculate_tax(-5_000) == 0
        finally:
            etf_monitor.ETF_PLAN["tax_brackets"] = original


class TestTaxImpact:
    """Tests for tax impact calculation when selling positions."""

    def test_tax_impact_with_gain(self, irpf_2025_brackets):
        """Test tax impact calculation for a profitable position."""
        from monitors import etf_monitor

        original = etf_monitor.ETF_PLAN.get("tax_brackets")
        etf_monitor.ETF_PLAN["tax_brackets"] = irpf_2025_brackets

        try:
            # 10 units, bought at 100€, now worth 150€ = 500€ gain
            result = etf_monitor.calculate_tax_impact(
                units=10, avg_cost=100.0, current_price=150.0
            )

            assert result is not None
            assert result["gain"] == 500.0  # (150-100) * 10
            assert result["tax"] == 95.0  # 500 × 19%
            assert result["net"] == 1500.0 - 95.0  # Value minus tax
        finally:
            etf_monitor.ETF_PLAN["tax_brackets"] = original

    def test_tax_impact_with_loss(self, irpf_2025_brackets):
        """Test tax impact for a position in loss."""
        from monitors import etf_monitor

        original = etf_monitor.ETF_PLAN.get("tax_brackets")
        etf_monitor.ETF_PLAN["tax_brackets"] = irpf_2025_brackets

        try:
            # 10 units, bought at 150€, now worth 100€ = -500€ loss
            result = etf_monitor.calculate_tax_impact(
                units=10, avg_cost=150.0, current_price=100.0
            )

            assert result is not None
            assert result["gain"] == -500.0
            assert result["tax"] == 0.0  # No tax on losses
            assert result["net"] == 1000.0  # Full value, no tax
        finally:
            etf_monitor.ETF_PLAN["tax_brackets"] = original

    def test_tax_impact_no_cost_basis(self):
        """Test with no average cost (should return None)."""
        from monitors import etf_monitor

        result = etf_monitor.calculate_tax_impact(
            units=10, avg_cost=None, current_price=100.0
        )
        assert result is None

    def test_tax_impact_zero_units(self):
        """Test with zero units (should return None)."""
        from monitors import etf_monitor

        result = etf_monitor.calculate_tax_impact(
            units=0, avg_cost=100.0, current_price=150.0
        )
        assert result is None
