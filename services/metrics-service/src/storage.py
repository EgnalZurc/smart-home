"""Tier-1 in-memory storage: fixed-size ring buffers per metric series.

A *series* is identified by ``(metric, label)`` — e.g.
``("host.ram.percent", "")`` or ``("container.mem.percent", "portfolio-monitor")``.
Each series keeps the latest ``maxlen`` ``(ts, value)`` points in a
:class:`collections.deque`, so appends are O(1) and the oldest point is dropped
automatically once the buffer is full.

Design: 240 points * 30 s = 2 h of hi-resolution history (see design §4.1).
"""

from __future__ import annotations

import threading
from collections import deque

from config import RING_BUFFER_MAXLEN

# A single raw sample as produced by the collector.
Sample = tuple[str, str, float]  # (metric, label, value)
Point = tuple[int, float]  # (ts, value)


class RingBuffer:
    """Thread-safe collection of per-series ring buffers.

    The collector appends from an asyncio task while HTTP handlers read; a
    :class:`threading.Lock` guards the shared dict so a read never observes a
    half-mutated deque.
    """

    def __init__(self, maxlen: int = RING_BUFFER_MAXLEN) -> None:
        self._maxlen = maxlen
        self._series: dict[tuple[str, str], deque[Point]] = {}
        self._lock = threading.Lock()

    def add(self, metric: str, label: str, value: float, ts: int) -> None:
        """Append one point to the ``(metric, label)`` series."""
        key = (metric, label)
        with self._lock:
            buf = self._series.get(key)
            if buf is None:
                buf = deque(maxlen=self._maxlen)
                self._series[key] = buf
            buf.append((ts, float(value)))

    def add_batch(self, samples: list[Sample], ts: int) -> None:
        """Append many samples sharing the same timestamp (one collector tick)."""
        with self._lock:
            for metric, label, value in samples:
                key = (metric, label)
                buf = self._series.get(key)
                if buf is None:
                    buf = deque(maxlen=self._maxlen)
                    self._series[key] = buf
                buf.append((ts, float(value)))

    def series(
        self,
        metric: str,
        label: str = "",
        *,
        since: int | None = None,
        until: int | None = None,
    ) -> list[Point]:
        """Return the points for one series, optionally time-ranged.

        Args:
            metric: Metric name.
            label: Series label (container/service key); ``""`` for host.
            since: Inclusive lower bound on ``ts`` (unix seconds), or ``None``.
            until: Inclusive upper bound on ``ts`` (unix seconds), or ``None``.

        Returns:
            A list of ``(ts, value)`` points in insertion (chronological) order.
        """
        key = (metric, label)
        with self._lock:
            buf = self._series.get(key)
            points = list(buf) if buf is not None else []
        if since is not None:
            points = [p for p in points if p[0] >= since]
        if until is not None:
            points = [p for p in points if p[0] <= until]
        return points

    def latest(self) -> dict[str, dict[str, float | int | str]]:
        """Return the newest point for every known series.

        Returns a mapping ``"metric|label" -> {metric, label, ts, value}`` which
        is JSON-friendly for :func:`GET /api/metrics/latest`.
        """
        out: dict[str, dict[str, float | int | str]] = {}
        with self._lock:
            for (metric, label), buf in self._series.items():
                if not buf:
                    continue
                ts, value = buf[-1]
                out[f"{metric}|{label}"] = {
                    "metric": metric,
                    "label": label,
                    "ts": ts,
                    "value": value,
                }
        return out

    def keys(self) -> list[tuple[str, str]]:
        """Return all known ``(metric, label)`` series keys."""
        with self._lock:
            return list(self._series.keys())

    def window(self, start: int, end: int) -> dict[tuple[str, str], list[float]]:
        """Return all values per series whose ts is in ``[start, end)``.

        Used by the rollup task to compute per-window avg/max.
        """
        out: dict[tuple[str, str], list[float]] = {}
        with self._lock:
            for key, buf in self._series.items():
                vals = [v for (ts, v) in buf if start <= ts < end]
                if vals:
                    out[key] = vals
        return out

    def clear(self) -> None:
        """Drop all series (used in tests)."""
        with self._lock:
            self._series.clear()
