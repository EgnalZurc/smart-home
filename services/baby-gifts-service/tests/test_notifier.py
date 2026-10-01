"""Tests for the Telegram notifier module."""

import importlib
from unittest.mock import MagicMock, patch


class TestNotifier:
    """Tests for send_gift_notification function."""

    def test_notification_skipped_when_credentials_missing(self, monkeypatch):
        """Verify no error occurs when env vars are not set."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "")
        monkeypatch.setenv("TELEGRAM_CHAT_IDS", "")

        # Reload module to pick up new env vars
        import notifier

        importlib.reload(notifier)

        # Should return False but not raise any exception
        result = notifier.send_gift_notification("Test Gift", "John", "reserved")
        assert result is False

    def test_notification_message_format_reserved(self, monkeypatch):
        """Verify the message format for reserved action."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "test_chat_id")
        monkeypatch.setenv("TELEGRAM_CHAT_IDS", "")

        import notifier

        importlib.reload(notifier)

        with patch("notifier.httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.json.return_value = {"ok": True}
            mock_post.return_value = mock_response

            notifier.send_gift_notification("Carrito de bebé", "María", "reserved")

            # Verify the message format
            call_args = mock_post.call_args
            payload = call_args.kwargs["json"]
            assert payload["text"] == "🎁 *María* ha seleccionado: _Carrito de bebé_"
            assert payload["parse_mode"] == "Markdown"

    def test_notification_message_format_unreserved(self, monkeypatch):
        """Verify the message format for unreserved action."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "test_chat_id")
        monkeypatch.setenv("TELEGRAM_CHAT_IDS", "")

        import notifier

        importlib.reload(notifier)

        with patch("notifier.httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.json.return_value = {"ok": True}
            mock_post.return_value = mock_response

            notifier.send_gift_notification("Cuna", "Pedro", "unreserved")

            # Verify the message format
            call_args = mock_post.call_args
            payload = call_args.kwargs["json"]
            assert payload["text"] == "↩️ *Pedro* ha deseleccionado: _Cuna_"
            assert payload["parse_mode"] == "Markdown"

    def test_notification_sends_to_telegram(self, monkeypatch):
        """Verify correct URL and payload are sent to Telegram."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "my_bot_token")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "123456789")
        monkeypatch.setenv("TELEGRAM_CHAT_IDS", "")

        import notifier

        importlib.reload(notifier)

        with patch("notifier.httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.json.return_value = {"ok": True}
            mock_post.return_value = mock_response

            result = notifier.send_gift_notification("Juguete", "Ana", "reserved")

            # Verify the function returned True
            assert result is True

            # Verify the correct URL
            call_args = mock_post.call_args
            url = call_args.args[0]
            assert url == "https://api.telegram.org/botmy_bot_token/sendMessage"

            # Verify payload
            payload = call_args.kwargs["json"]
            assert payload["chat_id"] == "123456789"
            assert "Juguete" in payload["text"]
            assert "Ana" in payload["text"]
            # Verify timeout is passed
            assert call_args.kwargs.get("timeout") == 15.0

    def test_notification_handles_api_error(self, monkeypatch):
        """Verify the function handles API errors gracefully."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "test_chat_id")
        monkeypatch.setenv("TELEGRAM_CHAT_IDS", "")

        import notifier

        importlib.reload(notifier)

        with patch("notifier.httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "ok": False,
                "description": "Bad Request",
            }
            mock_post.return_value = mock_response

            result = notifier.send_gift_notification("Test", "User", "reserved")

            # Should return False on API error
            assert result is False

    def test_notification_handles_timeout(self, monkeypatch):
        """Verify the function handles timeout gracefully."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "test_chat_id")
        monkeypatch.setenv("TELEGRAM_CHAT_IDS", "")

        import notifier

        importlib.reload(notifier)

        import httpx

        with patch("notifier.httpx.post") as mock_post:
            mock_post.side_effect = httpx.TimeoutException("Timeout")

            result = notifier.send_gift_notification("Test", "User", "reserved")

            # Should return False on timeout
            assert result is False

    def test_notification_sends_to_multiple_chat_ids(self, monkeypatch):
        """Verify notifications are sent to all chat IDs in TELEGRAM_CHAT_IDS."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "")
        monkeypatch.setenv("TELEGRAM_CHAT_IDS", "111,222,333")

        import notifier

        importlib.reload(notifier)

        with patch("notifier.httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.json.return_value = {"ok": True}
            mock_post.return_value = mock_response

            result = notifier.send_gift_notification("Regalo", "Luis", "reserved")

            assert result is True
            # Should be called 3 times, once per chat ID
            assert mock_post.call_count == 3

            # Verify each chat ID was used
            chat_ids_called = [
                call.kwargs["json"]["chat_id"] for call in mock_post.call_args_list
            ]
            assert set(chat_ids_called) == {"111", "222", "333"}

    def test_chat_ids_takes_priority_over_chat_id(self, monkeypatch):
        """Verify TELEGRAM_CHAT_IDS takes priority over TELEGRAM_CHAT_ID."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "old_single_id")
        monkeypatch.setenv("TELEGRAM_CHAT_IDS", "new_id_1,new_id_2")

        import notifier

        importlib.reload(notifier)

        with patch("notifier.httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.json.return_value = {"ok": True}
            mock_post.return_value = mock_response

            notifier.send_gift_notification("Regalo", "Luis", "reserved")

            # Should only use the new IDs, not the old single one
            assert mock_post.call_count == 2
            chat_ids_called = [
                call.kwargs["json"]["chat_id"] for call in mock_post.call_args_list
            ]
            assert "old_single_id" not in chat_ids_called
            assert set(chat_ids_called) == {"new_id_1", "new_id_2"}

    def test_chat_ids_handles_whitespace(self, monkeypatch):
        """Verify TELEGRAM_CHAT_IDS handles whitespace correctly."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "")
        monkeypatch.setenv("TELEGRAM_CHAT_IDS", " 111 , 222 , 333 ")

        import notifier

        importlib.reload(notifier)

        with patch("notifier.httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.json.return_value = {"ok": True}
            mock_post.return_value = mock_response

            notifier.send_gift_notification("Regalo", "Luis", "reserved")

            chat_ids_called = [
                call.kwargs["json"]["chat_id"] for call in mock_post.call_args_list
            ]
            # Whitespace should be stripped
            assert set(chat_ids_called) == {"111", "222", "333"}

    def test_partial_failure_returns_false(self, monkeypatch):
        """Verify partial failures return False but continue sending."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "")
        monkeypatch.setenv("TELEGRAM_CHAT_IDS", "good_id,bad_id")

        import notifier

        importlib.reload(notifier)

        def mock_post_side_effect(url, **kwargs):
            mock_response = MagicMock()
            if kwargs["json"]["chat_id"] == "bad_id":
                mock_response.json.return_value = {
                    "ok": False,
                    "description": "Chat not found",
                }
            else:
                mock_response.json.return_value = {"ok": True}
            return mock_response

        with patch("notifier.httpx.post") as mock_post:
            mock_post.side_effect = mock_post_side_effect

            result = notifier.send_gift_notification("Regalo", "Luis", "reserved")

            # Should return False because one failed
            assert result is False
            # But should still try both
            assert mock_post.call_count == 2
