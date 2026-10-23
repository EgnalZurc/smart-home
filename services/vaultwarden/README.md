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

## Backup Procedure

**Critical**: Password vaults contain irreplaceable data. Regular backups are essential.

### What to back up

The vaultwarden data directory (`/home/pi/data/vaultwarden`) contains:
- `db.sqlite3` — Main database with all vault entries
- `attachments/` — File attachments stored in vaults
- `rsa_key.*` — RSA keys for encryption (regenerated if missing, but clients need re-auth)
- `config.json` — Runtime configuration

### Manual backup

```bash
# On the Pi, stop the container to ensure consistency
ssh pi@raspberrypi.local "cd ~/smart-home-prod && docker compose stop vaultwarden"

# Create timestamped backup
ssh pi@raspberrypi.local "tar -czf ~/backups/vaultwarden-\$(date +%Y%m%d-%H%M%S).tar.gz -C /home/pi/data vaultwarden"

# Restart the container
ssh pi@raspberrypi.local "cd ~/smart-home-prod && docker compose start vaultwarden"
```

### Restore from backup

```bash
# Stop the container
ssh pi@raspberrypi.local "cd ~/smart-home-prod && docker compose stop vaultwarden"

# Replace data directory
ssh pi@raspberrypi.local "rm -rf /home/pi/data/vaultwarden && tar -xzf ~/backups/vaultwarden-YYYYMMDD-HHMMSS.tar.gz -C /home/pi/data"

# Restart
ssh pi@raspberrypi.local "cd ~/smart-home-prod && docker compose up -d vaultwarden"
```

### Recommended schedule

- **Daily**: Automated backup of `db.sqlite3` (cron job)
- **Weekly**: Full backup of entire data directory
- **Off-site**: Copy critical backups to a separate location periodically

## Updating

To update to the latest vaultwarden version:
1. Update the image tag and digest in `Dockerfile`
2. Push changes to trigger CI/CD rebuild

Or manually trigger a deploy:
```bash
gh workflow run ci.yml -f service=vaultwarden --repo EgnalZurc/smart-home
```

**Note**: After major version updates, verify vault functionality and re-export a backup.

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

The `/passwords/alive` endpoint returns a JSON response when the API is ready:
```json
{"alive": true, "timestamp": "2026-10-23T12:00:00Z"}
```

This ensures:
- Web server (Rocket) is responding
- API layer is functional (not just port open)
- Subpath routing is working correctly
