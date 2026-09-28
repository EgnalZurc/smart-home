"""
Test Telegram notifier.

Tests the notification logic without actually sending messages.
"""

import pytest
from unittest.mock import patch, MagicMock

from models import AlertLevel, Signal, ETFAnalysis, CryptoAnalysis


class TestNotifierConfiguration:
    """Tests for notifier configuration."""

    def test_notifier_disabled_without_credentials(self):
        """Notifier should be disabled without credentials."""
        with patch.dict("os.environ", {}, clear=True):
            # Re-import to pick up empty env
            import importlib
            import notifier as notifier_module
            importlib.reload(notifier_module)
            
            n = notifier_module.TelegramNotifier(bot_token="", chat_id="")
            assert not n.enabled

    def test_notifier_enabled_with_credentials(self):
        """Notifier should be enabled with credentials."""
        from notifier import TelegramNotifier
        
        n = TelegramNotifier(bot_token="test_token", chat_id="123456")
        assert n.enabled


class TestMessageFormatting:
    """Tests for message formatting functions."""

    def test_format_price(self):
        """Test price formatting."""
        from notifier import _format_price
        
        # Uses Spanish format: dots for thousands, price in euros
        result = _format_price(1234.56)
        assert "1.234" in result or "1,234" in result  # thousand separator
        assert "€" in result
        
        result = _format_price(1000000, 0)
        assert "€" in result

    def test_escape_markdown(self):
        """Test markdown escaping."""
        from notifier import _escape_md
        
        assert _escape_md("test*bold*") == "test\\*bold\\*"
        assert _escape_md("test_italic_") == "test\\_italic\\_"

    def test_level_emoji(self):
        """Test level emoji mapping."""
        from notifier import _level_emoji
        
        assert _level_emoji("DANGER") == "🔴"
        assert _level_emoji("WARN") == "🟡"
        assert _level_emoji("OK") == "🟢"


class TestAlertLogic:
    """Tests for alert sending logic."""

    def test_no_alert_when_ok(self):
        """Should not send alert when level is OK."""
        from notifier import TelegramNotifier
        
        notifier = TelegramNotifier(bot_token="test", chat_id="123")
        
        result = notifier.send_summary_alert(
            etf_results=[],
            crypto_results=[],
            overall_level=AlertLevel.OK,
            fear_greed=50,
        )
        
        assert result.success
        assert "No alert needed" in result.message

    def test_no_alert_when_info(self):
        """Should not send alert when level is INFO."""
        from notifier import TelegramNotifier
        
        notifier = TelegramNotifier(bot_token="test", chat_id="123")
        
        result = notifier.send_summary_alert(
            etf_results=[],
            crypto_results=[],
            overall_level=AlertLevel.INFO,
            fear_greed=50,
        )
        
        assert result.success
        assert "No alert needed" in result.message

    @patch("httpx.post")
    def test_alert_sent_when_warn(self, mock_post):
        """Should send alert when level is WARN."""
        mock_post.return_value = MagicMock(
            json=lambda: {"ok": True}
        )
        
        from notifier import TelegramNotifier
        
        notifier = TelegramNotifier(bot_token="test", chat_id="123")
        
        result = notifier.send_summary_alert(
            etf_results=[],
            crypto_results=[],
            overall_level=AlertLevel.WARN,
            fear_greed=75,
        )
        
        assert result.success
        mock_post.assert_called_once()

    @patch("httpx.post")
    def test_alert_sent_when_danger(self, mock_post):
        """Should send alert when level is DANGER."""
        mock_post.return_value = MagicMock(
            json=lambda: {"ok": True}
        )
        
        from notifier import TelegramNotifier
        
        notifier = TelegramNotifier(bot_token="test", chat_id="123")
        
        result = notifier.send_summary_alert(
            etf_results=[],
            crypto_results=[],
            overall_level=AlertLevel.DANGER,
            fear_greed=85,
        )
        
        assert result.success
        mock_post.assert_called_once()


class TestETFAlertFormatting:
    """Tests for ETF alert message formatting."""

    def test_format_etf_alert(self):
        """Test ETF alert message contains key info."""
        from notifier import _format_etf_alert
        
        analysis = ETFAnalysis(
            fund_id="IUIT",
            ticker="IUIT.L",
            name="iShares S&P 500 IT",
            color="#000",
            price=35.0,
            high_52w=40.0,
            low_52w=30.0,
            chg_1d=0.01,
            chg_1m=0.05,
            chg_3m=0.10,
            chg_ytd=0.15,
            ma50=34.0,
            ma200=32.0,
            drawdown=-0.125,
            annual_vol=0.20,
            units=33.5,
            avg_cost=32.77,
            current_value=1172.5,
            gain_loss_eur=74.7,
            gain_loss_pct=0.068,
            monthly_contrib=50.0,
            start_date="2024-01-01",
            tax_gain=74.7,
            tax_irpf=14.2,
            tax_net=1158.3,
            proj_expected=1200.0,
            proj_actual=1172.5,
            proj_deviation=-0.023,
            proj_year=1,
            signals=[Signal("Test", "Test signal", "WARN")],
            level=AlertLevel.WARN,
            recommendation=Signal("Hold", "Keep holding", "OK"),
            ohlc=[],
        )
        
        text = _format_etf_alert(analysis)
        
        assert "iShares S&P 500 IT" in text
        assert "35" in text  # price
        assert "WARN" not in text or "Señales" in text  # signals section


class TestCryptoAlertFormatting:
    """Tests for crypto alert message formatting."""

    def test_format_crypto_alert(self):
        """Test crypto alert message contains key info."""
        from notifier import _format_crypto_alert
        
        analysis = CryptoAnalysis(
            symbol="ETH",
            name="Ethereum",
            coingecko_id="ethereum",
            amount=0.17,
            product="Flexible Stake",
            position_type="flexible",
            apy=2.14,
            rescue_days=5,
            start_date="2024-01-01",
            maturity_date=None,
            next_distribution="2024-01-03",
            distribution_freq_days=2,
            price_eur=2500.0,
            change_24h=-8.0,
            change_30d=-15.0,
            ath=4800.0,
            ath_change_pct=-48.0,
            current_value=425.0,
            daily_gain=0.025,
            accumulated_gain=3.5,
            days_staked=140,
            days_until_available=5,
            days_until_reward=1,
            signals=[Signal("", "Drop warning", "WARN")],
            level=AlertLevel.WARN,
            ohlc=[],
        )
        
        text = _format_crypto_alert(analysis, fear_greed=25)
        
        assert "Ethereum" in text
        assert "2.14" in text  # APY
        assert "Fear & Greed" in text
        assert "25" in text  # F&G value
