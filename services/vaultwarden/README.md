# Vaultwarden Service

Self-hosted Bitwarden-compatible password manager for Cuchi Casa.

## Overview

This is a wrapper around the official [vaultwarden/server](https://github.com/dani-garcia/vaultwarden) image with environment variables pre-configured for our deployment.

## Access

- **Web Vault**: https://raspberrypi.tailaa37cd.ts.net/passwords/
- **Browser Extension**: Configure server URL as `https://raspberrypi.tailaa37cd.ts.net/passwords`

## Configuration

Environment variables are baked into the Docker image:

| Variable | Value | Description |
|----------|-------|-------------|
| `DOMAIN` | `https://raspberrypi.tailaa37cd.ts.net/passwords` | Base URL for the web vault |
| `WEBSOCKET_ENABLED` | `true` | Enable push notifications |
| `SIGNUPS_ALLOWED` | `false` | Disable public registration |
| `LOG_LEVEL` | `warn` | Logging verbosity |

### Secrets (runtime)

The `ADMIN_TOKEN` is stored in GitHub Secrets and injected at runtime via docker-compose. Never commit this token to the repository.

To access the admin panel: https://raspberrypi.tailaa37cd.ts.net/passwords/admin

## Deployment

Deployed automatically via CI/CD when changes are pushed to `services/vaultwarden/`.

Manual deploy:
```bash
gh workflow run ci.yml -f service=vaultwarden --repo EgnalZurc/smart-home
```

## Data Persistence

Vault data is stored at `/home/pi/data/vaultwarden` on the Pi, mounted as `/data` in the container.

## Updating

To update to the latest vaultwarden version:
1. The CI rebuilds with `--pull` to fetch the latest base image
2. Push any change to `services/vaultwarden/` to trigger a rebuild

Or manually trigger a deploy which will pull the latest base image.

## Health Check

The container includes a health check that verifies the service is fully operational:

```yaml
healthcheck:
  test: ["CMD", "curl", "-sf", "http://localhost:80/passwords/alive"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 30s
```

The `/passwords/alive` endpoint returns a JSON timestamp when the API is ready, ensuring:
- Web server (Rocket) is responding
- API layer is functional (not just port open)
- Subpath routing is working correctly
