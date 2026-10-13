"""Configuration for metrics-service, read from environment variables.

All tunables live here so the collector, storage and samplers import a single
source of truth. Defaults match the design document (Wave 3.1b).
"""

from __future__ import annotations

import os

# ── Logging ──────────────────────────────────────────────────────────────────
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

# ── Service ──────────────────────────────────────────────────────────────────
SERVICE_NAME = "metrics-service"
PORT = int(os.environ.get("METRICS_PORT", "8011"))

# ── Collector cadence ────────────────────────────────────────────────────────
# One tick every COLLECT_INTERVAL_S seconds (design: 30 s). Kept >= the health
# cache TTL (5 s) so most ticks hit a real health check, not a cache echo.
COLLECT_INTERVAL_S = int(os.environ.get("METRICS_COLLECT_INTERVAL_S", "30"))

# ── Ring buffer (tier 1) ─────────────────────────────────────────────────────
# 240 samples * 30 s = 2 h of hi-resolution history per series.
RING_BUFFER_MAXLEN = int(os.environ.get("METRICS_RING_BUFFER_MAXLEN", "240"))

# ── SQLite (tier 2) ──────────────────────────────────────────────────────────
DB_PATH = os.environ.get("METRICS_DB_PATH", "/app/data/metrics.db")
# Rollup window in seconds (design: 5 min averages).
ROLLUP_INTERVAL_S = int(os.environ.get("METRICS_ROLLUP_INTERVAL_S", "300"))
# Retention in days for rolled-up rows (design: 30 days).
RETENTION_DAYS = int(os.environ.get("METRICS_RETENTION_DAYS", "30"))
# Prune cadence in seconds (design: daily).
PRUNE_INTERVAL_S = int(os.environ.get("METRICS_PRUNE_INTERVAL_S", str(24 * 3600)))

# ── Host sampler paths (overridable for tests) ───────────────────────────────
PROC_STAT = os.environ.get("METRICS_PROC_STAT", "/proc/stat")
PROC_MEMINFO = os.environ.get("METRICS_PROC_MEMINFO", "/proc/meminfo")
PROC_LOADAVG = os.environ.get("METRICS_PROC_LOADAVG", "/proc/loadavg")
THERMAL_ZONE = os.environ.get(
    "METRICS_THERMAL_ZONE", "/sys/class/thermal/thermal_zone0/temp"
)
DISK_PATH = os.environ.get("METRICS_DISK_PATH", "/")
# CPU sample window (seconds) — short sleep to compute a jiffy delta.
CPU_SAMPLE_WINDOW_S = float(os.environ.get("METRICS_CPU_SAMPLE_WINDOW_S", "0.5"))

# ── Docker sampler ───────────────────────────────────────────────────────────
DOCKER_PROXY_URL = os.environ.get(
    "METRICS_DOCKER_PROXY_URL", "http://docker-socket-proxy:2375"
)

# ── Health sampler ───────────────────────────────────────────────────────────
BACKEND_HEALTH_URL = os.environ.get(
    "METRICS_BACKEND_HEALTH_URL", "http://smart-home-backend:8080/api/health/all"
)

# ── HTTP timeouts ────────────────────────────────────────────────────────────
HTTP_TIMEOUT_S = float(os.environ.get("METRICS_HTTP_TIMEOUT_S", "5.0"))
