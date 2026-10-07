"""Baby Gifts Service — Telegram Notifier.

Sends notifications to Telegram when gifts are selected or deselected.

Configuration via config.py (from environment variables):
- TELEGRAM_BOT_TOKEN: Bot token (required)
- TELEGRAM_CHAT_IDS: Comma-separated list of chat IDs to notify (preferred)
- TELEGRAM_CHAT_ID: Single chat ID (fallback for backwards compatibility)

Example: TELEGRAM_CHAT_IDS=123456789,987654321
"""

import logging

import httpx
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID_SINGLE, TELEGRAM_CHAT_IDS_RAW

logger = logging.getLogger(__name__)


def _get_chat_ids() -> list[str]:
    """Get list of chat IDs to notify.

    Priority:
    1. TELEGRAM_CHAT_IDS (comma-separated list)
    2. TELEGRAM_CHAT_ID (single ID, backwards compatibility)
    """
    if TELEGRAM_CHAT_IDS_RAW:
        # Split by comma, strip whitespace, filter empty
        return [cid.strip() for cid in TELEGRAM_CHAT_IDS_RAW.split(",") if cid.strip()]
    if TELEGRAM_CHAT_ID_SINGLE:
        return [TELEGRAM_CHAT_ID_SINGLE]
    return []


def send_gift_notification(gift_name: str, person_name: str, action: str) -> bool:
    """Send a notification to Telegram about a gift selection/deselection.

    Args:
        gift_name: Name of the gift
        person_name: Name of the person who performed the action
        action: Either 'reserved' or 'unreserved'

    Returns:
        True if all notifications were sent successfully, False otherwise
    """
    chat_ids = _get_chat_ids()

    if not TELEGRAM_BOT_TOKEN or not chat_ids:
        logger.warning(
            "[telegram] Notification skipped — missing TELEGRAM_BOT_TOKEN or chat IDs"
        )
        return False

    if action == "reserved":
        message = f"🎁 *{person_name}* ha seleccionado: _{gift_name}_"
    else:
        message = f"↩️ *{person_name}* ha deseleccionado: _{gift_name}_"

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    success = True

    for chat_id in chat_ids:
        try:
            resp = httpx.post(
                url,
                json={
                    "chat_id": chat_id,
                    "text": message,
                    "parse_mode": "Markdown",
                },
                timeout=15.0,
            )

            data = resp.json()
            if data.get("ok"):
                logger.info(
                    f"[telegram] Notification sent to {chat_id}: {action} '{gift_name}' by {person_name}"
                )
            else:
                error = data.get("description", "Unknown error")
                logger.error(f"[telegram] API error for chat {chat_id}: {error}")
                success = False

        except httpx.TimeoutException:
            logger.error(f"[telegram] Request timeout for chat {chat_id}")
            success = False
        except Exception as e:
            logger.error(f"[telegram] Error sending to chat {chat_id}: {e}")
            success = False

    return success
