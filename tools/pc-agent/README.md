# pc-agent

Lightweight agent running on Windows PC for remote control from the Raspberry Pi dashboard.

## Features

- **Valheim Server Control**: Start/stop/restart the valheim-server Docker container
- **World Management**: List, create, activate, delete worlds
- **Server Configuration**: Edit .env and restart to apply
- **Server Logs**: View recent logs
- **Power Profiles**: Switch between Gaming/Servidor/Balanced power modes

## Requirements

- Windows 10/11
- Python 3.11+
- Docker Desktop (for Valheim container control)
- PowerShell scripts in `C:\Users\acmls\Documents\Scripts\`:
  - `ModoGaming.ps1`
  - `ModoServidor.ps1`
  - `ModoBalanced.ps1`

## Deployment

### Option A: Automated via GitHub Actions (recommended)

pc-agent deploys automatically when you push changes to `tools/pc-agent/` and merge to main.

**First-time setup:**

1. **Install GitHub Actions runner on your PC:**
   ```powershell
   # Download runner from: https://github.com/EgnalZurc/smart-home/settings/actions/runners/new
   # Choose: Self-hosted, Windows, x64
   
   # Extract and configure
   cd E:\actions-runner
   .\config.cmd --url https://github.com/EgnalZurc/smart-home --token <TOKEN>
   
   # Add labels: gaming-pc
   # Install as service
   .\svc.cmd install
   .\svc.cmd start
   ```

2. **Create `.env` file at `E:\pc-agent\.env`:**
   ```
   PC_AGENT_TOKEN=<same-as-pi>
   VALHEIM_CONTAINER=valheim-server
   VALHEIM_SERVER_DIR=E:\valheim-server
   SCRIPTS_DIR=C:\Users\acmls\Documents\Scripts
   ```

3. **Install pc-agent as Windows Service (first time only):**
   ```powershell
   cd E:\pc-agent
   .\install-service.ps1
   ```

4. **Create GitHub environment** `gaming-pc` in repo settings (optional, for protection rules)

After setup, any push to main that changes `tools/pc-agent/` will auto-deploy.

### Option B: Manual deployment

1. **Clone or copy the pc-agent folder** to your PC:
   ```powershell
   # Option A: Clone the repo
   git clone git@github.com:EgnalZurc/smart-home.git
   cd smart-home\tools\pc-agent
   
   # Option B: Just copy the folder manually from D:\Development\smart-home\tools\pc-agent
   ```

2. **Create `.env` from template:**
   ```powershell
   copy .env.example .env
   notepad .env
   ```
   
   Configure:
   ```
   PC_AGENT_TOKEN=<same-token-as-in-pi-.env>
   VALHEIM_CONTAINER=valheim-server
   VALHEIM_SERVER_DIR=C:\path\to\your\valheim-server
   SCRIPTS_DIR=C:\Users\acmls\Documents\Scripts
   ```

3. **Run manually (for testing):**
   ```powershell
   .\run.bat
   ```

4. **Install as Windows Service (for production):**
   ```powershell
   # Run as Administrator
   .\install-service.ps1
   ```

### Updating pc-agent

When you make changes to pc-agent:

```powershell
cd D:\Development\smart-home\tools\pc-agent

# If running as service, stop it first
nssm stop pc-agent

# Pull latest (if using git)
git pull

# Restart service
nssm start pc-agent
```

### Firewall

Allow inbound connections on port 8090:

```powershell
New-NetFirewallRule -DisplayName "pc-agent" -Direction Inbound -Port 8090 -Protocol TCP -Action Allow
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `PC_AGENT_TOKEN` | (empty) | API token for authentication |
| `VALHEIM_CONTAINER` | `valheim-server` | Docker container name |
| `VALHEIM_SERVER_DIR` | `C:\valheim-server` | Valheim server installation |
| `SCRIPTS_DIR` | `C:\Users\acmls\Documents\Scripts` | Power profile scripts |

The Valheim paths are relative to `VALHEIM_SERVER_DIR`:
- `.env` — Server configuration
- `server_data/worlds_local/` — World save folders
- `server_data/logs/` — Server log files

## API Endpoints

### Health (no auth)
```
GET /health
```

### Valheim Server
```
GET  /valheim/status        # Container + server status
POST /valheim/start         # Start container
POST /valheim/stop          # Stop container (30s graceful)
POST /valheim/restart       # Restart container
GET  /valheim/config        # Server .env config
POST /valheim/config        # Update config + restart
GET  /valheim/logs          # Recent log lines
GET  /valheim/worlds        # List worlds
POST /valheim/worlds/new    # Create world
POST /valheim/worlds/activate  # Switch world + restart
DELETE /valheim/worlds/{name}  # Delete world
```

### Power Profiles
```
GET  /system/mode           # Current profile
POST /system/mode/{mode}    # Set profile (gaming/servidor/balanced)
```

All endpoints except `/health` require `X-Api-Token` header.

## Architecture

```
┌───────────────────────────────────────────────────────────────────┐
│                  Raspberry Pi (192.168.1.163)                     │
│  ┌──────────┐      ┌───────────────┐                              │
│  │ Dashboard │─────▶│ valheim-admin │──────────────────────────────┤
│  └──────────┘      └───────────────┘                              │
└───────────────────────────────────────────────────────────────────┘
                              │
                              │ HTTP (WiFi: 192.168.1.x)
                              ▼
┌───────────────────────────────────────────────────────────────────┐
│                  Windows PC (192.168.1.164)                       │
│  ┌───────────────┐                                                │
│  │   pc-agent    │──────┬────────────────────────────────────────┐│
│  │ (Python:8090) │      │                                        ││
│  └───────────────┘      ▼                                        ││
│        │         ┌─────────────────┐   ┌───────────────────────┐ ││
│        │         │ Docker Desktop  │   │ C:\valheim-server\    │ ││
│        │         │ valheim-server  │◀──│ .env, worlds, logs    │ ││
│        │         └─────────────────┘   └───────────────────────┘ ││
│        │                                                         ││
│        └────────▶ PowerShell scripts (power profiles)            ││
└───────────────────────────────────────────────────────────────────┘
```

## Logs

When running as service:
```powershell
Get-Content logs\stdout.log -Tail 50 -Wait
```

## Troubleshooting

**"Docker not available"**
- Ensure Docker Desktop is running
- Check Docker is accessible: `docker ps`

**"PC unreachable" from Pi**
- Check PC IP: `Get-NetIPAddress -AddressFamily IPv4`
- Check firewall allows port 8090
- Test from Pi: `curl http://192.168.1.164:8090/health`

**"Invalid token"**
- Ensure `PC_AGENT_TOKEN` matches in both:
  - `pc-agent/.env` (on PC)
  - `smart-home-prod/.env` (on Pi)
