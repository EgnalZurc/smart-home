# Smart Home API Documentation

## Overview

This document describes all the APIs exposed by the Smart Home platform. The services are deployed as Docker containers and communicate through an internal Docker network. External access is provided through an nginx reverse proxy.

> ⚠️ **Important:** Before modifying service configurations, read [NAMING_CONVENTIONS.md](NAMING_CONVENTIONS.md) to understand the critical naming rules that prevent 502 errors.

## Base URLs

| Service | Internal URL | External URL (via nginx) |
|---------|--------------|--------------------------|
| Dashboard | http://smart-home-backend:8080 | https://raspberrypi.local/ |
| Baby Gifts | http://baby-gifts-service:8004 | https://raspberrypi.local/smart-home/baby-gifts |
| AC Service | http://ac-service:8002 | https://raspberrypi.local/smart-home/ac |
| Vacaciones | http://vacaciones-service:8003 | https://raspberrypi.local/smart-home/vacaciones |
| Casita Sueños | http://casita-suenos:8001 | https://raspberrypi.local/api/casita/* |

## Authentication

Most endpoints require authentication via nginx `auth_request` directive. The dashboard handles authentication and sets session cookies.

### Programmatic Authentication

The auth system uses form-based login that returns session cookies. To authenticate programmatically:

```bash
# Using curl with cookie jar
curl -c cookies.txt -X POST "https://raspberrypi.tailaa37cd.ts.net/auth/token" \
  -d "username=YOUR_USER" \
  -d "password=YOUR_PASS" \
  -d "next_url=/smart-home" \
  -L

# Use the cookies for subsequent requests
curl -b cookies.txt "https://raspberrypi.tailaa37cd.ts.net/api/containers"
```

```python
# Using Python httpx
import httpx

with httpx.Client(follow_redirects=True) as client:
    # Login (stores session cookie automatically)
    client.post(
        "https://raspberrypi.tailaa37cd.ts.net/auth/token",
        data={"username": "USER", "password": "PASS", "next_url": "/smart-home"}
    )
    
    # Authenticated requests
    resp = client.get("https://raspberrypi.tailaa37cd.ts.net/api/containers")
    print(resp.json())
```

```powershell
# Using PowerShell with session
$session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
Invoke-WebRequest -Uri "https://raspberrypi.tailaa37cd.ts.net/auth/token" `
  -Method POST -Body @{username="USER"; password="PASS"; next_url="/smart-home"} `
  -WebSession $session -MaximumRedirection 0 -ErrorAction SilentlyContinue

# Authenticated request
Invoke-RestMethod -Uri "https://raspberrypi.tailaa37cd.ts.net/api/containers" `
  -WebSession $session
```

### Test Script

A test script is provided at `scripts/test_api.py`:

```bash
# Set credentials
export SMART_HOME_USER=your_username
export SMART_HOME_PASS=your_password

# Run tests
python scripts/test_api.py -v
```

### Auth Endpoints

---

## Interactive API Documentation (Swagger/OpenAPI)

Each FastAPI service exposes auto-generated API documentation:

| Service | Swagger UI | OpenAPI Spec | ReDoc |
|---------|------------|--------------|-------|
| Dashboard | `/swagger` | `/openapi.json` | `/redoc` |
| AC Service | `http://ac-service:8002/swagger` | `http://ac-service:8002/openapi.json` | `http://ac-service:8002/redoc` |
| Baby Gifts | `http://baby-gifts-service:8004/swagger` | `http://baby-gifts-service:8004/openapi.json` | `http://baby-gifts-service:8004/redoc` |
| Vacaciones | `http://vacaciones-service:8003/swagger` | `http://vacaciones-service:8003/openapi.json` | `http://vacaciones-service:8003/redoc` |
| Casita Sueños | ❌ N/A (raw HTTP) | ❌ N/A | ❌ N/A |

### Accessing Swagger UI

**Via nginx (external):**
- Dashboard: `https://raspberrypi.tailaa37cd.ts.net/swagger`

**Via SSH tunnel (internal services):**
```bash
# Forward AC service docs to localhost
ssh -L 8002:ac-service:8002 pi@raspberrypi
# Then open: http://localhost:8002/swagger
```

**From Pi directly:**
```bash
# Test OpenAPI spec
curl http://smart-home-backend:8080/openapi.json | head -c 500
curl http://ac-service:8002/openapi.json | head -c 500
```

---

## Dashboard Service (Port 8080)

### Health Endpoints

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| GET | `/health` | Service health check | No |
| GET | `/api/health/backend` | Backend health | No |
| GET | `/api/health/zigbee` | Zigbee/MQTT health (proxied from ac-service) | No |
| GET | `/api/health/ac` | AC service health | No |
| GET | `/api/health/vacaciones` | Vacaciones service health | No |
| GET | `/api/health/immich` | Immich photo server health | No |
| GET | `/api/health/casita` | Casita Sueños health | No |
| GET | `/api/health/passwords` | Vaultwarden health | No |
| GET | `/api/health/valheim` | Valheim server health | No |
| GET | `/api/health/valheim-admin` | Valheim admin health | No |

### Authentication Endpoints

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| GET | `/auth/login` | Serve login page | No |
| POST | `/auth/token` | Login with username/password (form data) | No |
| POST | `/auth/logout` | Logout and clear session | Yes |
| GET | `/auth/me` | Get current user info and profile | Yes |
| GET | `/auth/verify` | nginx auth_request verification | Cookie |
| GET | `/auth/trust/approve` | Approve device trust (email link) | Signed |
| GET | `/auth/trust/reject` | Reject device trust (email link) | Signed |

#### POST /auth/token

Form data parameters:
- `username` (required): User's username
- `password` (required): User's password  
- `trusted` (optional): "true" to request device trust
- `next_url` (optional): Redirect URL after login (default: "/smart-home")

Returns:
- 303 redirect with `session` cookie on success
- HTML login page with error message on failure

#### GET /auth/me

Returns current user info:
```json
{
  "username": "egnal",
  "profile_key": "SUPER",
  "show_config_apps": true,
  "can_view_level": 1,
  "can_edit_level": 1
}
```

### Container Management

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| GET | `/api/containers` | List all controllable containers | Yes |
| POST | `/api/containers/{app_key}/stop` | Stop a service | Yes |
| POST | `/api/containers/{app_key}/start` | Start a service | Yes |

### System

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| GET | `/api/system/stats` | Raspberry Pi system stats (CPU, RAM, disk) | Yes |
| GET | `/api/system/mode` | Get current Pi mode | Yes |
| POST | `/api/system/mode/{mode}` | Switch Pi mode | Yes |

### Casita Sueños Proxy

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| GET | `/api/casita/status` | Get property listings | Yes |
| GET | `/api/casita/radar` | Get radar/alert data | Yes |
| GET | `/api/casita/dismissed` | Get dismissed properties | Yes |
| GET | `/api/casita/schedule` | Get scraping schedule | Yes |
| POST | `/api/casita/schedule` | Update scraping schedule | Yes |
| POST | `/api/casita/dismiss` | Dismiss a property | Yes |
| POST | `/api/casita/undismiss` | Undismiss a property | Yes |
| POST | `/api/casita/mark-viewed` | Mark property as viewed | Yes |
| POST | `/api/casita/save-comment` | Save comment on property | Yes |
| GET | `/api/casita/summary` | Get AI summary | Yes |
| POST | `/api/casita/run-scraping` | Trigger manual scraping | Yes |
| POST | `/api/casita/run-summary` | Trigger AI summary | Yes |

### External Proxies (CORS)

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| GET | `/api/proxy/flood` | Flood risk data proxy | Yes |
| GET | `/api/proxy/firms` | NASA FIRMS fire data proxy | Yes |

---

## Baby Gifts Service (Port 8004)

### Health

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| GET | `/health` | Service health | No |
| GET | `/api/health/baby-gifts` | Health alias | No |

### Admin API (Protected)

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| GET | `/api/baby-gifts` | Get all gifts with full details | Yes (Admin) |
| POST | `/api/baby-gifts` | Create a new gift | Yes (Admin) |
| PUT | `/api/baby-gifts/{gift_id}` | Update a gift | Yes (Admin) |
| DELETE | `/api/baby-gifts/{gift_id}` | Delete a gift | Yes (Admin) |
| POST | `/api/baby-gifts/{gift_id}/unreserve` | Admin unreserve | Yes (Admin) |
| PUT | `/api/baby-gifts/categories` | Update categories | Yes (Admin) |

### Invitation Management (Admin)

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| GET | `/api/baby-gifts/invitations` | List all invitations | Yes (Admin) |
| POST | `/api/baby-gifts/invitations` | Create invitation | Yes (Admin) |
| DELETE | `/api/baby-gifts/invitations/{token}` | Delete invitation | Yes (Admin) |
| POST | `/api/baby-gifts/invitations/{token}/revoke` | Revoke invitation | Yes (Admin) |

### Authenticated User API

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| GET | `/api/baby-gifts/user` | Get gifts for authenticated user | Yes |
| POST | `/api/baby-gifts/user/reserve/{gift_id}` | Reserve a gift | Yes |
| POST | `/api/baby-gifts/user/unreserve/{gift_id}` | Cancel reservation | Yes |

### Guest API (Token-based)

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| GET | `/api/baby-gifts/guest/{token}` | Get gifts for guest | Token |
| POST | `/api/baby-gifts/guest/{token}/reserve/{gift_id}` | Reserve as guest | Token |
| POST | `/api/baby-gifts/guest/{token}/unreserve/{gift_id}` | Cancel guest reservation | Token |

### SPA Serving

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| GET | `/smart-home/baby-gifts` | Admin SPA | Yes |
| GET | `/baby-gifts/i/{token}` | Guest SPA | Token |

---

## AC Service (Port 8002)

### Health

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| GET | `/health` | Service health | No |
| GET | `/api/health/zigbee` | Zigbee/MQTT health | No |

### Status & Sensors

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| GET | `/api/status` | Current AC state and averages | Yes |
| GET | `/api/sensors` | All sensor readings | Yes |
| GET | `/api/sensors/history` | Historical sensor data | Yes |
| GET | `/api/history` | AC control history | Yes |
| GET | `/api/ac_real` | Real AC state from MELCloud | Yes |
| GET | `/api/outdoor` | Outdoor weather data | Yes |

### Configuration

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| GET | `/api/config` | Get AC configuration | Yes |
| POST | `/api/config` | Update AC configuration | Yes |

### Control

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| POST | `/api/control_mode` | Set control mode (auto/manual/off) | Yes |
| POST | `/api/manual_params` | Set manual parameters | Yes |
| POST | `/api/manual_param` | Update single parameter | Yes |

### Analytics

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| GET | `/api/humidity/study` | Humidity analysis summary | Yes |
| POST | `/api/humidity/study/run` | Trigger humidity analysis | Yes |
| GET | `/api/errors` | Error history | Yes |
| GET | `/api/subscriptions/stats` | MQTT subscription stats | Yes |

### Energy (Stub)

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| GET | `/api/energy/current` | Current energy usage | Yes |
| GET | `/api/energy/hourly` | Hourly energy data | Yes |
| GET | `/api/energy/monthly` | Monthly energy data | Yes |

---

## Vacaciones Service (Port 8003)

### Health

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| GET | `/health` | Service health | No |
| GET | `/api/health/vacaciones` | Health alias for dashboard | No |

### SPA

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| GET | `/smart-home/vacaciones` | Vacaciones SPA page | Yes |

### Vacaciones API

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| GET | `/api/vacaciones` | Get all vacation data (nucleos, personas, years) | Yes |
| GET | `/api/vacaciones/config` | Get configuration (nucleos + personas) | Yes |
| POST | `/api/vacaciones/config` | Save configuration | Yes |
| POST | `/api/vacaciones/year` | Add a new year | Yes |
| POST | `/api/vacaciones/year/{year}` | Save a year's planning | Yes |
| DELETE | `/api/vacaciones/year/{year}` | Delete a year | Yes |

---

## Casita Sueños Service (Port 8001)

> ⚠️ **Note:** This service uses a raw HTTP server, not FastAPI. No OpenAPI/Swagger available.

### Health

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| GET | `/health` | Service health | No |

### Status & Properties API

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| GET | `/status` | Full system status (properties, schedule, stats) | Yes |
| GET | `/radar` | Properties above alert threshold | Yes |
| GET | `/dismissed` | Dismissed properties list | Yes |

### Property Actions

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| POST | `/dismiss` | Dismiss a property (body: `{"uid": "..."}`) | Yes |
| POST | `/undismiss` | Restore a dismissed property | Yes |
| POST | `/mark_viewed` | Mark property as viewed | Yes |
| POST | `/save_comment` | Save comment on property | Yes |

### Scraping Control

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| GET | `/schedule` | Get current scraping schedule | Yes |
| POST | `/schedule` | Update scraping schedule | Yes |
| POST | `/run_scraping` | Trigger manual scraping | Yes |
| POST | `/run_summary` | Trigger AI summary generation | Yes |

---

## Validation Results (2026-09-27 21:05 UTC+2)

All services validated successfully via `docker exec nginx-reverse-proxy wget`:

| Service | Health Check | Sample Endpoint | Status |
|---------|--------------|-----------------|--------|
| Dashboard | ✅ `{"status":"ok"}` | `/api/health/backend` → `{"online":true}` | OK |
| Baby Gifts | ✅ `{"online":true,"service":"baby-gifts"}` | `/api/baby-gifts` → gifts array | OK |
| AC Service | ✅ `{"online":true,"service":"ac"}` | `/api/status` → full status | OK |
| Vacaciones | ✅ `{"online":true,"service":"vacaciones"}` | `/api/vacaciones/config` → config | OK |
| Casita Sueños | ✅ `{"online":true}` | `/status` → full status with 978 properties | OK |

---

## Deployment

> 📖 **Read First:** [NAMING_CONVENTIONS.md](NAMING_CONVENTIONS.md) - Critical rules for service naming

### Service Naming Rules

**Docker DNS uses the service name (not container_name) for internal communication.**

| Service | docker-compose name | nginx upstream |
|---------|---------------------|----------------|
| Dashboard | `smart-home-backend` | `http://smart-home-backend:8080` |
| AC Service | `ac-service` | `http://ac-service:8002` |
| Baby Gifts | `baby-gifts-service` | `http://baby-gifts-service:8004` |
| Vacaciones | `vacaciones-service` | `http://vacaciones-service:8003` |
| Casita Sueños | `casita-suenos` | `http://casita-suenos:8001` |

### From GitHub Actions

The deploy workflow builds Docker images and pushes to Docker Hub. Due to network constraints, SSH deploy may fail. Images are always pushed successfully.

### Manual Deploy

```bash
# From this PC (with SSH access to Pi)
ssh pi@raspberrypi.local "cd ~/smart-home-prod && docker compose pull && docker compose up -d"

# Or use the PowerShell script
.\scripts\deploy.ps1 [service]
```

### Service Names

- `all` - Deploy all services
- `dashboard` - Smart Home Dashboard
- `ac-service` - AC Controller
- `baby-gifts-service` - Baby Gifts Registry
- `vacaciones-service` - Vacation Planner
- `casita-suenos` - Property Monitor
