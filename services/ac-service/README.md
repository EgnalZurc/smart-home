# ac-service

Climate control microservice for the smart-home platform. Overrides a Mitsubishi
AC's internal thermostat using real room temperatures read from distributed Zigbee
sensors, keeping the house at a target temperature while minimizing compressor
on/off cycles.

## Overview

The service runs a control loop that:

- Reads temperature/humidity from Zigbee sensors (auto-discovered via Zigbee2MQTT,
  delivered over MQTT).
- Averages the active sensor readings and compares them to the target temperature.
- Drives a Mitsubishi AC unit through the **MELCloud** API (login + device
  state/commands).
- Runs the control decision through a formal state machine, with cooldown logic to
  protect the compressor.
- Persists controller state to disk so it resumes where it left off after a restart.
- Serves a small SPA plus a JSON API, both behind nginx.

> **Note:** AC control is done via the **MELCloud** API (Mitsubishi), not Sensibo.
> Outdoor weather/air-quality comes from Open-Meteo.

## Port

- **Internal**: `8002`
- Auth is handled by nginx (`auth_request`) before requests reach this service —
  the service trusts all incoming requests as already authenticated.

## Tech Stack

- Python 3.12
- FastAPI + Uvicorn
- paho-mqtt (sensor communication)
- httpx (MELCloud API + Open-Meteo)
- PyYAML

(see `requirements.txt` for pinned versions)

## Architecture

Service-local modules (`src/`):

| File | Role |
|------|------|
| `main.py` | FastAPI app, lifespan wiring, and all HTTP routes |
| `controllers/ac_controller.py` | Control loop, drives the state machine and MELCloud |
| `controllers/state_machine.py` | Pure control logic (no I/O, fully unit-tested) |
| `ac_temp_scheduler.py` | Scheduled target-temperature adjustments |
| `outdoor.py` | Open-Meteo outdoor weather/AQI fetcher |
| `spa.py` | Serves the SPA HTML |
| `state_persistence.py` | Load/save controller state to `/app/data/controller_state.json` |
| `static/` | SPA assets (index.html, JS, i18n locales) |

Shared modules (from `libs/smart_home_common`):

| Module | Role |
|--------|------|
| `smart_home_common.clients.melcloud` | HTTP client for the MELCloud API (login, device state, commands) |
| `smart_home_common.clients.zigbee` | Startup discovery of temperature sensors from Zigbee2MQTT |
| `smart_home_common.mqtt.handler` | MQTT connection + in-memory sensor readings/history |
| `smart_home_common.mqtt.subscription` | Periodic polling (MELCloud state + Open-Meteo outdoor data) |
| `smart_home_common.utils.error_tracker` | Tracks active, categorized service errors |

### Startup sequence (`lifespan`)

1. Discover temperature sensors from Zigbee2MQTT (continues without sensors if none).
2. Start the MQTT handler and connect to the broker.
3. Log in to MELCloud (controller stays passive and an error is tracked if login fails).
4. Build the `ACController`, restore persisted state, and start the control loop.
5. Start the subscription manager (periodic MELCloud + Open-Meteo polling).
6. Start the AC temperature scheduler.

## API Endpoints

The SPA lives at `/smart-home/ac`; the JSON API is served under `/api/ac/*`.

### SPA & Health

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/smart-home/ac` | Serve the AC control SPA |
| GET | `/health` | Internal health check (Docker/nginx) |
| GET | `/api/health/ac` | Public health check |
| GET | `/api/ac/health/zigbee` | Zigbee/MQTT health + active sensor count |

### Alerts (Unified Alerts System)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/ac/alerts` | Current AC alerts for the unified dashboard alerts system. Returns `sensor_alert` when sensor data is stale (>1h). |

### Status & Control

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/ac/status` | Current AC + sensor status (averages, setpoint, mode, real AC state) |
| GET | `/api/ac/history` | Controller action history (`?limit=`) |
| GET | `/api/ac/config` | Current controller configuration |
| POST | `/api/ac/config` | Update config (target temp, hysteresis, loop interval) |
| POST | `/api/ac/control` | Set control mode (`auto` / `manual` / `off`) |
| POST | `/api/ac/manual` | Set manual params (temperature, fan speed, mode) |
| POST | `/api/ac/manual/param` | Update a single manual param (`?param=&value=`) |
| GET | `/api/ac/real` | Real AC state read live from MELCloud |

### Sensors & Environment

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/ac/sensors` | All sensor readings (online status, temp, humidity, battery) |
| GET | `/api/ac/sensors/history` | Sensor reading history (`?start=&end=&last=`) |
| GET | `/api/ac/outdoor` | Outdoor temperature, humidity, and AQI (cached, via Open-Meteo) |
| GET | `/api/ac/errors` | Active tracked errors |
| GET | `/api/ac/subscriptions/stats` | Subscription manager stats |

### Energy

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/ac/energy/current` | Current consumption (placeholder — energy tracker not in ac-service) |
| GET | `/api/ac/energy/hourly` | Hourly energy data (placeholder) |
| GET | `/api/ac/energy/monthly` | Monthly energy data (placeholder) |

Interactive API docs are available at `/swagger` (Swagger UI) and `/redoc`.

## Environment Variables

Required (the service refuses to start without these):

| Variable | Description |
|----------|-------------|
| `MELCLOUD_EMAIL` | MELCloud account email |
| `MELCLOUD_PASSWORD` | MELCloud account password |
| `MELCLOUD_DEVICE_ID` | MELCloud AC device ID (integer) |
| `MELCLOUD_BUILDING_ID` | MELCloud building ID (integer) |

Optional (defaults shown):

| Variable | Default | Description |
|----------|---------|-------------|
| `MQTT_BROKER` | `mosquitto` | MQTT broker hostname |
| `MQTT_PORT` | `1883` | MQTT broker port |
| `MELCLOUD_URL` | `https://app.melcloud.com` | MELCloud base URL |
| `TARGET_TEMPERATURE` | `26.0` | Target room temperature (°C) |
| `HYSTERESIS_ON` | `0.5` | Degrees above target before forcing cooling |
| `HYSTERESIS_OFF` | `0.3` | Degrees below target before turning off |
| `MIN_SETPOINT_TEMP` | `19.0` | Minimum AC setpoint |
| `MAX_SETPOINT_TEMP` | `30.0` | Maximum AC setpoint |
| `COOLDOWN_SECONDS` | `180` | Minimum off-time to protect the compressor |
| `LOOP_INTERVAL` | `10` | Control loop interval (seconds) |
| `SENSOR_TIMEOUT` | `3600` | Age (s) after which a sensor is considered offline |
| `MELCLOUD_UPDATE_INTERVAL` | `30` | MELCloud state poll interval (seconds) |
| `OUTDOOR_UPDATE_INTERVAL` | `600` | Open-Meteo poll interval (seconds) |
| `LOCATION_LATITUDE` | `40.396644` | Latitude for outdoor weather lookup |
| `LOCATION_LONGITUDE` | `-3.622511` | Longitude for outdoor weather lookup |
| `CORS_ORIGINS` | `*` | Comma-separated allowed CORS origins |

(see `src/main.py` for the full list, including fan-speed and AC-power tuning knobs)

## Persistence

Controller state is persisted to `/app/data/controller_state.json` (mounted volume)
and restored on startup, so the AC resumes its previous mode/setpoint after a
restart. Sensor readings and history are kept in memory only.

## Development

```bash
cd services/ac-service
pip install -r requirements.txt

# Run locally (required env vars must be set first)
cd src && uvicorn main:app --reload --port 8002
```

### Tests

Tests set the required MELCloud/MQTT env vars automatically (`tests/conftest.py`).

```bash
cd services/ac-service
pytest tests/ -v
```

### Lint

```bash
ruff check src/ tests/
ruff format src/ tests/
```

## Docker

```bash
docker build -t egnal/smart-home-ac-service:latest .

docker run -p 8002:8002 \
  -e MQTT_BROKER=mosquitto \
  -e MELCLOUD_EMAIL=you@example.com \
  -e MELCLOUD_PASSWORD=secret \
  -e MELCLOUD_DEVICE_ID=12345 \
  -e MELCLOUD_BUILDING_ID=67890 \
  -v ac-data:/app/data \
  egnal/smart-home-ac-service:latest
```

The image is a multi-stage Python 3.12-slim build running as the non-root `appuser`
and exposing port `8002`.

## Security

### MQTT Authentication

The service connects to the MQTT broker for sensor data. **In production, MQTT
authentication is required** to prevent unauthorized access to sensor readings and
potential injection of false data.

| Variable | Required in Production | Description |
|----------|------------------------|-------------|
| `MQTT_USER` | **Yes** | MQTT broker username |
| `MQTT_PASSWORD` | **Yes** | MQTT broker password |

If these variables are not set, the service logs a warning at startup and connects
without authentication. This is acceptable for local development but **must not be
used in production**.

Configure credentials in your `docker-compose.prod.yml` environment block or use
Docker secrets (see below).

### MELCloud Credentials

The service requires MELCloud credentials to control the AC unit. These credentials
grant full control over your AC system.

**Production recommendations:**

1. **Do not store credentials in plain `.env` files** committed to version control.
2. Use **Docker secrets** or an external secret manager (e.g., HashiCorp Vault,
   AWS Secrets Manager) to inject credentials at runtime.
3. MELCloud does not support API keys or OAuth — only email/password authentication.
   Consider creating a dedicated MELCloud account for home automation rather than
   using your personal account.

**Using Docker secrets (recommended):**

```yaml
# docker-compose.prod.yml
services:
  ac-service:
    secrets:
      - melcloud_email
      - melcloud_password
      - mqtt_user
      - mqtt_password
    environment:
      MELCLOUD_EMAIL_FILE: /run/secrets/melcloud_email
      MELCLOUD_PASSWORD_FILE: /run/secrets/melcloud_password
      MQTT_USER_FILE: /run/secrets/mqtt_user
      MQTT_PASSWORD_FILE: /run/secrets/mqtt_password

secrets:
  melcloud_email:
    file: ./secrets/melcloud_email.txt
  melcloud_password:
    file: ./secrets/melcloud_password.txt
  mqtt_user:
    file: ./secrets/mqtt_user.txt
  mqtt_password:
    file: ./secrets/mqtt_password.txt
```

> **Note:** The service does not currently support `*_FILE` environment variables
> for reading secrets from files. This is a planned enhancement. For now, pass
> credentials directly via environment variables sourced from a secrets manager
> or use Docker Compose's `env_file` with a non-committed secrets file.

### Credential Rotation

- **MQTT**: Rotate credentials in the broker configuration and update the service's
  environment variables. Restart the service to apply.
- **MELCloud**: Change the password in the MELCloud app/website, then update the
  service's `MELCLOUD_PASSWORD`. Restart to re-authenticate.

There is no automatic credential rotation — plan for periodic manual rotation as
part of your security hygiene.

## Hardware

- **AC Unit**: Mitsubishi (controlled via MELCloud)
- **Sensors**: SONOFF SNZB-02D (Zigbee 3.0 temperature/humidity)
- **Coordinator**: SONOFF ZBDongle-E, bridged by Zigbee2MQTT over MQTT
