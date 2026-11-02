"""
Shared notification library for smart-home services.

NOTE: TelegramNotifier has been consolidated into smart_home_common.telegram.
Import it from there instead:

    from smart_home_common.telegram import TelegramNotifier, TelegramResult

This module now only exports EmailSender.

Usage:
    from libs.notifications import EmailSender, NotificationResult

    sender = EmailSender()
    result = sender.send(
        subject="Alert",
        html_body="<h1>Hello</h1>",
        recipient="user@example.com"
    )
"""

from .email_sender import EmailSender, NotificationResult

__all__ = [
    "EmailSender",
    "NotificationResult",
]
