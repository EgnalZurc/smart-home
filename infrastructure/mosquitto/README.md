# Mosquitto MQTT Broker

Eclipse Mosquitto broker for the smart-home stack. All MQTT traffic (Zigbee2MQTT ↔ sensors, ac-service ↔ sensors) flows through this broker.

## Security Configuration

As of this setup, **anonymous access is disabled**. All clients must authenticate.

### First-Time Setup (on the Pi)

1. **Create the password file** before starting the containers:

   ```bash
   cd ~/smart-home-prod
   
   # Create empty file first (Mosquitto won't start without it)
   touch infrastructure/mosquitto/passwd
   
   # Start mosquitto temporarily to create users
   docker compose up -d mosquitto
   
   # Add users (you'll be prompted for passwords)
   docker exec -it mosquitto mosquitto_passwd -c /mosquitto/config/passwd zigbee2mqtt
   docker exec -it mosquitto mosquitto_passwd /mosquitto/config/passwd ac-service
   
   # Restart to pick up the new credentials
   docker compose restart mosquitto
   ```

2. **Update Zigbee2MQTT configuration** (`data/zigbee2mqtt/configuration.yaml`):

   ```yaml
   mqtt:
     base_topic: zigbee2mqtt
     server: mqtt://mosquitto:1883
     user: zigbee2mqtt
     password: <the password you set above>
   ```

3. **Update ac-service environment** (`.env`):

   ```bash
   MQTT_USER=ac-service
   MQTT_PASSWORD=<the password you set above>
   ```

4. **Restart all services**:

   ```bash
   docker compose up -d --force-recreate zigbee2mqtt ac-service
   ```

### Adding More MQTT Users

```bash
docker exec -it mosquitto mosquitto_passwd /mosquitto/config/passwd <new-username>
docker compose restart mosquitto
```

### Troubleshooting

**"Connection refused" after enabling auth:**
- Verify the password file exists: `docker exec mosquitto cat /mosquitto/config/passwd`
- Check credentials match between services and the password file
- Look at mosquitto logs: `docker logs mosquitto --tail 50`

**Services can't connect:**
- Services connect via Docker DNS (`mosquitto:1883`), not localhost
- Port 1883 is no longer exposed to the host (internal network only)

## Files

| File | Purpose |
|------|---------|
| `mosquitto.conf` | Main configuration (auth, persistence, logging) |
| `passwd` | Password file (created on first deploy, NOT committed) |

## Network

- **Internal port:** 1883 (Docker network `smart-home`)
- **Host exposure:** None (removed for security)
- **Accessible from:** zigbee2mqtt, ac-service, any service on `smart-home` network
