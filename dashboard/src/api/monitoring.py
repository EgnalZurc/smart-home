"""Memory monitoring API endpoints.

Receives daily memory snapshots from the Pi cron job, stores history,
and provides alerts for services exceeding thresholds.
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/monitoring", tags=["Monitoring"])

# Storage configuration
HISTORY_DIR = Path("/app/data/monitoring")
HISTORY_FILE = HISTORY_DIR / "memory_history.json"
MAX_HISTORY_DAYS = 30
ALERT_THRESHOLD_PERCENT = 80


class MemorySnapshot(BaseModel):
    """Single container memory measurement."""

    container: str
    used_mib: float
    limit_mib: float
    percent: float


class SnapshotPayload(BaseModel):
    """Payload from the cron job."""

    timestamp: str  # ISO format
    stats: list[MemorySnapshot]


class AlertItem(BaseModel):
    """A service that exceeded the threshold."""

    container: str
    percent: float
    used_mib: float
    limit_mib: float
    timestamp: str


def _load_history() -> dict[str, Any]:
    """Load history from JSON file."""
    if not HISTORY_FILE.exists():
        return {"snapshots": []}
    try:
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load memory history: %s", exc)
        return {"snapshots": []}


def _save_history(data: dict[str, Any]) -> None:
    """Save history to JSON file, pruning old entries."""
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)

    # Prune entries older than MAX_HISTORY_DAYS
    cutoff = datetime.utcnow() - timedelta(days=MAX_HISTORY_DAYS)
    cutoff_str = cutoff.isoformat()

    data["snapshots"] = [
        s for s in data["snapshots"] if s.get("timestamp", "") >= cutoff_str
    ]

    HISTORY_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


@router.post("/memory/snapshot")
async def receive_memory_snapshot(payload: SnapshotPayload) -> dict[str, Any]:
    """Receive a memory snapshot from the cron job.

    Returns any services that exceed the alert threshold.
    """
    history = _load_history()

    # Build snapshot record
    snapshot_record = {
        "timestamp": payload.timestamp,
        "stats": [s.model_dump() for s in payload.stats],
    }
    history["snapshots"].append(snapshot_record)
    _save_history(history)

    # Check for alerts
    alerts = []
    for stat in payload.stats:
        if stat.percent >= ALERT_THRESHOLD_PERCENT:
            alerts.append(
                {
                    "container": stat.container,
                    "percent": stat.percent,
                    "used_mib": stat.used_mib,
                    "limit_mib": stat.limit_mib,
                }
            )

    logger.info(
        "Memory snapshot received: %d services, %d alerts",
        len(payload.stats),
        len(alerts),
    )

    return {
        "status": "ok",
        "received": len(payload.stats),
        "alerts": alerts,
    }


@router.get("/memory/history")
async def get_memory_history(
    days: int = Query(default=7, ge=1, le=30, description="Number of days to retrieve"),
) -> dict[str, Any]:
    """Get memory snapshot history for the last N days."""
    history = _load_history()

    cutoff = datetime.utcnow() - timedelta(days=days)
    cutoff_str = cutoff.isoformat()

    filtered = [
        s for s in history.get("snapshots", []) if s.get("timestamp", "") >= cutoff_str
    ]

    return {
        "days": days,
        "count": len(filtered),
        "snapshots": filtered,
    }


@router.get("/memory/alerts")
async def get_memory_alerts(
    days: int = Query(default=7, ge=1, le=30, description="Number of days to check"),
) -> dict[str, Any]:
    """Get all services that exceeded the alert threshold in the last N days."""
    history = _load_history()

    cutoff = datetime.utcnow() - timedelta(days=days)
    cutoff_str = cutoff.isoformat()

    alerts: list[AlertItem] = []
    for snapshot in history.get("snapshots", []):
        ts = snapshot.get("timestamp", "")
        if ts < cutoff_str:
            continue
        for stat in snapshot.get("stats", []):
            if stat.get("percent", 0) >= ALERT_THRESHOLD_PERCENT:
                alerts.append(
                    AlertItem(
                        container=stat["container"],
                        percent=stat["percent"],
                        used_mib=stat["used_mib"],
                        limit_mib=stat["limit_mib"],
                        timestamp=ts,
                    )
                )

    # Sort by percent descending
    alerts.sort(key=lambda a: a.percent, reverse=True)

    return {
        "days": days,
        "threshold_percent": ALERT_THRESHOLD_PERCENT,
        "count": len(alerts),
        "alerts": [a.model_dump() for a in alerts],
    }
