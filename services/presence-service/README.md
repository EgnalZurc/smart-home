# presence-service

Multi-signal household **presence detection** for the Cuchi Casa platform. Fuses
three independent weak signals into one per-person state with a confidence score:

- **Router / ARP** (owned MAC on the LAN) — primary home/away signal.
- **BLE beacons** (ESP32 → MQTT) — corroborate + fill the WiFi-sleep gap.
- **Zigbee motion** (`zigbee2mqtt` → MQTT) — anonymous house occupancy + sleep.

It publishes presence to MQTT (`presence/<person>/state`,
`presence/house/occupancy`) for `ac-service` and future automations, and drives
Telegram arrival/departure notifications via `libs/notifications`.

See the full design in
[`docs/designs/presence-service-design.md`](../../docs/designs/presence-service-design.md).

> **Status: scaffold.** This directory currently ships the service skeleton —
> FastAPI app, DB-backed health endpoint, SQLite schema (people/devices/beacons/
> zones + current snapshot + transition history) and the domain models. The
> inference engine, MQTT handler, router poller, notifier and the read/config
> API land in later tasks.

## Classification

Infrastructure-style background service with a (future) user-facing config SPA.
Served on `:8013`, reachable only through the backend proxy under
`/api/presence/*` (SUPER-gated); the browser never talks to `:8013` directly.
Final tile classification (controllable vs infra) is an open review question —
see design §10.1.

## Endpoints (scaffold)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | `{online, service, db_ok, router_online, mqtt_online, last_tick_age_s}` |
| `/api/health/presence` | GET | health alias for the dashboard catalogue / CI |

Interactive docs at `/swagger`.

## Configuration

All tunables are environment variables (prefixed `PRESENCE_`); see
[`src/config.py`](src/config.py) and [`settings.example.toml`](settings.example.toml)
for every knob and its default. People/devices/beacons/zones are **data**, stored
in SQLite and managed via the config API (seeded from `PRESENCE_PEOPLE_SEED` on
first run). Secrets (router password/SSH key, Telegram token) live only in `.env`
and are never logged.

### Bind-mount permissions (deploy trap)

The host dir `./data/presence-service` must exist and be owned by UID 1000
**before** `docker compose up`, or the non-root container cannot create its
SQLite DB (`db_ok=false`). The CI deploy step creates it with the right owner.

## Privacy

Presence is the most privacy-sensitive service on the platform (design §12):
opt-in, owner-enrolled devices only; no biometrics/cameras; MAC/BLE IDs are PII
kept on-device, never logged (logs reference `person_id` slugs); only discrete
home/away transitions are retained (1 year), never a continuous location trail;
a per-person pause switch is provided.

## Development

Build and test only in the CI-equivalent dev container (never on the host):

```powershell
# From the repo root
.\dev.ps1 ci presence-service    # reproduce CI lint + test
```

Tests run as in CI — from the service directory with `PYTHONPATH=src`:

```bash
cd services/presence-service && PYTHONPATH=src python -m pytest tests/
```
