"""
Portfolio Monitor — Scheduled Alerts System.

Manages alerts that trigger on specific dates:
- Crypto maturity dates (sell/move)
- Monthly DCA reminders
- Custom review dates

Alerts in the next 5 days are shown in the dashboard.
Alerts due today trigger Telegram notifications.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from config import SCHEDULED_ALERTS
from models import ScheduledAlert

logger = logging.getLogger(__name__)


def get_all_alerts() -> list[ScheduledAlert]:
    """Get all configured scheduled alerts."""
    alerts = []
    for raw in SCHEDULED_ALERTS:
        try:
            alert = ScheduledAlert(
                alert_id=raw.get("id", ""),
                date=raw.get("date", ""),
                action=raw.get("action", "review"),
                symbol=raw.get("symbol", ""),
                title=raw.get("title", ""),
                description=raw.get("description", ""),
                priority=raw.get("priority", "medium"),
                recurring=raw.get("recurring"),
                triggered=False,
            )
            alerts.append(alert)
        except Exception as e:
            logger.warning(f"Invalid alert config: {e}")
    return alerts


def get_upcoming_alerts(days: int = 5) -> list[ScheduledAlert]:
    """Get alerts scheduled within the next N days."""
    today = datetime.now(timezone.utc).date()
    cutoff = today + timedelta(days=days)
    
    upcoming = []
    for alert in get_all_alerts():
        try:
            alert_date = datetime.fromisoformat(alert.date).date()
            if today <= alert_date <= cutoff:
                upcoming.append(alert)
        except (ValueError, TypeError):
            continue
    
    # Sort by date
    upcoming.sort(key=lambda a: a.date)
    return upcoming


def get_alerts_due_today() -> list[ScheduledAlert]:
    """Get alerts that are due today."""
    today = datetime.now(timezone.utc).date().isoformat()
    return [a for a in get_all_alerts() if a.date == today]


def check_and_trigger_alerts(notifier: Any) -> list[ScheduledAlert]:
    """
    Check for alerts due today and send notifications.
    Returns list of triggered alerts.
    """
    due_alerts = get_alerts_due_today()
    triggered = []
    
    for alert in due_alerts:
        logger.info(f"Alert due today: {alert.title}")
        
        # Send notification
        result = notifier.send_scheduled_alert(alert)
        if result.success:
            alert.triggered = True
            triggered.append(alert)
            logger.info(f"  → Notification sent for {alert.alert_id}")
        else:
            logger.error(f"  → Failed to send: {result.message}")
    
    return triggered


def generate_next_recurring_alerts() -> list[dict[str, Any]]:
    """
    Generate next occurrences for recurring alerts.
    Called every 5 days to regenerate monthly DCA alerts.
    """
    today = datetime.now(timezone.utc).date()
    new_alerts = []
    
    for alert in get_all_alerts():
        if not alert.recurring:
            continue
        
        try:
            alert_date = datetime.fromisoformat(alert.date).date()
            
            # If alert date has passed, generate next occurrence
            if alert_date < today:
                if alert.recurring == "monthly":
                    # Next month, same day
                    if alert_date.month == 12:
                        next_date = alert_date.replace(year=alert_date.year + 1, month=1)
                    else:
                        next_date = alert_date.replace(month=alert_date.month + 1)
                    
                    new_alerts.append({
                        "id": f"{alert.alert_id}_{next_date.isoformat()}",
                        "date": next_date.isoformat(),
                        "action": alert.action,
                        "symbol": alert.symbol,
                        "title": alert.title,
                        "description": alert.description,
                        "priority": alert.priority,
                        "recurring": alert.recurring,
                    })
                    
        except (ValueError, TypeError):
            continue
    
    return new_alerts


def serialize_alert(alert: ScheduledAlert) -> dict[str, Any]:
    """Convert alert to JSON-serializable dict."""
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
    }
