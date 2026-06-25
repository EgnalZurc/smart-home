"""Persistent in-memory error/warning tracking (F0.30).

Usage:
    tracker.register("melcloud_error", "error", "MELCloud unreachable", "melcloud")
    tracker.clear("melcloud_error")
    tracker.get_active()  ->  list[dict]
"""
import threading
import time
from dataclasses import dataclass


@dataclass
class _TrackedError:
    id: str
    timestamp: float
    severity: str  # "error" | "warning"
    message: str
    source: str


class ErrorTracker:
    """Thread-safe, key-based error registry.
    Calling register() with an existing id is a no-op (original timestamp preserved).
    Call clear() when the condition resolves.
    """

    def __init__(self):
        self._errors: dict = {}
        self._lock = threading.Lock()

    def register(self, error_id: str, severity: str, message: str, source: str) -> None:
        """Register an error. No-op if already active."""
        with self._lock:
            if error_id not in self._errors:
                self._errors[error_id] = _TrackedError(
                    id=error_id,
                    timestamp=time.time(),
                    severity=severity,
                    message=message,
                    source=source,
                )

    def clear(self, error_id: str) -> None:
        """Clear an error when its condition is resolved."""
        with self._lock:
            self._errors.pop(error_id, None)

    def get_active(self) -> list:
        """Return active errors sorted newest-first."""
        with self._lock:
            return sorted(
                [
                    {
                        "id": e.id,
                        "timestamp": e.timestamp,
                        "severity": e.severity,
                        "message": e.message,
                        "source": e.source,
                    }
                    for e in self._errors.values()
                ],
                key=lambda x: x["timestamp"],
                reverse=True,
            )

    def has_active(self) -> bool:
        with self._lock:
            return bool(self._errors)
