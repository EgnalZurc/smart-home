"""
Telegram notification client for smart-home services.

This module now re-uses the unified Telegram client that lives in
``smart_home_common.telegram`` when it is importable, falling back to a
local copy of the implementation when ``smart_home_common`` is not installed
(e.g. standalone use of the ``libs/notifications`` package).

The public API is kept backwards compatible with earlier releases:
``TelegramNotifier.send`` defaults to ``parse_mode="Markdown"`` and
``send_test`` sends an unformatted message.

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

import httpx

logger = logging.getLogger(__name__)

try:
    from smart_home_common.telegram import TelegramNotifier as _CommonNotifier
    from smart_home_common.telegram import TelegramResult as _CommonResult

    _HAS_COMMON = True
except ImportError:  # pragma: no cover - exercised only without the shared lib
    _HAS_COMMON = False


if _HAS_COMMON:
    TelegramResult = _CommonResult

    class TelegramNotifier(_CommonNotifier):
        """Telegram client backed by the shared ``smart_home_common`` client.

        Keeps the historical ``libs.notifications`` behaviour: ``send`` defaults
        to Markdown parse mode and the HTTP call is routed through this module's
        ``httpx`` so existing tests that patch
        ``libs.notifications.telegram.httpx.post`` keep working.
        """

        def _post(self, url: str, payload: dict) -> httpx.Response:
            return httpx.post(url, json=payload, timeout=self._timeout)

        def send(
            self,
            message: str,
            parse_mode: str = "Markdown",
            disable_notification: bool = False,
            disable_web_page_preview: bool = True,
        ) -> TelegramResult:
            """Send a message (Markdown by default) to all configured chats."""
            return super().send(
                message,
                parse_mode=parse_mode,
                disable_notification=disable_notification,
                disable_web_page_preview=disable_web_page_preview,
            )

        def send_test(self) -> TelegramResult:
            """Send a plain-text test message to verify configuration."""
            return super().send(
                "\U0001f514 Test notification from smart-home", parse_mode=""
            )

else:  # pragma: no cover - standalone fallback without smart_home_common
    import os
    from dataclasses import dataclass

    @dataclass
    class TelegramResult:
        """Result of a Telegram notification attempt."""

        success: bool
        message: str
        successful_count: int = 0
        failed_count: int = 0

    class TelegramNotifier:
        """Standalone Telegram notification client (fallback implementation)."""

        TELEGRAM_API_BASE = "https://api.telegram.org"

        def __init__(
            self,
            bot_token: str = "",
            chat_ids: list[str] | None = None,
            timeout: float = 15.0,
        ):
            self._bot_token = bot_token
            self._chat_ids = chat_ids or []
            self._timeout = timeout

        @classmethod
        def from_env(cls) -> "TelegramNotifier":
            bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
            chat_ids_raw = os.getenv("TELEGRAM_CHAT_IDS", "")
            chat_id_single = os.getenv("TELEGRAM_CHAT_ID", "")

            chat_ids: list[str] = []
            if chat_ids_raw:
                chat_ids = [c.strip() for c in chat_ids_raw.split(",") if c.strip()]
            elif chat_id_single:
                chat_ids = [chat_id_single]

            return cls(bot_token=bot_token, chat_ids=chat_ids)

        @property
        def enabled(self) -> bool:
            return bool(self._bot_token and self._chat_ids)

        def send(
            self,
            message: str,
            parse_mode: str = "Markdown",
            disable_notification: bool = False,
            disable_web_page_preview: bool = True,
        ) -> TelegramResult:
            if not self.enabled:
                logger.warning(
                    "[telegram] Notification skipped - missing bot token or chat IDs"
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
                        "disable_web_page_preview": disable_web_page_preview,
                    }
                    if parse_mode:
                        payload["parse_mode"] = parse_mode
                    if disable_notification:
                        payload["disable_notification"] = True

                    resp = httpx.post(url, json=payload, timeout=self._timeout)
                    data = resp.json()

                    if data.get("ok"):
                        logger.info("[telegram] Message sent to chat %s", chat_id)
                        successful += 1
                    else:
                        error = data.get("description", "Unknown error")
                        logger.error(
                            "[telegram] API error for chat %s: %s", chat_id, error
                        )
                        errors.append(f"{chat_id}: {error}")
                        failed += 1

                except httpx.TimeoutException:
                    logger.error("[telegram] Request timeout for chat %s", chat_id)
                    errors.append(f"{chat_id}: timeout")
                    failed += 1
                except Exception as e:
                    logger.error(
                        "[telegram] Error sending to chat %s: %s",
                        chat_id,
                        type(e).__name__,
                    )
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
            return self.send(
                message,
                parse_mode="Markdown",
                disable_notification=disable_notification,
                disable_web_page_preview=disable_web_page_preview,
            )

        def send_test(self) -> TelegramResult:
            return self.send(
                "\U0001f514 Test notification from smart-home", parse_mode=""
            )
