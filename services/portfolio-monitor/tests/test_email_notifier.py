"""
Tests for the email_notifier module.
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

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
