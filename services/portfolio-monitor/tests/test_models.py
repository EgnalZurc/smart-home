"""
Test data models.

Ensures dataclasses and enums work correctly.
"""

from models import AlertLevel, CryptoAnalysis, ETFAnalysis, Signal


class TestAlertLevel:
    """Tests for AlertLevel enum."""

    def test_alert_level_ordering(self):
        """Alert levels should have correct severity ordering."""
        assert AlertLevel.OK.value < AlertLevel.INFO.value
        assert AlertLevel.INFO.value < AlertLevel.WARN.value
        assert AlertLevel.WARN.value < AlertLevel.DANGER.value

    def test_escalate_returns_higher_level(self):
        """escalate() should return the higher of two levels."""
        assert AlertLevel.OK.escalate(AlertLevel.WARN) == AlertLevel.WARN
        assert AlertLevel.WARN.escalate(AlertLevel.OK) == AlertLevel.WARN
        assert AlertLevel.DANGER.escalate(AlertLevel.INFO) == AlertLevel.DANGER

    def test_escalate_same_level(self):
        """escalate() with same level should return that level."""
        assert AlertLevel.WARN.escalate(AlertLevel.WARN) == AlertLevel.WARN


class TestSignal:
    """Tests for Signal dataclass."""

    def test_signal_fields(self):
        """Signal should have required fields."""
        signal = Signal(
            title="Test Title",
            body="Test body message",
            level="WARN",
        )

        assert signal.title == "Test Title"
        assert signal.body == "Test body message"
        assert signal.level == "WARN"

    def test_signal_empty_title_allowed(self):
        """Signal can have empty title (for inline signals)."""
        signal = Signal(title="", body="Body only", level="INFO")
        assert signal.title == ""


class TestETFAnalysis:
    """Tests for ETFAnalysis dataclass."""

    def test_etf_analysis_creation(self):
        """ETFAnalysis should be creatable with required fields."""
        analysis = ETFAnalysis(
            fund_id="IUIT",
            ticker="IUIT.L",
            name="Test Fund",
            color="#000000",
            price=100.0,
            high_52w=120.0,
            low_52w=80.0,
            chg_1d=0.01,
            chg_1m=0.05,
            chg_3m=0.10,
            chg_ytd=0.15,
            ma50=95.0,
            ma200=90.0,
            drawdown=-0.10,
            annual_vol=0.20,
            units=10.0,
            avg_cost=90.0,
            current_value=1000.0,
            gain_loss_eur=100.0,
            gain_loss_pct=0.11,
            monthly_contrib=50.0,
            start_date="2024-01-01",
            tax_gain=100.0,
            tax_irpf=19.0,
            tax_net=981.0,
            proj_expected=1200.0,
            proj_actual=1000.0,
            proj_deviation=-0.167,
            proj_year=1,
            signals=[],
            level=AlertLevel.OK,
            recommendation=Signal("OK", "All good", "OK"),
            ohlc=[],
        )

        assert analysis.fund_id == "IUIT"
        assert analysis.price == 100.0
        assert analysis.level == AlertLevel.OK


class TestCryptoAnalysis:
    """Tests for CryptoAnalysis dataclass."""

    def test_crypto_analysis_creation(self):
        """CryptoAnalysis should be creatable with required fields."""
        analysis = CryptoAnalysis(
            symbol="ETH",
            name="Ethereum",
            coingecko_id="ethereum",
            amount=0.5,
            product="Flexible Stake",
            position_type="flexible",
            apy=2.0,
            rescue_days=5,
            start_date="2024-01-01",
            maturity_date=None,
            next_distribution="2024-01-03",
            distribution_freq_days=2,
            price_eur=2500.0,
            change_24h=1.5,
            change_30d=10.0,
            ath=4800.0,
            ath_change_pct=-48.0,
            current_value=1250.0,
            daily_gain=0.07,
            accumulated_gain=1.0,
            days_staked=14,
            days_until_available=5,
            days_until_reward=1,
            signals=[],
            level=AlertLevel.OK,
            ohlc=[],
        )

        assert analysis.symbol == "ETH"
        assert analysis.amount == 0.5
        assert analysis.position_type == "flexible"
