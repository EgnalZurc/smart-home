"""
Portfolio Monitor — Alerts endpoints.

List upcoming scheduled alerts and mark an alert as completed (only once its
date has arrived). Completing an alert reloads the orchestrator's cached alert
list so the next summary reflects the change.

``get_orchestrator`` is resolved through the ``api.routes`` package namespace at
call time so tests patching ``api.routes.get_orchestrator`` take effect here.
"""

from fastapi import APIRouter, HTTPException

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


@router.post("/alerts/{alert_id}/complete")
async def complete_alert(alert_id: str):
    """Mark an alert as completed. Only allowed if date has arrived."""
    import api.routes as routes
    from alerts import mark_alert_completed

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
