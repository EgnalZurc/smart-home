# energy-monitor

Shelly EM power/energy time-series collector for the smart-home platform.
Infrastructure service — not user-facing, not in `CONTROLLABLE_CONTAINERS`,
not exposed through nginx. Reached only via the backend proxy under
`/api/energy/*`. Design: `docs/designs/energy-monitor-design.md`.

> Status: **scaffold**. This commit stands up the FastAPI app, SQLite store and
> health surface. The Shelly polling collector, alert engine and full read API
> (`/api/energy/power`, `/consumption`, `/summary`, `/alerts`, `/thresholds`)
> land in later tasks.

## Layout

```
services/energy-monitor/
  Dockerfile              # multi-stage, build context = repo root (needs libs/)
  requirements.txt        # fastapi, uvicorn, httpx (+ pytest, pytest-asyncio)
  pytest.ini
  settings.example.toml   # documents every ENERGY_* tunable
  src/
    main.py               # FastAPI app + lifespan + health + /api/energy/current stub
    config.py             # all env-var tunables (single source of truth)
    database.py           # EnergyStore (SQLite): power_samples / energy_readings / energy_alerts
  tests/
    test_api.py           # health + stub endpoint
    test_database.py      # schema, writes, reads, retention prune
    test_config.py        # defaults + env overrides
```

## Endpoints (`:8012`)

| Endpoint | Purpose |
|----------|---------|
| `GET /health` | `{online, service, db_ok, meter_online, collector_last_tick_age_s}` |
| `GET /api/health/energy` | health alias for the dashboard catalogue / CI |
| `GET /api/energy/current` | newest power per channel (empty until the collector lands) |

`meter_online` / `collector_last_tick_age_s` report `null` in the scaffold and
turn informative once the collector is wired in.

## Configuration

All tunables are environment variables read in `src/config.py`; see
`settings.example.toml` for the full list and defaults. Key ones:

- `ENERGY_PORT` (8012), `ENERGY_POLL_INTERVAL_S` (10)
- `ENERGY_DB_PATH` (`/app/data/energy.db`)
- `ENERGY_DEVICES` — Shelly inventory as JSON
- `ENERGY_TARIFF_MODE` / `ENERGY_PRICE_EUR_KWH`
- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_IDS` — alert delivery (optional)

## Run tests (as CI does)

```bash
pip install -r services/energy-monitor/requirements.txt
pip install -e libs/smart_home_common
cd services/energy-monitor && PYTHONPATH=src python -m pytest tests/ -v \
  --cov=src --cov-report=term-missing --cov-fail-under=80
```

## Deploy

Image `egnal/smart-home-energy-monitor:latest`, 64 MB mem limit, bind mount
`./data/energy-monitor:/app/data`. The CI deploy step `mkdir -p` + `chown
1000:1000` the data dir **before** `docker compose up` so the non-root
container can create its SQLite DB (`db_ok=true`).
