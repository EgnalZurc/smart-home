"""
Portfolio Monitor — Summary endpoints.

Read-only snapshots of the portfolio: the full combined summary plus per-asset
views (ETF, crypto, savings). All responses go through the NaN/Inf-safe JSON
helpers so a bad float from an upstream source can never 500 the endpoint.

``get_orchestrator`` is resolved through the ``api.routes`` package namespace at
call time so tests patching ``api.routes.get_orchestrator`` take effect here.
"""

from fastapi import APIRouter

from .helpers import _safe_float, _safe_json, _serialize_alert, _serialize_analysis

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


@router.get("/summary")
async def get_summary():
    """Get the full portfolio summary."""
    import api.routes as routes

    orch = routes.get_orchestrator()
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


@router.get("/etf")
async def get_etf_summary():
    """Get ETF portfolio summary."""
    import api.routes as routes

    orch = routes.get_orchestrator()
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
    import api.routes as routes

    orch = routes.get_orchestrator()
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
    import api.routes as routes

    orch = routes.get_orchestrator()
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
