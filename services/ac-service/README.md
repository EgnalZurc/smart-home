# AC Service

Climate control service for the Cuchi Casa platform.

## Overview

This service provides intelligent air conditioning control using:
- 5 Zigbee temperature/humidity sensors distributed throughout the house
- MELCloud API integration for Mitsubishi AC control
- State machine with 7 states for optimal temperature management
- Override of internal AC thermostat using real room temperatures

## Port

- **Internal**: 8002
- **External**: Via nginx at `/api/ac/*`

## API Endpoints

All endpoints are proxied through the dashboard at `/api/ac/*`.

### Status & Control
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/ac/status` | Current AC status, temperatures, mode |
| POST | `/api/ac/mode/{mode}` | Set mode (auto/manual/off) |
| POST | `/api/ac/target/{temp}` | Set target temperature |
| POST | `/api/ac/power/{state}` | Set AC power (on/off) |

### Sensors
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/ac/sensors` | All sensor readings |
| GET | `/api/ac/sensors/{id}` | Single sensor reading |
| GET | `/api/ac/sensors/history` | Historical sensor data |

### Energy & Analysis
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/ac/energy` | Energy consumption data |
| GET | `/api/ac/humidity/study` | Humidity analysis |

### Configuration
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/ac/config` | Current configuration |
| POST | `/api/ac/config` | Update configuration |

### Health
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health/ac` | AC service health |
| GET | `/api/ac/health/zigbee` | Zigbee connection health |

## Control Logic

```
Every 45 seconds:
  temps = [read active sensors via MQTT]
  average = mean(temps)

  If average > target + 0.5°C → AC ON, setpoint 19°C (force cooling)
  If target - 0.3°C < average < target + 0.5°C → AC ON, proportional setpoint
  If average ≤ target - 0.3°C → AC OFF (with 5 min cooldown)
```

## State Machine

The controller uses a formal state machine with 7 states:
- IDLE
- COOLING
- COOLDOWN
- MANUAL_ON
- MANUAL_OFF
- ERROR
- WAITING_COMPRESSOR

## Tech Stack

- Python 3.12
- FastAPI + Uvicorn
- Paho-MQTT (sensor communication)
- httpx (MELCloud API)
- PyYAML (configuration)

## Hardware

- **AC Unit**: Mitsubishi PEAD-SM71JA (S/N 3XM10399)
- **Sensors**: 5x SONOFF SNZB-02D (Zigbee 3.0, LCD display)
- **Coordinator**: SONOFF ZBDongle-E V2

## Development

```bash
cd services/ac-service
pip install -r requirements.txt
cd src && uvicorn main:app --reload --port 8002
```

## Docker

```bash
docker build -t egnal/smart-home-ac-service:latest .
docker run -p 8002:8002 \
  -e MQTT_HOST=mosquitto \
  -e MELCLOUD_USER=user \
  -e MELCLOUD_PASSWORD=pass \
  egnal/smart-home-ac-service:latest
```

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| MQTT_HOST | MQTT broker hostname | Yes |
| MQTT_PORT | MQTT broker port | No (default: 1883) |
| MELCLOUD_USER | MELCloud account email | Yes |
| MELCLOUD_PASSWORD | MELCloud account password | Yes |

## Related Files

- Frontend: `dashboard/src/static/dashboard.html` (AC section)
- Proxy routes: `dashboard/src/api/routes.py` (AC section)
- State persistence: `dashboard/src/state_persistence.py`
- Controller: `dashboard/src/controllers/ac_controller.py`
