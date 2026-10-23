# valheim-admin

Proxy service that bridges the smart-home dashboard (Raspberry Pi) with pc-agent
(Windows PC) to control the Valheim dedicated server.

## Architecture

```
Dashboard (Pi) → valheim-admin (Pi) → pc-agent (Windows PC) → Valheim Server
```

The valheim-admin service runs on the Raspberry Pi as a Docker container and
proxies all commands to pc-agent over HTTP. The actual Valheim server, worlds,
logs, and configuration files live on the Windows PC.

## Requirements

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `PC_AGENT_URL` | Yes | URL of pc-agent (e.g., `http://192.168.1.164:8090`) |
| `PC_AGENT_TOKEN` | Yes | Authentication token for pc-agent |

### Network

- Port 8080 (internal, proxied by nginx via `/valheim-admin/`)
- Must be able to reach pc-agent on the local network

### Docker Configuration

This service does **not** require access to the Docker socket. Unlike other
services that manage containers directly, valheim-admin is a pure HTTP proxy
that forwards requests to pc-agent. All container/process management happens
on the Windows PC via pc-agent.

If you're looking at docker-compose and wondering about socket mounts:
- **valheim-admin**: No socket needed (HTTP proxy only)
- **pc-agent** (Windows): Controls Docker on Windows, not via socket mount

## API Endpoints

### Health

- `GET /health` - Liveness check (always returns online)
- `GET /health/ready` - Readiness check (verifies pc-agent connectivity)

### Server Control

- `GET /api/status` - Get server status
- `POST /api/server/start` - Start the server (rate limited)
- `POST /api/server/stop` - Stop the server (rate limited)
- `POST /api/server/restart` - Restart the server (rate limited)

### Configuration

- `GET /api/config` - Get server configuration
- `POST /api/config` - Update server configuration (JSON body)

### Logs

- `GET /api/logs?lines=N` - Get recent log lines (default: 80, max: 10000)

### World Management

- `GET /api/worlds` - List available worlds
- `POST /api/worlds/new` - Create new world (form: `world_name`)
- `POST /api/worlds/activate` - Activate a world (form: `world_name`)
- `DELETE /api/worlds/{name}` - Delete a world

## Security

- Authentication is handled by nginx via `auth_request`
- All user input is validated before forwarding to pc-agent
- Rate limiting on server control endpoints prevents abuse
- Security headers added to all responses

## Development

Run tests:
```bash
# From repo root
.\dev.ps1 ci valheim-admin
```

Run locally (requires pc-agent running):
```bash
PC_AGENT_URL=http://localhost:8090 PC_AGENT_TOKEN=test uvicorn src.main:app --port 8080
```
