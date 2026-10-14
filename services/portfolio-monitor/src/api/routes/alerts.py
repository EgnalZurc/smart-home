"""
Portfolio Monitor — Alerts endpoints.

List upcoming scheduled alerts and mark an alert as completed (only once its
date has arrived). Completing an alert reloads the orchestrator's cached alert
list so the next summary reflects the change. Also exposes the currently active
WARN/DANGER market alerts for the unified alerts system.

``get_orchestrator`` is resolved through the ``api.routes`` package namespace at
call time so tests patching ``api.routes.get_orchestrator`` take effect here.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from models import AlertLevel

from .helpers import _safe_json, _serialize_alert

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


@router.get("/alerts")
async def get_alerts():
    """Get upcoming scheduled alerts (next 5 days + overdue)."""
    import api.routes as routes

    orch = routes.get_orchestrator()
    summary = orch.get_summary()

    return _safe_json(
        {
            "upcoming": [_serialize_alert(a) for a in summary.upcoming_alerts],
            "count": len(summary.upcoming_alerts),
        }
    )


@router.get("/alerts/active")
async def get_active_alerts():
    """Return current WARN/DANGER market alerts for the unified alerts system.

    Scans the latest per-asset analyses (ETF + crypto) in the orchestrator's
    cached summary and surfaces every position at WARN or DANGER as a flat
    alert object in the shape the unified dashboard alerts widget expects.
    Savings have no severity signals, so they are not included.
    """
    import api.routes as routes

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

    return _safe_json({"alerts": alerts})


@router.post("/alerts/{alert_id}/complete")
async def complete_alert(alert_id: str):
    """Mark an alert as completed. Only allowed if date has arrived."""
    from alerts import mark_alert_completed

    import api.routes as routes

    success = mark_alert_completed(alert_id)

    if not success:
        raise HTTPException(
            status_code=400,
            detail="Cannot complete alert — either not found or date hasn't arrived",
        )

    # Reload alerts in summary
    orch = routes.get_orchestrator()
    orch._load_upcoming_alerts()

    return {"status": "completed", "alert_id": alert_id}
