"""Unified synchronous Telegram notification client for smart-home services.

This is the canonical Telegram client shared by every service. It uses a
synchronous ``httpx`` client (the same pattern as the casita ``notifier.py``)
so services can send alerts without pulling in asyncio or
``python-telegram-bot``.

Interface:
    from smart_home_common.telegram import TelegramNotifier

    notifier = TelegramNotifier(
        bot_token="your_bot_token",
        chat_ids=["123456789", "987654321"],
    )
    result = notifier.send("Plain alert")           # no parse mode
    result = notifier.send_markdown("*Bold* alert")  # Markdown parse mode
    if result.success:
        print(f"Delivered to {result.successful_count} chat(s)")

Environment-variable construction:
    notifier = TelegramNotifier.from_env()
    # Reads:
    #   TELEGRAM_BOT_TOKEN  - bot token from @BotFather (required)
    #   TELEGRAM_CHAT_IDS   - comma-separated chat IDs (preferred)
    #   TELEGRAM_CHAT_ID    - single chat ID (fallback, backwards compat)
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)


@dataclass
class TelegramResult:
    """Result of a Telegram notification attempt."""

    success: bool
    """True only if every target chat received the message."""

    message: str
    """Human-readable status message."""

    successful_count: int = 0
    """Number of chats that received the message."""

    failed_count: int = 0
    """Number of chats that failed to receive the message."""


class TelegramNotifier:
    """Synchronous Telegram notification client supporting multiple chat IDs."""

    TELEGRAM_API_BASE = "https://api.telegram.org"

    def __init__(
        self,
        bot_token: str = "",
        chat_ids: list[str] | None = None,
        timeout: float = 15.0,
    ) -> None:
        """Initialize the notifier.

        Args:
            bot_token: Telegram bot token from @BotFather.
            chat_ids: Chat IDs that should receive messages.
            timeout: Per-request HTTP timeout in seconds (default: 15).
        """
        self._bot_token = bot_token
        self._chat_ids = list(chat_ids) if chat_ids else []
        self._timeout = timeout

    @classmethod
    def from_env(cls) -> TelegramNotifier:
        """Build a notifier from environment variables.

        Reads ``TELEGRAM_BOT_TOKEN``, ``TELEGRAM_CHAT_IDS`` (comma-separated,
        preferred) and ``TELEGRAM_CHAT_ID`` (single-value fallback).
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
        """True when a bot token and at least one chat ID are configured."""
        return bool(self._bot_token and self._chat_ids)

    def _post(self, url: str, payload: dict) -> httpx.Response:
        """Issue the HTTP POST. Isolated so subclasses/tests can override it."""
        return httpx.post(url, json=payload, timeout=self._timeout)

    def send(
        self,
        message: str,
        parse_mode: str = "",
        disable_notification: bool = False,
        disable_web_page_preview: bool = True,
    ) -> TelegramResult:
        """Send a plain-text message to every configured chat.

        Args:
            message: Text to send.
            parse_mode: Telegram parse mode ("Markdown", "HTML" or "" for none).
            disable_notification: Send silently (no sound) when True.
            disable_web_page_preview: Suppress link previews when True.

        Returns:
            A :class:`TelegramResult` describing delivery.
        """
        if not self.enabled:
            logger.warning("[telegram] Notification skipped - missing bot token or chat IDs")
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
                payload: dict = {
                    "chat_id": chat_id,
                    "text": message,
                    "disable_web_page_preview": disable_web_page_preview,
                }
                if parse_mode:
                    payload["parse_mode"] = parse_mode
                if disable_notification:
                    payload["disable_notification"] = True

                resp = self._post(url, payload)
                data = resp.json()

                if data.get("ok"):
                    logger.info("[telegram] Message sent to chat %s", chat_id)
                    successful += 1
                else:
                    error = data.get("description", "Unknown error")
                    logger.error("[telegram] API error for chat %s: %s", chat_id, error)
                    errors.append(f"{chat_id}: {error}")
                    failed += 1

            except httpx.TimeoutException:
                logger.error("[telegram] Request timeout for chat %s", chat_id)
                errors.append(f"{chat_id}: timeout")
                failed += 1
            except httpx.HTTPStatusError as e:
                logger.error(
                    "[telegram] HTTP error for chat %s: %d", chat_id, e.response.status_code
                )
                errors.append(f"{chat_id}: HTTP {e.response.status_code}")
                failed += 1
            except (httpx.RequestError, json.JSONDecodeError) as e:
                # Log only the error type to avoid leaking the bot token that
                # may appear in the request URL inside exception messages.
                logger.error("[telegram] Error sending to chat %s: %s", chat_id, type(e).__name__)
                errors.append(f"{chat_id}: {type(e).__name__}")
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

    def send_markdown(
        self,
        message: str,
        disable_notification: bool = False,
        disable_web_page_preview: bool = True,
    ) -> TelegramResult:
        """Send a Markdown-formatted message to every configured chat.

        Convenience wrapper around :meth:`send` with ``parse_mode="Markdown"``.
        """
        return self.send(
            message,
            parse_mode="Markdown",
            disable_notification=disable_notification,
            disable_web_page_preview=disable_web_page_preview,
        )

    def send_test(self) -> TelegramResult:
        """Send a plain-text test message to verify configuration."""
        return self.send("\U0001f514 Test notification from smart-home")
