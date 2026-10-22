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
import sqlite3
import time
from typing import Any

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
    DOCKER_STATS_CONCURRENCY,
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


def _make_notifier() -> Any:
    """Build a TelegramNotifier from the environment, tolerating import layout.

    In the container ``/app/libs`` is on ``sys.path`` (set by ``main.py`` /
    ``LIBS_PATH``), so ``notifications`` is a top-level package. Under pytest the
    repo root is on ``sys.path`` instead, so the package is ``libs.notifications``.
    Try both so the engine is wired identically in prod and in tests.

    Returns:
        TelegramNotifier: Configured notifier instance (may be disabled if env
            vars are missing).

    Raises:
        ImportError: If neither import path resolves (broken installation).
    """
    try:
        from notifications import TelegramNotifier
    except ImportError:  # pragma: no cover - exercised only under pytest layout
        from libs.notifications import TelegramNotifier
    return TelegramNotifier.from_env()


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# Host sampler (ported from dashboard/src/system/stats.py)
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
def _read_cpu_times(path: str | None = None) -> tuple[float, float]:
    """Read CPU jiffies from /proc/stat for CPU usage calculation.

    Parses the first line of /proc/stat to extract total and idle CPU time.
    The idle time includes both idle and iowait jiffies.

    Args:
        path: Override path to /proc/stat (for testing with fixture files).
            Defaults to PROC_STAT from config.

    Returns:
        A tuple of (total_jiffies, idle_jiffies) as floats.

    Raises:
        FileNotFoundError: If the stat file does not exist.
        ValueError: If the file format is unexpected.
    """
    path = path if path is not None else PROC_STAT
    with open(path) as fh:
        line = fh.readline()
    fields = [float(x) for x in line.split()[1:]]
    idle = fields[3] + (fields[4] if len(fields) > 4 else 0)
    total = sum(fields)
    return total, idle


def _read_meminfo(path: str | None = None) -> dict[str, int]:
    """Parse /proc/meminfo into a dictionary of memory values.

    Reads all entries from /proc/meminfo and returns them as a dict mapping
    field names (without colons) to their values in kilobytes.

    Args:
        path: Override path to /proc/meminfo (for testing with fixture files).
            Defaults to PROC_MEMINFO from config.

    Returns:
        Dict mapping field names to values in kB, e.g.
        {"MemTotal": 8167952, "MemFree": 234567, ...}.

    Raises:
        FileNotFoundError: If the meminfo file does not exist.
    """
    path = path if path is not None else PROC_MEMINFO
    mem: dict[str, int] = {}
    with open(path) as fh:
        for line in fh:
            parts = line.split()
            if len(parts) >= 2:
                mem[parts[0].rstrip(":")] = int(parts[1])
    return mem


def sample_memory(path: str | None = None) -> list[Sample]:
    """Collect RAM and swap usage metrics from /proc/meminfo.

    Calculates used memory following the same algorithm as ``free -m``:
    used = total - free - buffers - cached (excluding shared memory).

    Args:
        path: Override path to /proc/meminfo (for testing with fixture files).
            Defaults to PROC_MEMINFO from config.

    Returns:
        List of Sample tuples:
        - ("host.ram.used_mb", "", <float>): Used RAM in megabytes
        - ("host.ram.percent", "", <float>): RAM usage as percentage
        - ("host.swap.used_mb", "", <float>): Used swap in megabytes

    Raises:
        FileNotFoundError: If /proc/meminfo is not accessible.
    """
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
    """Collect host CPU usage percentage using a jiffy-delta measurement.

    Measures CPU usage by reading /proc/stat twice with a short sleep window
    between reads, then calculating the percentage of non-idle time.

    Note:
        This function blocks for ``window_s`` seconds (default 0.1s from config).
        In async contexts, run via ``asyncio.to_thread()``.

    Args:
        path: Override path to /proc/stat (for testing with fixture files).
            Defaults to PROC_STAT from config.
        window_s: Measurement window duration in seconds.
            Defaults to CPU_SAMPLE_WINDOW_S from config.

    Returns:
        List containing a single Sample tuple:
        - ("host.cpu.percent", "", <float>): CPU usage as percentage (0-100)

    Raises:
        FileNotFoundError: If /proc/stat is not accessible.
    """
    window_s = window_s if window_s is not None else CPU_SAMPLE_WINDOW_S
    t1, i1 = _read_cpu_times(path)
    time.sleep(window_s)
    t2, i2 = _read_cpu_times(path)
    dt = t2 - t1
    di = i2 - i1
    cpu_pct = round((1.0 - di / dt) * 100, 1) if dt > 0 else 0.0
    return [("host.cpu.percent", "", cpu_pct)]


def sample_disk(path: str | None = None) -> list[Sample]:
    """Collect host disk usage percentage using statvfs.

    Reads filesystem statistics for the configured disk path and calculates
    the percentage of used space (total - available for unprivileged users).

    Args:
        path: Filesystem path to measure. Defaults to DISK_PATH from config
            (typically "/" on the Pi).

    Returns:
        List containing a single Sample tuple:
        - ("host.disk.percent", "", <float>): Disk usage as percentage (0-100)

    Raises:
        OSError: If the path is not accessible or not a mounted filesystem.
    """
    path = path if path is not None else DISK_PATH
    sv = os.statvfs(path)
    total_b = sv.f_frsize * sv.f_blocks
    free_b = sv.f_frsize * sv.f_bavail
    used_b = total_b - free_b
    pct = round(used_b / total_b * 100, 1) if total_b else 0.0
    return [("host.disk.percent", "", pct)]


def sample_temp(path: str | None = None) -> list[Sample]:
    """Collect SoC temperature from the thermal zone file.

    Reads the CPU/SoC temperature from the Linux thermal subsystem. The raw
    value is in millidegrees Celsius and is converted to degrees.

    Args:
        path: Override path to thermal zone file (for testing).
            Defaults to THERMAL_ZONE from config
            (typically /sys/class/thermal/thermal_zone0/temp).

    Returns:
        List containing a single Sample tuple:
        - ("host.temp.celsius", "", <float>): Temperature in degrees Celsius

    Raises:
        FileNotFoundError: If the thermal zone file does not exist.
        ValueError: If the file content is not a valid integer.
    """
    path = path if path is not None else THERMAL_ZONE
    with open(path) as fh:
        raw = int(fh.read().strip())
    return [("host.temp.celsius", "", round(raw / 1000, 1))]


def sample_load(path: str | None = None) -> list[Sample]:
    """Collect the 1-minute load average from /proc/loadavg.

    Reads the system load average, which represents the average number of
    processes in the run queue over the last minute.

    Args:
        path: Override path to /proc/loadavg (for testing with fixture files).
            Defaults to PROC_LOADAVG from config.

    Returns:
        List containing a single Sample tuple:
        - ("host.load.1m", "", <float>): 1-minute load average

    Raises:
        FileNotFoundError: If /proc/loadavg is not accessible.
    """
    path = path if path is not None else PROC_LOADAVG
    with open(path) as fh:
        first = fh.read().split()[0]
    return [("host.load.1m", "", float(first))]


def sample_host(*, with_cpu: bool = True) -> list[Sample]:
    """Collect all host-level metrics, tolerating individual sampler failures.

    Aggregates samples from memory, disk, temperature, and load samplers.
    If any individual sampler fails, its error is logged and the remaining
    samplers continue to execute.

    Args:
        with_cpu: If True, include CPU sampling (which blocks for ~0.1s).
            Set to False for faster collection when CPU data is not needed.

    Returns:
        List of Sample tuples from all successful samplers. May be empty if
        all samplers fail.

    Side Effects:
        Logs warnings for any sampler that raises an exception.
    """
    samples: list[Sample] = []
    samplers = [sample_memory, sample_disk, sample_temp, sample_load]
    if with_cpu:
        samplers.insert(1, sample_cpu)
    for fn in samplers:
        try:
            samples.extend(fn())
        except (OSError, ValueError) as exc:
            logger.warning("[HostSampler] %s collection failed: %s", fn.__name__, exc)
    return samples


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# Docker sampler (pull from docker-socket-proxy)
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
def _cpu_percent_from_stats(stats: dict[str, Any]) -> float:
    """Compute container CPU percentage from a Docker stats payload.

    Uses the same algorithm as ``docker stats`` to calculate CPU usage from
    the delta between current and previous CPU readings in the stats JSON.

    Args:
        stats: Docker stats JSON payload (from /containers/{id}/stats with
            stream=false). Must contain cpu_stats and precpu_stats keys.

    Returns:
        CPU usage as a percentage (0-100+, may exceed 100 on multi-core).
        Returns 0.0 if the payload is malformed or deltas are zero.
    """
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


def parse_container_stats(name: str, stats: dict[str, Any]) -> list[Sample]:
    """Translate a container's Docker stats payload into metric samples.

    Extracts memory usage (excluding page cache, like ``docker stats``) and
    CPU percentage from the Docker stats JSON.

    Args:
        name: Container name (used as the sample label).
        stats: Docker stats JSON payload from /containers/{id}/stats.

    Returns:
        List of Sample tuples:
        - ("container.mem.used_mb", <name>, <float>): Memory usage in MB
        - ("container.mem.percent", <name>, <float>): Memory as % of limit
        - ("container.cpu.percent", <name>, <float>): CPU usage percentage
    """
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


async def _fetch_container_stats(
    client: httpx.AsyncClient,
    proxy_url: str,
    cid: str,
    name: str,
    semaphore: asyncio.Semaphore,
) -> list[Sample]:
    """Fetch stats for a single container, respecting the concurrency semaphore.

    Args:
        client: httpx.AsyncClient instance for making HTTP requests.
        proxy_url: Base URL of the docker-socket-proxy service.
        cid: Container ID.
        name: Container name (for labeling samples).
        semaphore: Semaphore to limit concurrent requests.

    Returns:
        List of Sample tuples for this container, or empty list on failure.
    """
    async with semaphore:
        try:
            r = await client.get(f"{proxy_url}/containers/{cid}/stats?stream=false")
            r.raise_for_status()
            return parse_container_stats(name, r.json())
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning(
                "[DockerSampler] Stats collection failed for '%s': %s", name, exc
            )
            return []


async def sample_docker(
    client: httpx.AsyncClient, proxy_url: str = DOCKER_PROXY_URL
) -> list[Sample]:
    """Pull per-container metrics from docker-socket-proxy.

    Discovers running containers dynamically via ``GET /containers/json``,
    then fetches stats for each container in parallel (bounded by
    DOCKER_STATS_CONCURRENCY) to reduce total collection time.

    Args:
        client: httpx.AsyncClient instance for making HTTP requests.
        proxy_url: Base URL of the docker-socket-proxy service.
            Defaults to DOCKER_PROXY_URL from config.

    Returns:
        List of Sample tuples for all containers (memory and CPU metrics).
        Returns empty list if the container list cannot be retrieved.

    Side Effects:
        Logs warnings if listing containers or fetching individual stats fails.
    """
    try:
        resp = await client.get(f"{proxy_url}/containers/json")
        resp.raise_for_status()
        containers = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("[DockerSampler] Container list failed: %s", exc)
        return []

    # Build list of (cid, name) pairs to fetch
    targets: list[tuple[str, str]] = []
    for c in containers:
        cid = c.get("Id")
        if not cid:
            continue
        names = c.get("Names") or []
        name = names[0].lstrip("/") if names else cid[:12]
        targets.append((cid, name))

    if not targets:
        return []

    # Fetch all container stats in parallel with bounded concurrency
    semaphore = asyncio.Semaphore(DOCKER_STATS_CONCURRENCY)
    tasks = [
        _fetch_container_stats(client, proxy_url, cid, name, semaphore)
        for cid, name in targets
    ]
    results = await asyncio.gather(*tasks)

    # Flatten results
    samples: list[Sample] = []
    for result in results:
        samples.extend(result)
    return samples


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# Health sampler (pull from backend /api/health/all)
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
def parse_health(payload: dict[str, Any]) -> list[Sample]:
    """Translate /api/health/all response into latency and online samples.

    Converts the backend health snapshot into time-series samples for each
    monitored service. Cached entries are excluded from latency samples to
    ensure trends reflect real request times.

    CRITICAL (design Â§4/Â§7.2): Samples whose health entry has ``cached == true``
    are discarded so latency trends reflect real requests only, not cache echoes.

    Args:
        payload: JSON response from /api/health/all, mapping service keys to
            health entries like {"online": true, "latency_ms": 42, "cached": false}.

    Returns:
        List of Sample tuples:
        - ("service.<key>.online", <key>, 1.0|0.0): Service availability
        - ("service.<key>.latency_ms", <key>, <float>): Response time (if not cached)
    """
    samples: list[Sample] = []
    for key, entry in payload.items():
        if not isinstance(entry, dict):
            continue
        online = 1.0 if entry.get("online") else 0.0
        samples.append((f"service.{key}.online", key, online))
        # Discard cached echoes â€” they carry latency 0 and dilute the trend.
        if entry.get("cached"):
            continue
        latency = entry.get("latency_ms")
        if latency is not None:
            samples.append((f"service.{key}.latency_ms", key, float(latency)))
    return samples


async def sample_health(
    client: httpx.AsyncClient, url: str = BACKEND_HEALTH_URL
) -> list[Sample]:
    """Pull the backend health snapshot and convert to metric samples.

    Fetches the aggregated health status from the dashboard backend and
    transforms it into time-series samples for storage and alerting.

    Args:
        client: httpx.AsyncClient instance for making HTTP requests.
        url: Health endpoint URL. Defaults to BACKEND_HEALTH_URL from config.

    Returns:
        List of Sample tuples for service availability and latency.
        Returns empty list if the health endpoint is unreachable.

    Side Effects:
        Logs a warning if the health endpoint request fails.
    """
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        return parse_health(resp.json())
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("[HealthSampler] Health snapshot fetch failed: %s", exc)
        return []


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# Collector loop
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
class Collector:
    """Orchestrates metric collection, storage, and background processing.

    Owns the ring buffer (tier-1 hi-res storage), SQLite store (tier-2 rollups),
    and the alert engine. Manages three background asyncio tasks:
    - Collection loop: samples host/docker/health every COLLECT_INTERVAL_S
    - Rollup loop: aggregates ring buffer into SQLite every ROLLUP_INTERVAL_S
    - Prune loop: removes old data every PRUNE_INTERVAL_S

    Attributes:
        ring: RingBuffer for high-resolution recent samples.
        store: SqliteStore for rolled-up historical data.
        alert_engine: AlertEngine for threshold evaluation and notifications.
        last_tick_ts: Monotonic timestamp of the last successful tick.
    """

    def __init__(
        self,
        ring: RingBuffer | None = None,
        store: SqliteStore | None = None,
        alert_engine: AlertEngine | None = None,
    ) -> None:
        """Initialize the collector with optional dependency injection.

        Args:
            ring: RingBuffer instance. Created with defaults if not provided.
            store: SqliteStore instance. Created with defaults if not provided.
            alert_engine: AlertEngine instance. Created with store's DB path
                if not provided.
        """
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
        self._tasks: list[asyncio.Task[None]] = []
        self._client: httpx.AsyncClient | None = None

    # â”€â”€ Single tick â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    async def tick(self) -> list[Sample]:
        """Execute one collection cycle and store all samples.

        Collects host metrics (in a thread to avoid blocking), Docker stats,
        and health data concurrently. All samples are added to the ring buffer
        with the current timestamp.

        Returns:
            List of all Sample tuples collected in this tick.

        Side Effects:
            - Appends samples to the ring buffer
            - Updates last_tick_ts
            - Evaluates alert rules (if ALERTS_ENABLED)
            - Logs exceptions from alert evaluation
        """
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
                logger.exception("[Collector] Alert evaluation failed")

        return samples

    # â”€â”€ Rollup â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def rollup(self, now: int | None = None) -> int:
        """Aggregate the last completed window from ring buffer into SQLite.

        Computes average and maximum values for each metric series in the
        previous ROLLUP_INTERVAL_S window and writes them to the SQLite store.

        Args:
            now: Unix timestamp to use as "current time". Defaults to time.time().
                Useful for testing with controlled timestamps.

        Returns:
            Number of rows written to SQLite.

        Note:
            Idempotent per bucket: calling twice for the same window re-writes
            (INSERT OR REPLACE) the same rows.
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

    # â”€â”€ Background loops â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    async def _collect_loop(self) -> None:
        """Background task: run tick() every COLLECT_INTERVAL_S."""
        while True:
            try:
                await self.tick()
            except Exception:
                logger.exception("[Collector] Tick execution failed")
            await asyncio.sleep(COLLECT_INTERVAL_S)

    async def _rollup_loop(self) -> None:
        """Background task: run rollup() every ROLLUP_INTERVAL_S."""
        while True:
            await asyncio.sleep(ROLLUP_INTERVAL_S)
            try:
                self.rollup()
            except sqlite3.Error:
                logger.exception("[Collector] Rollup execution failed")

    async def _prune_loop(self) -> None:
        """Background task: prune old data every PRUNE_INTERVAL_S."""
        while True:
            await asyncio.sleep(PRUNE_INTERVAL_S)
            try:
                await asyncio.to_thread(self.store.prune)
            except sqlite3.Error:
                logger.exception("[Collector] Metrics prune failed")
            try:
                await asyncio.to_thread(
                    self.alert_engine.store.prune_history,
                    ALERT_HISTORY_RETENTION_DAYS,
                )
            except sqlite3.Error:
                logger.exception("[Collector] Alert history prune failed")

    async def start(self) -> None:
        """Initialize the HTTP client and spawn background tasks.

        Opens the shared httpx client for Docker/health requests and starts
        the collection, rollup, and prune background tasks.

        Side Effects:
            - Creates self._client
            - Initializes Telegram notifier (if ALERTS_ENABLED)
            - Loads persisted alert state
            - Spawns three asyncio tasks stored in self._tasks
            - Logs startup message
        """
        self._client = httpx.AsyncClient(timeout=HTTP_TIMEOUT_S)
        # Wire the Telegram notifier from the live environment and rehydrate the
        # active-alert set so a restart does not re-spam already-firing alerts.
        if ALERTS_ENABLED:
            try:
                notifier = _make_notifier()
                self.alert_engine.notifier = notifier
                if not notifier.enabled:
                    logger.warning(
                        "[Collector] Alerts enabled but Telegram notifier is "
                        "unconfigured (no TELEGRAM_BOT_TOKEN/CHAT_IDS) â€” alerts "
                        "will fire and persist but no message will be sent"
                    )
            except Exception:
                logger.exception("[Collector] Telegram notifier initialization failed")
            try:
                self.alert_engine.load_state()
            except sqlite3.Error:
                logger.exception("[Collector] Alert state load failed")
        self._tasks = [
            asyncio.create_task(self._collect_loop()),
            asyncio.create_task(self._rollup_loop()),
            asyncio.create_task(self._prune_loop()),
        ]
        logger.info("[Collector] Started (interval=%ds)", COLLECT_INTERVAL_S)

    async def stop(self) -> None:
        """Cancel background tasks and close the HTTP client.

        Gracefully shuts down all background tasks and releases the HTTP
        client resources.

        Side Effects:
            - Cancels all tasks in self._tasks
            - Closes self._client
            - Logs shutdown message
        """
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
        logger.info("[Collector] Stopped")

    # â”€â”€ Diagnostics â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def last_tick_age_s(self) -> float | None:
        """Return seconds since the last successful tick.

        Useful for health checks to detect stalled collection.

        Returns:
            Seconds since last tick (rounded to 1 decimal), or None if the
            collector has never completed a tick.
        """
        if self.last_tick_ts is None:
            return None
        return round(time.monotonic() - self.last_tick_ts, 1)
