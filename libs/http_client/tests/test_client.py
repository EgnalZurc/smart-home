"""
Tests for libs/http_client/client.py.

Covers:
- RetryClient initialization
- get() method with success, retry on 429/403, failure
- get_with_retry() convenience function
- RetryConfig dataclass
"""

from unittest.mock import MagicMock, patch

import pytest
import requests


class TestRetryConfig:
    """Tests for RetryConfig dataclass."""

    def test_default_values(self):
        """RetryConfig has sensible defaults."""
        from libs.http_client.client import RetryConfig

        config = RetryConfig()
        assert config.timeout == 15
        assert config.max_retries == 3
        assert config.initial_backoff == 5.0
        assert 429 in config.retryable_codes
        assert 403 in config.retryable_codes

    def test_custom_values(self):
        """RetryConfig accepts custom values."""
        from libs.http_client.client import RetryConfig

        config = RetryConfig(
            timeout=30,
            max_retries=5,
            initial_backoff=2.0,
            retryable_codes=(429, 500, 502),
        )
        assert config.timeout == 30
        assert config.max_retries == 5
        assert config.initial_backoff == 2.0
        assert 500 in config.retryable_codes


class TestRetryClient:
    """Tests for RetryClient class."""

    def test_init_defaults(self):
        """RetryClient initializes with defaults."""
        from libs.http_client import RetryClient

        client = RetryClient()
        assert client.default_headers == {}
        assert client.config.max_retries == 3

    def test_init_with_headers(self):
        """RetryClient accepts default headers."""
        from libs.http_client import RetryClient

        client = RetryClient(default_headers={"Authorization": "Bearer token"})
        assert client.default_headers["Authorization"] == "Bearer token"

    def test_get_success(self):
        """get() returns response on success."""
        from libs.http_client import RetryClient

        client = RetryClient()
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("requests.get", return_value=mock_response):
            response = client.get("https://api.example.com/data")

        assert response.status_code == 200

    def test_get_merges_headers(self):
        """get() merges default and request headers."""
        from libs.http_client import RetryClient

        client = RetryClient(default_headers={"X-Default": "default"})
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("requests.get", return_value=mock_response) as mock_get:
            client.get(
                "https://api.example.com/data",
                headers={"X-Custom": "custom"},
            )

        call_headers = mock_get.call_args[1]["headers"]
        assert call_headers["X-Default"] == "default"
        assert call_headers["X-Custom"] == "custom"

    def test_get_retries_on_429(self):
        """get() retries on 429 with exponential backoff."""
        from libs.http_client import RetryClient
        from libs.http_client.client import RetryConfig

        client = RetryClient(config=RetryConfig(max_retries=3, initial_backoff=0.01))

        rate_limited = MagicMock()
        rate_limited.status_code = 429

        success = MagicMock()
        success.status_code = 200

        with patch("requests.get", side_effect=[rate_limited, success]):
            with patch("time.sleep") as mock_sleep:
                response = client.get("https://api.example.com/data")

        assert response.status_code == 200
        mock_sleep.assert_called_once()

    def test_get_retries_on_403(self):
        """get() retries on 403."""
        from libs.http_client import RetryClient
        from libs.http_client.client import RetryConfig

        client = RetryClient(config=RetryConfig(max_retries=3, initial_backoff=0.01))

        forbidden = MagicMock()
        forbidden.status_code = 403

        success = MagicMock()
        success.status_code = 200

        with patch("requests.get", side_effect=[forbidden, success]):
            with patch("time.sleep"):
                response = client.get("https://api.example.com/data")

        assert response.status_code == 200

    def test_get_raises_after_max_retries(self):
        """get() raises HTTPError after exhausting retries."""
        from libs.http_client import RetryClient
        from libs.http_client.client import RetryConfig

        client = RetryClient(config=RetryConfig(max_retries=2, initial_backoff=0.01))

        rate_limited = MagicMock()
        rate_limited.status_code = 429
        rate_limited.raise_for_status.side_effect = requests.HTTPError(
            "429 Too Many Requests"
        )

        with patch("requests.get", return_value=rate_limited):
            with patch("time.sleep"):
                with pytest.raises(requests.HTTPError):
                    client.get("https://api.example.com/data")

    def test_get_raises_non_retryable_error(self):
        """get() raises immediately on non-retryable errors."""
        from libs.http_client import RetryClient

        client = RetryClient()

        error_response = MagicMock()
        error_response.status_code = 500
        error_response.raise_for_status.side_effect = requests.HTTPError(
            "500 Server Error"
        )

        with patch("requests.get", return_value=error_response):
            with pytest.raises(requests.HTTPError):
                client.get("https://api.example.com/data")

    def test_get_passes_params(self):
        """get() passes query parameters."""
        from libs.http_client import RetryClient

        client = RetryClient()
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("requests.get", return_value=mock_response) as mock_get:
            client.get(
                "https://api.example.com/data",
                params={"page": "1", "limit": "10"},
            )

        call_params = mock_get.call_args[1]["params"]
        assert call_params["page"] == "1"
        assert call_params["limit"] == "10"

    def test_exponential_backoff(self):
        """Backoff doubles between retries."""
        from libs.http_client import RetryClient
        from libs.http_client.client import RetryConfig

        client = RetryClient(config=RetryConfig(max_retries=3, initial_backoff=1.0))

        rate_limited = MagicMock()
        rate_limited.status_code = 429

        success = MagicMock()
        success.status_code = 200

        with patch("requests.get", side_effect=[rate_limited, rate_limited, success]):
            with patch("time.sleep") as mock_sleep:
                client.get("https://api.example.com/data")

        # First retry: 1.0s, second retry: 2.0s
        assert mock_sleep.call_count == 2
        assert mock_sleep.call_args_list[0][0][0] == 1.0
        assert mock_sleep.call_args_list[1][0][0] == 2.0


class TestGetWithRetry:
    """Tests for get_with_retry() convenience function."""

    def test_success(self):
        """get_with_retry returns response on success."""
        from libs.http_client import get_with_retry

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("requests.get", return_value=mock_response):
            response = get_with_retry("https://api.example.com/data")

        assert response.status_code == 200

    def test_custom_config(self):
        """get_with_retry accepts custom config parameters."""
        from libs.http_client import get_with_retry

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("requests.get", return_value=mock_response) as mock_get:
            get_with_retry(
                "https://api.example.com/data",
                timeout=30,
                max_retries=5,
            )

        assert mock_get.call_args[1]["timeout"] == 30

    def test_with_headers(self):
        """get_with_retry passes headers."""
        from libs.http_client import get_with_retry

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("requests.get", return_value=mock_response) as mock_get:
            get_with_retry(
                "https://api.example.com/data",
                headers={"X-API-Key": "secret"},
            )

        assert mock_get.call_args[1]["headers"]["X-API-Key"] == "secret"

    def test_with_params(self):
        """get_with_retry passes query parameters."""
        from libs.http_client import get_with_retry

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("requests.get", return_value=mock_response) as mock_get:
            get_with_retry(
                "https://api.example.com/data",
                params={"q": "search"},
            )

        assert mock_get.call_args[1]["params"]["q"] == "search"
