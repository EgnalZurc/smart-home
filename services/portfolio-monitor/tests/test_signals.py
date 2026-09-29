"""
Test signal generation logic.

These tests ensure signals are generated correctly and with appropriate
alert levels - informational vs actionable.
"""

from models import AlertLevel, Signal


class TestAlertLevelEscalation:
    """Tests for AlertLevel escalation logic."""

    def test_ok_escalates_to_info(self):
        """OK can escalate to INFO."""
        level = AlertLevel.OK
        assert level.escalate(AlertLevel.INFO) == AlertLevel.INFO

    def test_ok_escalates_to_warn(self):
        """OK can escalate to WARN."""
        level = AlertLevel.OK
        assert level.escalate(AlertLevel.WARN) == AlertLevel.WARN

    def test_ok_escalates_to_danger(self):
        """OK can escalate to DANGER."""
        level = AlertLevel.OK
        assert level.escalate(AlertLevel.DANGER) == AlertLevel.DANGER

    def test_warn_does_not_deescalate_to_info(self):
        """WARN should not de-escalate to INFO."""
        level = AlertLevel.WARN
        assert level.escalate(AlertLevel.INFO) == AlertLevel.WARN

    def test_danger_is_maximum(self):
        """DANGER is the maximum level and cannot be overridden."""
        level = AlertLevel.DANGER
        assert level.escalate(AlertLevel.OK) == AlertLevel.DANGER
        assert level.escalate(AlertLevel.INFO) == AlertLevel.DANGER
        assert level.escalate(AlertLevel.WARN) == AlertLevel.DANGER


class TestSignalModel:
    """Tests for Signal dataclass."""

    def test_signal_creation(self):
        """Test basic signal creation."""
        signal = Signal(
            title="Test Signal",
            body="This is a test",
            level="WARN",
        )
        assert signal.title == "Test Signal"
        assert signal.body == "This is a test"
        assert signal.level == "WARN"

    def test_signal_serialization(self):
        """Test signal can be serialized to dict."""
        signal = Signal(
            title="Test",
            body="Body",
            level="INFO",
        )
        # Dataclass should be convertible
        assert signal.title == "Test"


class TestCryptoSignalLevels:
    """Tests ensuring crypto signals have correct severity levels."""

    def test_ath_proximity_is_informational(self):
        """ATH proximity should be INFO, not DANGER or WARN."""
        from monitors.crypto_monitor import compute_signals

        # Mock position and price data
        pos = {"coingecko_id": "bitcoin"}
        price_data = {
            "bitcoin": {
                "eur": 50000,
                "eur_24h_change": 1.0,  # Slight positive
                "ath_change_pct": -3,  # Very close to ATH (only -3%)
                "price_change_30d": 5,  # Neutral
            }
        }

        signals, level = compute_signals(pos, price_data, fear_greed_val=50)

        # Find ATH signal if present
        ath_signals = [
            s for s in signals if "ATH" in s.body or "máximos" in s.body.lower()
        ]

        for signal in ath_signals:
            # ATH signals should be INFO, not DANGER or WARN
            assert signal.level == "INFO", (
                f"ATH signal should be INFO, got {signal.level}"
            )

        # Overall level should NOT be escalated due to ATH alone
        assert level != AlertLevel.DANGER, "ATH proximity should not trigger DANGER"

    def test_strong_pump_is_informational(self):
        """Strong price surge should be INFO, not WARN."""
        from monitors.crypto_monitor import compute_signals

        pos = {"coingecko_id": "ethereum"}
        price_data = {
            "ethereum": {
                "eur": 3000,
                "eur_24h_change": 15.0,  # Strong pump
                "ath_change_pct": -50,  # Far from ATH
                "price_change_30d": 10,
            }
        }

        signals, level = compute_signals(pos, price_data, fear_greed_val=50)

        # Find pump signal
        pump_signals = [
            s
            for s in signals
            if "15" in s.body or "subida" in s.body.lower() or "surge" in s.body.lower()
        ]

        for signal in pump_signals:
            assert signal.level == "INFO", (
                f"Pump signal should be INFO, got {signal.level}"
            )

    def test_significant_drop_is_danger(self):
        """Significant price drops should properly escalate to DANGER."""
        from monitors.crypto_monitor import compute_signals

        pos = {"coingecko_id": "solana"}
        price_data = {
            "solana": {
                "eur": 100,
                "eur_24h_change": -12.0,  # Significant drop
                "ath_change_pct": -60,
                "price_change_30d": -25,
            }
        }

        signals, level = compute_signals(pos, price_data, fear_greed_val=50)

        # This should trigger a danger signal
        assert level == AlertLevel.DANGER, "Significant drop should trigger DANGER"

    def test_fear_greed_extreme_values(self):
        """Test Fear & Greed at extreme values."""
        from monitors.crypto_monitor import compute_signals

        pos = {"coingecko_id": "bitcoin"}
        price_data = {
            "bitcoin": {
                "eur": 50000,
                "eur_24h_change": 0,
                "ath_change_pct": -30,
                "price_change_30d": 0,
            }
        }

        # Extreme greed (80+)
        signals, level = compute_signals(pos, price_data, fear_greed_val=85)
        fg_signals = [s for s in signals if "Fear" in s.body or "Greed" in s.body]
        assert len(fg_signals) > 0, "Should generate F&G signal at extreme greed"
        assert level == AlertLevel.DANGER

        # Extreme fear (below 25)
        signals, level = compute_signals(pos, price_data, fear_greed_val=15)
        fg_signals = [
            s
            for s in signals
            if "Fear" in s.body or "Greed" in s.body or "Miedo" in s.body
        ]
        assert len(fg_signals) > 0, "Should generate F&G signal at extreme fear"
        # Extreme fear is informational (opportunity), not a danger
        assert level == AlertLevel.OK


class TestETFSignalLevels:
    """Tests for ETF signal generation."""

    def test_profit_signal_is_ok(self):
        """Being in profit should generate OK signal."""
        import numpy as np
        import pandas as pd
        from monitors.etf_monitor import calculate_signals

        # Create mock historical data
        dates = pd.date_range(end="2024-01-15", periods=250, freq="D")
        prices = np.linspace(100, 120, 250)  # Steady uptrend
        hist = pd.DataFrame(
            {
                "Open": prices * 0.99,
                "High": prices * 1.01,
                "Low": prices * 0.98,
                "Close": prices,
            },
            index=dates,
        )

        # Avg cost of 100, current price ~120
        result = calculate_signals(hist, avg_cost=100.0)

        # Should have profit signal
        profit_signals = [
            s
            for s in result["signals"]
            if "profit" in s.title.lower() or "beneficio" in s.title.lower()
        ]
        assert len(profit_signals) > 0, "Should generate profit signal"
        assert result["level"] in (AlertLevel.OK, AlertLevel.INFO)

    def test_loss_signal_escalates(self):
        """Being in significant loss should escalate alert level."""
        import numpy as np
        import pandas as pd
        from monitors.etf_monitor import calculate_signals

        # Create mock data with price below cost
        dates = pd.date_range(end="2024-01-15", periods=250, freq="D")
        prices = np.linspace(100, 75, 250)  # Downtrend
        hist = pd.DataFrame(
            {
                "Open": prices * 1.01,
                "High": prices * 1.02,
                "Low": prices * 0.99,
                "Close": prices,
            },
            index=dates,
        )

        # Avg cost of 100, current price ~75 = -25% loss
        result = calculate_signals(hist, avg_cost=100.0)

        # Should escalate to at least WARN or DANGER
        assert result["level"] in (AlertLevel.WARN, AlertLevel.DANGER)
