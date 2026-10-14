# Dashboard Service

Main control panel and API gateway for the Cuchi Casa smart home platform.

## Overview

The dashboard is the central hub of the platform, providing:
- **Unified Web UI**: PWA with all apps accessible from one place
- **Authentication**: JWT-based auth with trusted device support
- **API Gateway**: Proxies all microservice APIs through unified Swagger
- **System Management**: Container control, resource monitoring

## Port

- **Internal**: 8080
- **External**: Via nginx at `/` (root)

## Features

### Web Interface
- Modern PWA, mobile-first design
- App launcher for all services
- System resource monitoring (RAM, CPU, disk, temperature)
- Container start/stop control
- Multi-language support (English/Spanish)
- Persistent dark/light mode toggle (per-user, synced across devices)

### Authentication
- JWT session cookies (24h TTL)
- Trusted device tokens for auto-login
- Profile-based access control (SUPER, FAMILIA_PRINCIPAL)
- Email-based device approval flow

### API Gateway
All microservice APIs are proxied through the dashboard:
- `/api/ac/*` → ac-service:8002
- `/api/vacaciones/*` → vacaciones-service:8003
- `/api/baby-gifts/*` → baby-gifts-service:8004
- `/api/casita/*` → casita-suenos:8001

### Unified Swagger
Single Swagger UI at `/swagger` documents ALL platform APIs.

## API Endpoints

### Authentication
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/auth/login` | Login page |
| POST | `/api/auth/token` | Authenticate and get session |
| POST | `/api/auth/logout` | End session |
| GET | `/api/auth/me` | Current user info |

### Health Checks
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health` | Dashboard health |
| GET | `/api/health/{service}` | Service health (backend, zigbee, ac, etc.) |

### System
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/system/containers` | Container states |
| POST | `/api/system/containers/{name}/start` | Start container |
| POST | `/api/system/containers/{name}/stop` | Stop container |
| GET | `/api/system/stats` | System resources |
| GET | `/api/system/summary` | Unified snapshot: containers + stats + alerts + per-service health (SUPER, 30s cache) |

`/api/system/summary` bundles the four home-view data sources into a single
SUPER-gated call so the dashboard does not have to fan out on every refresh. It
returns `{containers, stats, alerts, services_health, cached, timestamp}`,
gathering the sources concurrently in-process. A failing source degrades to an
`{"error": ...}` slot instead of failing the whole response. The payload is
cached for 30 seconds, keyed per user (because `alerts` embeds per-user
read-state). The optional `days` query param (1-30, default 1) sets the memory
alert look-back window and is forwarded to the alerts source.

### Unified Alerts
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/alerts/unified` | Aggregated alerts from all sources (memory, metrics, ac, portfolio, casita) |
| POST | `/api/alerts/mark-read` | Mark an alert as read for the current user (body: `{"alert_key": "..."}`) |
| GET | `/api/alerts/read-status` | List the alert keys the current user has marked as read |

Each alert returned by `/api/alerts/unified` carries a stable `key`
(`"{source}:{identifier}"`, e.g. `casita:fotocasa_182159128`) and a per-user
`read` boolean. The identifier is taken from the alert's `id`/`alert_id`/
`container` field when present, otherwise a short hash of its title and/or URL.
That same `key` is what you pass to `POST /api/alerts/mark-read`.

The response also includes `unread_count` — the number of alerts the current
user has not read across the whole aggregate (unaffected by filtering). Pass
`?unread_only=true` to return only the unread alerts while still reporting the
full `unread_count`. The existing `?days=` parameter still controls the memory
alert look-back window.

```json
{
  "count": 3,
  "unread_count": 2,
  "timestamp": "2026-10-14T06:54:00+00:00",
  "alerts": [
    {
      "source": "casita",
      "key": "casita:fotocasa_182159128",
      "severity": "info",
      "title": "New listing matched",
      "read": false
    }
  ]
}
```

Read state is tracked per user in the `alert_reads` SQLite table (shared
`AUTH_DB_PATH` database). Marking an alert read is idempotent — re-marking the
same `alert_key` just refreshes its timestamp. All three endpoints require an
authenticated session (any profile level).

### Monitoring
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/monitoring/memory/alerts` | Memory usage alerts (containers >80% RAM) |
| POST | `/api/monitoring/memory/snapshot` | Receive memory snapshot from cron |

### User Preferences
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/user/preferences` | Current user's UI preferences (`{"dark_mode": bool}`) |
| POST | `/api/user/preferences` | Persist UI preferences (body: `{"dark_mode": true/false}`) |

The dashboard theme (dark mode) is stored per user in the `dark_mode` column of
the `users` table (shared `AUTH_DB_PATH` database), so the choice follows the
user across devices and sessions rather than living only in browser
localStorage. New users default to dark mode. Both endpoints require an
authenticated session (any profile level) and operate only on the calling
user's own preferences. On page load the dashboard paints the last cached theme
immediately (no flash), then reconciles with `GET /api/user/preferences`;
toggling the switch in the user menu writes through via `POST`.

### Proxied Services
See individual service READMEs for their endpoints:
- [AC Service](../services/ac-service/README.md)
- [Vacaciones Service](../services/vacaciones-service/README.md)
- [Baby Gifts Service](../services/baby-gifts-service/README.md)
- [Casita Sueños](../services/casita-suenos/README.md)

## Tech Stack

- Python 3.12
- FastAPI + Uvicorn
- Paho-MQTT
- httpx (async HTTP)
- PyJWT (authentication)
- passlib (password hashing)

## Development

```bash
cd dashboard
pip install -r requirements.txt
cd src && uvicorn main:app --reload --port 8080
```

## Docker

```bash
docker build -t egnal/smart-home-dashboard:latest .
docker run -p 8080:8080 \
  -e AUTH_SECRET=your-secret \
  -v dashboard-data:/app/data \
  egnal/smart-home-dashboard:latest
```

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| AUTH_SECRET | JWT signing secret | Yes |
| AUTH_SESSION_TTL | Session duration (seconds) | No (default: 86400) |
| SMTP_HOST | Email server for device approval | No |
| SMTP_USER | Email username | No |
| SMTP_PASSWORD | Email password | No |

## Directory Structure

```
dashboard/
├── Dockerfile
├── requirements.txt
├── src/
│   ├── main.py              # FastAPI app, middleware, routing
│   ├── auth.py              # JWT handling
│   ├── auth_users.py        # User management
│   ├── auth_devices.py      # Trusted device tokens
│   ├── user_profiles.py     # Profile-based permissions
│   ├── api/
│   │   ├── routes.py        # Main API routes + service proxies
│   │   └── auth_routes.py   # Authentication endpoints
│   ├── controllers/         # Business logic
│   └── static/
│       ├── dashboard.html   # Main PWA
│       ├── login.html       # Login page
│       ├── vacaciones.html  # Vacation planner
│       └── casita.html      # Property monitor
└── tests/
    ├── unit/
    └── integration/
```

## Related Files

- Agent config: `.kiro/agents/smart-home-dev.md`
- Project standards: `.kiro/steering/project-standards.md`
- nginx config: `infrastructure/nginx/conf.d/smart-home.conf`
