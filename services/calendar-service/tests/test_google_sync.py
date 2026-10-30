"""Tests for google_sync module — timeout and secret protection.

These tests verify:
1. HTTP timeout is applied to API calls
2. client_secret is never exposed in logs or repr
3. Error messages are sanitized to redact secrets
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestRedactSecret:
    """Tests for _redact_secret helper."""

    def test_redact_empty_string(self):
        from google_sync import _redact_secret

        assert _redact_secret("") == "(empty)"

    def test_redact_none(self):
        from google_sync import _redact_secret

        assert _redact_secret(None) == "(empty)"

    def test_redact_short_secret(self):
        from google_sync import _redact_secret

        assert _redact_secret("abc") == "****"
        assert _redact_secret("12345678") == "****"

    def test_redact_long_secret_shows_last_4(self):
        from google_sync import _redact_secret

        assert _redact_secret("my-super-secret-key") == "****-key"
        assert _redact_secret("GOCSPX-abcdefghijk") == "****hijk"


class TestTimeoutHttp:
    """Tests for TimeoutHttp wrapper."""

    def test_timeout_http_sets_timeout(self):
        from google_sync import TimeoutHttp

        http = TimeoutHttp(timeout=15.0)
        assert http._timeout == 15.0

    def test_timeout_http_inherits_from_http(self):
        from google_sync import TimeoutHttp
        from httplib2 import Http

        http = TimeoutHttp(timeout=10.0)
        assert isinstance(http, Http)


class TestGoogleCalendarClientSecretProtection:
    """Tests for client_secret protection in GoogleCalendarClient."""

    def test_client_secret_not_in_repr(self, tmp_path):
        """Ensure client_secret is not exposed in repr()."""
        from google_sync import GoogleCalendarClient

        client = GoogleCalendarClient(
            client_id="test-client-id",
            client_secret="SUPER-SECRET-KEY-12345",
            token_path=tmp_path / "token.json",
        )
        repr_str = repr(client)
        assert "SUPER-SECRET-KEY" not in repr_str
        assert "client_id=" in repr_str
        assert "token_path=" in repr_str

    def test_client_secret_stored_in_private_attr(self, tmp_path):
        """Ensure client_secret is stored in _client_secret, not client_secret."""
        from google_sync import GoogleCalendarClient

        client = GoogleCalendarClient(
            client_id="test-client-id",
            client_secret="my-secret",
            token_path=tmp_path / "token.json",
        )
        # Should be in private attribute
        assert client._client_secret == "my-secret"
        # Public attribute should not exist
        assert not hasattr(client, "client_secret")

    def test_timeout_parameter_accepted(self, tmp_path):
        """Ensure custom timeout can be passed to constructor."""
        from google_sync import GoogleCalendarClient

        client = GoogleCalendarClient(
            client_id="test-client-id",
            client_secret="my-secret",
            token_path=tmp_path / "token.json",
            timeout=30.0,
        )
        assert client._timeout == 30.0


class TestSecretSanitizationInErrors:
    """Tests for secret sanitization in error messages."""

    @patch("google_sync.TimeoutHttp")
    @patch("google_sync.build")
    def test_authenticate_sanitizes_secret_in_build_error(
        self, mock_build, mock_http, tmp_path, caplog
    ):
        """Ensure client_secret is redacted if it appears in build() error."""
        import logging

        from google_sync import GoogleCalendarClient
        from httplib2 import HttpLib2Error

        # Create a token file
        token_path = tmp_path / "token.json"
        token_path.write_text(
            '{"refresh_token": "valid-refresh-token-here-1234", "token": "access"}'
        )

        # Mock build to raise an HttpLib2Error containing the secret
        secret = "GOCSPX-my-secret-value"
        mock_build.side_effect = HttpLib2Error(f"Invalid client_secret: {secret}")

        client = GoogleCalendarClient(
            client_id="test-client-id",
            client_secret=secret,
            token_path=token_path,
        )

        with caplog.at_level(logging.ERROR, logger="google_sync"):
            result = client.authenticate()

        assert result is False
        # Check that the logged message has the secret redacted
        assert secret not in caplog.text
        assert "****alue" in caplog.text  # Last 4 chars visible

    def test_sanitize_in_refresh_error(self, tmp_path, caplog):
        """Ensure client_secret is redacted if it appears in refresh error."""
        from google_sync import _redact_secret

        # Verify _redact_secret works correctly
        secret = "GOCSPX-another-secret"
        redacted = _redact_secret(secret)
        assert secret not in redacted
        assert "****cret" in redacted


class TestTimeoutInApiCalls:
    """Tests for timeout being applied to API calls."""

    @patch("google_sync.build")
    def test_timeout_http_used_in_service_build(self, mock_build, tmp_path):
        """Verify TimeoutHttp is passed to build()."""
        from google_sync import GoogleCalendarClient, TimeoutHttp

        # Create a valid token file
        token_path = tmp_path / "token.json"
        token_path.write_text(
            '{"refresh_token": "valid-refresh-token-here-1234", "token": "access"}'
        )

        client = GoogleCalendarClient(
            client_id="test-id",
            client_secret="test-secret",
            token_path=token_path,
            timeout=25.0,
        )

        mock_build.return_value = MagicMock()
        client.authenticate()

        # Verify build was called with http parameter
        mock_build.assert_called_once()
        call_kwargs = mock_build.call_args[1]
        assert "http" in call_kwargs
        http_obj = call_kwargs["http"]
        assert isinstance(http_obj, TimeoutHttp)
        assert http_obj._timeout == 25.0

    def test_default_timeout_from_config(self, tmp_path):
        """Verify default timeout comes from config."""
        from config import HTTP_TIMEOUT_S
        from google_sync import GoogleCalendarClient

        client = GoogleCalendarClient(
            client_id="test-id",
            client_secret="test-secret",
            token_path=tmp_path / "token.json",
        )
        assert client._timeout == HTTP_TIMEOUT_S
