"""Baby Gifts Service — Telegram Notifier.

Sends notifications to Telegram when gifts are selected or deselected.
Uses TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID environment variables.
"""

import logging
import os

import httpx

logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


def send_gift_notification(gift_name: str, person_name: str, action: str) -> bool:
    """Send a notification to Telegram about a gift selection/deselection.

    Args:
        gift_name: Name of the gift
        person_name: Name of the person who performed the action
        action: Either 'reserved' or 'unreserved'

    Returns:
        True if notification was sent successfully, False otherwise
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning(
            "[telegram] Notification skipped — missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID"
        )
        return False

    if action == "reserved":
        message = f"🎁 *{person_name}* ha seleccionado: _{gift_name}_"
    else:
        message = f"↩️ *{person_name}* ha deseleccionado: _{gift_name}_"

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    try:
        resp = httpx.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "Markdown",
            },
            timeout=15.0,
        )

        data = resp.json()
        if data.get("ok"):
            logger.info(
                f"[telegram] Notification sent: {action} '{gift_name}' by {person_name}"
            )
            return True
        else:
            error = data.get("description", "Unknown error")
            logger.error(f"[telegram] API error: {error}")
            return False

    except httpx.TimeoutException:
        logger.error("[telegram] Request timeout")
        return False
    except Exception as e:
        logger.error(f"[telegram] Error sending notification: {e}")
        return False
