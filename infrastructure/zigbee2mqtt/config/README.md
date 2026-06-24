# Zigbee2MQTT Configuration

## Directory Structure

This directory follows a clean separation between code and runtime data:

```
infrastructure/zigbee2mqtt/
├── config/                          # Configuration files (source code - in git)
│   ├── configuration.yaml           # Your actual config with secrets (NOT in git)
│   ├── configuration.example.yaml  # Template without secrets (in git)
│   └── README.md                    # This file (in git)
└── data/                            # Runtime data (NOT in git)
    ├── database.db                  # Zigbee2MQTT database
    ├── state.json                   # Current device states
    ├── coordinator_backup.json      # Coordinator backup
    ├── log/                         # Log files directory
    └── *.log                        # Migration logs
```

## Setup Instructions

1. Copy `config/configuration.example.yaml` to `config/configuration.yaml`
2. Generate a unique network key for your Zigbee network
3. Configure your devices in the `devices` section after pairing

## Files Description

### Source files (in git):
- `config/configuration.example.yaml` - Template configuration file
- `config/README.md` - This documentation

### Runtime files (NOT in git):
- `config/configuration.yaml` - Your actual configuration with network_key (sensitive)
- `data/database.db` - Zigbee2MQTT database with device states
- `data/state.json` - Current runtime state
- `data/coordinator_backup.json` - Zigbee coordinator backup
- `data/log/` - Log files directory
- `data/*.log` - Migration log files
- `data/configuration_backup_*.yaml` - Manual backup files

## Important Notes

⚠️ **Never commit `config/configuration.yaml` to git** - it contains your network_key which should remain private.

⚠️ **Keep backups safe** - The coordinator_backup.json and configuration.yaml are critical for recovering your Zigbee network if you need to reinstall.

⚠️ **The entire `data/` directory is gitignored** - all runtime files are kept separate from source code.

## Serial Bridge Configuration

This setup uses a TCP serial bridge (`serial_bridge.py` in project root) to connect the Zigbee coordinator to Docker:
- Serial port: `COM3` (Windows)
- TCP endpoint: `tcp://host.docker.internal:8282`
- Adapter: `ember`
