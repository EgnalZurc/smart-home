"""Unit tests for imap_base module error sanitization."""

import os
from unittest.mock import MagicMock, patch

import pytest


class TestSanitizeImapError:
    """Tests for sanitize_imap_error function."""

    def test_sanitizes_explicit_password(self):
        """Should redact provided password from error message."""
        from imap_base import sanitize_imap_error

        password = "myAppPassword123"
        msg = f"IMAP LOGIN failed: authentication error with '{password}'"
        result = sanitize_imap_error(msg, password)

        assert password not in result
        assert "<REDACTED>" in result

    def test_sanitizes_password_from_env(self):
        """Should redact password from environment variable."""
        from imap_base import sanitize_imap_error

        password = "envSecretPass456"
        with patch.dict(os.environ, {"GMAIL_APP_PASSWORD": password}):
            msg = f"Connection failed: {password} rejected"
            result = sanitize_imap_error(msg)

            assert password not in result
            assert "<REDACTED>" in result

    def test_handles_none_password(self):
        """Should handle None password gracefully."""
        from imap_base import sanitize_imap_error

        with patch.dict(os.environ, {}, clear=True):
            # Remove GMAIL_APP_PASSWORD if present
            os.environ.pop("GMAIL_APP_PASSWORD", None)
            msg = "Connection failed"
            result = sanitize_imap_error(msg, None)

            assert result == "Connection failed"

    def test_handles_empty_password(self):
        """Should not modify message with empty password."""
        from imap_base import sanitize_imap_error

        msg = "Error occurred"
        result = sanitize_imap_error(msg, "")

        assert result == "Error occurred"

    def test_handles_short_password(self):
        """Should not modify message with very short password."""
        from imap_base import sanitize_imap_error

        msg = "Error with abc"
        result = sanitize_imap_error(msg, "abc")

        # Short passwords (< 4 chars) are not redacted to avoid false positives
        assert result == "Error with abc"

    def test_case_insensitive_password_match(self):
        """Should match password case-insensitively."""
        from imap_base import sanitize_imap_error

        password = "MyPassword123"
        msg = "Failed with MYPASSWORD123 credential"
        result = sanitize_imap_error(msg, password)

        assert "MYPASSWORD123" not in result
        assert "<REDACTED>" in result

    def test_handles_special_regex_chars(self):
        """Should handle passwords with regex special characters."""
        from imap_base import sanitize_imap_error

        password = "pass+word*123"
        msg = f"Auth failed: {password}"
        result = sanitize_imap_error(msg, password)

        assert "pass+word*123" not in result
        assert "<REDACTED>" in result

    def test_sanitizes_multiple_occurrences(self):
        """Should redact all occurrences of password."""
        from imap_base import sanitize_imap_error

        password = "secretPass"
        msg = f"Login with {password} failed, retry with {password}"
        result = sanitize_imap_error(msg, password)

        assert password not in result
        assert result.count("<REDACTED>") == 2


class TestConnectImapSanitization:
    """Tests for connect_imap error sanitization."""

    @patch("imap_base.imaplib.IMAP4_SSL")
    def test_sanitizes_login_error(self, mock_imap_class):
        """Should sanitize password from login exception."""
        import imaplib

        from imap_base import connect_imap

        password = "mySecretAppPass"
        mock_imap = MagicMock()
        mock_imap_class.return_value = mock_imap
        mock_imap.login.side_effect = imaplib.IMAP4.error(
            f"Authentication failed for {password}"
        )

        with pytest.raises(imaplib.IMAP4.error) as exc_info:
            connect_imap("test@gmail.com", password)

        # Password should not appear in the exception message
        assert password not in str(exc_info.value)
        assert "<REDACTED>" in str(exc_info.value)

    @patch("imap_base.imaplib.IMAP4_SSL")
    def test_sanitizes_connection_error(self, mock_imap_class):
        """Should sanitize password from connection exception."""
        from imap_base import connect_imap

        password = "connPassword789"
        mock_imap_class.side_effect = OSError(
            f"Failed to connect with credentials {password}"
        )

        with pytest.raises(OSError) as exc_info:
            connect_imap("test@gmail.com", password)

        assert password not in str(exc_info.value)
        assert "<REDACTED>" in str(exc_info.value)


class TestCollectMessagesSanitization:
    """Tests for collect_messages error sanitization."""

    def test_sanitizes_fetch_error(self):
        """Should sanitize password in fetch errors."""
        import imaplib

        from imap_base import collect_messages

        password = "fetchPassSecret"

        # Mock IMAP connection that only works for INBOX
        mock_imap = MagicMock()

        def select_side_effect(folder):
            if folder == "INBOX":
                return ("OK", None)
            return ("NO", None)

        mock_imap.select.side_effect = select_side_effect
        mock_imap.search.return_value = (None, [b"1"])
        mock_imap.fetch.side_effect = imaplib.IMAP4.error(
            f"Fetch failed with credential {password}"
        )

        with patch.dict(os.environ, {"GMAIL_APP_PASSWORD": password}):
            collected, errors, failed_ids = collect_messages(
                mock_imap, "sender@test.com"
            )

        # Password should not appear in error messages
        assert len(errors) == 1
        assert password not in errors[0]
        assert "<REDACTED>" in errors[0]

    def test_sanitizes_folder_error(self):
        """Should sanitize password in folder access errors."""
        import imaplib

        from imap_base import collect_messages

        password = "folderPassSecret"

        # Mock IMAP connection that fails on select
        mock_imap = MagicMock()
        mock_imap.select.side_effect = imaplib.IMAP4.error(
            f"Folder access denied: {password}"
        )

        # The error is logged but not returned in errors list
        # (folder errors are just logged and skipped)
        with patch.dict(os.environ, {"GMAIL_APP_PASSWORD": password}):
            with patch("imap_base.logger") as mock_logger:
                collected, errors, failed_ids = collect_messages(
                    mock_imap, "sender@test.com"
                )

                # Verify logger.warning was called with sanitized message
                for call in mock_logger.warning.call_args_list:
                    call_args = call[0]  # positional arguments
                    # Check the format string arguments, not the Exception object
                    for arg in call_args:
                        if isinstance(arg, str) and password in arg:
                            pytest.fail(f"Password found in log: {arg}")


class TestDeleteProcessedSanitization:
    """Tests for delete_processed error sanitization."""

    def test_sanitizes_store_error(self):
        """Should sanitize password in store errors."""
        import imaplib

        from imap_base import delete_processed

        password = "storePassSecret"

        # Create mock alert
        mock_alert = MagicMock()
        mock_alert.property_id = "12345"
        mock_alert.email_id = "1"
        mock_alert.folder = "INBOX"

        # Mock IMAP connection that fails on store
        mock_imap = MagicMock()
        mock_imap.select.return_value = ("OK", None)
        mock_imap.store.side_effect = imaplib.IMAP4.error(f"Store failed: {password}")

        with patch.dict(os.environ, {"GMAIL_APP_PASSWORD": password}):
            with patch("imap_base.logger") as mock_logger:
                delete_processed(mock_imap, [mock_alert])

                # Verify logger.warning was called with sanitized message
                warning_calls = mock_logger.warning.call_args_list
                for call in warning_calls:
                    call_args = call[0]
                    for arg in call_args:
                        if isinstance(arg, str) and password in arg:
                            pytest.fail(f"Password found in log: {arg}")

    def test_sanitizes_expunge_error(self):
        """Should sanitize password in expunge errors."""
        import imaplib

        from imap_base import delete_processed

        password = "expungePass"

        mock_alert = MagicMock()
        mock_alert.property_id = "12345"
        mock_alert.email_id = "1"
        mock_alert.folder = "INBOX"

        mock_imap = MagicMock()
        mock_imap.select.return_value = ("OK", None)
        mock_imap.store.return_value = ("OK", None)
        mock_imap.expunge.side_effect = imaplib.IMAP4.error(
            f"Expunge failed: credential {password}"
        )

        with patch.dict(os.environ, {"GMAIL_APP_PASSWORD": password}):
            with patch("imap_base.logger") as mock_logger:
                delete_processed(mock_imap, [mock_alert])

                # Verify logger.warning was called with sanitized message
                warning_calls = mock_logger.warning.call_args_list
                for call in warning_calls:
                    call_args = call[0]
                    for arg in call_args:
                        if isinstance(arg, str) and password in arg:
                            pytest.fail(f"Password found in log: {arg}")


class TestIntegrationImapSanitization:
    """Integration tests verifying IMAP errors don't leak passwords."""

    def test_connect_imap_imaplib_error_sanitized(self):
        """Verify imaplib.IMAP4.error exceptions are sanitized."""
        import imaplib

        from imap_base import connect_imap

        password = "realAppPassword"

        with patch("imap_base.imaplib.IMAP4_SSL") as mock_class:
            mock_imap = MagicMock()
            mock_class.return_value = mock_imap
            mock_imap.login.side_effect = imaplib.IMAP4.error(
                f"LOGIN failed: Invalid credentials {password}"
            )

            with pytest.raises(imaplib.IMAP4.error) as exc_info:
                connect_imap("test@gmail.com", password)

            assert password not in str(exc_info.value)
            assert "<REDACTED>" in str(exc_info.value)

    def test_exception_traceback_sanitized(self):
        """Verify exception message (which goes in tracebacks) is sanitized."""
        from imap_base import connect_imap

        password = "tracebackPassword123"

        with patch("imap_base.imaplib.IMAP4_SSL") as mock_class:
            mock_class.side_effect = ConnectionError(
                f"Connection refused with {password}"
            )

            try:
                connect_imap("test@gmail.com", password)
            except ConnectionError as e:
                # The exception message should be sanitized
                assert password not in str(e)
                assert "<REDACTED>" in str(e)
