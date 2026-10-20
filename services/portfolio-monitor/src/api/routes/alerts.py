"""
Portfolio Monitor — Alerts endpoints.

List upcoming scheduled alerts and mark an alert as completed (only once its
date has arrived). Completing an alert reloads the orchestrator's cached alert
list so the next summary reflects the change. Also exposes the currently active
WARN/DANGER market alerts for the unified alerts system.

``get_orchestrator`` is resolved through the ``api.routes`` package namespace at
call time so tests patching ``api.routes.get_orchestrator`` take effect here.
"""

import logging
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from models import AlertLevel

from .auth import require_auth
from .helpers import _enforce_rate_limit, _public_read_limiter, _safe_json, _serialize_alert

logger = logging.getLogger(__name__)

# Valid alert_id: alphanumeric, underscore, hyphen only
_VALID_ALERT_ID = re.compile(r"^[a-zA-Z0-9_-]+$")


def _validate_alert_id(alert_id: str) -> bool:
    """Validate alert_id format: alphanumeric, underscore, hyphen only."""
    return bool(alert_id and _VALID_ALERT_ID.match(alert_id))


router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


@router.get("/alerts")
async def get_alerts(request: Request):
    """Get upcoming scheduled alerts (next 5 days + overdue)."""
    import api.routes as routes

    _enforce_rate_limit(_public_read_limiter, request)
    orch = routes.get_orchestrator()
    summary = orch.get_summary()

    return _safe_json(
        {
            "upcoming": [_serialize_alert(a) for a in summary.upcoming_alerts],
            "count": len(summary.upcoming_alerts),
        }
    )


@router.get("/alerts/active")
async def get_active_alerts(request: Request):
    """Return current WARN/DANGER market alerts for the unified alerts system.

    Scans the latest per-asset analyses (ETF + crypto) in the orchestrator's
    cached summary and surfaces every position at WARN or DANGER as a flat
    alert object in the shape the unified dashboard alerts widget expects.
    Savings have no severity signals, so they are not included.
    """
    import api.routes as routes

    _enforce_rate_limit(_public_read_limiter, request)
    orch = routes.get_orchestrator()
    summary = orch.get_summary()

    now = datetime.now(timezone.utc).isoformat()

    alerts = []
    analyses = list(summary.etf_analysis or []) + list(summary.crypto_analysis or [])
    for analysis in analyses:
        if analysis.level < AlertLevel.WARN:
            continue

        severity = "critical" if analysis.level == AlertLevel.DANGER else "warning"
        # Signal.body carries the human-readable text; take the first 3.
        detail = "; ".join(s.body for s in (analysis.signals or [])[:3])

        alerts.append(
            {
                "source": "portfolio",
                "severity": severity,
                "title": f"{analysis.name}: {analysis.level.name}",
                "detail": detail,
                "timestamp": now,
                "link": "/portfolio",
            }
        )

    # Rebalance drift: surface each position whose allocation left its target
    # band as a warning-severity alert in the same unified shape.
    import config
    from monitors.rebalance import compute_rebalance

    rebalance = compute_rebalance(
        etf_analyses=summary.etf_analysis or [],
        crypto_analyses=summary.crypto_analysis or [],
        etf_funds=list(config.get_etf_portfolio().values()),
        crypto_positions=config.get_crypto_positions(),
        threshold_pct=config.get_rebalance_config().get("threshold_pct", 5.0),
    )
    for pos in rebalance["positions"]:
        if not pos["needs_rebalance"]:
            continue
        direction = "over" if pos["deviation"] > 0 else "under"
        alerts.append(
            {
                "source": "portfolio",
                "severity": "warning",
                "title": f"Rebalance: {pos['name']}",
                "detail": (
                    f"{pos['current_allocation']:.1f}% vs target "
                    f"{pos['target_allocation']:.1f}% "
                    f"({direction} by {abs(pos['deviation']):.1f} pts)"
                ),
                "timestamp": now,
                "link": "/portfolio",
            }
        )

    # Upcoming dividends: surface any dividend estimated within the next 7 days
    # as an informational alert so they appear in the unified alerts feed.
    import asyncio

    from monitors.etf_monitor import calculate_dividend_info

    portfolio = config.get_etf_portfolio()
    prices: dict[str, float] = {}
    for analysis in summary.etf_analysis or []:
        ticker = getattr(analysis, "ticker", None)
        price = getattr(analysis, "price", None)
        if ticker and price:
            prices[ticker] = float(price)

    today = datetime.now(timezone.utc).date()
    for fund_id, cfg in portfolio.items():
        ticker = cfg.get("ticker", "")
        units = cfg.get("units", 0.0) or 0.0
        current_price = prices.get(ticker)
        info = await asyncio.to_thread(
            calculate_dividend_info, ticker, current_price, units
        )
        next_date_str = info.get("next_dividend_date")
        if not next_date_str:
            continue
        try:
            next_date = datetime.fromisoformat(next_date_str).date()
        except ValueError:
            continue
        days_until = (next_date - today).days
        if 0 <= days_until <= 7:
            est_income = info.get("estimated_annual_income", 0.0)
            # Quarterly estimate: TTM / 4
            quarterly_est = (est_income / 4) if est_income else 0.0
            alerts.append(
                {
                    "source": "portfolio",
                    "severity": "info",
                    "title": f"Dividend: {cfg.get('name', fund_id)}",
                    "detail": (
                        f"Expected ~{next_date_str} "
                        f"(in {days_until} days, ~€{quarterly_est:.2f})"
                    ),
                    "timestamp": now,
                    "link": "/portfolio",
                }
            )

    return _safe_json({"alerts": alerts})


@router.post("/alerts/{alert_id}/complete", dependencies=[Depends(require_auth)])
async def complete_alert(alert_id: str):
    """Mark an alert as completed. Only allowed if date has arrived."""
    from alerts import get_all_alerts, mark_alert_completed

    import api.routes as routes

    # Validate alert_id format
    if not _validate_alert_id(alert_id):
        logger.warning(f"Invalid alert_id format rejected: {alert_id!r}")
        raise HTTPException(
            status_code=400,
            detail="Invalid alert_id format",
        )

    # Check if alert exists
    all_alerts = get_all_alerts()
    alert = next((a for a in all_alerts if a.alert_id == alert_id), None)
    if not alert:
        logger.warning(f"Alert not found: {alert_id}")
        raise HTTPException(
            status_code=404,
            detail="Alert not found",
        )

    # Attempt to complete (may still fail if date hasn't arrived)
    success = mark_alert_completed(alert_id)

    if not success:
        logger.info(f"Cannot complete alert {alert_id}: date hasn't arrived yet")
        raise HTTPException(
            status_code=400,
            detail="Cannot complete alert — date hasn't arrived yet",
        )

    # Reload alerts in summary
    orch = routes.get_orchestrator()
    orch._load_upcoming_alerts()

    logger.info(f"Alert completed: {alert_id}")
    return {"status": "completed", "alert_id": alert_id}
