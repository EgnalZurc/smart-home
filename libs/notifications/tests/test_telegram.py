"""
Tests for libs/notifications/telegram.py.

Covers:
- TelegramNotifier initialization with explicit params and from_env
- TelegramResult dataclass
- send() method: success, disabled, API errors, timeouts, partial failures
- send_test() method
- enabled property
- Multiple chat ID handling
"""

import os
from unittest.mock import MagicMock, patch

import httpx


class TestTelegramResult:
    """Tests for TelegramResult dataclass."""

    def test_success_result(self):
        """TelegramResult with success=True."""
        from libs.notifications import TelegramResult

        result = TelegramResult(
            success=True,
            message="Sent to 2 chat(s)",
            successful_count=2,
            failed_count=0,
        )
        assert result.success is True
        assert result.message == "Sent to 2 chat(s)"
        assert result.successful_count == 2
        assert result.failed_count == 0

    def test_partial_failure_result(self):
        """TelegramResult with partial success."""
        from libs.notifications import TelegramResult

        result = TelegramResult(
            success=False,
            message="Partial: 1 sent, 1 failed",
            successful_count=1,
            failed_count=1,
        )
        assert result.success is False
        assert result.successful_count == 1
        assert result.failed_count == 1


class TestTelegramNotifierInitialization:
    """Tests for TelegramNotifier initialization."""

    def test_init_with_explicit_params(self):
        """TelegramNotifier initializes with explicit parameters."""
        from libs.notifications import TelegramNotifier

        notifier = TelegramNotifier(
            bot_token="test_token_123",
            chat_ids=["111", "222"],
            timeout=30.0,
        )

        assert notifier._bot_token == "test_token_123"
        assert notifier._chat_ids == ["111", "222"]
        assert notifier._timeout == 30.0
        assert notifier.enabled is True

    def test_init_with_defaults(self):
        """TelegramNotifier initializes with empty defaults."""
        from libs.notifications import TelegramNotifier

        notifier = TelegramNotifier()

        assert notifier._bot_token == ""
        assert notifier._chat_ids == []
        assert notifier._timeout == 15.0
        assert notifier.enabled is False

    def test_enabled_requires_token_and_chat_ids(self):
        """enabled property requires both token and chat_ids."""
        from libs.notifications import TelegramNotifier

        # Missing both
        notifier = TelegramNotifier()
        assert notifier.enabled is False

        # Missing chat_ids
        notifier = TelegramNotifier(bot_token="token")
        assert notifier.enabled is False

        # Missing token
        notifier = TelegramNotifier(chat_ids=["123"])
        assert notifier.enabled is False

        # Both present
        notifier = TelegramNotifier(bot_token="token", chat_ids=["123"])
        assert notifier.enabled is True


class TestTelegramNotifierFromEnv:
    """Tests for TelegramNotifier.from_env()."""

    def test_from_env_with_chat_ids(self):
        """from_env reads TELEGRAM_CHAT_IDS."""
        from libs.notifications import TelegramNotifier

        env = {
            "TELEGRAM_BOT_TOKEN": "bot_token_env",
            "TELEGRAM_CHAT_IDS": "111,222,333",
            "TELEGRAM_CHAT_ID": "old_id",  # Should be ignored
        }

        with patch.dict(os.environ, env, clear=False):
            notifier = TelegramNotifier.from_env()

        assert notifier._bot_token == "bot_token_env"
        assert notifier._chat_ids == ["111", "222", "333"]
        assert notifier.enabled is True

    def test_from_env_fallback_to_single_chat_id(self):
        """from_env falls back to TELEGRAM_CHAT_ID."""
        from libs.notifications import TelegramNotifier

        env = {
            "TELEGRAM_BOT_TOKEN": "bot_token_env",
            "TELEGRAM_CHAT_ID": "single_id",
        }

        with patch.dict(os.environ, env, clear=False):
            # Ensure TELEGRAM_CHAT_IDS is not set
            with patch.dict(os.environ, {"TELEGRAM_CHAT_IDS": ""}, clear=False):
                notifier = TelegramNotifier.from_env()

        assert notifier._chat_ids == ["single_id"]

    def test_from_env_handles_whitespace(self):
        """from_env strips whitespace from chat IDs."""
        from libs.notifications import TelegramNotifier

        env = {
            "TELEGRAM_BOT_TOKEN": "token",
            "TELEGRAM_CHAT_IDS": "  111 , 222 ,  333  ",
        }

        with patch.dict(os.environ, env, clear=False):
            notifier = TelegramNotifier.from_env()

        assert notifier._chat_ids == ["111", "222", "333"]

    def test_from_env_handles_empty_entries(self):
        """from_env filters empty entries."""
        from libs.notifications import TelegramNotifier

        env = {
            "TELEGRAM_BOT_TOKEN": "token",
            "TELEGRAM_CHAT_IDS": "111,,222,",
        }

        with patch.dict(os.environ, env, clear=False):
            notifier = TelegramNotifier.from_env()

        assert notifier._chat_ids == ["111", "222"]


class TestTelegramNotifierSend:
    """Tests for TelegramNotifier.send() method."""

    def test_send_when_not_configured(self):
        """send returns failure when not configured."""
        from libs.notifications import TelegramNotifier

        notifier = TelegramNotifier()
        result = notifier.send("Hello")

        assert result.success is False
        assert "not configured" in result.message.lower()

    def test_send_success_single_chat(self):
        """send succeeds with single chat ID."""
        from libs.notifications import TelegramNotifier

        notifier = TelegramNotifier(bot_token="test_token", chat_ids=["123"])

        with patch("libs.notifications.telegram.httpx.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"ok": True}
            mock_post.return_value = mock_resp

            result = notifier.send("Hello")

        assert result.success is True
        assert result.successful_count == 1
        assert result.failed_count == 0
        mock_post.assert_called_once()

        # Verify payload
        call_args = mock_post.call_args
        assert call_args.kwargs["json"]["chat_id"] == "123"
        assert call_args.kwargs["json"]["text"] == "Hello"
        assert call_args.kwargs["json"]["parse_mode"] == "Markdown"

    def test_send_success_multiple_chats(self):
        """send succeeds with multiple chat IDs."""
        from libs.notifications import TelegramNotifier

        notifier = TelegramNotifier(bot_token="test_token", chat_ids=["111", "222"])

        with patch("libs.notifications.telegram.httpx.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"ok": True}
            mock_post.return_value = mock_resp

            result = notifier.send("Hello")

        assert result.success is True
        assert result.successful_count == 2
        assert result.failed_count == 0
        assert mock_post.call_count == 2

    def test_send_with_parse_mode_html(self):
        """send uses specified parse_mode."""
        from libs.notifications import TelegramNotifier

        notifier = TelegramNotifier(bot_token="token", chat_ids=["123"])

        with patch("libs.notifications.telegram.httpx.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"ok": True}
            mock_post.return_value = mock_resp

            notifier.send("<b>Bold</b>", parse_mode="HTML")

        assert mock_post.call_args.kwargs["json"]["parse_mode"] == "HTML"

    def test_send_without_parse_mode(self):
        """send excludes parse_mode when empty."""
        from libs.notifications import TelegramNotifier

        notifier = TelegramNotifier(bot_token="token", chat_ids=["123"])

        with patch("libs.notifications.telegram.httpx.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"ok": True}
            mock_post.return_value = mock_resp

            notifier.send("Plain text", parse_mode="")

        assert "parse_mode" not in mock_post.call_args.kwargs["json"]

    def test_send_with_disable_notification(self):
        """send includes disable_notification when True."""
        from libs.notifications import TelegramNotifier

        notifier = TelegramNotifier(bot_token="token", chat_ids=["123"])

        with patch("libs.notifications.telegram.httpx.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"ok": True}
            mock_post.return_value = mock_resp

            notifier.send("Silent", disable_notification=True)

        assert mock_post.call_args.kwargs["json"]["disable_notification"] is True

    def test_send_api_error(self):
        """send handles API errors gracefully."""
        from libs.notifications import TelegramNotifier

        notifier = TelegramNotifier(bot_token="token", chat_ids=["123"])

        with patch("libs.notifications.telegram.httpx.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {
                "ok": False,
                "description": "Chat not found",
            }
            mock_post.return_value = mock_resp

            result = notifier.send("Hello")

        assert result.success is False
        assert result.failed_count == 1
        assert "Chat not found" in result.message

    def test_send_timeout(self):
        """send handles timeout gracefully."""
        from libs.notifications import TelegramNotifier

        notifier = TelegramNotifier(bot_token="token", chat_ids=["123"])

        with patch("libs.notifications.telegram.httpx.post") as mock_post:
            mock_post.side_effect = httpx.TimeoutException("Timeout")

            result = notifier.send("Hello")

        assert result.success is False
        assert result.failed_count == 1
        assert "timeout" in result.message.lower()

    def test_send_partial_failure(self):
        """send reports partial failure correctly."""
        from libs.notifications import TelegramNotifier

        notifier = TelegramNotifier(bot_token="token", chat_ids=["good", "bad"])

        def mock_post_side_effect(url, **kwargs):
            mock_resp = MagicMock()
            if kwargs["json"]["chat_id"] == "bad":
                mock_resp.json.return_value = {
                    "ok": False,
                    "description": "Chat not found",
                }
            else:
                mock_resp.json.return_value = {"ok": True}
            return mock_resp

        with patch("libs.notifications.telegram.httpx.post") as mock_post:
            mock_post.side_effect = mock_post_side_effect

            result = notifier.send("Hello")

        assert result.success is False  # Not all succeeded
        assert result.successful_count == 1
        assert result.failed_count == 1
        assert "Partial" in result.message

    def test_send_uses_correct_url(self):
        """send uses correct Telegram API URL."""
        from libs.notifications import TelegramNotifier

        notifier = TelegramNotifier(bot_token="my_bot_token", chat_ids=["123"])

        with patch("libs.notifications.telegram.httpx.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"ok": True}
            mock_post.return_value = mock_resp

            notifier.send("Hello")

        url = mock_post.call_args.args[0]
        assert url == "https://api.telegram.org/botmy_bot_token/sendMessage"

    def test_send_uses_configured_timeout(self):
        """send uses the configured timeout."""
        from libs.notifications import TelegramNotifier

        notifier = TelegramNotifier(bot_token="token", chat_ids=["123"], timeout=30.0)

        with patch("libs.notifications.telegram.httpx.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"ok": True}
            mock_post.return_value = mock_resp

            notifier.send("Hello")

        assert mock_post.call_args.kwargs["timeout"] == 30.0


class TestTelegramNotifierSendTest:
    """Tests for TelegramNotifier.send_test() method."""

    def test_send_test_sends_test_message(self):
        """send_test sends a test notification."""
        from libs.notifications import TelegramNotifier

        notifier = TelegramNotifier(bot_token="token", chat_ids=["123"])

        with patch("libs.notifications.telegram.httpx.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"ok": True}
            mock_post.return_value = mock_resp

            result = notifier.send_test()

        assert result.success is True
        payload = mock_post.call_args.kwargs["json"]
        assert "Test notification" in payload["text"]
        assert "🔔" in payload["text"]
        # send_test uses no parse_mode
        assert "parse_mode" not in payload


class TestTelegramNotifierExceptionHandling:
    """Tests for exception handling in TelegramNotifier."""

    def test_send_handles_generic_exception(self):
        """send handles generic exceptions gracefully."""
        from libs.notifications import TelegramNotifier

        notifier = TelegramNotifier(bot_token="token", chat_ids=["123"])

        with patch("libs.notifications.telegram.httpx.post") as mock_post:
            mock_post.side_effect = Exception("Network error")

            result = notifier.send("Hello")

        assert result.success is False
        assert result.failed_count == 1
        assert "Network error" in result.message
