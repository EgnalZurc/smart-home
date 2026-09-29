"""
Portfolio Monitor — Monitor registry and base classes.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from models import AlertLevel


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
