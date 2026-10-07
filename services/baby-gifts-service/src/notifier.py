"""Baby Gifts Service — Telegram Notifier.

Sends notifications to Telegram when gifts are selected or deselected.

This module wraps the shared TelegramNotifier library with gift-specific
message formatting.

Configuration via environment variables (through libs/notifications):
- TELEGRAM_BOT_TOKEN: Bot token (required)
- TELEGRAM_CHAT_IDS: Comma-separated list of chat IDs to notify (preferred)
- TELEGRAM_CHAT_ID: Single chat ID (fallback for backwards compatibility)

Example: TELEGRAM_CHAT_IDS=123456789,987654321
"""

import logging
import sys

logger = logging.getLogger(__name__)

# Import TelegramNotifier from shared lib
# The lib path is added to PYTHONPATH in Dockerfile/CI
try:
    from libs.notifications import TelegramNotifier
except ImportError:
    # Fallback for local development without libs in path
    sys.path.insert(0, str(__file__).replace("\\", "/").split("/services/")[0])
    from libs.notifications import TelegramNotifier


# Module-level notifier instance (lazy initialization)
_notifier: TelegramNotifier | None = None


def _get_notifier() -> TelegramNotifier:
    """Get or create the TelegramNotifier instance."""
    global _notifier
    if _notifier is None:
        _notifier = TelegramNotifier.from_env()
    return _notifier


def send_gift_notification(gift_name: str, person_name: str, action: str) -> bool:
    """Send a notification to Telegram about a gift selection/deselection.

    Args:
        gift_name: Name of the gift
        person_name: Name of the person who performed the action
        action: Either 'reserved' or 'unreserved'

    Returns:
        True if all notifications were sent successfully, False otherwise
    """
    notifier = _get_notifier()

    if not notifier.enabled:
        logger.warning(
            "[telegram] Notification skipped — missing TELEGRAM_BOT_TOKEN or chat IDs"
        )
        return False

    if action == "reserved":
        message = f"🎁 *{person_name}* ha seleccionado: _{gift_name}_"
    else:
        message = f"↩️ *{person_name}* ha deseleccionado: _{gift_name}_"

    result = notifier.send(message, parse_mode="Markdown")

    if result.success:
        logger.info(
            f"[telegram] Notification sent: {action} '{gift_name}' by {person_name}"
        )
    else:
        logger.error(f"[telegram] Notification failed: {result.message}")

    return result.success


def reset_notifier() -> None:
    """Reset the notifier instance (for testing)."""
    global _notifier
    _notifier = None
