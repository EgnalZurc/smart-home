"""
Tests for lazy credential loading.

These tests verify that credentials (API keys, SMTP passwords) are loaded
lazily at request time, not at module load time, reducing security exposure.
"""

import os
from unittest.mock import patch


class TestCryptoMonitorLazyCredentials:
    """Tests for lazy loading of CoinGecko API key."""

    def test_get_cg_headers_returns_empty_when_no_key(self):
        """Returns empty dict when COINGECKO_API_KEY is not set."""
        from monitors.crypto_monitor import _get_cg_headers

        with patch.dict(os.environ, {}, clear=True):
            # Ensure the key is not set
            os.environ.pop("COINGECKO_API_KEY", None)
            headers = _get_cg_headers()

        assert headers == {}

    def test_get_cg_headers_returns_key_when_set(self):
        """Returns API key header when COINGECKO_API_KEY is set."""
        from monitors.crypto_monitor import _get_cg_headers

        with patch.dict(os.environ, {"COINGECKO_API_KEY": "test-api-key-12345"}):
            headers = _get_cg_headers()

        assert headers == {"x-cg-demo-api-key": "test-api-key-12345"}

    def test_get_cg_headers_reads_fresh_value_each_call(self):
        """Headers function reads env var on each call (lazy, not cached)."""
        from monitors.crypto_monitor import _get_cg_headers

        # First call with one key
        with patch.dict(os.environ, {"COINGECKO_API_KEY": "key-version-1"}):
            headers1 = _get_cg_headers()

        # Second call with different key (simulates rotation)
        with patch.dict(os.environ, {"COINGECKO_API_KEY": "key-version-2"}):
            headers2 = _get_cg_headers()

        assert headers1["x-cg-demo-api-key"] == "key-version-1"
        assert headers2["x-cg-demo-api-key"] == "key-version-2"

    def test_fetch_market_batch_passes_lazy_headers(self):
        """fetch_market_batch calls client.get with lazy headers."""
        from monitors.crypto_monitor import _market_cache, fetch_market_batch

        _market_cache.clear()

        mock_response = [{"id": "bitcoin", "current_price": 50000}]

        with patch.dict(os.environ, {"COINGECKO_API_KEY": "lazy-test-key"}):
            with patch("monitors.crypto_monitor._cg_client") as mock_client:
                mock_client.get.return_value.json.return_value = mock_response
                fetch_market_batch(["bitcoin"])

                # Verify headers were passed
                call_args = mock_client.get.call_args
                assert call_args is not None
                headers_arg = call_args.kwargs.get("headers", {})
                assert headers_arg.get("x-cg-demo-api-key") == "lazy-test-key"

        _market_cache.clear()

    def test_fetch_ohlc_passes_lazy_headers(self):
        """fetch_ohlc calls client.get with lazy headers."""
        from monitors.crypto_monitor import _ohlc_cache, fetch_ohlc

        _ohlc_cache.clear()

        mock_ohlc = [[1234567890, 50000, 51000, 49000, 50500]]

        with patch.dict(os.environ, {"COINGECKO_API_KEY": "ohlc-test-key"}):
            with patch("monitors.crypto_monitor._cg_client") as mock_client:
                mock_client.get.return_value.json.return_value = mock_ohlc
                fetch_ohlc("bitcoin", days=30)

                call_args = mock_client.get.call_args
                assert call_args is not None
                headers_arg = call_args.kwargs.get("headers", {})
                assert headers_arg.get("x-cg-demo-api-key") == "ohlc-test-key"

        _ohlc_cache.clear()

    def test_fetch_exchange_trust_passes_lazy_headers(self):
        """fetch_exchange_trust_score calls client.get with lazy headers."""
        from monitors.crypto_monitor import (
            _exchange_trust_cache,
            fetch_exchange_trust_score,
        )

        _exchange_trust_cache.clear()

        with patch.dict(os.environ, {"COINGECKO_API_KEY": "trust-test-key"}):
            with patch("monitors.crypto_monitor._cg_client") as mock_client:
                mock_client.get.return_value.json.return_value = {"trust_score": 8}
                fetch_exchange_trust_score("binance")

                call_args = mock_client.get.call_args
                assert call_args is not None
                headers_arg = call_args.kwargs.get("headers", {})
                assert headers_arg.get("x-cg-demo-api-key") == "trust-test-key"

        _exchange_trust_cache.clear()


class TestEmailNotifierLazyCredentials:
    """Tests for lazy loading of SMTP credentials."""

    def test_builtin_sender_password_is_property(self):
        """_smtp_password is a property, not an instance attribute."""
        from email_notifier import _BuiltinEmailSender

        # Create sender with no password in env
        with patch.dict(os.environ, {"SMTP_USER": "test@example.com"}, clear=True):
            os.environ.pop("SMTP_PASSWORD", None)
            os.environ.pop("AUTH_SMTP_PASSWORD", None)
            sender = _BuiltinEmailSender()

        # Verify it's a property (descriptor) on the class
        assert isinstance(type(sender).__dict__["_smtp_password"], property)

    def test_builtin_sender_reads_password_lazily(self):
        """Password is read at access time, not at init."""
        from email_notifier import _BuiltinEmailSender

        # Create sender with no password
        with patch.dict(os.environ, {"SMTP_USER": "test@example.com"}, clear=True):
            os.environ.pop("SMTP_PASSWORD", None)
            sender = _BuiltinEmailSender()

        # Now set the password after init
        with patch.dict(os.environ, {"SMTP_PASSWORD": "late-set-password"}):
            password = sender._smtp_password

        assert password == "late-set-password"

    def test_builtin_sender_password_respects_rotation(self):
        """Password changes are reflected immediately (no stale cache)."""
        from email_notifier import _BuiltinEmailSender

        with patch.dict(
            os.environ,
            {"SMTP_USER": "test@example.com", "SMTP_PASSWORD": "password-v1"},
        ):
            sender = _BuiltinEmailSender()
            assert sender._smtp_password == "password-v1"

        # Rotate password
        with patch.dict(os.environ, {"SMTP_PASSWORD": "password-v2"}):
            assert sender._smtp_password == "password-v2"

    def test_builtin_sender_enabled_checks_password_lazily(self):
        """enabled property also uses lazy password check."""
        from email_notifier import _BuiltinEmailSender

        with patch.dict(os.environ, {"SMTP_USER": "test@example.com"}, clear=True):
            os.environ.pop("SMTP_PASSWORD", None)
            sender = _BuiltinEmailSender()

        # Should be disabled without password
        with patch.dict(os.environ, {}, clear=True):
            os.environ["SMTP_USER"] = "test@example.com"
            os.environ.pop("SMTP_PASSWORD", None)
            assert sender.enabled is False

        # Should be enabled once password is set
        with patch.dict(
            os.environ,
            {"SMTP_USER": "test@example.com", "SMTP_PASSWORD": "now-set"},
        ):
            assert sender.enabled is True

    def test_builtin_sender_fallback_to_auth_smtp_password(self):
        """Falls back to AUTH_SMTP_PASSWORD if SMTP_PASSWORD not set."""
        from email_notifier import _BuiltinEmailSender

        with patch.dict(
            os.environ,
            {"SMTP_USER": "test@example.com", "AUTH_SMTP_PASSWORD": "fallback-pass"},
            clear=True,
        ):
            os.environ.pop("SMTP_PASSWORD", None)
            sender = _BuiltinEmailSender()
            assert sender._smtp_password == "fallback-pass"


class TestNoCredentialLeakage:
    """Tests to verify credentials don't leak during normal operations."""

    def test_cg_headers_not_in_module_globals(self):
        """No hardcoded API key in module-level constants."""
        import monitors.crypto_monitor as cm

        # Check that _CG_API_KEY is not defined at module level
        assert not hasattr(cm, "_CG_API_KEY"), "_CG_API_KEY should not exist"

        # Check that _cg_headers is not defined at module level
        assert not hasattr(cm, "_cg_headers"), "_cg_headers should not exist"

    def test_smtp_password_not_stored_in_init(self):
        """SMTP password is not stored as instance variable during __init__."""
        from email_notifier import _BuiltinEmailSender

        with patch.dict(
            os.environ,
            {"SMTP_USER": "test@example.com", "SMTP_PASSWORD": "secret123"},
        ):
            sender = _BuiltinEmailSender()

        # Check instance __dict__ directly - password should not be there
        assert "_smtp_password" not in sender.__dict__
