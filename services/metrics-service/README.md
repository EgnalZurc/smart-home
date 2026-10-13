# metrics-service

Infrastructure service that collects Pi **host metrics**, per-container **Docker
stats** and **service-health latency** into a time-series store with retention,
and exposes a read API the dashboard polls to render trend widgets.

Design: `.kiro/designs/metrics-service-design.md` (Wave 3.1a). This is the
Wave 3.1b implementation (phases 1–5: skeleton, host sampler + ring buffer,
SQLite rollup/prune, Docker + health samplers, backend proxy + CI).

## What it collects (every 30 s)

| Family | Metrics | Source |
|--------|---------|--------|
| Host | `host.cpu.percent`, `host.ram.used_mb`, `host.ram.percent`, `host.swap.used_mb`, `host.disk.percent`, `host.temp.celsius`, `host.load.1m` | `/proc`, `/sys` (bind-mounted RO), `statvfs` |
| Container | `container.mem.used_mb`, `container.mem.percent`, `container.cpu.percent` | docker-socket-proxy `:2375` (pull) |
| Service | `service.<key>.latency_ms`, `service.<key>.online` | backend `/api/health/all` (pull) |

Health samples with `cached == true` are **discarded** so latency trends reflect
real requests only (design §4/§7.2).

## Storage (two tiers)

- **Ring buffer** (in-memory): 240 points × 30 s = 2 h hi-resolution per series.
- **SQLite** (`/app/data/metrics.db`): 5-min avg/max rollup, 30-day retention
  (daily prune + WAL checkpoint). Uses `smart_home_common.sqlite_helpers`.

## API (port 8011)

Proxied through the backend under `/api/metrics/*` (SUPER-gated); the browser
never talks to `:8011` directly.

| Endpoint | Purpose |
|----------|---------|
| `GET /health` | `{online, service, db_ok, collector_last_tick_age_s}` |
| `GET /api/health/metrics` | health alias (dashboard catalogue / CI) |
| `GET /api/metrics/latest` | newest sample per series (ring buffer) |
| `GET /api/metrics/series?metric=&label=&since=&until=&resolution=hi\|rollup` | one time-ranged series |
| `GET /api/metrics/summary?window=1h\|24h\|7d\|30d` | min/avg/max per metric |

`since`/`until` accept a unix timestamp or a relative offset (`-1h`, `-30m`, `-7d`).

## Infrastructure classification

Not in `APP_CATALOGUE`, not in `CONTROLLABLE_CONTAINERS`, no nginx location —
same class as nginx/mosquitto. There is no service tile and no start/stop button.

## Local development

```powershell
# Full CI (ruff + format + bandit + hadolint + pytest, 80% coverage) in the dev container
.\dev.ps1 ci metrics-service
```

## Resource budget

`mem_limit: 64m`. One 30 s tick does a few HTTP GETs + file reads + deque
appends; effectively idle. SQLite ≈ 23 MB on disk for 30 days of 45 series.
