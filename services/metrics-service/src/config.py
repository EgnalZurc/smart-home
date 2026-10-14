"""Configuration for metrics-service, read from environment variables.

All tunables live here so the collector, storage and samplers import a single
source of truth. Defaults match the design document (Wave 3.1b).
"""

from __future__ import annotations

import os

# ── Logging ──────────────────────────────────────────────────────────────────
LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO").upper()

# ── Service ──────────────────────────────────────────────────────────────────
SERVICE_NAME: str = "metrics-service"
PORT: int = int(os.environ.get("METRICS_PORT", "8011"))

# ── Collector cadence ────────────────────────────────────────────────────────
# One tick every COLLECT_INTERVAL_S seconds (design: 30 s). Kept >= the health
# cache TTL (5 s) so most ticks hit a real health check, not a cache echo.
COLLECT_INTERVAL_S: int = int(os.environ.get("METRICS_COLLECT_INTERVAL_S", "30"))

# ── Ring buffer (tier 1) ─────────────────────────────────────────────────────
# 240 samples * 30 s = 2 h of hi-resolution history per series.
RING_BUFFER_MAXLEN: int = int(os.environ.get("METRICS_RING_BUFFER_MAXLEN", "240"))

# ── SQLite (tier 2) ──────────────────────────────────────────────────────────
DB_PATH: str = os.environ.get("METRICS_DB_PATH", "/app/data/metrics.db")
# Rollup window in seconds (design: 5 min averages).
ROLLUP_INTERVAL_S: int = int(os.environ.get("METRICS_ROLLUP_INTERVAL_S", "300"))
# Retention in days for rolled-up rows (design: 30 days).
RETENTION_DAYS: int = int(os.environ.get("METRICS_RETENTION_DAYS", "30"))
# Prune cadence in seconds (design: daily).
PRUNE_INTERVAL_S: int = int(os.environ.get("METRICS_PRUNE_INTERVAL_S", str(24 * 3600)))

# ── Host sampler paths (overridable for tests) ───────────────────────────────
PROC_STAT: str = os.environ.get("METRICS_PROC_STAT", "/proc/stat")
PROC_MEMINFO: str = os.environ.get("METRICS_PROC_MEMINFO", "/proc/meminfo")
PROC_LOADAVG: str = os.environ.get("METRICS_PROC_LOADAVG", "/proc/loadavg")
THERMAL_ZONE: str = os.environ.get(
    "METRICS_THERMAL_ZONE", "/sys/class/thermal/thermal_zone0/temp"
)
DISK_PATH: str = os.environ.get("METRICS_DISK_PATH", "/")
# CPU sample window (seconds) — short sleep to compute a jiffy delta.
CPU_SAMPLE_WINDOW_S: float = float(os.environ.get("METRICS_CPU_SAMPLE_WINDOW_S", "0.5"))

# ── Docker sampler ───────────────────────────────────────────────────────────
DOCKER_PROXY_URL: str = os.environ.get(
    "METRICS_DOCKER_PROXY_URL", "http://docker-socket-proxy:2375"
)

# ── Health sampler ───────────────────────────────────────────────────────────
BACKEND_HEALTH_URL: str = os.environ.get(
    "METRICS_BACKEND_HEALTH_URL", "http://smart-home-backend:8080/api/health/all"
)

# ── HTTP timeouts ────────────────────────────────────────────────────────────
HTTP_TIMEOUT_S: float = float(os.environ.get("METRICS_HTTP_TIMEOUT_S", "5.0"))

# ── Rate limiting (M-8) ──────────────────────────────────────────────────────
# Maximum requests per minute per IP for non-health endpoints.
MAX_REQUESTS_PER_MINUTE: int = int(
    os.environ.get("METRICS_MAX_REQUESTS_PER_MINUTE", "60")
)
# Window size in seconds for rate limit tracking.
RATE_LIMIT_WINDOW_S: int = int(os.environ.get("METRICS_RATE_LIMIT_WINDOW_S", "60"))

# ── Input validation (M-7) ───────────────────────────────────────────────────
# Maximum length for container names in API requests.
MAX_CONTAINER_NAME_LEN: int = 64
# Maximum length for metric names in API requests.
MAX_METRIC_NAME_LEN: int = 128

# ── Summary window presets (seconds) ─────────────────────────────────────────
SUMMARY_WINDOWS: dict[str, int] = {
    "1h": 3600,
    "24h": 86400,
    "7d": 604800,
    "30d": 2592000,
}

# ── Time offset multipliers (for relative since/until parsing) ───────────────
TIME_OFFSET_MULTIPLIERS: dict[str, int] = {
    "s": 1,
    "m": 60,
    "h": 3600,
    "d": 86400,
}

# ── Alerting (Wave 3.3) ──────────────────────────────────────────────────────
# Master switch for the alert engine. When off, the collector still samples but
# evaluate_tick is never called (useful to silence a noisy baseline week).
ALERTS_ENABLED: bool = (
    os.environ.get("METRICS_ALERTS_ENABLED", "true").lower() == "true"
)
# Retention for the alert_history audit trail (days). Longer than metrics so an
# alert postmortem outlives the 30-day metric window.
ALERT_HISTORY_RETENTION_DAYS: int = int(
    os.environ.get("METRICS_ALERT_HISTORY_RETENTION_DAYS", "90")
)
# Telegram delivery is driven by libs/notifications.TelegramNotifier.from_env(),
# which reads TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_IDS. If unset, the notifier is
# simply disabled (alerts still fire + persist, just no message is sent).
