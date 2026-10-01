# Vaultwarden Proxy Configuration

## Overview

Vaultwarden is deployed behind nginx with a **subpath configuration** (`DOMAIN=/passwords`).
This means all Vaultwarden routes are served under `/passwords/*`.

However, Bitwarden clients (browser extensions, mobile apps, desktop apps) may call
API endpoints **without** the `/passwords` prefix, especially if the server URL is
configured as `https://host/passwords` but the client internally removes the path
for certain API calls.

## The Problem: HTTP 301 Redirects Break POST Requests

### What Happened

Initially, we used HTTP 301 redirects to handle legacy routes:

```nginx
# ❌ BROKEN - DO NOT USE
location /identity/ { return 301 /passwords$request_uri; }
```

This caused authentication failures because:

1. Client sends `POST /identity/connect/token` (login request)
2. Nginx returns `301 Moved Permanently` to `/passwords/identity/connect/token`
3. Browser follows redirect but **converts POST to GET** (HTTP spec behavior)
4. Vaultwarden receives GET instead of POST → returns 404 or error
5. Client shows "Syncing failed" or "An error has occurred"

### The Fix: Use rewrite + proxy_pass

```nginx
# ✅ CORRECT - Preserves HTTP method
location /identity/ {
    rewrite ^/identity/(.*)$ /passwords/identity/$1 break;
    proxy_pass http://vaultwarden:80;
    # ... headers ...
}
```

This internally rewrites the URL and proxies directly, preserving the original
HTTP method (POST, PUT, DELETE, etc.).

## Complete List of Bitwarden API Endpoints

Based on the official Bitwarden API documentation, these endpoints must be proxied:

### Authentication
- `/identity/connect/token` - OAuth2 token endpoint (login, refresh)
- `/identity/accounts/*` - Account registration

### Core API (`/api/*`)
| Endpoint | Description |
|----------|-------------|
| `/api/sync` | Full vault sync |
| `/api/accounts/*` | Account management |
| `/api/ciphers/*` | Password entries (logins, cards, notes, identities) |
| `/api/folders/*` | Folder management |
| `/api/collections/*` | Collection management (organizations) |
| `/api/organizations/*` | Organization management |
| `/api/sends/*` | Bitwarden Send (secure sharing) |
| `/api/settings/*` | User settings |
| `/api/devices/*` | Device management |
| `/api/two-factor/*` | 2FA setup and management |
| `/api/auth-requests/*` | Passwordless login requests |
| `/api/emergency-access/*` | Emergency access contacts |
| `/api/events/*` | Event logs |
| `/api/groups/*` | Organization groups |
| `/api/hibp/*` | Have I Been Pwned integration |
| `/api/import/*` | Import from other password managers |
| `/api/notifications/*` | Push notification registration |
| `/api/policies/*` | Organization policies |
| `/api/push/*` | Push notifications |
| `/api/reports/*` | Security reports |
| `/api/users/*` | User management |
| `/api/web-authn/*` | WebAuthn/FIDO2 authentication |

### Other Endpoints
- `/notifications/` - WebSocket for real-time sync
- `/icons/*` - Website favicon proxy
- `/vw_static/*` - Static assets for web vault

## Current nginx Configuration

```nginx
# Main route - all /passwords/* requests
location /passwords/ {
    proxy_pass http://vaultwarden:80;
    # WebSocket support for notifications
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
}

# Legacy routes - rewrite + proxy (NOT redirect!)
location /identity/ {
    rewrite ^/identity/(.*)$ /passwords/identity/$1 break;
    proxy_pass http://vaultwarden:80;
}

location ~ ^/api/(sync|accounts|ciphers|...) {
    rewrite ^/api/(.*)$ /passwords/api/$1 break;
    proxy_pass http://vaultwarden:80;
}

location /notifications/ {
    rewrite ^/notifications/(.*)$ /passwords/notifications/$1 break;
    proxy_pass http://vaultwarden:80;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
}
```

## Debugging Tips

### Check nginx access logs for failed requests
```bash
docker exec nginx-reverse-proxy tail -100 /var/log/nginx/access.log | grep -E "identity|api/sync|passwords"
```

### Look for 301/404 responses
```bash
# 301 = redirect (may break POST)
# 404 = route not found
# 200 = success
# 401 = auth required (expected for protected endpoints)
```

### Test endpoints directly
```bash
# Inside the Pi
curl -X POST http://vaultwarden:80/passwords/identity/connect/token \
  -H "Content-Type: application/x-www-form-urlencoded"
# Should return 400 (bad request) or 422 (missing params), NOT 404
```

## Lessons Learned

### For Future Services with Subpath Deployments

1. **Never use 301/302 redirects for API endpoints** - they convert POST/PUT/DELETE to GET
2. **Use `rewrite ... break` + `proxy_pass`** to preserve HTTP methods
3. **Test with actual clients**, not just curl GET requests
4. **Check client behavior** - some clients strip the path from Server URL
5. **Document all endpoints** that need legacy route support

### When to Use Redirects vs Rewrite+Proxy

| Scenario | Solution |
|----------|----------|
| User bookmarks old URL | 301 redirect (browser will update bookmark) |
| API endpoint | rewrite + proxy_pass (preserve HTTP method) |
| Static assets | Either works |
| WebSocket | rewrite + proxy_pass (connection upgrade) |

## Related Files

- `infrastructure/nginx/conf.d/smart-home.conf` - nginx configuration
- `docker-compose.yml` - Vaultwarden container with `DOMAIN` env var
- `.kiro/steering/vaultwarden.md` - Vaultwarden service documentation

## References

- [Vaultwarden Wiki - Proxy Examples](https://github.com/dani-garcia/vaultwarden/wiki/Proxy-examples)
- [Bitwarden API Documentation](https://bitwarden.com/help/bitwarden-apis/)
- [HTTP 301 and POST requests](https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/301)
