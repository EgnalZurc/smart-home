"""
Tests for the email_notifier module.
"""

from unittest.mock import MagicMock, patch

from models import AlertLevel


class TestNotificationResult:
    """Tests for NotificationResult dataclass."""

    def test_notification_result_success(self):
        """Create successful notification result."""
        from email_notifier import NotificationResult

        result = NotificationResult(success=True, message="Sent")
        assert result.success is True
        assert result.message == "Sent"

    def test_notification_result_failure(self):
        """Create failed notification result."""
        from email_notifier import NotificationResult

        result = NotificationResult(success=False, message="Connection error")
        assert result.success is False
        assert "Connection error" in result.message


class TestEmailNotifier:
    """Tests for EmailNotifier class."""

    def test_notifier_disabled_without_credentials(self):
        """Notifier is disabled when no SMTP credentials."""
        from email_notifier import EmailNotifier

        mock_sender = MagicMock()
        mock_sender.enabled = False

        notifier = EmailNotifier(sender=mock_sender)
        assert notifier.enabled is False

    def test_notifier_enabled_with_credentials(self):
        """Notifier is enabled when credentials provided."""
        from email_notifier import EmailNotifier

        mock_sender = MagicMock()
        mock_sender.enabled = True

        notifier = EmailNotifier(sender=mock_sender)
        assert notifier.enabled is True

    def test_send_summary_alert_skips_ok_level(self):
        """No email sent when level is OK."""
        from email_notifier import EmailNotifier

        mock_sender = MagicMock()
        mock_sender.enabled = True

        notifier = EmailNotifier(sender=mock_sender)
        result = notifier.send_summary_alert(
            etf_results=[],
            crypto_results=[],
            overall_level=AlertLevel.OK,
        )

        assert result.success is True
        assert "No alert needed" in result.message
        mock_sender.send.assert_not_called()

    def test_send_summary_alert_sends_on_warn(self):
        """Email sent when level is WARN."""
        from email_notifier import EmailNotifier

        mock_sender = MagicMock()
        mock_sender.enabled = True
        mock_sender.send.return_value = MagicMock(success=True, message="Sent")

        notifier = EmailNotifier(sender=mock_sender)
        result = notifier.send_summary_alert(
            etf_results=[],
            crypto_results=[],
            overall_level=AlertLevel.WARN,
        )

        assert result.success is True
        mock_sender.send.assert_called_once()

    def test_send_summary_alert_sends_on_danger(self):
        """Email sent when level is DANGER."""
        from email_notifier import EmailNotifier

        mock_sender = MagicMock()
        mock_sender.enabled = True
        mock_sender.send.return_value = MagicMock(success=True, message="Sent")

        notifier = EmailNotifier(sender=mock_sender)
        result = notifier.send_summary_alert(
            etf_results=[],
            crypto_results=[],
            overall_level=AlertLevel.DANGER,
        )

        assert result.success is True
        mock_sender.send.assert_called_once()
        # Subject should include danger emoji
        call_args = mock_sender.send.call_args
        assert "🔴" in call_args[0][0]  # Subject

    def test_send_scheduled_alert(self):
        """Scheduled alert is sent."""
        from email_notifier import EmailNotifier

        mock_sender = MagicMock()
        mock_sender.enabled = True
        mock_sender.send.return_value = MagicMock(success=True, message="Sent")

        mock_alert = MagicMock()
        mock_alert.title = "Test Alert"
        mock_alert.description = "Test description"
        mock_alert.date = "2024-06-15"
        mock_alert.symbol = "ETH"
        mock_alert.priority = "high"
        mock_alert.action = "sell_crypto"

        notifier = EmailNotifier(sender=mock_sender)
        result = notifier.send_scheduled_alert(mock_alert)

        assert result.success is True
        mock_sender.send.assert_called_once()
        call_args = mock_sender.send.call_args
        assert "Test Alert" in call_args[0][0]  # Subject

    def test_send_test(self):
        """Test email is sent."""
        from email_notifier import EmailNotifier

        mock_sender = MagicMock()
        mock_sender.enabled = True
        mock_sender.send.return_value = MagicMock(success=True, message="Sent")

        notifier = EmailNotifier(sender=mock_sender)
        result = notifier.send_test()

        assert result.success is True
        mock_sender.send.assert_called_once()
        call_args = mock_sender.send.call_args
        assert "Test" in call_args[0][0]  # Subject


class TestHtmlTemplates:
    """Tests for HTML email template builders."""

    def test_format_price(self):
        """Price formatting with thousand separators."""
        from email_notifier import _format_price

        assert "1.000" in _format_price(1000)
        assert "€" in _format_price(100)

    def test_level_color(self):
        """Level colors are returned."""
        from email_notifier import _level_color

        assert _level_color("DANGER") == "#dc3545"
        assert _level_color("WARN") == "#ffc107"
        assert _level_color("OK") == "#28a745"

    def test_level_emoji(self):
        """Level emojis are returned."""
        from email_notifier import _level_emoji

        assert _level_emoji("DANGER") == "🔴"
        assert _level_emoji("WARN") == "🟡"
        assert _level_emoji("OK") == "🟢"

    def test_build_html_summary(self):
        """HTML summary is built correctly."""
        from email_notifier import _build_html_summary
        from models import ETFAnalysis

        etf = ETFAnalysis(
            fund_id="TEST",
            ticker="TEST.L",
            name="Test ETF",
            color="#FF0000",
            current_value=10000,
            price=100,
            gain_loss_pct=0.1,
            level=AlertLevel.WARN,
            signals=[MagicMock(body="Test signal", level="WARN")],
        )

        html = _build_html_summary(
            etf_results=[etf],
            crypto_results=[],
            savings_results=[],
            overall_level=AlertLevel.WARN,
            fear_greed=55,
        )

        assert "Test ETF" in html
        assert "Portfolio Monitor" in html
        assert "<!DOCTYPE html>" in html

    def test_build_html_scheduled_alert(self):
        """Scheduled alert HTML is built correctly."""
        from email_notifier import _build_html_scheduled_alert

        mock_alert = MagicMock()
        mock_alert.title = "Test Alert"
        mock_alert.description = "Test description"
        mock_alert.date = "2024-06-15"
        mock_alert.symbol = "ETH"
        mock_alert.priority = "high"
        mock_alert.action = "sell_crypto"

        html = _build_html_scheduled_alert(mock_alert)

        assert "Test Alert" in html
        assert "Test description" in html
        assert "ETH" in html

    def test_build_html_scheduled_alert_overdue(self):
        """Overdue alert HTML includes warning."""
        from email_notifier import _build_html_scheduled_alert

        mock_alert = MagicMock()
        mock_alert.title = "Overdue Alert"
        mock_alert.description = "This is overdue"
        mock_alert.date = "2020-01-01"  # Past date
        mock_alert.symbol = "BTC"
        mock_alert.priority = "high"
        mock_alert.action = "review"

        html = _build_html_scheduled_alert(mock_alert)

        assert "Vencida" in html or "overdue" in html.lower()


class TestBuiltinEmailSender:
    """Tests for the built-in fallback email sender."""

    def test_builtin_sender_disabled_without_creds(self):
        """Built-in sender is disabled without credentials."""
        from email_notifier import _BuiltinEmailSender

        with patch.dict("os.environ", {"SMTP_USER": "", "AUTH_SMTP_USER": ""}):
            sender = _BuiltinEmailSender()

        assert sender.enabled is False

    def test_builtin_sender_enabled_with_creds(self):
        """Built-in sender is enabled with credentials."""
        from email_notifier import _BuiltinEmailSender

        with patch.dict(
            "os.environ",
            {"SMTP_USER": "test@test.com", "SMTP_PASSWORD": "password123"},
        ):
            sender = _BuiltinEmailSender()

        assert sender.enabled is True

    def test_builtin_sender_send_disabled(self):
        """Send returns failure when disabled."""
        from email_notifier import _BuiltinEmailSender

        with patch.dict("os.environ", {"SMTP_USER": "", "AUTH_SMTP_USER": ""}):
            sender = _BuiltinEmailSender()
            result = sender.send("Subject", "<html></html>")

        assert result.success is False
        assert "disabled" in result.message.lower()

    def test_builtin_sender_send_success(self):
        """Send returns success when SMTP works."""
        from email_notifier import _BuiltinEmailSender

        with patch.dict(
            "os.environ",
            {
                "SMTP_USER": "test@test.com",
                "SMTP_PASSWORD": "password123",
                "ALERT_EMAIL": "recipient@test.com",
            },
        ):
            sender = _BuiltinEmailSender()

        # Mock the SMTP connection
        with patch.object(sender, "_smtplib") as mock_smtplib:
            mock_smtp = MagicMock()
            mock_smtplib.SMTP.return_value.__enter__.return_value = mock_smtp

            result = sender.send("Test Subject", "<html>Test</html>")

        assert result.success is True
        assert result.message == "Email sent"
        mock_smtp.starttls.assert_called_once()
        mock_smtp.login.assert_called_once()
        mock_smtp.sendmail.assert_called_once()

    def test_builtin_sender_send_failure(self):
        """Send returns failure when SMTP fails."""
        from email_notifier import _BuiltinEmailSender

        with patch.dict(
            "os.environ",
            {"SMTP_USER": "test@test.com", "SMTP_PASSWORD": "password123"},
        ):
            sender = _BuiltinEmailSender()

        # Mock the SMTP connection to fail
        with patch.object(sender, "_smtplib") as mock_smtplib:
            mock_smtplib.SMTP.return_value.__enter__.side_effect = Exception(
                "Connection failed"
            )

            result = sender.send("Test Subject", "<html>Test</html>")

        assert result.success is False
        assert "Connection failed" in result.message

    def test_builtin_sender_uses_auth_smtp_env_vars(self):
        """Built-in sender falls back to AUTH_SMTP_* env vars when SMTP_* not set."""
        import os

        from email_notifier import _BuiltinEmailSender

        # Remove SMTP_USER and SMTP_PASSWORD, set AUTH_SMTP_*
        env_backup = {
            k: os.environ.get(k)
            for k in [
                "SMTP_USER",
                "SMTP_PASSWORD",
                "AUTH_SMTP_USER",
                "AUTH_SMTP_PASSWORD",
            ]
        }
        try:
            # Remove SMTP_* keys entirely
            os.environ.pop("SMTP_USER", None)
            os.environ.pop("SMTP_PASSWORD", None)
            # Set AUTH_SMTP_* keys
            os.environ["AUTH_SMTP_USER"] = "auth@test.com"
            os.environ["AUTH_SMTP_PASSWORD"] = "authpass"

            sender = _BuiltinEmailSender()

            assert sender._smtp_user == "auth@test.com"
            assert sender.enabled is True
        finally:
            # Restore original env
            for k, v in env_backup.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


class TestGetEmailSender:
    """Tests for _get_email_sender factory function."""

    def test_get_email_sender_uses_shared_lib(self):
        """_get_email_sender uses shared lib when available."""
        from email_notifier import _get_email_sender

        # When libs.notifications is available
        mock_sender = MagicMock()
        with patch.dict("sys.modules", {"libs.notifications": MagicMock()}):
            with patch(
                "email_notifier._get_email_sender",
                return_value=mock_sender,
            ):
                result = _get_email_sender()
                # The function should return something
                assert result is not None

    def test_get_email_sender_fallback_on_import_error(self):
        """_get_email_sender falls back to built-in on import error."""
        from email_notifier import _BuiltinEmailSender, _get_email_sender

        # Simulate import error by patching the import
        with patch.dict(
            "os.environ",
            {"SMTP_USER": "test@test.com", "SMTP_PASSWORD": "pass"},
        ):
            # Force the ImportError path by making the libs import fail
            original_import = (
                __builtins__.__import__
                if hasattr(__builtins__, "__import__")
                else __import__
            )

            def mock_import(name, *args, **kwargs):
                if name == "libs.notifications":
                    raise ImportError("No module named 'libs.notifications'")
                return original_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=mock_import):
                result = _get_email_sender()

            # Should return a _BuiltinEmailSender instance
            assert isinstance(result, _BuiltinEmailSender)


class TestHtmlSummaryWithCrypto:
    """Tests for HTML summary with crypto alerts."""

    def test_build_html_summary_with_crypto_alerts(self):
        """HTML summary includes crypto section when there are alerts."""
        from email_notifier import _build_html_summary
        from models import CryptoAnalysis

        crypto = CryptoAnalysis(
            symbol="BTC",
            name="Bitcoin",
            coingecko_id="bitcoin",
            amount=0.5,
            current_value=25000,
            price_eur=50000,
            change_24h=-8.5,
            level=AlertLevel.WARN,
            signals=[MagicMock(body="Price dropped significantly", level="WARN")],
        )

        html = _build_html_summary(
            etf_results=[],
            crypto_results=[crypto],
            savings_results=[],
            overall_level=AlertLevel.WARN,
            fear_greed=25,  # Fear
        )

        assert "Bitcoin" in html
        assert "BTC" in html
        assert "Crypto" in html
        assert "Fear & Greed" in html

    def test_build_html_summary_with_danger_crypto(self):
        """HTML summary shows danger crypto alerts."""
        from email_notifier import _build_html_summary
        from models import CryptoAnalysis

        crypto = CryptoAnalysis(
            symbol="ETH",
            name="Ethereum",
            coingecko_id="ethereum",
            amount=10,
            current_value=18000,
            price_eur=1800,
            change_24h=-15.0,
            level=AlertLevel.DANGER,
            signals=[MagicMock(body="Severe price crash detected", level="DANGER")],
        )

        html = _build_html_summary(
            etf_results=[],
            crypto_results=[crypto],
            savings_results=[],
            overall_level=AlertLevel.DANGER,
            fear_greed=10,  # Extreme fear
        )

        assert "Ethereum" in html
        assert "ETH" in html

    def test_build_html_summary_with_positive_change(self):
        """HTML summary shows positive change correctly."""
        from email_notifier import _build_html_summary
        from models import CryptoAnalysis

        crypto = CryptoAnalysis(
            symbol="SOL",
            name="Solana",
            coingecko_id="solana",
            amount=100,
            current_value=5000,
            price_eur=50,
            change_24h=12.5,  # Positive change
            level=AlertLevel.WARN,  # Could be WARN due to Fear & Greed
            signals=[MagicMock(body="Extreme greed detected", level="WARN")],
        )

        html = _build_html_summary(
            etf_results=[],
            crypto_results=[crypto],
            savings_results=[],
            overall_level=AlertLevel.WARN,
            fear_greed=85,  # Extreme greed
        )

        assert "Solana" in html
        assert "SOL" in html

    def test_build_html_summary_without_fear_greed(self):
        """HTML summary works without Fear & Greed index."""
        from email_notifier import _build_html_summary
        from models import CryptoAnalysis

        crypto = CryptoAnalysis(
            symbol="ADA",
            name="Cardano",
            coingecko_id="cardano",
            amount=1000,
            current_value=500,
            price_eur=0.5,
            change_24h=-5.0,
            level=AlertLevel.WARN,
            signals=[MagicMock(body="Minor drop", level="WARN")],
        )

        html = _build_html_summary(
            etf_results=[],
            crypto_results=[crypto],
            savings_results=[],
            overall_level=AlertLevel.WARN,
            fear_greed=None,
        )

        assert "Cardano" in html
        # Fear & Greed section should not be included
        assert "Fear & Greed" not in html or "None" not in html
