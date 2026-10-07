"""
Shared email notification library for smart-home services.

Usage:
    from libs.notifications import EmailSender, NotificationResult

    sender = EmailSender()
    result = sender.send(
        subject="Alert",
        html_body="<h1>Hello</h1>",
        recipient="user@example.com"  # optional, defaults to ALERT_EMAIL
    )
    if result.success:
        print("Sent!")
"""

from .email_sender import EmailSender, NotificationResult

__all__ = ["EmailSender", "NotificationResult"]
