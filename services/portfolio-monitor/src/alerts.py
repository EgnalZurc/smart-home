"""
Portfolio Monitor — Scheduled Alerts System.

Manages alerts that trigger on specific dates:
- Crypto maturity dates (sell/move)
- Custom review dates

Alerts are shown in the dashboard.
Alerts due today (or past and not completed) trigger email notifications.
Users can mark alerts as completed once the date has arrived.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import config
from config import DATA_DIR
from models import ScheduledAlert

logger = logging.getLogger(__name__)

# File to persist alert completion state
ALERTS_STATE_FILE = DATA_DIR / "alerts_state.json"


def _load_alerts_state() -> dict[str, dict[str, Any]]:
    """Load persisted alerts state (completed, triggered)."""
    try:
        if ALERTS_STATE_FILE.exists():
            with open(ALERTS_STATE_FILE) as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"Could not load alerts state: {e}")
    return {}


def _save_alerts_state(state: dict[str, dict[str, Any]]) -> None:
    """Persist alerts state to disk."""
    try:
        ALERTS_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(ALERTS_STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        logger.error(f"Could not save alerts state: {e}")


def get_all_alerts() -> list[ScheduledAlert]:
    """Get all configured scheduled alerts with their completion state."""
    state = _load_alerts_state()
    alerts = []

    for raw in config.get_scheduled_alerts():
        try:
            alert_id = raw.get("id", "")
            alert_state = state.get(alert_id, {})

            alert = ScheduledAlert(
                alert_id=alert_id,
                date=raw.get("date", ""),
                action=raw.get("action", "review"),
                symbol=raw.get("symbol", ""),
                title=raw.get("title", ""),
                description=raw.get("description", ""),
                priority=raw.get("priority", "medium"),
                recurring=raw.get("recurring"),
                triggered=alert_state.get("triggered", False),
                completed=alert_state.get("completed", False),
                completed_at=alert_state.get("completed_at"),
            )
            alerts.append(alert)
        except Exception as e:
            logger.warning(f"Invalid alert config: {e}")
    return alerts


def get_upcoming_alerts(days: int = 5) -> list[ScheduledAlert]:
    """
    Get alerts to show in dashboard.

    Includes:
    - Alerts scheduled within the next N days (not completed)
    - Overdue alerts (date passed, not completed)
    """
    today = datetime.now(timezone.utc).date()
    cutoff = today + timedelta(days=days)

    upcoming = []
    for alert in get_all_alerts():
        # Skip completed alerts
        if alert.completed:
            continue

        try:
            alert_date = datetime.fromisoformat(alert.date).date()

            # Include if: overdue (past) or within the next N days
            if alert_date <= cutoff:
                upcoming.append(alert)
        except (ValueError, TypeError):
            continue

    # Sort by date (overdue first, then upcoming)
    upcoming.sort(key=lambda a: a.date)
    return upcoming


def get_alerts_due(include_overdue: bool = True) -> list[ScheduledAlert]:
    """
    Get alerts that need notification.

    Returns alerts where:
    - Date is today or in the past
    - Not yet triggered (notification not sent)
    - Not completed
    """
    today = datetime.now(timezone.utc).date()

    due = []
    for alert in get_all_alerts():
        # Skip already triggered or completed
        if alert.triggered or alert.completed:
            continue

        try:
            alert_date = datetime.fromisoformat(alert.date).date()

            if include_overdue:
                # Due if today or past
                if alert_date <= today:
                    due.append(alert)
            else:
                # Only today
                if alert_date == today:
                    due.append(alert)
        except (ValueError, TypeError):
            continue

    return due


def mark_alert_triggered(alert_id: str) -> bool:
    """Mark an alert as triggered (notification sent)."""
    state = _load_alerts_state()

    if alert_id not in state:
        state[alert_id] = {}

    state[alert_id]["triggered"] = True
    state[alert_id]["triggered_at"] = datetime.now(timezone.utc).isoformat()

    _save_alerts_state(state)
    logger.info(f"Alert {alert_id} marked as triggered")
    return True


def mark_alert_completed(alert_id: str) -> bool:
    """
    Mark an alert as completed by the user.

    Only allowed if the alert date has arrived (today or past).
    """
    # Find the alert
    all_alerts = get_all_alerts()
    alert = next((a for a in all_alerts if a.alert_id == alert_id), None)

    if not alert:
        logger.warning(f"Alert {alert_id} not found")
        return False

    # Check if date has arrived
    today = datetime.now(timezone.utc).date()
    try:
        alert_date = datetime.fromisoformat(alert.date).date()
        if alert_date > today:
            logger.warning(f"Cannot complete alert {alert_id} — date hasn't arrived")
            return False
    except (ValueError, TypeError):
        return False

    # Mark as completed
    state = _load_alerts_state()

    if alert_id not in state:
        state[alert_id] = {}

    state[alert_id]["completed"] = True
    state[alert_id]["completed_at"] = datetime.now(timezone.utc).isoformat()

    _save_alerts_state(state)
    logger.info(f"Alert {alert_id} marked as completed")
    return True


def check_and_trigger_alerts(notifier: Any) -> list[ScheduledAlert]:
    """
    Check for alerts due today (or overdue) and send notifications.
    Returns list of triggered alerts.
    """
    due_alerts = get_alerts_due(include_overdue=True)
    triggered = []

    if not due_alerts:
        logger.debug("No alerts due for notification")
        return triggered

    for alert in due_alerts:
        logger.info(f"Alert due: {alert.title} (date: {alert.date})")

        # Send notification
        result = notifier.send_scheduled_alert(alert)
        if result.success:
            mark_alert_triggered(alert.alert_id)
            alert.triggered = True
            triggered.append(alert)
            logger.info(f"  → Notification sent for {alert.alert_id}")
        else:
            logger.error(f"  → Failed to send: {result.message}")

    return triggered


def serialize_alert(alert: ScheduledAlert) -> dict[str, Any]:
    """Convert alert to JSON-serializable dict."""
    # Calculate days until (negative if overdue)
    days_until = None
    is_actionable = False
    try:
        today = datetime.now(timezone.utc).date()
        alert_date = datetime.fromisoformat(alert.date).date()
        days_until = (alert_date - today).days
        is_actionable = alert_date <= today and not alert.completed
    except (ValueError, TypeError):
        pass

    return {
        "id": alert.alert_id,
        "date": alert.date,
        "action": alert.action,
        "symbol": alert.symbol,
        "title": alert.title,
        "description": alert.description,
        "priority": alert.priority,
        "recurring": alert.recurring,
        "triggered": alert.triggered,
        "completed": alert.completed,
        "completed_at": alert.completed_at,
        "days_until": days_until,
        "is_actionable": is_actionable,  # Can be marked as completed
    }
