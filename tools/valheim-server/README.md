# Valheim Dedicated Server

Valheim game server running on Egnal's Windows PC, controlled remotely via the smart-home dashboard.

## Architecture

```
Dashboard (Pi) → valheim-admin (Pi) → pc-agent (PC) → valheim-server (PC)
```

## Requirements

- Windows PC with Docker Desktop
- pc-agent running (see `tools/pc-agent/`)
- Port forwarding: 2456-2458 UDP to PC IP

## Setup

1. Create directory: `E:\valheim-server`
2. Copy files:
   ```powershell
   Copy-Item docker-compose.yml E:\valheim-server\
   Copy-Item .env.example E:\valheim-server\.env
   ```
3. Edit `.env` with your server password
4. Create data directories:
   ```powershell
   mkdir E:\valheim-server\server_files
   mkdir E:\valheim-server\server_data
   ```
5. Start:
   ```powershell
   cd E:\valheim-server
   docker compose up -d
   ```

## Resource Limits

- Memory limit: 8 GB (prevents runaway usage)
- Memory reservation: 2 GB (guaranteed minimum)

Typical usage: 1.5-2 GB RAM, ~30% CPU with 1-2 players.

## Management

Use the dashboard's Valheim panel or valheim-admin UI to:
- Start/stop server
- View logs
- Change world
- Monitor players

## Worlds

Worlds are stored in `E:\valheim-server\server_data\worlds_local/`.
Backups run every 12 hours and keep 3 days of history.
