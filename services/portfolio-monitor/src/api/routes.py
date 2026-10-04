"""
Portfolio Monitor — API Routes.
"""

import math
from datetime import datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse
from models import AlertLevel
from orchestrator import get_orchestrator

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


def _scrub_payload(obj: Any) -> Any:
    """Recursively replace every NaN/Inf float in a payload with None.

    Final safety net applied to the WHOLE response just before it is
    serialized. Even if a future field, code path, or serializer leaks a
    raw NaN/Inf (numpy or Python), this guarantees the payload is strict-JSON
    compliant, so the endpoint can never again 500 with
    'Out of range float values are not JSON compliant'.
    """
    if isinstance(obj, dict):
        return {k: _scrub_payload(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_scrub_payload(item) for item in obj]
    # bool is a subclass of int — leave it untouched.
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    # Catch numpy floats and anything float-like that is not already a str.
    if not isinstance(obj, (str, int)) and hasattr(obj, "__float__"):
        try:
            fval = float(obj)
        except (TypeError, ValueError):
            return obj
        return None if (math.isnan(fval) or math.isinf(fval)) else fval
    return obj


class _SafeJSONResponse(JSONResponse):
    """JSONResponse that can never emit NaN/Inf.

    ``render`` scrubs the payload recursively (NaN/Inf -> None) and then
    serializes with ``allow_nan=False``. The scrub removes every non-finite
    float so the strict dump always succeeds; ``allow_nan=False`` is a
    belt-and-braces guard that would raise loudly (caught by tests) if a value
    ever slipped past the scrub, instead of silently emitting invalid JSON.
    """

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
    """Convert NaN/Inf floats to None for JSON compliance.

    Handles both Python float and numpy float types.
    """
    if value is None:
        return None
    try:
        # Convert to Python float first (handles np.float64, etc.)
        fval = float(value)
        if math.isnan(fval) or math.isinf(fval):
            return None
        return fval
    except (TypeError, ValueError):
        return value


def _serialize_analysis(obj: Any) -> Any:
    """Convert an analysis dataclass (or any nested value) to a JSON-safe form.

    Recurses through dataclasses, lists and tuples so that NaN/Inf floats are
    scrubbed to None at ANY depth — including nested lists like ``ohlc``
    (a list of ``[open, high, low, close]`` rows), where yfinance gaps can
    leave np.float64(nan) values that break JSON serialization.
    """
    # Dataclass → dict, recursing on each field.
    if hasattr(obj, "__dataclass_fields__"):
        result = {}
        for field_name in obj.__dataclass_fields__:
            result[field_name] = _serialize_analysis(getattr(obj, field_name))
        return result

    # Enums / datetimes keep their existing representation.
    if isinstance(obj, AlertLevel):
        return obj.name
    if isinstance(obj, datetime):
        return obj.isoformat()

    # Strings and bools are returned verbatim (bool is a subclass of int, so it
    # must be checked before the numeric branch).
    if isinstance(obj, (str, bool)):
        return obj

    # Lists / tuples → recurse element-wise (handles ohlc = list[list[float]]).
    if isinstance(obj, (list, tuple)):
        return [_serialize_analysis(item) for item in obj]

    # Dicts → recurse value-wise.
    if isinstance(obj, dict):
        return {k: _serialize_analysis(v) for k, v in obj.items()}

    # Any numeric type, including numpy floats → scrub NaN/Inf.
    if isinstance(obj, (int, float)) or hasattr(obj, "__float__"):
        return _safe_float(obj)

    return obj


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


# ─────────────────────────────────────────────────────────────────────────────
# Control endpoints
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/refresh")
async def refresh_all(background_tasks: BackgroundTasks):
    """Trigger a refresh of all monitors."""
    orch = get_orchestrator()

    async def run_refresh():
        await orch.run_all_monitors()

    background_tasks.add_task(run_refresh)

    return {"status": "refresh_started", "monitors": ["etf", "crypto", "savings"]}


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
    """
    Mark an alert as completed.

    Only allowed if the alert date has arrived (today or past).
    """
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


@router.post("/refresh/{monitor_name}")
async def refresh_monitor(monitor_name: str, background_tasks: BackgroundTasks):
    """Trigger a refresh of a specific monitor."""
    if monitor_name not in ["etf", "crypto"]:
        raise HTTPException(status_code=404, detail=f"Unknown monitor: {monitor_name}")

    orch = get_orchestrator()

    async def run_refresh():
        await orch.run_monitor(monitor_name)

    background_tasks.add_task(run_refresh)

    return {"status": "refresh_started", "monitor": monitor_name}


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


@router.post("/reload-config")
async def reload_config():
    """Reload configuration from disk."""
    orch = get_orchestrator()
    orch.reload_config()
    return {"status": "config_reloaded"}


# ─────────────────────────────────────────────────────────────────────────────
# Notification endpoints
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/notifications/test")
async def test_notification():
    """Send a test notification to verify email setup."""
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
# Health endpoint
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/health")
async def health_check():
    """Health check endpoint."""
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
