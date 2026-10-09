# Mosquitto MQTT Broker

Eclipse Mosquitto is the MQTT broker for Zigbee sensor communication.

## Architecture

```
┌─────────────────┐         ┌─────────────────┐         ┌─────────────────┐
│   Zigbee2MQTT   │ ──────> │    MOSQUITTO    │ <────── │   ac-service    │
│   (publisher)   │  MQTT   │   (broker:1883) │  MQTT   │   (subscriber)  │
└─────────────────┘         └─────────────────┘         └─────────────────┘
```

## Security

- **Authentication**: Password-based (`passwd` file)
- **Authorization**: ACL-based topic permissions (`acl.conf`)
- **Network**: Exposed only to Docker network (not to host)

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
