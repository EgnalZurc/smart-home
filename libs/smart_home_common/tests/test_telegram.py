"""
Tests for smart_home_common.telegram.

Covers:
- TelegramNotifier initialization (explicit params + from_env)
- TelegramResult dataclass
- enabled property
- send() / send_markdown(): success, disabled, API errors, timeouts, partials
- send_test()
- Multiple chat ID handling and payload shape
"""

import os
from unittest.mock import MagicMock, patch

import httpx

from smart_home_common.telegram import TelegramNotifier, TelegramResult


def _mock_ok_response():
    resp = MagicMock()
    resp.json.return_value = {"ok": True}
    return resp


class TestTelegramResult:
    def test_success_result(self):
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
        result = TelegramResult(
            success=False,
            message="Partial: 1 sent, 1 failed",
            successful_count=1,
            failed_count=1,
        )
        assert result.success is False
        assert result.successful_count == 1
        assert result.failed_count == 1


class TestInitialization:
    def test_init_with_explicit_params(self):
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
        notifier = TelegramNotifier()
        assert notifier._bot_token == ""
        assert notifier._chat_ids == []
        assert notifier._timeout == 15.0
        assert notifier.enabled is False

    def test_chat_ids_are_copied(self):
        """The notifier must not alias the caller's list."""
        src = ["111"]
        notifier = TelegramNotifier(bot_token="t", chat_ids=src)
        src.append("222")
        assert notifier._chat_ids == ["111"]

    def test_enabled_requires_token_and_chat_ids(self):
        assert TelegramNotifier().enabled is False
        assert TelegramNotifier(bot_token="token").enabled is False
        assert TelegramNotifier(chat_ids=["123"]).enabled is False
        assert TelegramNotifier(bot_token="token", chat_ids=["123"]).enabled is True


class TestFromEnv:
    def test_from_env_with_chat_ids(self):
        env = {
            "TELEGRAM_BOT_TOKEN": "bot_token_env",
            "TELEGRAM_CHAT_IDS": "111,222,333",
            "TELEGRAM_CHAT_ID": "old_id",  # ignored when CHAT_IDS present
        }
        with patch.dict(os.environ, env, clear=False):
            notifier = TelegramNotifier.from_env()
        assert notifier._bot_token == "bot_token_env"
        assert notifier._chat_ids == ["111", "222", "333"]
        assert notifier.enabled is True

    def test_from_env_fallback_to_single_chat_id(self):
        env = {
            "TELEGRAM_BOT_TOKEN": "bot_token_env",
            "TELEGRAM_CHAT_ID": "single_id",
            "TELEGRAM_CHAT_IDS": "",
        }
        with patch.dict(os.environ, env, clear=False):
            notifier = TelegramNotifier.from_env()
        assert notifier._chat_ids == ["single_id"]

    def test_from_env_handles_whitespace(self):
        env = {
            "TELEGRAM_BOT_TOKEN": "token",
            "TELEGRAM_CHAT_IDS": "  111 , 222 ,  333  ",
        }
        with patch.dict(os.environ, env, clear=False):
            notifier = TelegramNotifier.from_env()
        assert notifier._chat_ids == ["111", "222", "333"]

    def test_from_env_handles_empty_entries(self):
        env = {
            "TELEGRAM_BOT_TOKEN": "token",
            "TELEGRAM_CHAT_IDS": "111,,222,",
        }
        with patch.dict(os.environ, env, clear=False):
            notifier = TelegramNotifier.from_env()
        assert notifier._chat_ids == ["111", "222"]


class TestSend:
    def test_send_when_not_configured(self):
        result = TelegramNotifier().send("Hello")
        assert result.success is False
        assert "not configured" in result.message.lower()

    def test_send_success_single_chat(self):
        notifier = TelegramNotifier(bot_token="test_token", chat_ids=["123"])
        with patch("smart_home_common.telegram.httpx.post") as mock_post:
            mock_post.return_value = _mock_ok_response()
            result = notifier.send("Hello")
        assert result.success is True
        assert result.successful_count == 1
        assert result.failed_count == 0
        mock_post.assert_called_once()
        payload = mock_post.call_args.kwargs["json"]
        assert payload["chat_id"] == "123"
        assert payload["text"] == "Hello"
        # Default send() uses no parse mode
        assert "parse_mode" not in payload

    def test_send_success_multiple_chats(self):
        notifier = TelegramNotifier(bot_token="test_token", chat_ids=["111", "222"])
        with patch("smart_home_common.telegram.httpx.post") as mock_post:
            mock_post.return_value = _mock_ok_response()
            result = notifier.send("Hello")
        assert result.success is True
        assert result.successful_count == 2
        assert result.failed_count == 0
        assert mock_post.call_count == 2

    def test_send_with_parse_mode_html(self):
        notifier = TelegramNotifier(bot_token="token", chat_ids=["123"])
        with patch("smart_home_common.telegram.httpx.post") as mock_post:
            mock_post.return_value = _mock_ok_response()
            notifier.send("<b>Bold</b>", parse_mode="HTML")
        assert mock_post.call_args.kwargs["json"]["parse_mode"] == "HTML"

    def test_send_disable_web_page_preview_default_true(self):
        notifier = TelegramNotifier(bot_token="token", chat_ids=["123"])
        with patch("smart_home_common.telegram.httpx.post") as mock_post:
            mock_post.return_value = _mock_ok_response()
            notifier.send("Hello")
        assert mock_post.call_args.kwargs["json"]["disable_web_page_preview"] is True

    def test_send_with_disable_notification(self):
        notifier = TelegramNotifier(bot_token="token", chat_ids=["123"])
        with patch("smart_home_common.telegram.httpx.post") as mock_post:
            mock_post.return_value = _mock_ok_response()
            notifier.send("Silent", disable_notification=True)
        assert mock_post.call_args.kwargs["json"]["disable_notification"] is True

    def test_send_api_error(self):
        notifier = TelegramNotifier(bot_token="token", chat_ids=["123"])
        with patch("smart_home_common.telegram.httpx.post") as mock_post:
            resp = MagicMock()
            resp.json.return_value = {"ok": False, "description": "Chat not found"}
            mock_post.return_value = resp
            result = notifier.send("Hello")
        assert result.success is False
        assert result.failed_count == 1
        assert "Chat not found" in result.message

    def test_send_timeout(self):
        notifier = TelegramNotifier(bot_token="token", chat_ids=["123"])
        with patch("smart_home_common.telegram.httpx.post") as mock_post:
            mock_post.side_effect = httpx.TimeoutException("Timeout")
            result = notifier.send("Hello")
        assert result.success is False
        assert result.failed_count == 1
        assert "timeout" in result.message.lower()

    def test_send_partial_failure(self):
        notifier = TelegramNotifier(bot_token="token", chat_ids=["good", "bad"])

        def side_effect(url, **kwargs):
            resp = MagicMock()
            if kwargs["json"]["chat_id"] == "bad":
                resp.json.return_value = {"ok": False, "description": "Chat not found"}
            else:
                resp.json.return_value = {"ok": True}
            return resp

        with patch("smart_home_common.telegram.httpx.post") as mock_post:
            mock_post.side_effect = side_effect
            result = notifier.send("Hello")
        assert result.success is False
        assert result.successful_count == 1
        assert result.failed_count == 1
        assert "Partial" in result.message

    def test_send_uses_correct_url(self):
        notifier = TelegramNotifier(bot_token="my_bot_token", chat_ids=["123"])
        with patch("smart_home_common.telegram.httpx.post") as mock_post:
            mock_post.return_value = _mock_ok_response()
            notifier.send("Hello")
        url = mock_post.call_args.args[0]
        assert url == "https://api.telegram.org/botmy_bot_token/sendMessage"

    def test_send_uses_configured_timeout(self):
        notifier = TelegramNotifier(bot_token="token", chat_ids=["123"], timeout=30.0)
        with patch("smart_home_common.telegram.httpx.post") as mock_post:
            mock_post.return_value = _mock_ok_response()
            notifier.send("Hello")
        assert mock_post.call_args.kwargs["timeout"] == 30.0

    def test_send_handles_request_error(self):
        notifier = TelegramNotifier(bot_token="token", chat_ids=["123"])
        with patch("smart_home_common.telegram.httpx.post") as mock_post:
            mock_post.side_effect = httpx.RequestError("Network error")
            result = notifier.send("Hello")
        assert result.success is False
        assert result.failed_count == 1
        # Only the exception type is surfaced (never the message, which could
        # leak the bot token present in the request URL).
        assert "RequestError" in result.message
        assert "Network error" not in result.message


class TestSendMarkdown:
    def test_send_markdown_sets_parse_mode(self):
        notifier = TelegramNotifier(bot_token="token", chat_ids=["123"])
        with patch("smart_home_common.telegram.httpx.post") as mock_post:
            mock_post.return_value = _mock_ok_response()
            result = notifier.send_markdown("*Bold* text")
        assert result.success is True
        payload = mock_post.call_args.kwargs["json"]
        assert payload["parse_mode"] == "Markdown"
        assert payload["text"] == "*Bold* text"

    def test_send_markdown_when_not_configured(self):
        result = TelegramNotifier().send_markdown("*Bold*")
        assert result.success is False
        assert "not configured" in result.message.lower()


class TestSendTest:
    def test_send_test_sends_message_without_parse_mode(self):
        notifier = TelegramNotifier(bot_token="token", chat_ids=["123"])
        with patch("smart_home_common.telegram.httpx.post") as mock_post:
            mock_post.return_value = _mock_ok_response()
            result = notifier.send_test()
        assert result.success is True
        payload = mock_post.call_args.kwargs["json"]
        assert "Test notification" in payload["text"]
        assert "parse_mode" not in payload


class TestPackageExports:
    def test_exported_from_top_level(self):
        import smart_home_common

        assert smart_home_common.TelegramNotifier is TelegramNotifier
        assert smart_home_common.TelegramResult is TelegramResult
