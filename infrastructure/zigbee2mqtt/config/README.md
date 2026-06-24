# Zigbee2MQTT Configuration

## Directory Structure

This directory contains only configuration files (source code). All runtime data is stored in the centralized `/data/zigbee2mqtt/` directory at the project root.

```
project_root/
├── infrastructure/
│   └── zigbee2mqtt/
│       └── config/                      # Configuration files (source code - in git)
│           ├── configuration.yaml       # Your actual config with secrets (NOT in git)
│           ├── configuration.example.yaml  # Template without secrets (in git)
│           └── README.md                # This file (in git)
└── data/
    └── zigbee2mqtt/                     # Runtime data (NOT in git)
        ├── database.db                  # Zigbee2MQTT database
        ├── state.json                   # Current device states
        ├── coordinator_backup.json      # Coordinator backup
        ├── log/                         # Log files directory
        └── *.log                        # Migration logs
```

## Setup Instructions

1. Copy `configuration.example.yaml` to `configuration.yaml`
2. Generate a unique network key for your Zigbee network
3. Configure your devices in the `devices` section after pairing

## Files Description

### Source files (in git):
- `configuration.example.yaml` - Template configuration file
- `README.md` - This documentation

### Runtime files (NOT in git - located in `/data/zigbee2mqtt/`):
- Runtime database, logs, state, and backups are stored in the centralized data directory

## Important Notes

⚠️ **Never commit `configuration.yaml` to git** - it contains your network_key which should remain private.

⚠️ **Keep backups safe** - The coordinator_backup.json and configuration.yaml are critical for recovering your Zigbee network if you need to reinstall.

⚠️ **All runtime data is centralized** - Check `/data/zigbee2mqtt/` at the project root for all runtime files.

## Serial Bridge Configuration

This setup uses a TCP serial bridge (`serial_bridge.py` in project root) to connect the Zigbee coordinator to Docker:
- Serial port: `COM3` (Windows)
- TCP endpoint: `tcp://host.docker.internal:8282`
- Adapter: `ember`
