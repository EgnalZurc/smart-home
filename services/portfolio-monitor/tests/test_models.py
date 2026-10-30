"""
Test data models.

Ensures dataclasses and enums work correctly.
"""

from models import (
    AlertLevel,
    CryptoAnalysis,
    DeFiAnalysis,
    ETFAnalysis,
    Signal,
)


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


class TestDeFiAnalysis:
    """Tests for DeFiAnalysis dataclass."""

    def test_defi_analysis_creation(self):
        """DeFiAnalysis should be creatable with required fields."""
        analysis = DeFiAnalysis(
            position_id="Aave:USDC",
            protocol="Aave",
            asset="USDC",
            amount=1000.0,
            apy_pct=4.5,
            platform_url="https://app.aave.com/",
            estimated_value=1000.0,
            daily_yield=45 / 365,
            monthly_yield=45 / 12,
            yearly_yield=45.0,
            level=AlertLevel.OK,
        )

        assert analysis.position_id == "Aave:USDC"
        assert analysis.protocol == "Aave"
        assert analysis.asset == "USDC"
        assert analysis.amount == 1000.0
        assert analysis.apy_pct == 4.5
        assert analysis.yearly_yield == 45.0
        assert analysis.level == AlertLevel.OK

    def test_defi_analysis_defaults(self):
        """DeFiAnalysis defaults to zeroed values and OK level."""
        analysis = DeFiAnalysis(
            position_id="x",
            protocol="Lido",
            asset="stETH",
        )

        assert analysis.amount == 0.0
        assert analysis.apy_pct == 0.0
        assert analysis.platform_url == ""
        assert analysis.estimated_value == 0.0
        assert analysis.yearly_yield == 0.0
        assert analysis.level == AlertLevel.OK


class TestMonitorState:
    """Tests for MonitorState dataclass."""

    def test_from_dict_with_timezone(self):
        """from_dict handles timestamps with timezone info."""

        from models import MonitorState

        data = {
            "last_etf_run": "2024-06-15T10:30:00+02:00",
            "last_crypto_run": "2024-06-15T08:30:00Z",
        }

        state = MonitorState.from_dict(data)

        assert state.last_etf_run is not None
        assert state.last_etf_run.tzinfo is not None
        assert state.last_crypto_run is not None
        assert state.last_crypto_run.tzinfo is not None

    def test_from_dict_without_timezone(self):
        """from_dict assumes UTC for timestamps without timezone."""
        from datetime import timezone

        from models import MonitorState

        data = {
            "last_etf_run": "2024-06-15T10:30:00",
            "last_crypto_run": "2024-06-15T08:30:00",
        }

        state = MonitorState.from_dict(data)

        # Should have UTC timezone added
        assert state.last_etf_run is not None
        assert state.last_etf_run.tzinfo == timezone.utc
        assert state.last_crypto_run is not None
        assert state.last_crypto_run.tzinfo == timezone.utc

    def test_from_dict_empty_values(self):
        """from_dict handles empty/None timestamp values."""
        from models import MonitorState

        data = {
            "last_etf_run": None,
            "last_crypto_run": "",
        }

        state = MonitorState.from_dict(data)

        assert state.last_etf_run is None
        assert state.last_crypto_run is None

    def test_from_dict_missing_keys(self):
        """from_dict handles missing keys."""
        from models import MonitorState

        state = MonitorState.from_dict({})

        assert state.last_etf_run is None
        assert state.last_crypto_run is None

    def test_to_dict(self):
        """to_dict serializes timestamps correctly."""
        from datetime import datetime, timezone

        from models import MonitorState

        state = MonitorState()
        state.last_etf_run = datetime(2024, 6, 15, 10, 30, 0, tzinfo=timezone.utc)
        state.last_crypto_run = None

        data = state.to_dict()

        assert data["last_etf_run"] == "2024-06-15T10:30:00+00:00"
        assert data["last_crypto_run"] is None
