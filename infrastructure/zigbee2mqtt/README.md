# Zigbee2MQTT Configuration

## Setup Instructions

1. Copy `configuration.example.yaml` to `configuration.yaml`
2. Generate a unique network key for your Zigbee network
3. Configure your devices in the `devices` section after pairing

## Files in this directory

### Source files (in git):
- `configuration.example.yaml` - Template configuration file

### Runtime files (NOT in git):
- `configuration.yaml` - Your actual configuration with network_key (sensitive)
- `database.db` - Zigbee2MQTT database with device states
- `state.json` - Current runtime state
- `coordinator_backup.json` - Zigbee coordinator backup
- `log/` - Log files directory
- `*.log` - Migration log files
- `configuration_backup_*.yaml` - Manual backup files

## Important Notes

⚠️ **Never commit `configuration.yaml` to git** - it contains your network_key which should remain private.

⚠️ **Keep backups safe** - The coordinator_backup.json and configuration.yaml are critical for recovering your Zigbee network if you need to reinstall.

## Serial Bridge Configuration

This setup uses a TCP serial bridge (`serial_bridge.py` in project root) to connect the Zigbee coordinator to Docker:
- Serial port: `COM3` (Windows)
- TCP endpoint: `tcp://host.docker.internal:8282`
- Adapter: `ember`
