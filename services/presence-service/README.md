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

### Network capabilities (ARP sweep mode)

When `PRESENCE_ROUTER_MODE=arpsweep` (the default), the service performs active
ARP scanning of the local subnet to detect device presence. This requires raw
socket access.

**Docker requirement:** The container must have `CAP_NET_RAW`:

```yaml
# docker-compose.prod.yml
presence-service:
  cap_add:
    - NET_RAW
```

**Alternative (not recommended):** Running the container as root also works, but
violates the principle of least privilege. The production compose uses `cap_add`
instead.

**Other router modes:** If using `openwrt_ssh`, `fritzbox`, or `mikrotik` modes,
the service queries the router via SSH/API and does not need `NET_RAW`.

### MQTT topic security

The service validates all MQTT topics at startup to prevent topic injection:

- **Subscription topics** (`BLE_TOPIC`, `MOTION_TOPIC`): Allow MQTT wildcards
  (`#`, `+`) for pattern matching, but reject other special characters.
- **Publish prefix** (`MQTT_PUBLISH_PREFIX`): Wildcards are **not** allowed to
  prevent injection into arbitrary topics.

Allowed characters: `a-zA-Z0-9/_-`. Invalid topics cause a startup failure with
a clear error message.

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
