"""Collector: polls every Shelly EM device and persists power/energy.

Mirrors ``metrics-service``'s collector pattern (design §3.3): a long-lived
:class:`Collector` owns the per-channel ring buffer, the SQLite store and three
asyncio loops started/stopped by the FastAPI lifespan.

Cadences (all configurable in ``config.py``):

- **poll** every ``POLL_INTERVAL_S`` (10 s): read instantaneous power from each
  device into the ring buffer (tier 1, hi-res, in-memory).
- **rollup** every ``ROLLUP_INTERVAL_S`` (60 s): average the ring buffer's last
  completed minute per channel into ``power_samples`` (tier 2, SQLite).
- **energy snapshot** every ``ENERGY_SNAPSHOT_INTERVAL_S`` (hourly): write the
  raw monotonic Wh counter per channel into ``energy_readings``.
- **prune** daily: drop rows past their retention window.

Device inventory comes from ``ENERGY_DEVICES`` (JSON). A malformed entry is
skipped with a warning rather than crashing the service.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
from collections import defaultdict, deque

import httpx
from config import (
    DEVICES_JSON,
    ENERGY_SNAPSHOT_INTERVAL_S,
    HTTP_TIMEOUT_S,
    POLL_INTERVAL_S,
    PRUNE_INTERVAL_S,
    RING_BUFFER_MAXLEN,
    ROLLUP_INTERVAL_S,
    SHELLY_PASSWORD,
    SHELLY_USER,
)
from database import EnergyStore
from shelly_client import GEN1, ShellyEMClient

logger: logging.Logger = logging.getLogger(__name__)

# One hi-res power point: (unix_ts, power_w, voltage, pf).
PowerPoint = tuple[int, float, float | None, float | None]

__all__ = ["Collector", "PowerPoint", "parse_devices"]


def parse_devices(raw: str) -> list[dict]:
    """Parse the ``ENERGY_DEVICES`` JSON string into a validated device list.

    Each entry must have ``id`` and ``ip``; ``gen`` defaults to 1 and
    ``channels`` to ``{}``. Malformed entries are dropped with a warning so one
    bad config line never takes the whole collector down.

    SECURITY: Credentials are resolved in this order:
    1. Per-device "username"/"password" in the JSON entry (highest priority)
    2. Global SHELLY_USER/SHELLY_PASSWORD environment variables (fallback)
    3. No authentication (if neither is set)

    Args:
        raw: JSON string containing an array of device configuration objects.
            Each object should have at minimum ``id`` (device identifier) and
            ``ip`` (device address). Optional fields: ``gen`` (Shelly generation,
            defaults to 1), ``channels`` (channel-to-label mapping), ``username``
            and ``password`` (per-device authentication).

    Returns:
        A list of validated device dictionaries, each containing:
        - id: Device identifier string
        - ip: Device IP address string
        - gen: Shelly generation (1 or 2)
        - channels: Dict mapping channel IDs to human labels
        - username: Authentication username (or None)
        - password: Authentication password (or None)

    Raises:
        No exceptions are raised; invalid JSON or malformed entries are logged
        as warnings and skipped, returning an empty or partial list.
    """
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError) as exc:
        logger.warning("ENERGY_DEVICES is not valid JSON (%s); no devices loaded", exc)
        return []
    if not isinstance(parsed, list):
        logger.warning("ENERGY_DEVICES must be a JSON array; no devices loaded")
        return []
    devices: list[dict] = []
    for entry in parsed:
        if not isinstance(entry, dict) or not entry.get("id") or not entry.get("ip"):
            logger.warning("Skipping malformed device entry: %r", entry)
            continue
        # SECURITY: Per-device credentials override global env vars
        username = entry.get("username") or SHELLY_USER or None
        password = entry.get("password") or SHELLY_PASSWORD or None
        devices.append(
            {
                "id": str(entry["id"]),
                "ip": str(entry["ip"]),
                "gen": int(entry.get("gen", GEN1)),
                "channels": entry.get("channels") or {},
                "username": username,
                "password": password,
            }
        )
    return devices


def _global_channel(device_id: str, channel: str) -> str:
    """Build the globally-unique channel key used in storage: ``<dev>:<ch>``.

    Two devices may both expose ``ch0``; namespacing by device id keeps their
    series distinct in the ring buffer and SQLite.

    Args:
        device_id: The device identifier (e.g., "shelly-em-01").
        channel: The channel identifier within the device (e.g., "ch0", "ch1").

    Returns:
        A colon-separated string ``<device_id>:<channel>`` that uniquely
        identifies this channel across all devices in the system.
    """
    return f"{device_id}:{channel}"


class Collector:
    """Owns the Shelly clients, the per-channel ring buffer and the poll loops."""

    def __init__(
        self,
        store: EnergyStore | None = None,
        devices: list[dict] | None = None,
    ) -> None:
        """Initialize the collector with optional injected dependencies.

        Sets up the internal data structures for power/energy collection:
        - Ring buffer for hi-res power samples (tier 1, in-memory)
        - Latest energy readings for hourly snapshots
        - Channel labels from device inventory

        Args:
            store: Optional pre-configured EnergyStore instance. If None,
                creates a new EnergyStore with default settings. Useful for
                testing with mock or in-memory stores.
            devices: Optional pre-parsed device list. If None, parses the
                ``DEVICES_JSON`` configuration. Useful for testing with
                controlled device inventories.

        Note:
            Shelly clients are not created until ``start()`` is called.
            This allows the collector to be instantiated at module load
            without network side effects.
        """
        self.store = store if store is not None else EnergyStore()
        self.devices = devices if devices is not None else parse_devices(DEVICES_JSON)
        self.clients: dict[str, ShellyEMClient] = {}
        # channel -> deque[PowerPoint]; last RING_BUFFER_MAXLEN hi-res samples.
        self.ring: dict[str, deque[PowerPoint]] = defaultdict(
            lambda: deque(maxlen=RING_BUFFER_MAXLEN)
        )
        # channel -> most-recent raw Wh counter seen (for the hourly snapshot).
        self.latest_energy: dict[str, float] = {}
        # channel -> human label (from the inventory) for the read API.
        self.labels: dict[str, str] = {}
        self.last_tick_ts: float | None = None
        self.meter_online: bool | None = None
        self._tasks: list[asyncio.Task] = []

    # ── Setup ─────────────────────────────────────────────────────────────────
    def _build_clients(self) -> None:
        """Instantiate one ShellyEMClient per inventory entry."""
        for dev in self.devices:
            self.clients[dev["id"]] = ShellyEMClient(
                device_id=dev["id"],
                ip=dev["ip"],
                gen=dev["gen"],
                channels=dev["channels"],
                username=dev.get("username"),
                password=dev.get("password"),
                timeout=HTTP_TIMEOUT_S,
            )
            for ch, label in dev["channels"].items():
                self.labels[_global_channel(dev["id"], ch)] = label

    # ── Single tick ───────────────────────────────────────────────────────────
    async def tick(self) -> int:
        """Poll every device once; append power to the ring buffer.

        Returns the number of channels that reported data this tick. Updates
        ``meter_online`` (True if at least one device answered) and
        ``last_tick_ts``.
        """
        ts = int(time.time())
        if not self.clients:
            self.last_tick_ts = time.monotonic()
            self.meter_online = None  # nothing to poll
            return 0

        statuses = await asyncio.gather(
            *(c.get_status() for c in self.clients.values()),
            return_exceptions=True,
        )

        channels_seen = 0
        any_online = False
        for status in statuses:
            if isinstance(status, BaseException):
                logger.warning("device poll raised: %s", status)
                continue
            if not status.get("online"):
                continue
            any_online = True
            dev_id = status["device_id"]
            for ch, reading in status["power"].items():
                key = _global_channel(dev_id, ch)
                power = reading.get("power")
                if power is None:
                    continue
                self.ring[key].append(
                    (ts, power, reading.get("voltage"), reading.get("pf"))
                )
                channels_seen += 1
            for ch, wh in status["energy"].items():
                self.latest_energy[_global_channel(dev_id, ch)] = wh

        self.meter_online = any_online
        self.last_tick_ts = time.monotonic()
        return channels_seen

    # ── Rollup ──────────────────────────────────────────────────────────────────
    def rollup(self, now: int | None = None) -> int:
        """Average the last completed minute of ring data into SQLite.

        Returns the number of rows written. Idempotent per bucket
        (``INSERT OR REPLACE`` keyed on ``(ts, channel)``).
        """
        now = int(time.time()) if now is None else now
        bucket = (now // ROLLUP_INTERVAL_S) * ROLLUP_INTERVAL_S
        start = bucket - ROLLUP_INTERVAL_S  # roll up the *previous* complete window
        rows: list[tuple[str, float, float | None, float | None, float | None]] = []
        for channel, points in self.ring.items():
            window = [p for p in points if start <= p[0] < bucket]
            if not window:
                continue
            powers = [p[1] for p in window]
            voltages = [p[2] for p in window if p[2] is not None]
            pfs = [p[3] for p in window if p[3] is not None]
            rows.append(
                (
                    channel,
                    round(sum(powers) / len(powers), 2),
                    round(max(powers), 2),
                    round(sum(voltages) / len(voltages), 2) if voltages else None,
                    round(sum(pfs) / len(pfs), 3) if pfs else None,
                )
            )
        return self.store.write_power(start, rows)

    def snapshot_energy(self, now: int | None = None) -> int:
        """Persist the current raw Wh counter per channel to SQLite.

        Returns the number of rows written. No-op when no energy has been seen.
        """
        now = int(time.time()) if now is None else now
        rows = [(ch, wh) for ch, wh in self.latest_energy.items()]
        return self.store.write_energy(now, rows)

    # ── Read API support ──────────────────────────────────────────────────────
    def current(self) -> dict:
        """Return the newest power reading per channel for ``/api/energy/current``.

        Shape matches the scaffold stub so the endpoint contract is stable::

            {"ts", "total_w", "channels": {<key>: {power, voltage, pf, label}},
             "meter_online"}
        """
        channels: dict[str, dict] = {}
        total_w = 0.0
        latest_ts = int(time.time())
        for key, points in self.ring.items():
            if not points:
                continue
            ts, power, voltage, pf = points[-1]
            latest_ts = max(latest_ts, ts) if channels else ts
            total_w += power
            channels[key] = {
                "power": round(power, 2),
                "voltage": voltage,
                "pf": pf,
                "label": self.labels.get(key, key),
            }
        return {
            "ts": latest_ts,
            "total_w": round(total_w, 2),
            "channels": channels,
            "meter_online": self.meter_online,
        }

    # ── Background loops ──────────────────────────────────────────────────────
    async def _poll_loop(self) -> None:
        while True:
            try:
                await self.tick()
            except (httpx.HTTPError, asyncio.TimeoutError, OSError) as exc:
                logger.warning("collector tick failed: %s", exc)
            await asyncio.sleep(POLL_INTERVAL_S)

    async def _rollup_loop(self) -> None:
        while True:
            await asyncio.sleep(ROLLUP_INTERVAL_S)
            try:
                await asyncio.to_thread(self.rollup)
            except (sqlite3.Error, OSError) as exc:
                logger.warning("rollup failed: %s", exc)

    async def _energy_loop(self) -> None:
        while True:
            await asyncio.sleep(ENERGY_SNAPSHOT_INTERVAL_S)
            try:
                await asyncio.to_thread(self.snapshot_energy)
            except (sqlite3.Error, OSError) as exc:
                logger.warning("energy snapshot failed: %s", exc)

    async def _prune_loop(self) -> None:
        while True:
            await asyncio.sleep(PRUNE_INTERVAL_S)
            try:
                await asyncio.to_thread(self.store.prune)
            except (sqlite3.Error, OSError) as exc:
                logger.warning("prune failed: %s", exc)

    async def start(self) -> None:
        """Build the Shelly clients and spawn the background tasks."""
        self._build_clients()
        self._tasks = [
            asyncio.create_task(self._poll_loop()),
            asyncio.create_task(self._rollup_loop()),
            asyncio.create_task(self._energy_loop()),
            asyncio.create_task(self._prune_loop()),
        ]
        logger.info(
            "Collector started (%d device(s), poll=%ds)",
            len(self.clients),
            POLL_INTERVAL_S,
        )

    async def stop(self) -> None:
        """Cancel background tasks and close every Shelly client."""
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks = []
        for client in self.clients.values():
            try:
                await client.aclose()
            except httpx.HTTPError:  # pragma: no cover - best-effort cleanup
                logger.warning("failed to close client %s", client.device_id)
        logger.info("Collector stopped")

    # ── Diagnostics ─────────────────────────────────────────────────────────────
    def last_tick_age_s(self) -> float | None:
        """Seconds since the last tick, or None if the loop never ran."""
        if self.last_tick_ts is None:
            return None
        return round(time.monotonic() - self.last_tick_ts, 1)
