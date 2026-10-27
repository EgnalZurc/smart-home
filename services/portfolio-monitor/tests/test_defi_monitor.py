"""
Tests for the defi_monitor module.
"""

from unittest.mock import patch

import pytest
from models import AlertLevel


class TestYieldCalculation:
    """Tests for the yield projection function."""

    def test_calculate_yield(self):
        """Yield is projected correctly from amount and APY."""
        from monitors.defi_monitor import calculate_yield

        daily, monthly, yearly = calculate_yield(amount=1000, apy_pct=5.0)

        assert abs(yearly - 50) < 0.01  # 1000 * 0.05
        assert abs(monthly - (50 / 12)) < 0.01
        assert abs(daily - (50 / 365)) < 0.01

    def test_calculate_yield_zero_amount(self):
        """Zero amount means zero yield."""
        from monitors.defi_monitor import calculate_yield

        daily, monthly, yearly = calculate_yield(amount=0, apy_pct=5.0)

        assert daily == 0
        assert monthly == 0
        assert yearly == 0

    def test_calculate_yield_zero_apy(self):
        """Zero APY means zero yield."""
        from monitors.defi_monitor import calculate_yield

        daily, monthly, yearly = calculate_yield(amount=1000, apy_pct=0)

        assert daily == 0
        assert monthly == 0
        assert yearly == 0


class TestDeFiMonitor:
    """Tests for the DeFiMonitor class."""

    @pytest.mark.asyncio
    async def test_empty_positions(self):
        """Monitor handles an empty positions list."""
        from monitors.defi_monitor import DeFiMonitor

        with patch("config.DEFI_POSITIONS", []):
            monitor = DeFiMonitor()
            result = await monitor.run()

        assert result["total_value"] == 0
        assert result["yearly_yield"] == 0
        assert result["level"] == AlertLevel.OK
        assert len(result["analysis"]) == 0
        assert result["last_update"] is None

    @pytest.mark.asyncio
    async def test_single_position(self):
        """Monitor processes a single position correctly."""
        from monitors.defi_monitor import DeFiMonitor

        positions = [
            {
                "protocol": "Aave",
                "asset": "USDC",
                "amount": 1000.0,
                "apy_pct": 4.5,
                "platform_url": "https://app.aave.com/",
            }
        ]

        with patch("config.DEFI_POSITIONS", positions):
            monitor = DeFiMonitor()
            result = await monitor.run()

        assert result["total_value"] == 1000.0
        assert abs(result["yearly_yield"] - 45) < 0.01  # 1000 * 0.045
        assert len(result["analysis"]) == 1

        analysis = result["analysis"][0]
        assert analysis.protocol == "Aave"
        assert analysis.asset == "USDC"
        assert analysis.position_id == "Aave:USDC"
        assert analysis.amount == 1000.0
        assert analysis.apy_pct == 4.5
        assert analysis.platform_url == "https://app.aave.com/"
        assert analysis.estimated_value == 1000.0
        assert abs(analysis.yearly_yield - 45) < 0.01
        assert abs(analysis.monthly_yield - (45 / 12)) < 0.01
        assert abs(analysis.daily_yield - (45 / 365)) < 0.01
        assert analysis.level == AlertLevel.OK

    @pytest.mark.asyncio
    async def test_multiple_positions(self):
        """Monitor aggregates multiple positions."""
        from monitors.defi_monitor import DeFiMonitor

        positions = [
            {"protocol": "Aave", "asset": "USDC", "amount": 1000.0, "apy_pct": 4.0},
            {"protocol": "Lido", "asset": "stETH", "amount": 500.0, "apy_pct": 3.0},
        ]

        with patch("config.DEFI_POSITIONS", positions):
            monitor = DeFiMonitor()
            result = await monitor.run()

        assert result["total_value"] == 1500.0
        # 1000 * 0.04 + 500 * 0.03 = 40 + 15 = 55
        assert abs(result["yearly_yield"] - 55) < 0.01
        assert len(result["analysis"]) == 2

    @pytest.mark.asyncio
    async def test_get_level_always_ok(self):
        """DeFi monitor always returns OK level."""
        from monitors.defi_monitor import DeFiMonitor

        with patch("config.DEFI_POSITIONS", []):
            monitor = DeFiMonitor()
            await monitor.run()

        assert monitor.get_level() == AlertLevel.OK

    @pytest.mark.asyncio
    async def test_get_last_update(self):
        """Monitor tracks last update after a run."""
        from monitors.defi_monitor import DeFiMonitor

        positions = [
            {"protocol": "Aave", "asset": "USDC", "amount": 100.0, "apy_pct": 2.0}
        ]

        with patch("config.DEFI_POSITIONS", positions):
            monitor = DeFiMonitor()

            assert monitor.get_last_update() is None

            result = await monitor.run()
            assert result["last_update"] is not None
            assert monitor.get_last_update() is not None

    @pytest.mark.asyncio
    async def test_get_results(self):
        """get_results returns the last analysis list."""
        from monitors.defi_monitor import DeFiMonitor

        positions = [
            {"protocol": "Compound", "asset": "DAI", "amount": 200.0, "apy_pct": 1.5}
        ]

        with patch("config.DEFI_POSITIONS", positions):
            monitor = DeFiMonitor()
            await monitor.run()

        results = monitor.get_results()
        assert len(results) == 1
        assert results[0].protocol == "Compound"

    @pytest.mark.asyncio
    async def test_handles_invalid_position(self):
        """Monitor skips invalid positions and processes valid ones."""
        from monitors.defi_monitor import DeFiMonitor

        positions = [
            {"protocol": "Aave", "asset": "USDC", "amount": 500.0, "apy_pct": 4.0},
            # Non-numeric amount should be skipped gracefully
            {"protocol": "Broken", "asset": "???", "amount": "not-a-number"},
        ]

        with patch("config.DEFI_POSITIONS", positions):
            monitor = DeFiMonitor()
            result = await monitor.run()

        # Valid position still processed
        assert result["total_value"] >= 500.0
        assert len(result["analysis"]) >= 1

    @pytest.mark.asyncio
    async def test_missing_optional_fields(self):
        """Monitor fills sensible defaults for missing optional fields."""
        from monitors.defi_monitor import DeFiMonitor

        positions = [{"protocol": "Yearn", "asset": "USDT", "amount": 300.0}]

        with patch("config.DEFI_POSITIONS", positions):
            monitor = DeFiMonitor()
            result = await monitor.run()

        analysis = result["analysis"][0]
        assert analysis.apy_pct == 0.0
        assert analysis.platform_url == ""
        assert analysis.yearly_yield == 0.0


class TestPositionIdSanitization:
    """Tests for position_id sanitization (security fix)."""

    def test_sanitize_position_id_normal(self):
        """Normal protocol:asset IDs pass through."""
        from monitors.defi_monitor import _sanitize_position_id

        assert _sanitize_position_id("Aave", "USDC") == "Aave:USDC"
        assert _sanitize_position_id("Lido", "stETH") == "Lido:stETH"

    def test_sanitize_position_id_removes_special_chars(self):
        """Special characters are removed from position_id."""
        from monitors.defi_monitor import _sanitize_position_id

        # Injection attempts should be sanitized (quotes, semicolons, spaces removed)
        # Note: dashes and underscores are intentionally allowed
        assert _sanitize_position_id("Aave<script>", "USDC") == "Aavescript:USDC"
        # The -- remains because dashes are valid chars in protocol/asset names
        assert (
            _sanitize_position_id("Protocol", "'; DROP TABLE--")
            == "Protocol:DROPTABLE--"
        )

    def test_sanitize_position_id_empty_values(self):
        """Empty protocol or asset get 'unknown' placeholder."""
        from monitors.defi_monitor import _sanitize_position_id

        assert _sanitize_position_id("", "") == "unknown:unknown"
        assert _sanitize_position_id("Aave", "") == "Aave:unknown"
        assert _sanitize_position_id("", "USDC") == "unknown:USDC"

    def test_sanitize_position_id_truncates_long_values(self):
        """Very long values are truncated to 100 chars."""
        from monitors.defi_monitor import _sanitize_position_id

        long_protocol = "A" * 100
        long_asset = "B" * 100
        result = _sanitize_position_id(long_protocol, long_asset)

        assert len(result) <= 100

    def test_sanitize_position_id_allows_dash_underscore(self):
        """Dashes and underscores are allowed in position_id."""
        from monitors.defi_monitor import _sanitize_position_id

        assert _sanitize_position_id("Uniswap-V3", "ETH_USDC") == "Uniswap-V3:ETH_USDC"
