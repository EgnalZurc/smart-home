# Mosquitto MQTT Broker

Eclipse Mosquitto is the MQTT broker for Zigbee sensor communication.

## Architecture

```
┌─────────────────┐         ┌─────────────────┐         ┌─────────────────┐
│   Zigbee2MQTT   │ ──────> │    MOSQUITTO    │ <────── │   ac-service    │
│   (publisher)   │  MQTT   │   (broker:1883) │  MQTT   │   (subscriber)  │
└─────────────────┘         └─────────────────┘         └─────────────────┘
```

## Security Overview

- **Authentication**: Password-based (`passwd` file)
- **Authorization**: ACL-based topic permissions (`acl.conf`)
- **Network**: Exposed only to Docker network (not to host)
- **Anonymous**: Disabled (`allow_anonymous false`)

## Authentication

### Password File (`passwd`)

Mosquitto uses a password file with hashed credentials. The file is NOT in git (secrets).

**Location**: `/mosquitto/config/passwd` (container) → `./data/mosquitto/config/passwd` (host)

**Managing users**:
```bash
# Add/update user (inside container)
docker exec -it mosquitto mosquitto_passwd /mosquitto/config/passwd username

# Delete user
docker exec -it mosquitto mosquitto_passwd -D /mosquitto/config/passwd username

# Create new file with first user (destroys existing!)
docker exec -it mosquitto mosquitto_passwd -c /mosquitto/config/passwd username
```

**File format** (hashed, not plaintext):
```
zigbee2mqtt:$7$101$abc123...hashed...
ac-service:$7$101$def456...hashed...
```

### Current Users

| User | Purpose | Created By |
|------|---------|------------|
| `zigbee2mqtt` | Zigbee2MQTT bridge | Initial setup |
| `ac-service` | AC automation service | Initial setup |

## Authorization (ACL)

### Topic Permissions Model

ACL rules in `acl.conf` control what each user can read/write:

```
user <username>
topic <permission> <topic-pattern>
```

**Permissions**:
- `read` - Subscribe only
- `write` - Publish only  
- `readwrite` - Both subscribe and publish

**Wildcards**:
- `+` - Single level (e.g., `zigbee2mqtt/+` matches `zigbee2mqtt/sensor1`)
- `#` - Multi-level (e.g., `zigbee2mqtt/#` matches `zigbee2mqtt/bridge/state`)

### Current ACL Configuration

```
# Zigbee2MQTT - full control of its namespace
user zigbee2mqtt
topic readwrite zigbee2mqtt/#

# AC Service - read-only sensor data
user ac-service
topic read zigbee2mqtt/+
topic read zigbee2mqtt/bridge/#
```

**Principle of least privilege**:
- `zigbee2mqtt` has full access to publish sensor data and handle bridge commands
- `ac-service` can only READ sensor data, cannot publish (no device control)

### Adding a New Service

1. Create user in passwd file:
   ```bash
   docker exec -it mosquitto mosquitto_passwd /mosquitto/config/passwd new-service
   ```

2. Add ACL rules to `acl.conf`:
   ```
   # New service - describe what it needs
   user new-service
   topic read zigbee2mqtt/sensor-name
   ```

3. Add password to `.env` on Pi:
   ```bash
   echo "MQTT_NEW_SERVICE_PASSWORD=<password>" >> ~/smart-home-prod/.env
   ```

4. Restart mosquitto:
   ```bash
   docker compose restart mosquitto
   ```

## Security Best Practices

### Network Isolation

Mosquitto is NOT exposed to the host network. Only Docker containers on the `smart-home` network can connect:

```yaml
# docker-compose.prod.yml
mosquitto:
  networks:
    - smart-home
  # NO ports: section = not exposed to host
```

### Certificate Authentication (Alternative)

For higher security environments, Mosquitto supports TLS client certificates:

```
# mosquitto.conf (not currently used)
listener 8883
cafile /mosquitto/certs/ca.crt
certfile /mosquitto/certs/server.crt
keyfile /mosquitto/certs/server.key
require_certificate true
```

**Why we use password auth instead**:
- Simpler certificate management for a home network
- All traffic is internal to Docker network
- External access is via Tailscale (already encrypted)

### Monitoring for Unauthorized Access

Check for authentication failures:
```bash
docker logs mosquitto 2>&1 | grep -i "denied\|failed\|error"
```

Check connected clients:
```bash
docker exec mosquitto mosquitto_sub -u ac-service -P <password> -t '$SYS/broker/clients/connected' -C 1
```

## Files

| File | Purpose |
|------|---------|
| `mosquitto.conf` | Main configuration |
| `acl.conf` | Topic permissions per user |
| `passwd.example` | Template (real passwd is on Pi only) |

## Initial Setup (First Deploy)

After the first deploy with authentication enabled, run these commands on the Pi:

```bash
# 1. Create the passwd directory and file
cd ~/smart-home-prod
mkdir -p data/mosquitto

# 2. Generate password file (runs mosquitto_passwd inside temp container)
docker run --rm -v $(pwd)/data/mosquitto:/mosquitto/config eclipse-mosquitto:2.0.18 \
  mosquitto_passwd -c /mosquitto/config/passwd zigbee2mqtt
# Enter password when prompted

docker run --rm -v $(pwd)/data/mosquitto:/mosquitto/config eclipse-mosquitto:2.0.18 \
  mosquitto_passwd /mosquitto/config/passwd ac-service
# Enter password when prompted

# 3. Add passwords to production .env
echo "MQTT_AC_SERVICE_PASSWORD=<ac-service-password>" >> .env

# 4. Update Zigbee2MQTT configuration
nano data/zigbee2mqtt/configuration.yaml
# Under mqtt: section add:
#   user: zigbee2mqtt
#   password: <zigbee2mqtt-password>

# 5. Restart services to apply
docker compose up -d --force-recreate mosquitto zigbee2mqtt ac-service
```

## Volumes

| Container Path | Host Path | Purpose |
|---------------|-----------|---------|
| `/mosquitto/config/mosquitto.conf` | `./infrastructure/mosquitto/mosquitto.conf` | Config (git) |
| `/mosquitto/config/acl.conf` | `./infrastructure/mosquitto/acl.conf` | ACLs (git) |
| `/mosquitto/config/passwd` | `./data/mosquitto/config/passwd` | Passwords (NOT git) |
| `/mosquitto/data/` | `./data/mosquitto/data/` | Persistence |
| `/mosquitto/log/` | `./data/mosquitto/log/` | Log files |

## Troubleshooting

### Check if broker is running
```bash
docker logs mosquitto --tail 20
```

### Test authentication
```bash
docker exec mosquitto mosquitto_sub -u ac-service -P <password> -t 'zigbee2mqtt/#' -C 1 -W 5
```

### View connected clients
```bash
docker exec mosquitto mosquitto_sub -u ac-service -P <password> -t '$SYS/broker/clients/connected' -C 1
```

## Resource Limits

| Setting | Value | Purpose |
|---------|-------|---------|
| `max_connections` | 50 | Max simultaneous clients |
| `max_inflight_messages` | 20 | QoS 1/2 messages in flight |
| `max_queued_messages` | 1000 | Messages queued per client |
| `message_size_limit` | 10KB | Max message payload |
| Container memory | 16MB | Docker memory limit |
