"""
Portfolio Monitor — API Routes.
"""

import math
from datetime import datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from models import AlertLevel
from orchestrator import get_orchestrator

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


def _safe_float(value: Any) -> Any:
    """Convert NaN/Inf floats to None for JSON compliance."""
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def _serialize_analysis(obj: Any) -> dict:
    """Convert analysis dataclass to serializable dict."""
    if hasattr(obj, "__dataclass_fields__"):
        result = {}
        for field_name in obj.__dataclass_fields__:
            value = getattr(obj, field_name)
            if isinstance(value, AlertLevel):
                result[field_name] = value.name
            elif isinstance(value, datetime):
                result[field_name] = value.isoformat()
            elif isinstance(value, float):
                result[field_name] = _safe_float(value)
            elif isinstance(value, list):
                result[field_name] = [_serialize_analysis(item) for item in value]
            elif hasattr(value, "__dataclass_fields__"):
                result[field_name] = _serialize_analysis(value)
            else:
                result[field_name] = _safe_float(value) if isinstance(value, float) else value
        return result
    return _safe_float(obj) if isinstance(obj, float) else obj


# ─────────────────────────────────────────────────────────────────────────────
# Summary endpoints
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/summary")
async def get_summary():
    """Get the full portfolio summary."""
    orch = get_orchestrator()
    summary = orch.get_summary()

    return {
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


def _serialize_alert(alert) -> dict:
    """Convert alert to serializable dict."""
    return {
        "id": alert.alert_id,
        "date": alert.date,
        "action": alert.action,
        "symbol": alert.symbol,
        "title": alert.title,
        "description": alert.description,
        "priority": alert.priority,
        "recurring": alert.recurring,
    }


@router.get("/etf")
async def get_etf_summary():
    """Get ETF portfolio summary."""
    orch = get_orchestrator()
    summary = orch.get_summary()

    return {
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


@router.get("/crypto")
async def get_crypto_summary():
    """Get crypto staking summary."""
    orch = get_orchestrator()
    summary = orch.get_summary()

    return {
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

    return {
        "total_balance": _safe_float(summary.savings_total_balance),
        "yearly_interest": _safe_float(summary.savings_yearly_interest),
        "last_update": summary.savings_last_update.isoformat()
        if summary.savings_last_update
        else None,
        "analysis": [_serialize_analysis(a) for a in summary.savings_analysis],
    }


@router.get("/alerts")
async def get_alerts():
    """Get upcoming scheduled alerts (next 5 days)."""
    orch = get_orchestrator()
    summary = orch.get_summary()

    return {
        "upcoming": [_serialize_alert(a) for a in summary.upcoming_alerts],
        "count": len(summary.upcoming_alerts),
    }


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
    """Send a test notification to verify Telegram setup."""
    from notifier import TelegramNotifier

    notifier = TelegramNotifier()

    if not notifier.enabled:
        raise HTTPException(
            status_code=503,
            detail="Notifications disabled — missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID",
        )

    result = notifier.send_test()

    if result.success:
        return {"status": "sent", "message": result.message}
    else:
        raise HTTPException(status_code=500, detail=result.message)


@router.get("/notifications/status")
async def notification_status():
    """Get the notification system status."""
    from notifier import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TelegramNotifier

    notifier = TelegramNotifier()

    return {
        "enabled": notifier.enabled,
        "telegram_configured": bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID),
        "bot_token_set": bool(TELEGRAM_BOT_TOKEN),
        "chat_id_set": bool(TELEGRAM_CHAT_ID),
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
