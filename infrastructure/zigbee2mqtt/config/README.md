# Zigbee2MQTT Configuration

## Directory Structure

This directory contains configuration templates. The actual runtime configuration is stored in `/data/zigbee2mqtt/configuration.yaml`.

```
project_root/
├── infrastructure/
│   └── zigbee2mqtt/
│       └── config/                      # Configuration templates (in git)
│           ├── configuration.example.yaml  # Template without secrets (in git)
│           └── README.md                # This file (in git)
└── data/
    └── zigbee2mqtt/                     # Runtime data AND config (NOT in git)
        ├── configuration.yaml           # Actual config with secrets
        ├── database.db                  # Zigbee2MQTT database
        ├── state.json                   # Current device states
        ├── coordinator_backup.json      # Coordinator backup
        ├── log/                         # Log files directory
        └── *.log                        # Migration logs
```

## Setup Instructions

1. Copy `configuration.example.yaml` to `/data/zigbee2mqtt/configuration.yaml`
2. Generate a unique network key (see below)
3. Configure your devices in the `devices` section after pairing

## Generating the Network Key

The `network_key` is a 128-bit encryption key that secures all Zigbee traffic in your network.

### Generate a secure key

```bash
# On Linux/macOS/Pi:
openssl rand -hex 16

# Output example: a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6
```

### Apply the key

In `/data/zigbee2mqtt/configuration.yaml`, replace the `GENERATE` placeholder:

```yaml
advanced:
  network_key: a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6  # Your generated key
```

### ⚠️ Important warnings

- **Unique per installation**: Never reuse a network key from another network or from documentation examples.
- **Changing the key requires re-pairing ALL devices**: The key encrypts the Zigbee mesh. If you change it, existing devices cannot communicate and must be factory-reset and re-paired.
- **Keep it secret**: Anyone with your network key can decrypt your Zigbee traffic and potentially inject malicious commands.
- **Back it up**: Store the key securely (password manager, encrypted backup). Losing it means re-pairing everything.

## Files Description

### Source files (in git):
- `configuration.example.yaml` - Template configuration file
- `README.md` - This documentation

### Runtime files (NOT in git - located in `/data/zigbee2mqtt/`):
- `configuration.yaml` - Your actual configuration with network_key (sensitive)
- Runtime database, logs, state, and backups

## Important Notes

⚠️ **Configuration is in `/data/zigbee2mqtt/configuration.yaml`** - NOT in this directory.

⚠️ **Never commit `/data/` to git** - it contains your network_key and runtime data.

⚠️ **Keep backups safe** - The coordinator_backup.json and configuration.yaml are critical for recovering your Zigbee network if you need to reinstall.

## Serial Bridge Configuration

This setup uses a TCP serial bridge (`scripts/serial_bridge.py`) to connect the Zigbee coordinator to Docker:
- Serial port: `COM3` (Windows)
- TCP endpoint: `tcp://host.docker.internal:8282`
- Adapter: `ember`

## Frontend Authentication

The Zigbee2MQTT frontend is protected by two layers of authentication:

### Layer 1: nginx auth_request (primary)
All requests to `/zigbee/` go through nginx's `auth_request` directive, which validates the user's session cookie against the main dashboard. Unauthenticated users are redirected to the login page.

### Layer 2: Z2M auth_token (defense-in-depth)
As an additional security measure, the frontend can require an auth token. This protects against scenarios where nginx auth might be bypassed (misconfiguration, internal network access, etc.).

#### Setup

1. Generate a secure token:
   ```bash
   openssl rand -hex 32
   ```

2. Add it to `.env` on the Pi:
   ```bash
   Z2M_FRONTEND_PASSWORD=your_generated_token_here
   ```

3. Update `/data/zigbee2mqtt/configuration.yaml`:
   ```yaml
   frontend:
     enabled: true
     port: 8081
     auth_token: '!env Z2M_FRONTEND_PASSWORD'
   ```

4. Restart the zigbee2mqtt container:
   ```bash
   docker compose restart zigbee2mqtt
   ```

The `!env` directive tells Zigbee2MQTT to read the value from the environment variable. If `Z2M_FRONTEND_PASSWORD` is empty or not set, the frontend will have no token protection (nginx auth still applies).
