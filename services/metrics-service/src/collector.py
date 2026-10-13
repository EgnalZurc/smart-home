"""Collector: host/docker/health samplers + the periodic collection loop.

Every ``COLLECT_INTERVAL_S`` seconds the collector:
  1. samples host metrics (direct /proc, /sys reads),
  2. pulls per-container Docker stats from docker-socket-proxy,
  3. pulls the already-computed health snapshot from the backend,
and writes every resulting sample into the tier-1 ring buffer.

A separate cadence rolls the ring buffer up into SQLite (5-min avg/max) and a
daily task prunes rows older than the retention window.

Host sampling logic is ported almost verbatim from
``dashboard/src/system/stats.py`` (proven on the Pi), parameterised so tests can
point it at fixture files.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time

import httpx
from alert_store import AlertStore
from alerts import AlertEngine
from config import (
    ALERT_HISTORY_RETENTION_DAYS,
    ALERTS_ENABLED,
    BACKEND_HEALTH_URL,
    COLLECT_INTERVAL_S,
    CPU_SAMPLE_WINDOW_S,
    DISK_PATH,
    DOCKER_PROXY_URL,
    HTTP_TIMEOUT_S,
    PROC_LOADAVG,
    PROC_MEMINFO,
    PROC_STAT,
    PRUNE_INTERVAL_S,
    ROLLUP_INTERVAL_S,
    THERMAL_ZONE,
)
from sqlite_store import SqliteStore
from storage import RingBuffer, Sample

logger = logging.getLogger(__name__)


def _make_notifier():
    """Build a TelegramNotifier from the environment, tolerating import layout.

    In the container ``/app/libs`` is on ``sys.path`` (set by ``main.py`` /
    ``LIBS_PATH``), so ``notifications`` is a top-level package. Under pytest the
    repo root is on ``sys.path`` instead, so the package is ``libs.notifications``.
    Try both so the engine is wired identically in prod and in tests.
    """
    try:
        from notifications import TelegramNotifier
    except ImportError:  # pragma: no cover - exercised only under pytest layout
        from libs.notifications import TelegramNotifier
    return TelegramNotifier.from_env()


# ═══════════════════════════════════════════════════════════════════════════════
# Host sampler (ported from dashboard/src/system/stats.py)
# ═══════════════════════════════════════════════════════════════════════════════
def _read_cpu_times(path: str | None = None) -> tuple[float, float]:
    """Read (total, idle) CPU jiffies from /proc/stat."""
    path = path if path is not None else PROC_STAT
    with open(path) as fh:
        line = fh.readline()
    fields = [float(x) for x in line.split()[1:]]
    idle = fields[3] + (fields[4] if len(fields) > 4 else 0)
    total = sum(fields)
    return total, idle


def _read_meminfo(path: str | None = None) -> dict[str, int]:
    """Parse /proc/meminfo into a {key: kB} dict."""
    path = path if path is not None else PROC_MEMINFO
    mem: dict[str, int] = {}
    with open(path) as fh:
        for line in fh:
            parts = line.split()
            if len(parts) >= 2:
                mem[parts[0].rstrip(":")] = int(parts[1])
    return mem


def sample_memory(path: str | None = None) -> list[Sample]:
    """Return RAM/swap samples from /proc/meminfo."""
    mem = _read_meminfo(path)
    total_kb = mem.get("MemTotal", 0)
    free_kb = mem.get("MemFree", 0)
    buffers_kb = mem.get("Buffers", 0)
    cached_kb = mem.get("Cached", 0) + mem.get("SReclaimable", 0) - mem.get("Shmem", 0)
    used_kb = total_kb - free_kb - buffers_kb - max(0, cached_kb)
    swap_total = mem.get("SwapTotal", 0)
    swap_free = mem.get("SwapFree", 0)
    swap_used = swap_total - swap_free

    samples: list[Sample] = [
        ("host.ram.used_mb", "", round(used_kb / 1024, 1)),
        (
            "host.ram.percent",
            "",
            round(used_kb / total_kb * 100, 1) if total_kb else 0.0,
        ),
        ("host.swap.used_mb", "", round(swap_used / 1024, 1)),
    ]
    return samples


def sample_cpu(path: str | None = None, window_s: float | None = None) -> list[Sample]:
    """Return a host CPU% sample using a short jiffy-delta window."""
    window_s = window_s if window_s is not None else CPU_SAMPLE_WINDOW_S
    t1, i1 = _read_cpu_times(path)
    time.sleep(window_s)
    t2, i2 = _read_cpu_times(path)
    dt = t2 - t1
    di = i2 - i1
    cpu_pct = round((1.0 - di / dt) * 100, 1) if dt > 0 else 0.0
    return [("host.cpu.percent", "", cpu_pct)]


def sample_disk(path: str | None = None) -> list[Sample]:
    """Return host disk-usage% from statvfs."""
    path = path if path is not None else DISK_PATH
    sv = os.statvfs(path)
    total_b = sv.f_frsize * sv.f_blocks
    free_b = sv.f_frsize * sv.f_bavail
    used_b = total_b - free_b
    pct = round(used_b / total_b * 100, 1) if total_b else 0.0
    return [("host.disk.percent", "", pct)]


def sample_temp(path: str | None = None) -> list[Sample]:
    """Return SoC temperature in °C from the thermal zone."""
    path = path if path is not None else THERMAL_ZONE
    with open(path) as fh:
        raw = int(fh.read().strip())
    return [("host.temp.celsius", "", round(raw / 1000, 1))]


def sample_load(path: str | None = None) -> list[Sample]:
    """Return the 1-minute load average from /proc/loadavg."""
    path = path if path is not None else PROC_LOADAVG
    with open(path) as fh:
        first = fh.read().split()[0]
    return [("host.load.1m", "", float(first))]


def sample_host(*, with_cpu: bool = True) -> list[Sample]:
    """Collect all host metrics, tolerating individual sampler failures."""
    samples: list[Sample] = []
    samplers = [sample_memory, sample_disk, sample_temp, sample_load]
    if with_cpu:
        samplers.insert(1, sample_cpu)
    for fn in samplers:
        try:
            samples.extend(fn())
        except Exception as exc:
            logger.warning("host sampler %s failed: %s", fn.__name__, exc)
    return samples


# ═══════════════════════════════════════════════════════════════════════════════
# Docker sampler (pull from docker-socket-proxy)
# ═══════════════════════════════════════════════════════════════════════════════
def _cpu_percent_from_stats(stats: dict) -> float:
    """Compute container CPU% from a Docker stats payload (non-streaming)."""
    try:
        cpu = stats["cpu_stats"]
        pre = stats["precpu_stats"]
        cpu_delta = cpu["cpu_usage"]["total_usage"] - pre["cpu_usage"]["total_usage"]
        sys_delta = cpu.get("system_cpu_usage", 0) - pre.get("system_cpu_usage", 0)
        online = cpu.get("online_cpus") or len(
            cpu["cpu_usage"].get("percpu_usage") or [1]
        )
        if sys_delta > 0 and cpu_delta > 0:
            return round((cpu_delta / sys_delta) * online * 100.0, 1)
    except (KeyError, TypeError, ZeroDivisionError):
        pass
    return 0.0


def parse_container_stats(name: str, stats: dict) -> list[Sample]:
    """Translate one container's Docker stats payload into samples."""
    samples: list[Sample] = []
    mem = stats.get("memory_stats", {}) or {}
    usage = mem.get("usage")
    limit = mem.get("limit")
    # Docker includes page cache in usage; subtract it like `docker stats` does.
    cache = (mem.get("stats", {}) or {}).get("inactive_file", 0)
    if usage is not None:
        used_mb = round(max(0, usage - cache) / (1024 * 1024), 1)
        samples.append(("container.mem.used_mb", name, used_mb))
        if limit:
            pct = round(max(0, usage - cache) / limit * 100, 1)
            samples.append(("container.mem.percent", name, pct))
    samples.append(("container.cpu.percent", name, _cpu_percent_from_stats(stats)))
    return samples


async def sample_docker(
    client: httpx.AsyncClient, proxy_url: str = DOCKER_PROXY_URL
) -> list[Sample]:
    """Pull per-container stats from docker-socket-proxy.

    Discovers running containers dynamically (``GET /containers/json``) then
    fetches a one-shot stats snapshot for each (``?stream=false``).
    """
    samples: list[Sample] = []
    try:
        resp = await client.get(f"{proxy_url}/containers/json")
        resp.raise_for_status()
        containers = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("docker sampler: list failed: %s", exc)
        return samples

    for c in containers:
        cid = c.get("Id")
        names = c.get("Names") or []
        name = names[0].lstrip("/") if names else cid[:12] if cid else "unknown"
        if not cid:
            continue
        try:
            r = await client.get(f"{proxy_url}/containers/{cid}/stats?stream=false")
            r.raise_for_status()
            samples.extend(parse_container_stats(name, r.json()))
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("docker sampler: stats for %s failed: %s", name, exc)
    return samples


# ═══════════════════════════════════════════════════════════════════════════════
# Health sampler (pull from backend /api/health/all)
# ═══════════════════════════════════════════════════════════════════════════════
def parse_health(payload: dict) -> list[Sample]:
    """Translate /api/health/all into latency + online samples.

    CRITICAL (design §4/§7.2): samples whose health entry has ``cached == true``
    are discarded so latency trends reflect real requests only, not cache echoes.
    """
    samples: list[Sample] = []
    for key, entry in payload.items():
        if not isinstance(entry, dict):
            continue
        online = 1.0 if entry.get("online") else 0.0
        samples.append((f"service.{key}.online", key, online))
        # Discard cached echoes — they carry latency 0 and dilute the trend.
        if entry.get("cached"):
            continue
        latency = entry.get("latency_ms")
        if latency is not None:
            samples.append((f"service.{key}.latency_ms", key, float(latency)))
    return samples


async def sample_health(
    client: httpx.AsyncClient, url: str = BACKEND_HEALTH_URL
) -> list[Sample]:
    """Pull the backend health snapshot and parse it into samples."""
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        return parse_health(resp.json())
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("health sampler failed: %s", exc)
        return []


# ═══════════════════════════════════════════════════════════════════════════════
# Collector loop
# ═══════════════════════════════════════════════════════════════════════════════
class Collector:
    """Owns the ring buffer, SQLite store and the periodic asyncio tasks."""

    def __init__(
        self,
        ring: RingBuffer | None = None,
        store: SqliteStore | None = None,
        alert_engine: AlertEngine | None = None,
    ) -> None:
        self.ring = ring if ring is not None else RingBuffer()
        self.store = store if store is not None else SqliteStore()
        # Alert engine shares the ring buffer (reads hi-res samples) and its own
        # SQLite tables in the SAME DB file as the metrics store, so tests that
        # inject a temp-path store transparently get a temp-path alert store too.
        self.alert_engine = (
            alert_engine
            if alert_engine is not None
            else AlertEngine(self.ring, AlertStore(self.store.db_path))
        )
        self.last_tick_ts: float | None = None
        self._last_rollup_bucket: int | None = None
        self._tasks: list[asyncio.Task] = []
        self._client: httpx.AsyncClient | None = None

    # ── Single tick ───────────────────────────────────────────────────────────
    async def tick(self) -> list[Sample]:
        """Run one collection cycle and append all samples to the ring buffer."""
        ts = int(time.time())
        samples: list[Sample] = []

        # Host sampling is blocking (file reads + a short sleep); run it off the
        # event loop so the collector does not stall other tasks.
        samples.extend(await asyncio.to_thread(sample_host))

        if self._client is not None:
            docker_samples, health_samples = await asyncio.gather(
                sample_docker(self._client),
                sample_health(self._client),
            )
            samples.extend(docker_samples)
            samples.extend(health_samples)

        self.ring.add_batch(samples, ts)
        self.last_tick_ts = time.monotonic()

        # Evaluate alert rules against the freshly-updated ring buffer. Failures
        # here must never kill the collection loop, so swallow + log.
        if ALERTS_ENABLED:
            try:
                self.alert_engine.evaluate_tick(now=ts)
            except Exception:
                logger.exception("alert evaluation failed")

        return samples

    # ── Rollup ──────────────────────────────────────────────────────────────────
    def rollup(self, now: int | None = None) -> int:
        """Average the last completed rollup window into SQLite.

        Returns the number of rows written. Idempotent per bucket: calling it
        twice for the same window re-writes (INSERT OR REPLACE) the same rows.
        """
        now = int(time.time()) if now is None else now
        bucket = (now // ROLLUP_INTERVAL_S) * ROLLUP_INTERVAL_S
        start = bucket - ROLLUP_INTERVAL_S  # roll up the *previous* complete window
        window = self.ring.window(start, bucket)
        rows: list[tuple[str, str, float, float]] = []
        for (metric, label), values in window.items():
            avg = sum(values) / len(values)
            rows.append((metric, label, round(avg, 2), round(max(values), 2)))
        written = self.store.write_rollup(start, rows)
        self._last_rollup_bucket = start
        return written

    # ── Background loops ──────────────────────────────────────────────────────
    async def _collect_loop(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:
                logger.exception("collector tick failed")
            await asyncio.sleep(COLLECT_INTERVAL_S)

    async def _rollup_loop(self) -> None:
        while True:
            await asyncio.sleep(ROLLUP_INTERVAL_S)
            try:
                self.rollup()
            except Exception:
                logger.exception("rollup failed")

    async def _prune_loop(self) -> None:
        while True:
            await asyncio.sleep(PRUNE_INTERVAL_S)
            try:
                await asyncio.to_thread(self.store.prune)
            except Exception:
                logger.exception("prune failed")
            try:
                await asyncio.to_thread(
                    self.alert_engine.store.prune_history,
                    ALERT_HISTORY_RETENTION_DAYS,
                )
            except Exception:
                logger.exception("alert history prune failed")

    async def start(self) -> None:
        """Open the HTTP client and spawn the background tasks."""
        self._client = httpx.AsyncClient(timeout=HTTP_TIMEOUT_S)
        # Wire the Telegram notifier from the live environment and rehydrate the
        # active-alert set so a restart does not re-spam already-firing alerts.
        if ALERTS_ENABLED:
            try:
                notifier = _make_notifier()
                self.alert_engine.notifier = notifier
                if not notifier.enabled:
                    logger.warning(
                        "Alerts enabled but Telegram notifier is unconfigured "
                        "(no TELEGRAM_BOT_TOKEN/CHAT_IDS) — alerts will fire and "
                        "persist but no message will be sent"
                    )
            except Exception:
                logger.exception("failed to initialise Telegram notifier")
            try:
                self.alert_engine.load_state()
            except Exception:
                logger.exception("failed to load persisted alert state")
        self._tasks = [
            asyncio.create_task(self._collect_loop()),
            asyncio.create_task(self._rollup_loop()),
            asyncio.create_task(self._prune_loop()),
        ]
        logger.info("Collector started (interval=%ds)", COLLECT_INTERVAL_S)

    async def stop(self) -> None:
        """Cancel background tasks and close the HTTP client."""
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._tasks = []
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        logger.info("Collector stopped")

    # ── Diagnostics ─────────────────────────────────────────────────────────────
    def last_tick_age_s(self) -> float | None:
        """Seconds since the last successful tick, or None if never ticked."""
        if self.last_tick_ts is None:
            return None
        return round(time.monotonic() - self.last_tick_ts, 1)
