"""Unit tests for config module credential sanitization functions."""


class TestSanitizeTelegramError:
    """Tests for sanitize_telegram_error function."""

    def test_sanitizes_bot_url_token(self):
        """Should redact token from Telegram API URL."""
        from config import sanitize_telegram_error

        msg = "Error: https://api.telegram.org/bot123456789:ABCdef-ghIJKL_mnoPQR/sendMessage failed"
        result = sanitize_telegram_error(msg)

        assert "123456789:ABCdef" not in result
        assert "/bot<REDACTED>/" in result
        assert "sendMessage" in result

    def test_sanitizes_standalone_token(self):
        """Should redact standalone token format."""
        from config import sanitize_telegram_error

        msg = "Token 9876543210:ZYXwvu_tsrqPONM-lkjIHGfed failed validation"
        result = sanitize_telegram_error(msg)

        assert "9876543210:ZYXwvu" not in result
        assert "<REDACTED>" in result

    def test_preserves_non_token_content(self):
        """Should not modify unrelated content."""
        from config import sanitize_telegram_error

        msg = "Connection timeout after 30s"
        result = sanitize_telegram_error(msg)

        assert result == msg

    def test_handles_empty_string(self):
        """Should handle empty string gracefully."""
        from config import sanitize_telegram_error

        result = sanitize_telegram_error("")
        assert result == ""

    def test_sanitizes_multiple_tokens(self):
        """Should redact multiple tokens in same message."""
        from config import sanitize_telegram_error

        # Tokens must be at least 20 chars after the : to match the pattern
        msg = "Token1: 111111:ABCdefGHIjklMNOpqrSTU and Token2: 222222:VWXyzABCdefGHIjklMNOp"
        result = sanitize_telegram_error(msg)

        assert "111111:ABCdef" not in result
        assert "222222:VWXyz" not in result
        assert result.count("<REDACTED>") == 2


class TestSanitizeImapError:
    """Tests for sanitize_imap_error function."""

    def test_sanitizes_explicit_password(self):
        """Should redact provided password from error message."""
        from config import sanitize_imap_error

        password = "mySecureAppPassword123"
        msg = f"IMAP LOGIN failed: authentication error with '{password}'"
        result = sanitize_imap_error(msg, password)

        assert password not in result
        assert "<REDACTED>" in result

    def test_sanitizes_password_in_bytes_repr(self):
        """Should redact password in bytes representation."""
        from config import sanitize_imap_error

        password = "appPass456"
        msg = f"Error: b'{password}' not accepted"
        result = sanitize_imap_error(msg, password)

        assert password not in result

    def test_sanitizes_generic_credential_patterns(self):
        """Should sanitize quoted strings that look like passwords."""
        from config import sanitize_imap_error

        msg = "Authentication failed: 'xyzABC12345678'"
        result = sanitize_imap_error(msg)

        assert "'<REDACTED>'" in result

    def test_preserves_short_strings(self):
        """Should not redact very short strings (likely not passwords)."""
        from config import sanitize_imap_error

        msg = "Error code: 'ERR'"
        result = sanitize_imap_error(msg)

        # Short strings are preserved
        assert "'ERR'" in result

    def test_handles_none_password(self):
        """Should handle None password gracefully."""
        from config import sanitize_imap_error

        msg = "Connection failed"
        result = sanitize_imap_error(msg, None)

        assert result == "Connection failed"

    def test_handles_empty_password(self):
        """Should handle empty string password."""
        from config import sanitize_imap_error

        msg = "Error occurred"
        result = sanitize_imap_error(msg, "")

        assert result == "Error occurred"

    def test_case_insensitive_password_match(self):
        """Should match password case-insensitively."""
        from config import sanitize_imap_error

        password = "MyPassword123"
        msg = "Failed with MYPASSWORD123 credential"
        result = sanitize_imap_error(msg, password)

        assert "MYPASSWORD123" not in result


class TestSanitizeCredentialError:
    """Tests for generic sanitize_credential_error function."""

    def test_sanitizes_single_credential(self):
        """Should redact a single credential."""
        from config import sanitize_credential_error

        msg = "API key abc123xyz failed"
        result = sanitize_credential_error(msg, ["abc123xyz"])

        assert "abc123xyz" not in result
        assert "<REDACTED>" in result

    def test_sanitizes_multiple_credentials(self):
        """Should redact multiple credentials."""
        from config import sanitize_credential_error

        msg = "Token 'secret1' and key 'secret2' are invalid"
        result = sanitize_credential_error(msg, ["secret1", "secret2"])

        assert "secret1" not in result
        assert "secret2" not in result
        assert result.count("<REDACTED>") >= 2

    def test_handles_none_credentials(self):
        """Should handle None credentials list."""
        from config import sanitize_credential_error

        msg = "Error message"
        result = sanitize_credential_error(msg, None)

        assert result == "Error message"

    def test_handles_empty_credentials_list(self):
        """Should handle empty credentials list."""
        from config import sanitize_credential_error

        msg = "Error message"
        result = sanitize_credential_error(msg, [])

        assert result == "Error message"

    def test_handles_short_credentials(self):
        """Should skip credentials shorter than 4 chars."""
        from config import sanitize_credential_error

        msg = "Error with key abc"
        result = sanitize_credential_error(msg, ["abc"])

        # Short credential not redacted (to avoid false positives)
        assert "abc" in result

    def test_handles_special_regex_chars(self):
        """Should handle credentials with regex special characters."""
        from config import sanitize_credential_error

        msg = "Failed with token: abc+def*123"
        result = sanitize_credential_error(msg, ["abc+def*123"])

        assert "abc+def*123" not in result
        assert "<REDACTED>" in result


class TestIntegrationNotifier:
    """Integration tests verifying notifier sanitizes Telegram errors."""

    def test_notifier_sanitizes_telegram_errors(self):
        """Verify _sanitize_telegram_error in notifier redacts tokens.

        Note: notifier.py has its own implementation of _sanitize_telegram_error
        which predates the config.py centralization. Both use the same logic.
        """
        from notifier import _sanitize_telegram_error

        # Create an exception-like object
        class FakeException(Exception):
            pass

        # Token must be at least 20 chars after : to match the pattern
        exc = FakeException("Request to /bot123456:ABCDEFGHijklmnopqrstu/send failed")
        result = _sanitize_telegram_error(exc)

        assert "123456:ABCDEFGH" not in result
        assert "<REDACTED>" in result
