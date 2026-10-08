"""
Portfolio Monitor — Notification endpoints.

Send a test email to validate SMTP setup (rate limited) and report the
notification system's current status.
"""

from fastapi import APIRouter, HTTPException, Request

from .helpers import _config_limiter, _enforce_rate_limit

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


@router.post("/notifications/test")
async def test_notification(request: Request):
    """Send a test notification to verify email setup. Rate limited."""
    _enforce_rate_limit(_config_limiter, request)

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
