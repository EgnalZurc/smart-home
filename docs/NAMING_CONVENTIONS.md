# Naming Conventions & Deployment Guidelines

## ⚠️ Critical Rule: Service Name = Container Name = DNS Name

In Docker Compose, containers communicate using the **service name** as DNS hostname within the Docker network. This is the most common source of 502/504 errors.

### The Rule

```yaml
services:
  # Service name MUST match what nginx/other services use for DNS resolution
  smart-home-backend:           # ← This is the DNS name used internally
    image: egnal/smart-home-dashboard:latest
    container_name: smart-home-backend  # ← This is for docker ps/logs
```

### ❌ Wrong (causes 502 errors)

```yaml
services:
  dashboard:                    # ← nginx tries to connect to "smart-home-backend"
    container_name: smart-home-backend  # ← but DNS only knows "dashboard"
```

### ✅ Correct

```yaml
services:
  smart-home-backend:           # ← Service name = what nginx config uses
    container_name: smart-home-backend
```

---

## Service Naming Table

| Service | docker-compose name | container_name | nginx upstream | Port |
|---------|---------------------|----------------|----------------|------|
| Dashboard/Backend | `smart-home-backend` | `smart-home-backend` | `smart-home-backend:8080` | 8080 |
| AC Service | `ac-service` | `ac-service` | `ac-service:8002` | 8002 |
| Baby Gifts | `baby-gifts-service` | `baby-gifts-service` | `baby-gifts-service:8004` | 8004 |
| Vacaciones | `vacaciones-service` | `vacaciones-service` | `vacaciones-service:8003` | 8003 |
| Casita Sueños | `casita-suenos` | `casita-suenos` | `casita-suenos:8001` | 8001 |
| Nginx | `nginx` | `nginx-reverse-proxy` | N/A | 80, 8443 |
| Mosquitto | `mosquitto` | `mosquitto` | N/A | 1883 |
| Zigbee2MQTT | `zigbee2mqtt` | `zigbee2mqtt` | `zigbee2mqtt:8081` | 8081 |

---

## External Services (Not in smart-home network)

Services running in separate Docker networks (e.g., Vaultwarden, Immich) cannot be accessed by service name. Use the Docker host IP instead:

```nginx
# ❌ Wrong - vaultwarden is in a different network
proxy_pass http://vaultwarden:80/;

# ✅ Correct - use Docker host bridge IP
proxy_pass http://172.17.0.1:8888/;
```

### Finding the Docker bridge IP

```bash
docker network inspect bridge --format '{{range .IPAM.Config}}{{.Gateway}}{{end}}'
# Usually: 172.17.0.1
```

---

## Pre-Deployment Checklist

Before deploying, verify:

1. **Service names match nginx config:**
   ```bash
   # Check what nginx expects
   grep -E 'proxy_pass|upstream' infrastructure/nginx/conf.d/smart-home.conf
   
   # Check docker-compose service names
   grep -E '^  [a-z]' docker-compose.prod.yml | head -20
   ```

2. **All services are in the same network:**
   ```yaml
   services:
     my-service:
       networks:
         - smart-home  # Must match nginx's network
   ```

3. **Ports are exposed (not published):**
   ```yaml
   services:
     my-service:
       expose:
         - 8080  # Internal only, nginx handles external access
   ```

4. **Test nginx config before reload:**
   ```bash
   docker exec nginx-reverse-proxy nginx -t
   ```

---

## Troubleshooting 502 Bad Gateway

1. **Check container is running:**
   ```bash
   docker ps | grep <service-name>
   ```

2. **Check service is listening on expected port:**
   ```bash
   docker exec <container> ss -tlnp
   # or
   docker logs <container> | tail -20
   ```

3. **Test connectivity from nginx:**
   ```bash
   docker exec nginx-reverse-proxy wget -qO- http://<service-name>:<port>/health
   ```

4. **Check DNS resolution:**
   ```bash
   docker exec nginx-reverse-proxy nslookup <service-name>
   ```

5. **Check nginx error logs:**
   ```bash
   docker logs nginx-reverse-proxy 2>&1 | grep -i error | tail -20
   ```

---

## Adding a New Service

When adding a new service:

1. **Define service in docker-compose.prod.yml:**
   ```yaml
   new-service:
     image: egnal/smart-home-new-service:latest
     container_name: new-service
     expose:
       - 8005
     networks:
       - smart-home
   ```

2. **Add nginx location block** in `infrastructure/nginx/conf.d/smart-home.conf`:
   ```nginx
   location /new-service {
       set $new_host "new-service";
       proxy_pass http://$new_host:8005;
       # ... headers ...
   }
   ```

3. **Update this naming table** with the new service.

4. **Update docs/API.md** with new endpoints.

5. **Test locally before deploying:**
   ```bash
   docker-compose -f docker-compose.prod.yml config  # Validate YAML
   docker-compose -f docker-compose.prod.yml up -d
   curl http://localhost/new-service/health
   ```

---

## Common Mistakes

| Mistake | Symptom | Fix |
|---------|---------|-----|
| Service name ≠ nginx upstream | 502 Bad Gateway | Match service name to nginx config |
| Service in wrong network | 502 Bad Gateway | Add `networks: [smart-home]` |
| External service accessed by name | 502 Bad Gateway | Use `172.17.0.1:<port>` |
| Port mismatch | 502 Bad Gateway | Verify port in Dockerfile/CMD matches compose |
| Container not started | 502 Bad Gateway | Check `docker ps` and logs |

---

Last updated: September 2026
