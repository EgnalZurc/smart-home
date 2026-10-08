"""Outdoor weather and air-quality fetching.

Pulls current temperature, humidity and European AQI from the Open-Meteo
public APIs. This is an external, best-effort data source: on any network or
HTTP failure the fetch returns ``None`` and records a warning in the error
tracker rather than raising, so a transient outage never crashes the control
loop or the subscription manager.

The httpx timeouts are tuned for the Raspberry Pi, where the TLS handshake to
these endpoints has been observed to be slow: ``connect=15s`` gives the
handshake room, and the transport retries twice on connection errors.

Extracted from ``main.py`` so the logic is importable and unit-testable on its
own instead of living inline in the FastAPI lifespan.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Protocol

import httpx

logger = logging.getLogger(__name__)

WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"


class ErrorTrackerLike(Protocol):
    """Minimal error-tracker surface used by the outdoor fetcher."""

    def register(
        self, error_id: str, severity: str, message: str, source: str
    ) -> None: ...

    def clear(self, error_id: str) -> None: ...


def build_outdoor_fetcher(
    latitude: float,
    longitude: float,
    error_tracker: ErrorTrackerLike,
) -> Callable[[], dict | None]:
    """Build a zero-arg fetcher closure for the subscription manager.

    Args:
        latitude: Location latitude for the weather/AQI query.
        longitude: Location longitude for the weather/AQI query.
        error_tracker: Receives a ``register``/``clear`` call for the
            ``"outdoor_fetch"`` error id depending on the fetch outcome.

    Returns:
        A callable taking no arguments that returns a dict with
        ``temperature``/``humidity``/``aqi`` on success, or ``None`` on any
        failure (having registered a warning with the error tracker).
    """

    def fetch_outdoor_temp() -> dict | None:
        # connect=15.0 allows more time for the (slow on Pi) SSL handshake,
        # read=10.0 for data transfer, pool=5.0 for connection reuse.
        timeout = httpx.Timeout(connect=15.0, read=10.0, write=10.0, pool=5.0)
        transport = httpx.HTTPTransport(retries=2)

        try:
            with httpx.Client(timeout=timeout, transport=transport) as client:
                weather_resp = client.get(
                    WEATHER_URL,
                    params={
                        "latitude": latitude,
                        "longitude": longitude,
                        "current": "temperature_2m,relative_humidity_2m",
                        "timezone": "Europe/Madrid",
                    },
                )
                weather_resp.raise_for_status()

                aqi_resp = client.get(
                    AIR_QUALITY_URL,
                    params={
                        "latitude": latitude,
                        "longitude": longitude,
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
            logger.error("SSL/Connect timeout fetching outdoor data: %s", e)
            error_tracker.register(
                "outdoor_fetch",
                "warning",
                "Outdoor data unavailable: connection timeout",
                "outdoor",
            )
            return None
        except httpx.HTTPStatusError as e:
            logger.error("HTTP error fetching outdoor data: %s", e)
            error_tracker.register(
                "outdoor_fetch",
                "warning",
                f"Outdoor data unavailable: HTTP {e.response.status_code}",
                "outdoor",
            )
            return None
        except Exception as e:
            logger.error("Failed to fetch outdoor data: %s", e)
            error_tracker.register(
                "outdoor_fetch",
                "warning",
                f"Outdoor data unavailable: {e}",
                "outdoor",
            )
            return None

    return fetch_outdoor_temp
