"""
Shared notification library for smart-home services.

Usage:
    from libs.notifications import EmailSender, NotificationResult
    from libs.notifications import TelegramNotifier, TelegramResult

    # Email
    sender = EmailSender()
    result = sender.send(
        subject="Alert",
        html_body="<h1>Hello</h1>",
        recipient="user@example.com"
    )

    # Telegram
    notifier = TelegramNotifier.from_env()
    result = notifier.send("🔔 Alert message")
"""

from .email_sender import EmailSender, NotificationResult
from .telegram import TelegramNotifier, TelegramResult

__all__ = [
    "EmailSender",
    "NotificationResult",
    "TelegramNotifier",
    "TelegramResult",
]
