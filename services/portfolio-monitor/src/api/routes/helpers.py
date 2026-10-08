"""
Portfolio Monitor — Shared route helpers.

Includes:
- Rate limiting primitives shared across sub-routers
- Safe JSON serialization (no NaN/Inf)
- Analysis/alert serialization

These helpers carry no business logic; they only shape responses and enforce
request rate limits so every sub-router behaves consistently.
"""

import math
from collections.abc import Callable
from datetime import datetime
from functools import wraps
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from models import AlertLevel
from smart_home_common.rate_limiter import InMemoryRateLimiter

# ─────────────────────────────────────────────────────────────────────────────
# Rate Limiting
#
# Uses the shared thread-safe InMemoryRateLimiter from smart_home_common instead
# of a service-local implementation, so every service enforces limits the same
# way. The shared limiter uses a fixed window and exposes get_status(), which we
# use to compute the Retry-After header.
# ─────────────────────────────────────────────────────────────────────────────
# Rate limiters for different endpoint groups
_refresh_limiter = InMemoryRateLimiter(max_requests=5, window_seconds=60)
_config_limiter = InMemoryRateLimiter(max_requests=2, window_seconds=60)


def _retry_after_seconds(limiter: InMemoryRateLimiter, key: str) -> int:
    """Seconds a client should wait before retrying, for the Retry-After header."""
    reset_at = limiter.get_status(key).reset_at
    return max(0, int((reset_at - datetime.now()).total_seconds())) + 1


def _enforce_rate_limit(limiter: InMemoryRateLimiter, request: Request) -> None:
    """Raise HTTP 429 (with Retry-After) when a client exceeds the limiter.

    Shared by endpoints that cannot easily use the ``rate_limit`` decorator
    (e.g. those taking BackgroundTasks), so the 429 shape stays identical.
    """
    client_ip = request.client.host if request.client else "unknown"
    if not limiter.is_allowed(client_ip):
        retry_after = _retry_after_seconds(limiter, client_ip)
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Try again in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )


def rate_limit(limiter: InMemoryRateLimiter):
    """Decorator to apply rate limiting to an endpoint."""

    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, request: Request = None, **kwargs):
            # Use client IP as rate limit key
            client_ip = "unknown"
            if request:
                client_ip = request.client.host if request.client else "unknown"

            if not limiter.is_allowed(client_ip):
                retry_after = _retry_after_seconds(limiter, client_ip)
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


def _serialize_alert(alert) -> dict:
    """Convert alert to serializable dict."""
    from alerts import serialize_alert

    return serialize_alert(alert)
