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
