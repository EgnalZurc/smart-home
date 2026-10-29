"""
Portfolio Monitor — Monitor registry and base classes.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from models import AlertLevel


# ─────────────────────────────────────────────────────────────────────────────
# Shared sanitization helpers
# ─────────────────────────────────────────────────────────────────────────────
def sanitize_id(
    value: str | None, max_length: int = 50, default: str = "unknown"
) -> str:
    """Sanitize an identifier for safe use in logs and storage.

    Args:
        value: Raw identifier to sanitize.
        max_length: Maximum length of the result (default 50).
        default: Value to return if input is empty or sanitizes to empty.

    Returns:
        Sanitized identifier with invalid characters removed and
        length bounded to max_length chars.
    """
    if not value:
        return default

    # Remove any characters that aren't alphanumeric, dash, or underscore
    safe_id = re.sub(r"[^\w\-]", "", str(value))

    # Truncate to max length if needed
    if len(safe_id) > max_length:
        safe_id = safe_id[:max_length]

    # Return default if sanitization removed everything
    return safe_id if safe_id else default


class BaseMonitor(ABC):
    """Base class for all portfolio monitors."""

    name: str = "base"

    @abstractmethod
    async def run(self) -> dict[str, Any]:
        """Execute the monitor and return results."""
        pass

    @abstractmethod
    def get_level(self) -> AlertLevel:
        """Return the current alert level."""
        pass

    @abstractmethod
    def get_last_update(self) -> datetime | None:
        """Return the last update timestamp."""
        pass


# Monitor registry — monitors register themselves here
_MONITORS: dict[str, type[BaseMonitor]] = {}


def register_monitor(cls: type[BaseMonitor]) -> type[BaseMonitor]:
    """Decorator to register a monitor class."""
    _MONITORS[cls.name] = cls
    return cls


def get_monitor(name: str) -> type[BaseMonitor] | None:
    """Get a monitor class by name."""
    return _MONITORS.get(name)


def list_monitors() -> list[str]:
    """List all registered monitor names."""
    return list(_MONITORS.keys())


def get_all_monitors() -> dict[str, type[BaseMonitor]]:
    """Get all registered monitors."""
    return _MONITORS.copy()
