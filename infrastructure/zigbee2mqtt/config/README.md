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
2. Generate a unique network key for your Zigbee network
3. **Configure MQTT credentials** (see below)
4. Configure your devices in the `devices` section after pairing

## MQTT Authentication

Mosquitto requires authentication. Add your credentials to `configuration.yaml`:

```yaml
mqtt:
  base_topic: zigbee2mqtt
  server: mqtt://mosquitto:1883
  user: zigbee2mqtt
  password: <your-password-here>
```

The credentials must match those created with `mosquitto_passwd` on the Pi. See `infrastructure/mosquitto/README.md` for setup instructions.

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
