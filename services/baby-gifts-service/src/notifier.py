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

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING, Literal

logger: logging.Logger = logging.getLogger(__name__)

# Import TelegramNotifier from shared lib.
#
# Path resolution strategy:
# - Production (Docker): PYTHONPATH includes /app which contains libs/
# - CI (pytest): PYTHONPATH=src is set, and conftest.py adds the repo root
# - Local development: May not have libs/ in path, so we fall back to dynamic
#   path insertion based on the known repo structure (services/<name>/src/).
#
# The fallback uses sys.path.insert(0, ...) to prepend the repo root, which
# allows `from libs.notifications import ...` to resolve. This is intentional
# rather than using relative imports because:
# 1. libs/ is a shared library, not part of this service's package
# 2. The Dockerfile copies libs/ to /app/libs, not into the service directory
# 3. This pattern is used consistently across all services that use shared libs
try:
    from libs.notifications import TelegramNotifier
except ImportError:
    # Local development fallback: derive repo root from this file's known location
    # (/repo/services/baby-gifts-service/src/notifier.py → /repo)
    sys.path.insert(0, str(__file__).replace("\\", "/").split("/services/")[0])
    from libs.notifications import TelegramNotifier

if TYPE_CHECKING:
    from libs.notifications import NotificationResult, TelegramNotifier


# Module-level notifier instance (lazy initialization)
_notifier: TelegramNotifier | None = None


def _get_notifier() -> TelegramNotifier:
    """Get or create the TelegramNotifier instance.

    Uses lazy initialization to avoid configuration errors at import time.
    The notifier reads its configuration from environment variables.

    Returns:
        Configured TelegramNotifier instance.
    """
    global _notifier
    if _notifier is None:
        _notifier = TelegramNotifier.from_env()
    return _notifier


def send_gift_notification(
    gift_name: str,
    person_name: str,
    action: Literal["reserved", "unreserved"],
) -> bool:
    """Send a notification to Telegram about a gift selection/deselection.

    Formats a message with emoji and Markdown formatting, then sends it
    to all configured Telegram chat IDs.

    Args:
        gift_name: Name of the gift being acted upon.
        person_name: Display name of the person performing the action.
        action: The action performed - either 'reserved' or 'unreserved'.

    Returns:
        True if all notifications were sent successfully, False otherwise.
        Returns False if Telegram is not configured (missing token/chat IDs).
    """
    notifier: TelegramNotifier = _get_notifier()

    if not notifier.enabled:
        logger.warning(
            "[telegram] Notification skipped — missing TELEGRAM_BOT_TOKEN or chat IDs"
        )
        return False

    # Format message with emoji based on action
    message: str
    if action == "reserved":
        message = f"🎁 *{person_name}* ha seleccionado: _{gift_name}_"
    else:
        message = f"↩️ *{person_name}* ha deseleccionado: _{gift_name}_"

    result: NotificationResult = notifier.send(message, parse_mode="Markdown")

    if result.success:
        logger.info(
            f"[telegram] Notification sent: {action} '{gift_name}' by {person_name}"
        )
    else:
        logger.error(f"[telegram] Notification failed: {result.message}")

    return result.success


def reset_notifier() -> None:
    """Reset the notifier instance.

    Primarily used in testing to ensure a fresh notifier configuration
    between test cases.
    """
    global _notifier
    _notifier = None
