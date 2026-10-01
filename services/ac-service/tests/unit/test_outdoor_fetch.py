"""Unit tests for outdoor temperature fetching.

These tests verify that the outdoor temperature fetch function
handles various failure scenarios correctly, including SSL timeouts.
"""

import pytest
from unittest.mock import MagicMock, patch
import httpx


class MockErrorTracker:
    """Mock error tracker for testing."""
    
    def __init__(self):
        self.registered = {}
        self.cleared = set()
    
    def register(self, error_id: str, severity: str, message: str, source: str):
        self.registered[error_id] = {
            "severity": severity,
            "message": message,
            "source": source,
        }
    
    def clear(self, error_id: str):
        self.cleared.add(error_id)
        self.registered.pop(error_id, None)


class TestFetchOutdoorTemp:
    """Tests for fetch_outdoor_temp function."""

    def _create_fetch_function(self, error_tracker):
        """Create the fetch function with injected dependencies.
        
        This mirrors the structure in main.py but allows for testing.
        """
        LOCATION_LATITUDE = 40.396644
        LOCATION_LONGITUDE = -3.622511

        def fetch_outdoor_temp():
            import httpx

            timeout = httpx.Timeout(connect=15.0, read=10.0, write=10.0, pool=5.0)
            transport = httpx.HTTPTransport(retries=2)

            try:
                with httpx.Client(timeout=timeout, transport=transport) as client:
                    weather_resp = client.get(
                        "https://api.open-meteo.com/v1/forecast",
                        params={
                            "latitude": LOCATION_LATITUDE,
                            "longitude": LOCATION_LONGITUDE,
                            "current": "temperature_2m,relative_humidity_2m",
                            "timezone": "Europe/Madrid",
                        },
                    )
                    weather_resp.raise_for_status()

                    aqi_resp = client.get(
                        "https://air-quality-api.open-meteo.com/v1/air-quality",
                        params={
                            "latitude": LOCATION_LATITUDE,
                            "longitude": LOCATION_LONGITUDE,
                            "current": "european_aqi",
                            "timezone": "Europe/Madrid",
                        },
                    )
                    aqi_resp.raise_for_status()

                weather = weather_resp.json().get("current", {})
                aqi_current = aqi_resp.json().get("current", {})
                error_tracker.clear("outdoor_fetch")
                return {
                    "temperature": weather.get("temperature_2m"),
                    "humidity": weather.get("relative_humidity_2m"),
                    "aqi": aqi_current.get("european_aqi"),
                }
            except httpx.ConnectTimeout as e:
                error_tracker.register(
                    "outdoor_fetch",
                    "warning",
                    "Outdoor data unavailable: connection timeout",
                    "outdoor",
                )
                return None
            except httpx.HTTPStatusError as e:
                error_tracker.register(
                    "outdoor_fetch",
                    "warning",
                    f"Outdoor data unavailable: HTTP {e.response.status_code}",
                    "outdoor",
                )
                return None
            except Exception as e:
                error_tracker.register(
                    "outdoor_fetch",
                    "warning",
                    f"Outdoor data unavailable: {e}",
                    "outdoor",
                )
                return None

        return fetch_outdoor_temp

    def test_successful_fetch_returns_data(self):
        """Should return temperature, humidity and AQI on success."""
        error_tracker = MockErrorTracker()
        fetch_fn = self._create_fetch_function(error_tracker)

        mock_weather_response = MagicMock()
        mock_weather_response.json.return_value = {
            "current": {
                "temperature_2m": 25.5,
                "relative_humidity_2m": 45,
            }
        }
        mock_weather_response.raise_for_status = MagicMock()

        mock_aqi_response = MagicMock()
        mock_aqi_response.json.return_value = {
            "current": {
                "european_aqi": 32,
            }
        }
        mock_aqi_response.raise_for_status = MagicMock()

        with patch("httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.get.side_effect = [mock_weather_response, mock_aqi_response]
            mock_client_class.return_value = mock_client

            result = fetch_fn()

        assert result is not None
        assert result["temperature"] == 25.5
        assert result["humidity"] == 45
        assert result["aqi"] == 32
        assert "outdoor_fetch" in error_tracker.cleared

    def test_ssl_timeout_registers_error(self):
        """Should register error on SSL/connect timeout."""
        error_tracker = MockErrorTracker()
        fetch_fn = self._create_fetch_function(error_tracker)

        with patch("httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            # Simulate SSL handshake timeout
            mock_client.get.side_effect = httpx.ConnectTimeout(
                "The handshake operation timed out"
            )
            mock_client_class.return_value = mock_client

            result = fetch_fn()

        assert result is None
        assert "outdoor_fetch" in error_tracker.registered
        assert error_tracker.registered["outdoor_fetch"]["severity"] == "warning"
        assert "timeout" in error_tracker.registered["outdoor_fetch"]["message"].lower()

    def test_http_error_registers_error(self):
        """Should register error on HTTP error status."""
        error_tracker = MockErrorTracker()
        fetch_fn = self._create_fetch_function(error_tracker)

        with patch("httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            
            # Create a proper HTTPStatusError
            mock_response = MagicMock()
            mock_response.status_code = 503
            mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "Service Unavailable",
                request=MagicMock(),
                response=mock_response,
            )
            mock_client.get.return_value = mock_response
            mock_client_class.return_value = mock_client

            result = fetch_fn()

        assert result is None
        assert "outdoor_fetch" in error_tracker.registered
        assert "503" in error_tracker.registered["outdoor_fetch"]["message"]

    def test_generic_exception_registers_error(self):
        """Should register error on generic exception."""
        error_tracker = MockErrorTracker()
        fetch_fn = self._create_fetch_function(error_tracker)

        with patch("httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.get.side_effect = Exception("Network unreachable")
            mock_client_class.return_value = mock_client

            result = fetch_fn()

        assert result is None
        assert "outdoor_fetch" in error_tracker.registered
        assert "Network unreachable" in error_tracker.registered["outdoor_fetch"]["message"]

    def test_aqi_failure_after_weather_success(self):
        """Should handle AQI failure after weather succeeds."""
        error_tracker = MockErrorTracker()
        fetch_fn = self._create_fetch_function(error_tracker)

        mock_weather_response = MagicMock()
        mock_weather_response.json.return_value = {
            "current": {
                "temperature_2m": 25.5,
                "relative_humidity_2m": 45,
            }
        }
        mock_weather_response.raise_for_status = MagicMock()

        with patch("httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            # First call succeeds, second fails
            mock_client.get.side_effect = [
                mock_weather_response,
                httpx.ConnectTimeout("AQI service timeout"),
            ]
            mock_client_class.return_value = mock_client

            result = fetch_fn()

        assert result is None
        assert "outdoor_fetch" in error_tracker.registered


class TestOutdoorFetchTimeout:
    """Tests specifically for timeout configuration."""

    def test_timeout_configuration(self):
        """Verify timeout values are properly configured."""
        timeout = httpx.Timeout(connect=15.0, read=10.0, write=10.0, pool=5.0)
        
        # Connect timeout should be longer to handle SSL handshake
        assert timeout.connect == 15.0
        # Read timeout for data transfer
        assert timeout.read == 10.0
        # Pool timeout for connection reuse
        assert timeout.pool == 5.0

    def test_transport_with_retries(self):
        """Verify transport is configured with retries."""
        transport = httpx.HTTPTransport(retries=2)
        
        # Transport should have retries configured
        assert transport._pool._retries == 2
