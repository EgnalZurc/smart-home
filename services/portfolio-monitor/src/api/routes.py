"""
Portfolio Monitor — API Routes.

Includes:
- Rate limiting on expensive endpoints
- Health checks for external services
- Safe JSON serialization (no NaN/Inf)
"""

import math
import time
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime
from functools import wraps
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse
from models import AlertLevel
from orchestrator import get_orchestrator

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


# ─────────────────────────────────────────────────────────────────────────────
# Rate Limiting
# ─────────────────────────────────────────────────────────────────────────────
class RateLimiter:
    """Simple in-memory rate limiter using sliding window."""

    def __init__(self, max_requests: int = 5, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, key: str) -> bool:
        """Check if request is allowed and record it."""
        now = time.time()
        window_start = now - self.window_seconds

        # Clean old requests
        self._requests[key] = [t for t in self._requests[key] if t > window_start]

        # Check limit
        if len(self._requests[key]) >= self.max_requests:
            return False

        # Record request
        self._requests[key].append(now)
        return True

    def time_until_allowed(self, key: str) -> float:
        """Return seconds until next request is allowed."""
        if not self._requests[key]:
            return 0
        oldest = min(self._requests[key])
        return max(0, oldest + self.window_seconds - time.time())


# Rate limiters for different endpoint groups
_refresh_limiter = RateLimiter(max_requests=5, window_seconds=60)
_config_limiter = RateLimiter(max_requests=2, window_seconds=60)


def rate_limit(limiter: RateLimiter):
    """Decorator to apply rate limiting to an endpoint."""

    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, request: Request = None, **kwargs):
            # Use client IP as rate limit key
            client_ip = "unknown"
            if request:
                client_ip = request.client.host if request.client else "unknown"

            if not limiter.is_allowed(client_ip):
                retry_after = int(limiter.time_until_allowed(client_ip)) + 1
                raise HTTPException(
                    status_code=429,
                    detail=f"Rate limit exceeded. Try again in {retry_after} seconds.",
                    headers={"Retry-After": str(retry_after)},
                )
            return await func(*args, **kwargs)

        return wrapper

    return decorator


# ─────────────────────────────────────────────────────────────────────────────
# JSON Safety
# ─────────────────────────────────────────────────────────────────────────────
def _scrub_payload(obj: Any) -> Any:
    """Recursively replace every NaN/Inf float in a payload with None."""
    if isinstance(obj, dict):
        return {k: _scrub_payload(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_scrub_payload(item) for item in obj]
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if not isinstance(obj, (str, int)) and hasattr(obj, "__float__"):
        try:
            fval = float(obj)
        except (TypeError, ValueError):
            return obj
        return None if (math.isnan(fval) or math.isinf(fval)) else fval
    return obj


class _SafeJSONResponse(JSONResponse):
    """JSONResponse that can never emit NaN/Inf."""

    def render(self, content: Any) -> bytes:
        import json

        return json.dumps(
            _scrub_payload(content),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")


def _safe_json(payload: Any) -> JSONResponse:
    """Return a response whose body is guaranteed strict-JSON (no NaN/Inf)."""
    return _SafeJSONResponse(content=payload)


def _safe_float(value: Any) -> Any:
    """Convert NaN/Inf floats to None for JSON compliance."""
    if value is None:
        return None
    try:
        fval = float(value)
        if math.isnan(fval) or math.isinf(fval):
            return None
        return fval
    except (TypeError, ValueError):
        return value


def _serialize_analysis(obj: Any) -> Any:
    """Convert an analysis dataclass to a JSON-safe form."""
    if hasattr(obj, "__dataclass_fields__"):
        result = {}
        for field_name in obj.__dataclass_fields__:
            result[field_name] = _serialize_analysis(getattr(obj, field_name))
        return result

    if isinstance(obj, AlertLevel):
        return obj.name
    if isinstance(obj, datetime):
        return obj.isoformat()

    if isinstance(obj, (str, bool)):
        return obj

    if isinstance(obj, (list, tuple)):
        return [_serialize_analysis(item) for item in obj]

    if isinstance(obj, dict):
        return {k: _serialize_analysis(v) for k, v in obj.items()}

    if isinstance(obj, (int, float)) or hasattr(obj, "__float__"):
        return _safe_float(obj)

    return obj


# ─────────────────────────────────────────────────────────────────────────────
# External Service Health Checks
# ─────────────────────────────────────────────────────────────────────────────
async def check_yahoo_finance() -> dict[str, Any]:
    """Check Yahoo Finance API connectivity."""
    import asyncio

    try:
        # Run in executor to not block async loop
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _check_yahoo_sync)
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

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _check_coingecko_sync)
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

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _check_fear_greed_sync)
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

    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER", os.environ.get("AUTH_SMTP_USER", ""))

    if not smtp_user:
        return {"status": "not_configured"}

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, _check_smtp_sync, smtp_host, smtp_port
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


# ─────────────────────────────────────────────────────────────────────────────
# Summary endpoints
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/summary")
async def get_summary():
    """Get the full portfolio summary."""
    orch = get_orchestrator()
    summary = orch.get_summary()

    return _safe_json(
        {
            "etf": {
                "total_value": _safe_float(summary.etf_total_value),
                "total_invested": _safe_float(summary.etf_total_invested),
                "total_gain_loss": _safe_float(summary.etf_total_gain_loss),
                "total_gain_loss_pct": _safe_float(summary.etf_total_gain_loss_pct),
                "level": summary.etf_level.name,
                "last_update": summary.etf_last_update.isoformat()
                if summary.etf_last_update
                else None,
                "analysis": [_serialize_analysis(a) for a in summary.etf_analysis],
                "phase": summary.phase,
                "phase_months_remaining": summary.phase_months_remaining,
            },
            "crypto": {
                "total_value": _safe_float(summary.crypto_total_value),
                "total_daily_gain": _safe_float(summary.crypto_total_daily_gain),
                "level": summary.crypto_level.name,
                "last_update": summary.crypto_last_update.isoformat()
                if summary.crypto_last_update
                else None,
                "analysis": [_serialize_analysis(a) for a in summary.crypto_analysis],
                "fear_greed": _safe_float(summary.crypto_fear_greed),
                "fear_greed_label": summary.crypto_fear_greed_label,
            },
            "savings": {
                "total_balance": _safe_float(summary.savings_total_balance),
                "yearly_interest": _safe_float(summary.savings_yearly_interest),
                "last_update": summary.savings_last_update.isoformat()
                if summary.savings_last_update
                else None,
                "analysis": [_serialize_analysis(a) for a in summary.savings_analysis],
            },
            "upcoming_alerts": [_serialize_alert(a) for a in summary.upcoming_alerts],
        }
    )


def _serialize_alert(alert) -> dict:
    """Convert alert to serializable dict."""
    from alerts import serialize_alert

    return serialize_alert(alert)


@router.get("/etf")
async def get_etf_summary():
    """Get ETF portfolio summary."""
    orch = get_orchestrator()
    summary = orch.get_summary()

    return _safe_json(
        {
            "total_value": _safe_float(summary.etf_total_value),
            "total_invested": _safe_float(summary.etf_total_invested),
            "total_gain_loss": _safe_float(summary.etf_total_gain_loss),
            "total_gain_loss_pct": _safe_float(summary.etf_total_gain_loss_pct),
            "level": summary.etf_level.name,
            "last_update": summary.etf_last_update.isoformat()
            if summary.etf_last_update
            else None,
            "analysis": [_serialize_analysis(a) for a in summary.etf_analysis],
            "phase": summary.phase,
            "phase_months_remaining": summary.phase_months_remaining,
        }
    )


@router.get("/crypto")
async def get_crypto_summary():
    """Get crypto staking summary."""
    orch = get_orchestrator()
    summary = orch.get_summary()

    return _safe_json(
        {
            "total_value": _safe_float(summary.crypto_total_value),
            "total_daily_gain": _safe_float(summary.crypto_total_daily_gain),
            "level": summary.crypto_level.name,
            "last_update": summary.crypto_last_update.isoformat()
            if summary.crypto_last_update
            else None,
            "analysis": [_serialize_analysis(a) for a in summary.crypto_analysis],
            "fear_greed": _safe_float(summary.crypto_fear_greed),
            "fear_greed_label": summary.crypto_fear_greed_label,
        }
    )


@router.get("/savings")
async def get_savings_summary():
    """Get savings accounts summary."""
    orch = get_orchestrator()
    summary = orch.get_summary()

    return _safe_json(
        {
            "total_balance": _safe_float(summary.savings_total_balance),
            "yearly_interest": _safe_float(summary.savings_yearly_interest),
            "last_update": summary.savings_last_update.isoformat()
            if summary.savings_last_update
            else None,
            "analysis": [_serialize_analysis(a) for a in summary.savings_analysis],
        }
    )


# ─────────────────────────────────────────────────────────────────────────────
# Control endpoints (rate limited)
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/refresh")
async def refresh_all(request: Request, background_tasks: BackgroundTasks):
    """Trigger a refresh of all monitors. Rate limited: 5 req/min."""
    # Manual rate limit check (can't use decorator easily with BackgroundTasks)
    client_ip = request.client.host if request.client else "unknown"
    if not _refresh_limiter.is_allowed(client_ip):
        retry_after = int(_refresh_limiter.time_until_allowed(client_ip)) + 1
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Try again in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )

    orch = get_orchestrator()

    async def run_refresh():
        await orch.run_all_monitors()

    background_tasks.add_task(run_refresh)

    return {"status": "refresh_started", "monitors": ["etf", "crypto", "savings"]}


@router.post("/refresh/{monitor_name}")
async def refresh_monitor(
    monitor_name: str, request: Request, background_tasks: BackgroundTasks
):
    """Trigger a refresh of a specific monitor. Rate limited: 5 req/min."""
    if monitor_name not in ["etf", "crypto", "savings"]:
        raise HTTPException(status_code=404, detail=f"Unknown monitor: {monitor_name}")

    client_ip = request.client.host if request.client else "unknown"
    if not _refresh_limiter.is_allowed(client_ip):
        retry_after = int(_refresh_limiter.time_until_allowed(client_ip)) + 1
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Try again in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )

    orch = get_orchestrator()

    async def run_refresh():
        await orch.run_monitor(monitor_name)

    background_tasks.add_task(run_refresh)

    return {"status": "refresh_started", "monitor": monitor_name}


@router.post("/reload-config")
async def reload_config(request: Request):
    """Reload configuration from disk. Rate limited: 2 req/min."""
    client_ip = request.client.host if request.client else "unknown"
    if not _config_limiter.is_allowed(client_ip):
        retry_after = int(_config_limiter.time_until_allowed(client_ip)) + 1
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Try again in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )

    orch = get_orchestrator()
    orch.reload_config()
    return {"status": "config_reloaded"}


# ─────────────────────────────────────────────────────────────────────────────
# Alerts endpoints
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/alerts")
async def get_alerts():
    """Get upcoming scheduled alerts (next 5 days + overdue)."""
    orch = get_orchestrator()
    summary = orch.get_summary()

    return _safe_json(
        {
            "upcoming": [_serialize_alert(a) for a in summary.upcoming_alerts],
            "count": len(summary.upcoming_alerts),
        }
    )


@router.post("/alerts/{alert_id}/complete")
async def complete_alert(alert_id: str):
    """Mark an alert as completed. Only allowed if date has arrived."""
    from alerts import mark_alert_completed

    success = mark_alert_completed(alert_id)

    if not success:
        raise HTTPException(
            status_code=400,
            detail="Cannot complete alert — either not found or date hasn't arrived",
        )

    # Reload alerts in summary
    orch = get_orchestrator()
    orch._load_upcoming_alerts()

    return {"status": "completed", "alert_id": alert_id}


# ─────────────────────────────────────────────────────────────────────────────
# Notification endpoints
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/notifications/test")
async def test_notification(request: Request):
    """Send a test notification to verify email setup. Rate limited."""
    client_ip = request.client.host if request.client else "unknown"
    if not _config_limiter.is_allowed(client_ip):
        retry_after = int(_config_limiter.time_until_allowed(client_ip)) + 1
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Try again in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )

    from email_notifier import EmailNotifier

    notifier = EmailNotifier()

    if not notifier.enabled:
        raise HTTPException(
            status_code=503,
            detail="Email notifications disabled — missing SMTP configuration",
        )

    result = notifier.send_test()

    if result.success:
        return {"status": "sent", "message": result.message}
    else:
        raise HTTPException(status_code=500, detail=result.message)


@router.get("/notifications/status")
async def notification_status():
    """Get the notification system status."""
    from email_notifier import EmailNotifier

    notifier = EmailNotifier()

    return {
        "enabled": notifier.enabled,
        "type": "email",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Schedule endpoint
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/schedule")
async def get_schedule():
    """Get the monitoring schedule."""
    orch = get_orchestrator()
    schedule = orch.get_schedule()
    next_runs = orch.get_next_run_times()

    return {
        "schedule": schedule,
        "next_runs": {
            name: ts.isoformat() if ts else None for name, ts in next_runs.items()
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Health endpoints
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/health")
async def health_check():
    """Basic health check endpoint."""
    orch = get_orchestrator()
    state = orch.get_state()

    return {
        "online": True,
        "service": "portfolio-monitor",
        "last_etf_run": state.last_etf_run.isoformat() if state.last_etf_run else None,
        "last_crypto_run": state.last_crypto_run.isoformat()
        if state.last_crypto_run
        else None,
    }


@router.get("/health/external")
async def health_check_external():
    """
    Health check for external service connectivity.

    Checks:
    - Yahoo Finance API
    - CoinGecko API
    - Fear & Greed Index API
    - SMTP server

    Returns detailed status for each service.
    """
    import asyncio

    # Run all checks in parallel
    results = await asyncio.gather(
        check_yahoo_finance(),
        check_coingecko(),
        check_fear_greed(),
        check_smtp(),
        return_exceptions=True,
    )

    yahoo_result = (
        results[0]
        if not isinstance(results[0], Exception)
        else {"status": "error", "message": str(results[0])}
    )
    coingecko_result = (
        results[1]
        if not isinstance(results[1], Exception)
        else {"status": "error", "message": str(results[1])}
    )
    fear_greed_result = (
        results[2]
        if not isinstance(results[2], Exception)
        else {"status": "error", "message": str(results[2])}
    )
    smtp_result = (
        results[3]
        if not isinstance(results[3], Exception)
        else {"status": "error", "message": str(results[3])}
    )

    # Determine overall status
    statuses = [
        yahoo_result.get("status"),
        coingecko_result.get("status"),
        fear_greed_result.get("status"),
    ]
    # SMTP is optional, don't count it for overall status

    all_ok = all(s == "ok" for s in statuses)
    any_error = any(s == "error" for s in statuses)

    overall = "ok" if all_ok else "degraded" if not any_error else "unhealthy"

    return _safe_json(
        {
            "overall": overall,
            "services": {
                "yahoo_finance": yahoo_result,
                "coingecko": coingecko_result,
                "fear_greed": fear_greed_result,
                "smtp": smtp_result,
            },
            "timestamp": datetime.now().isoformat(),
        }
    )
