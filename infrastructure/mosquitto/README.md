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

## TLS/SSL Encryption

For environments requiring encrypted MQTT traffic (external clients, compliance requirements), Mosquitto supports TLS on port 8883.

### When to Use TLS

| Scenario | TLS Recommended? |
|----------|------------------|
| All clients on Docker network | No - already isolated |
| External access via Tailscale | No - Tailscale encrypts |
| Direct external access (port forwarding) | **Yes** |
| Compliance/audit requirements | **Yes** |
| Mixed internal + external clients | Yes for external listener |

**Current setup**: We use password auth over the isolated Docker network, with Tailscale for any external access. TLS adds overhead without security benefit in this configuration.

### TLS Setup Guide

See `mosquitto-tls.conf.example` for a complete TLS configuration template.

#### Step 1: Generate Certificates

**Option A: Self-signed (internal/testing)**

```bash
# Create certs directory
mkdir -p ~/smart-home-prod/data/mosquitto/certs
cd ~/smart-home-prod/data/mosquitto/certs

# Generate CA (Certificate Authority)
openssl genrsa -out ca.key 2048
openssl req -x509 -new -nodes -key ca.key -sha256 -days 3650 \
  -out ca.crt -subj "/CN=Mosquitto CA"

# Generate server key and CSR
openssl genrsa -out server.key 2048
openssl req -new -key server.key -out server.csr \
  -subj "/CN=mosquitto"

# Sign server certificate with CA
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key \
  -CAcreateserial -out server.crt -days 3650 -sha256

# Clean up CSR
rm server.csr

# Set permissions (mosquitto runs as uid 1883 in container)
chmod 644 ca.crt server.crt
chmod 640 server.key ca.key
sudo chown 1883:1883 server.key
```

**Option B: Let's Encrypt (public domain)**

```bash
# Install certbot
sudo apt install certbot

# Get certificate (requires port 80 accessible)
sudo certbot certonly --standalone -d mqtt.yourdomain.com

# Certificates will be at:
# /etc/letsencrypt/live/mqtt.yourdomain.com/fullchain.pem
# /etc/letsencrypt/live/mqtt.yourdomain.com/privkey.pem
```

#### Step 2: Update docker-compose.prod.yml

Add certificate volume mounts and expose port 8883:

```yaml
mosquitto:
  image: eclipse-mosquitto:2.0.18
  ports:
    - "8883:8883"  # TLS MQTT
  volumes:
    - ./infrastructure/mosquitto/mosquitto.conf:/mosquitto/config/mosquitto.conf:ro
    - ./infrastructure/mosquitto/acl.conf:/mosquitto/config/acl.conf:ro
    - ./data/mosquitto/config/passwd:/mosquitto/config/passwd:ro
    - ./data/mosquitto/certs:/mosquitto/certs:ro  # Add this
    - ./data/mosquitto/data:/mosquitto/data
    - ./data/mosquitto/log:/mosquitto/log
```

For Let's Encrypt:
```yaml
    - /etc/letsencrypt/live/mqtt.yourdomain.com/fullchain.pem:/mosquitto/certs/server.crt:ro
    - /etc/letsencrypt/live/mqtt.yourdomain.com/privkey.pem:/mosquitto/certs/server.key:ro
```

#### Step 3: Update mosquitto.conf

Add TLS listener configuration:

```
# TLS listener on standard port
listener 8883
cafile /mosquitto/certs/ca.crt
certfile /mosquitto/certs/server.crt
keyfile /mosquitto/certs/server.key
tls_version tlsv1.2

# Keep internal plain listener for Docker network
listener 1883
```

#### Step 4: Test TLS Connection

```bash
# From a machine with the CA certificate
mosquitto_sub -h raspberrypi.local -p 8883 \
  --cafile ca.crt \
  -u ac-service -P <password> \
  -t 'zigbee2mqtt/#' -C 1

# Test with openssl
openssl s_client -connect raspberrypi.local:8883 -CAfile ca.crt
```

### Client Certificate Authentication (mTLS)

For highest security, require client certificates instead of passwords:

```
# In mosquitto.conf
require_certificate true
use_identity_as_username true
```

With `use_identity_as_username`, the certificate's Common Name (CN) becomes the MQTT username for ACL matching.

**Generate client certificate:**

```bash
# Generate client key
openssl genrsa -out client.key 2048

# Generate client CSR (CN must match ACL username)
openssl req -new -key client.key -out client.csr \
  -subj "/CN=ac-service"

# Sign with CA
openssl x509 -req -in client.csr -CA ca.crt -CAkey ca.key \
  -CAcreateserial -out client.crt -days 365 -sha256
```

**Connect with client certificate:**

```bash
mosquitto_sub -h raspberrypi.local -p 8883 \
  --cafile ca.crt \
  --cert client.crt \
  --key client.key \
  -t 'zigbee2mqtt/#'
```

### Let's Encrypt Auto-Renewal

Set up a deploy hook to reload mosquitto after certificate renewal:

```bash
# /etc/letsencrypt/renewal-hooks/deploy/mosquitto-reload.sh
#!/bin/bash
docker exec mosquitto kill -HUP 1
```

```bash
chmod +x /etc/letsencrypt/renewal-hooks/deploy/mosquitto-reload.sh
```

### Troubleshooting TLS

**Check certificate validity:**
```bash
openssl x509 -in server.crt -text -noout | grep -A2 "Validity"
```

**Test TLS handshake:**
```bash
openssl s_client -connect raspberrypi.local:8883 -CAfile ca.crt -brief
```

**Common errors:**

| Error | Cause | Fix |
|-------|-------|-----|
| `certificate verify failed` | CA not trusted | Add CA to client's trusted store or use `--cafile` |
| `unable to get local issuer certificate` | Missing CA cert | Provide `cafile` in config |
| `certificate has expired` | Cert expired | Regenerate certificate |
| `wrong version number` | Plain MQTT to TLS port | Use port 8883 with TLS, 1883 without |
| `permission denied` reading key | Wrong file perms | `chmod 640 server.key; chown 1883:1883 server.key` |

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
| `mosquitto-tls.conf.example` | TLS configuration template |
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
