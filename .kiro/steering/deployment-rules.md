---
inclusion: auto
---
# Deployment Rules — Raspberry Pi

## CRITICAL: Never Fix the Pi Manually

The Raspberry Pi is a **deployment target**, not a development environment.

### ❌ NEVER do this:
- `scp` files directly to the Pi
- SSH to edit config files on the Pi
- `docker cp` files into running containers
- `docker compose up`, `docker compose pull`, `docker compose restart` on the Pi
- `docker exec` to modify anything inside containers
- Any manual "fix" that bypasses the deployment pipeline

### Why docker commands are forbidden:
Even "simple" commands like `docker compose up -d --force-recreate` bypass the deployment pipeline:
- No audit trail in GitHub Actions
- No verification step runs
- Creates inconsistency between what GitHub shows as deployed vs what's actually running
- The next CI deploy might not recreate if the image hash matches

### ✅ ALWAYS do this:
1. Fix the source code in `C:\Users\acmls\Documents\Development\smart-home`
2. Commit and push to GitHub
3. Deploy via GitHub Actions: `gh workflow run deploy.yml -f service=SERVICE --repo EgnalZurc/smart-home`
4. Verify deployment succeeded

### Why?
- Manual fixes are lost on next deployment
- Manual fixes create drift between code and production
- Manual fixes are not tracked in git
- The next person (including future you) won't know about the fix

## Deployment Methods

### Primary: GitHub Actions (PREFERRED)
```powershell
gh workflow run deploy.yml -f service=SERVICE --repo EgnalZurc/smart-home
```
Valid services: `all`, `dashboard`, `ac-service`, `baby-gifts-service`, `vacaciones-service`, `casita-suenos`

### Fallback: Direct Docker (only if GitHub Actions is broken)
```powershell
ssh pi@raspberrypi "cd ~/smart-home-prod && docker compose pull SERVICE && docker compose up -d SERVICE"
```

## What CAN be done on the Pi

These are OK because they're operational, not code fixes:
- Viewing logs: `docker logs CONTAINER`
- Restarting containers: `docker compose restart SERVICE`
- Checking status: `docker ps`, `docker stats`
- Network debugging: `docker network inspect`
- Disk cleanup: `docker system prune`

## nginx Configuration

nginx config lives in `infrastructure/nginx/conf.d/smart-home.conf`.

When nginx config changes:
1. Edit the file locally
2. Commit and push
3. Deploy: `gh workflow run ci.yml -f service=all --repo EgnalZurc/smart-home`

The deploy workflow copies the nginx config and reloads nginx automatically.

**If nginx config isn't deploying correctly**, the fix is to update the deployment workflow, NOT to scp the file manually.

## docker-compose.yml

Production compose file is `docker-compose.prod.yml` in the repo.

When docker-compose.prod.yml changes:
1. Edit the file locally
2. Commit and push
3. The deploy workflow automatically syncs it to Pi as `docker-compose.yml`

**Never edit docker-compose.yml directly on the Pi** — those changes will be overwritten on next deploy.
