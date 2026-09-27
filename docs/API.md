# Smart Home API Documentation

## Overview

This document describes all the APIs exposed by the Smart Home platform. The services are deployed as Docker containers and communicate through an internal Docker network. External access is provided through an nginx reverse proxy.

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
| POST | `/auth/token` | Login with username/password | No |
| POST | `/auth/logout` | Logout and clear session | Yes |
| GET | `/auth/me` | Get current user info | Yes |
| GET | `/auth/verify` | nginx auth_request verification | Cookie |
| GET | `/auth/trust/approve` | Approve device trust (email link) | Signed |
| GET | `/auth/trust/reject` | Reject device trust (email link) | Signed |

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

### Vacaciones API

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| GET | `/api/vacaciones` | Get vacation data | Yes |
| POST | `/api/vacaciones` | Update vacation data | Yes |

---

## Casita Sueños Service (Port 8001)

### Health

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| GET | `/health` | Service health | No |

### Properties API

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| GET | `/api/properties` | List properties | Yes |
| GET | `/api/properties/{id}` | Get property details | Yes |
| POST | `/api/properties/{id}/dismiss` | Dismiss property | Yes |
| POST | `/api/properties/{id}/undismiss` | Undismiss property | Yes |
| POST | `/api/properties/{id}/view` | Mark as viewed | Yes |
| POST | `/api/properties/{id}/comment` | Save comment | Yes |

### Scraping

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| POST | `/api/scrape` | Trigger manual scrape | Yes |
| GET | `/api/schedule` | Get schedule | Yes |
| POST | `/api/schedule` | Update schedule | Yes |

---

## Validation Results (2026-09-27)

All services validated successfully:

| Service | Health Check | Sample Endpoint | Status |
|---------|--------------|-----------------|--------|
| Dashboard | ✅ `{"status":"ok"}` | `/api/health/backend` → `{"online":true}` | OK |
| Baby Gifts | ✅ `{"online":true,"service":"baby-gifts"}` | `/api/baby-gifts` → gifts array | OK |
| AC Service | ✅ `{"online":true,"service":"ac"}` | `/api/status` → full status | OK |
| Vacaciones | ✅ `{"online":true,"service":"vacaciones"}` | N/A | OK |
| Casita Sueños | ✅ `{"online":true}` | N/A | OK |

---

## Deployment

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
