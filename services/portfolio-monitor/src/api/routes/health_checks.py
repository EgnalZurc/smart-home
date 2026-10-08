"""
Portfolio Monitor — External service health checks.

Connectivity probes for the APIs the service depends on (Yahoo Finance,
CoinGecko, Fear & Greed Index) plus SMTP reachability. Each async wrapper runs
its blocking sync probe in an executor so the event loop is never blocked.

The async wrappers resolve their sync counterparts through the ``api.routes``
package namespace at call time. Tests patch e.g. ``api.routes._check_yahoo_sync``
to simulate failures, and that late binding is what lets those patches take
effect on the real wrapper.
"""

from typing import Any


async def check_yahoo_finance() -> dict[str, Any]:
    """Check Yahoo Finance API connectivity."""
    import asyncio

    import api.routes as routes

    try:
        # Run in executor to not block async loop
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, routes._check_yahoo_sync)
        return result
    except Exception as e:
        return {"status": "error", "message": str(e)}


def _check_yahoo_sync() -> dict[str, Any]:
    """Synchronous Yahoo Finance check."""
    import yfinance as yf

    try:
        ticker = yf.Ticker("AAPL")
        info = ticker.fast_info
        if info and hasattr(info, "last_price"):
            return {"status": "ok", "test_ticker": "AAPL"}
        return {"status": "degraded", "message": "No price data"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


async def check_coingecko() -> dict[str, Any]:
    """Check CoinGecko API connectivity."""
    import asyncio

    import api.routes as routes

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, routes._check_coingecko_sync)
        return result
    except Exception as e:
        return {"status": "error", "message": str(e)}


def _check_coingecko_sync() -> dict[str, Any]:
    """Synchronous CoinGecko check."""
    import requests

    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/ping",
            timeout=10,
        )
        if r.status_code == 200:
            return {"status": "ok"}
        if r.status_code == 429:
            return {"status": "rate_limited"}
        return {"status": "error", "http_code": r.status_code}
    except requests.Timeout:
        return {"status": "timeout"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


async def check_fear_greed() -> dict[str, Any]:
    """Check Fear & Greed Index API connectivity."""
    import asyncio

    import api.routes as routes

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, routes._check_fear_greed_sync)
        return result
    except Exception as e:
        return {"status": "error", "message": str(e)}


def _check_fear_greed_sync() -> dict[str, Any]:
    """Synchronous Fear & Greed check."""
    import requests

    try:
        r = requests.get(
            "https://api.alternative.me/fng/?limit=1",
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            if data.get("data"):
                return {
                    "status": "ok",
                    "current_value": int(data["data"][0]["value"]),
                }
        return {"status": "error", "http_code": r.status_code}
    except Exception as e:
        return {"status": "error", "message": str(e)}


async def check_smtp() -> dict[str, Any]:
    """Check SMTP connectivity (without sending)."""
    import asyncio
    import os

    import api.routes as routes

    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER", os.environ.get("AUTH_SMTP_USER", ""))

    if not smtp_user:
        return {"status": "not_configured"}

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, routes._check_smtp_sync, smtp_host, smtp_port
        )
        return result
    except Exception as e:
        return {"status": "error", "message": str(e)}


def _check_smtp_sync(host: str, port: int) -> dict[str, Any]:
    """Synchronous SMTP check."""
    import socket

    try:
        # Just check TCP connectivity, don't authenticate
        sock = socket.create_connection((host, port), timeout=10)
        sock.close()
        return {"status": "ok", "host": host, "port": port}
    except TimeoutError:
        return {"status": "timeout", "host": host, "port": port}
    except Exception as e:
        return {"status": "error", "message": str(e)}
