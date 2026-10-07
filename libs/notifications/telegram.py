"""
Telegram notification client for smart-home services.

Usage:
    from libs.notifications import TelegramNotifier

    notifier = TelegramNotifier(
        bot_token="your_bot_token",
        chat_ids=["123456789", "987654321"]
    )
    result = notifier.send("Hello, World!", parse_mode="Markdown")
    if result.success:
        print(f"Sent to {result.successful_count} chats")

Environment variable initialization:
    notifier = TelegramNotifier.from_env()
    # Reads TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_IDS (comma-separated), TELEGRAM_CHAT_ID (fallback)
"""

import logging
import os
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)


@dataclass
class TelegramResult:
    """Result of a Telegram notification attempt."""

    success: bool
    """True if ALL messages were sent successfully."""

    message: str
    """Human-readable status message."""

    successful_count: int = 0
    """Number of chats that received the message."""

    failed_count: int = 0
    """Number of chats that failed to receive the message."""


class TelegramNotifier:
    """Telegram notification client supporting multiple chat IDs."""

    TELEGRAM_API_BASE = "https://api.telegram.org"

    def __init__(
        self,
        bot_token: str = "",
        chat_ids: list[str] | None = None,
        timeout: float = 15.0,
    ):
        """Initialize TelegramNotifier.

        Args:
            bot_token: Telegram bot token from @BotFather
            chat_ids: List of chat IDs to send messages to
            timeout: HTTP request timeout in seconds (default: 15)
        """
        self._bot_token = bot_token
        self._chat_ids = chat_ids or []
        self._timeout = timeout

    @classmethod
    def from_env(cls) -> "TelegramNotifier":
        """Create TelegramNotifier from environment variables.

        Reads:
            TELEGRAM_BOT_TOKEN: Bot token (required)
            TELEGRAM_CHAT_IDS: Comma-separated list of chat IDs (preferred)
            TELEGRAM_CHAT_ID: Single chat ID (fallback for backwards compat)

        Returns:
            TelegramNotifier instance
        """
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        chat_ids_raw = os.getenv("TELEGRAM_CHAT_IDS", "")
        chat_id_single = os.getenv("TELEGRAM_CHAT_ID", "")

        chat_ids: list[str] = []
        if chat_ids_raw:
            chat_ids = [cid.strip() for cid in chat_ids_raw.split(",") if cid.strip()]
        elif chat_id_single:
            chat_ids = [chat_id_single]

        return cls(bot_token=bot_token, chat_ids=chat_ids)

    @property
    def enabled(self) -> bool:
        """Return True if notifier is configured and can send messages."""
        return bool(self._bot_token and self._chat_ids)

    def send(
        self,
        message: str,
        parse_mode: str = "Markdown",
        disable_notification: bool = False,
    ) -> TelegramResult:
        """Send a message to all configured chat IDs.

        Args:
            message: Text message to send
            parse_mode: Telegram parse mode ("Markdown", "HTML", or "")
            disable_notification: If True, send silently without sound

        Returns:
            TelegramResult with success status and counts
        """
        if not self.enabled:
            logger.warning(
                "[telegram] Notification skipped — missing bot token or chat IDs"
            )
            return TelegramResult(
                success=False,
                message="Notifier not configured (missing token or chat IDs)",
            )

        url = f"{self.TELEGRAM_API_BASE}/bot{self._bot_token}/sendMessage"
        successful = 0
        failed = 0
        errors: list[str] = []

        for chat_id in self._chat_ids:
            try:
                payload = {
                    "chat_id": chat_id,
                    "text": message,
                }
                if parse_mode:
                    payload["parse_mode"] = parse_mode
                if disable_notification:
                    payload["disable_notification"] = True

                resp = httpx.post(url, json=payload, timeout=self._timeout)
                data = resp.json()

                if data.get("ok"):
                    logger.info(f"[telegram] Message sent to chat {chat_id}")
                    successful += 1
                else:
                    error = data.get("description", "Unknown error")
                    logger.error(f"[telegram] API error for chat {chat_id}: {error}")
                    errors.append(f"{chat_id}: {error}")
                    failed += 1

            except httpx.TimeoutException:
                logger.error(f"[telegram] Request timeout for chat {chat_id}")
                errors.append(f"{chat_id}: timeout")
                failed += 1
            except Exception as e:
                logger.error(f"[telegram] Error sending to chat {chat_id}: {e}")
                errors.append(f"{chat_id}: {e}")
                failed += 1

        all_success = failed == 0 and successful > 0
        if all_success:
            msg = f"Sent to {successful} chat(s)"
        elif successful > 0:
            msg = f"Partial: {successful} sent, {failed} failed"
        else:
            msg = f"Failed: {'; '.join(errors)}" if errors else "No messages sent"

        return TelegramResult(
            success=all_success,
            message=msg,
            successful_count=successful,
            failed_count=failed,
        )

    def send_test(self) -> TelegramResult:
        """Send a test message to verify configuration.

        Returns:
            TelegramResult from the test message
        """
        return self.send("🔔 Test notification from smart-home", parse_mode="")
