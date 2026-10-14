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

## Docker Socket Proxy dependency

metrics-service queries Docker container stats via **docker-socket-proxy**
(tecnativa/docker-socket-proxy) on port 2375 inside the `smart-home` network.
This avoids mounting `/var/run/docker.sock` directly into the container, which
would grant full Docker control.

### Required proxy permissions

The proxy is configured in `docker-compose.prod.yml` with least-privilege:

| Variable | Value | Why |
|----------|-------|-----|
| `CONTAINERS` | `1` | List containers, inspect stats (`/containers/json`, `/containers/{id}/stats`) |
| `POST` | `1` | Required for stats stream (POST to `/containers/{id}/stats`) |
| `IMAGES` | `0` | Not needed — we don't pull/list images |
| `INFO` | `0` | Not needed — no Docker host info |
| `NETWORKS` | `0` | Not needed — no network inspection |
| `VOLUMES` | `0` | Not needed — no volume inspection |
| `EXEC` | `0` | **Security**: no exec into containers |
| `DELETE` | `0` | **Security**: cannot delete containers |
| `BUILD` | `0` | **Security**: cannot build images |
| All others | `0` | Deny by default |

### Security notes

1. **Read-only access**: metrics-service only reads container stats; it cannot
   start, stop, delete, or exec into containers.
2. **Network-isolated**: docker-socket-proxy is only reachable inside the
   `smart-home` Docker network, not from the host or external networks.
3. **Socket mounted read-only**: The proxy mounts `/var/run/docker.sock:ro`.
4. **No sensitive env vars**: The collector never reads environment variables
   from containers — only CPU/memory stats.

### /proc and /sys mounts

metrics-service also mounts the Pi host's `/proc` and `/sys` read-only to sample
host metrics (CPU, RAM, temp, load). These are bind-mounted as:

```yaml
volumes:
  - /proc:/host/proc:ro
  - /sys:/host/sys:ro
```

Environment variables point the host sampler to these paths:

- `METRICS_PROC_STAT=/host/proc/stat`
- `METRICS_PROC_MEMINFO=/host/proc/meminfo`
- `METRICS_PROC_LOADAVG=/host/proc/loadavg`
- `METRICS_THERMAL_ZONE=/host/sys/class/thermal/thermal_zone0/temp`

Read-only mounts ensure the service cannot modify host kernel state.

## Resource budget

`mem_limit: 64m`. One 30 s tick does a few HTTP GETs + file reads + deque
appends; effectively idle. SQLite ≈ 23 MB on disk for 30 days of 45 series.
