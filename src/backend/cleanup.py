"""Automatic cleanup of unnecessary data.

Runs as a daily periodic task inside the backend.
Deletes:
- Old Zigbee2MQTT logs (> 3 days)
- Any unnecessary temporary files in /app/data
"""

import logging
import os
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# Zigbee2MQTT logs directory (inside container if mounted, or accessible via volume)
Z2M_LOG_DIR = os.environ.get("Z2M_LOG_DIR", "/app/data/log")
# Log retention days
LOG_RETENTION_DAYS = int(os.environ.get("LOG_RETENTION_DAYS", "3"))


def cleanup_old_logs(log_dir: str, max_age_days: int) -> int:
    """Deletes log directories/files older than max_age_days.

    Zigbee2MQTT creates folders with format YYYY-MM-DD.HH-MM-SS/ with a log.log inside.
    """
    removed = 0
    log_path = Path(log_dir)

    if not log_path.exists():
        logger.debug("Log directory not found: %s", log_dir)
        return 0

    max_age_seconds = max_age_days * 86400
    now = time.time()

    for entry in log_path.iterdir():
        try:
            # Check age by modification date
            entry_mtime = entry.stat().st_mtime
            age = now - entry_mtime

            if age > max_age_seconds:
                if entry.is_dir():
                    # Delete complete log directory
                    for file in entry.iterdir():
                        file.unlink()
                    entry.rmdir()
                else:
                    entry.unlink()
                removed += 1
                logger.info("Deleted old log: %s (%.0f days)", entry.name, age / 86400)
        except Exception as e:
            logger.warning("Error deleting %s: %s", entry, e)

    return removed


def run_cleanup():
    """Executes all cleanup tasks."""
    logger.info("=== Running daily cleanup ===")

    # 1. Zigbee2MQTT logs
    removed = cleanup_old_logs(Z2M_LOG_DIR, LOG_RETENTION_DAYS)
    logger.info("Zigbee2MQTT: %d old logs deleted (retention: %d days)", removed, LOG_RETENTION_DAYS)

    logger.info("=== Daily cleanup completed ===")


class CleanupScheduler:
    """Executes cleanup periodically in a thread."""

    def __init__(self, interval: int = 86400, grace_period: int = 60):
        """Initializes the scheduler.
        
        Args:
            interval: Interval between cleanups (seconds), default 24h
            grace_period: Wait time before first cleanup (seconds)
        """
        self._running = False
        self._thread: threading.Thread | None = None
        self._interval = interval
        self._grace_period = grace_period

    def start(self):
        """Starts the cleanup scheduler."""
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("Cleanup scheduler started (every %dh, retention %d days)",
                    self._interval // 3600, LOG_RETENTION_DAYS)

    def stop(self):
        """Stops the scheduler."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self):
        """Loop that executes cleanup periodically. Runs once on startup."""
        # Execute cleanup on startup (after grace period)
        time.sleep(self._grace_period)
        if self._running:
            run_cleanup()

        # Then periodically
        while self._running:
            time.sleep(self._interval)
            if self._running:
                run_cleanup()
