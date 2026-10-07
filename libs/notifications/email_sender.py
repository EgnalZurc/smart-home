"""
Generic email sender using SMTP.

Configuration via environment variables:
  - SMTP_HOST: SMTP server hostname (default: smtp.gmail.com)
  - SMTP_PORT: SMTP server port (default: 587)
  - SMTP_USER: SMTP username (email address)
  - SMTP_PASSWORD: SMTP password (app password for Gmail)
  - ALERT_EMAIL: Default recipient address (defaults to SMTP_USER)

Can also be configured programmatically via constructor parameters.
"""

from __future__ import annotations

import logging
import os
import smtplib
import ssl
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


@dataclass
class NotificationResult:
    """Result of a notification attempt."""

    success: bool
    message: str


class EmailSender:
    """
    Generic email sender using SMTP with TLS.

    Thread-safe and reusable. Each send() call opens and closes a connection.
    For high-volume sending, consider connection pooling.
    """

    def __init__(
        self,
        smtp_host: str | None = None,
        smtp_port: int | None = None,
        smtp_user: str | None = None,
        smtp_password: str | None = None,
        default_recipient: str | None = None,
        timeout: int = 15,
    ) -> None:
        """
        Initialize the email sender.

        Args:
            smtp_host: SMTP server hostname. Defaults to SMTP_HOST env var or smtp.gmail.com.
            smtp_port: SMTP server port. Defaults to SMTP_PORT env var or 587.
            smtp_user: SMTP username. Defaults to SMTP_USER or AUTH_SMTP_USER env var.
            smtp_password: SMTP password. Defaults to SMTP_PASSWORD or AUTH_SMTP_PASSWORD env var.
            default_recipient: Default recipient. Defaults to ALERT_EMAIL env var or smtp_user.
            timeout: Connection timeout in seconds.
        """
        self._smtp_host = smtp_host or os.environ.get("SMTP_HOST", "smtp.gmail.com")
        self._smtp_port = smtp_port or int(os.environ.get("SMTP_PORT", "587"))
        self._smtp_user = smtp_user or os.environ.get(
            "SMTP_USER", os.environ.get("AUTH_SMTP_USER", "")
        )
        self._smtp_password = smtp_password or os.environ.get(
            "SMTP_PASSWORD", os.environ.get("AUTH_SMTP_PASSWORD", "")
        )
        self._default_recipient = (
            default_recipient
            or os.environ.get("ALERT_EMAIL")
            or self._smtp_user
        )
        self._timeout = timeout
        self._enabled = bool(self._smtp_user and self._smtp_password)

        if self._enabled:
            logger.info(
                "[email] Sender initialized (host: %s, recipient: %s)",
                self._smtp_host,
                self._default_recipient,
            )
        else:
            logger.warning(
                "[email] Sender disabled — missing SMTP_USER or SMTP_PASSWORD"
            )

    @property
    def enabled(self) -> bool:
        """Return True if email sending is enabled (credentials configured)."""
        return self._enabled

    @property
    def default_recipient(self) -> str:
        """Return the default recipient email address."""
        return self._default_recipient

    def send(
        self,
        subject: str,
        html_body: str,
        recipient: str | None = None,
        plain_body: str | None = None,
    ) -> NotificationResult:
        """
        Send an HTML email.

        Args:
            subject: Email subject line.
            html_body: HTML content of the email.
            recipient: Recipient email address. Defaults to default_recipient.
            plain_body: Optional plain text alternative. If not provided,
                        only HTML is sent.

        Returns:
            NotificationResult with success status and message.
        """
        if not self._enabled:
            return NotificationResult(
                success=False,
                message="Email disabled — missing SMTP credentials",
            )

        to_addr = recipient or self._default_recipient
        if not to_addr:
            return NotificationResult(
                success=False,
                message="No recipient specified and no default configured",
            )

        # Build message
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self._smtp_user
        msg["To"] = to_addr

        if plain_body:
            msg.attach(MIMEText(plain_body, "plain", "utf-8"))
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        try:
            ctx = ssl.create_default_context()
            with smtplib.SMTP(
                self._smtp_host, self._smtp_port, timeout=self._timeout
            ) as server:
                server.starttls(context=ctx)
                server.login(self._smtp_user, self._smtp_password)
                server.sendmail(self._smtp_user, to_addr, msg.as_bytes())

            logger.info("[email] Sent to %s: %s", to_addr, subject[:50])
            return NotificationResult(success=True, message="Email sent")

        except smtplib.SMTPAuthenticationError as e:
            logger.error("[email] SMTP authentication error: %s", e)
            return NotificationResult(success=False, message=f"Auth error: {e}")
        except smtplib.SMTPException as e:
            logger.error("[email] SMTP error: %s", e)
            return NotificationResult(success=False, message=f"SMTP error: {e}")
        except (ConnectionError, TimeoutError) as e:
            logger.error("[email] Connection error: %s", e)
            return NotificationResult(success=False, message=f"Connection error: {e}")
        except Exception as e:
            logger.error("[email] Unexpected error sending email: %s", e)
            return NotificationResult(success=False, message=str(e))

    def send_test(self) -> NotificationResult:
        """Send a test email to verify configuration."""
        from datetime import datetime

        subject = "✅ Email Test — Configuration OK"
        html = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: sans-serif; padding: 20px;">
    <h2>✅ Email Notifications Working</h2>
    <p>Email notifications are configured correctly.</p>
    <p><small>{datetime.now().strftime("%d/%m/%Y %H:%M")}</small></p>
</body>
</html>
"""
        return self.send(subject, html)
