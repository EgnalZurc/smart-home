# nginx Reverse Proxy

nginx serves as the reverse proxy and TLS termination point for all Cuchi Casa services.

## Architecture

```
Internet → Tailscale Funnel :443 → localhost:8443 → nginx → Docker services
                                                     ↓
                            ┌────────────────────────┼────────────────────────┐
                            ↓                        ↓                        ↓
                    dashboard:8080          ac-service:8002          vaultwarden:80
                            ...other services...
```

## Files

| File | Purpose |
|------|---------|
| `nginx.conf` | Main configuration (TLS, rate limiting, logging) |
| `conf.d/smart-home.conf` | Server blocks and location routing |
| `snippets/security-headers.conf` | Security headers shared across server blocks |
| `html/` | Static HTML files (error pages, SSO vendor page) |

## Security Configuration

### TLS Settings

Located in `nginx.conf`:

| Setting | Value | Purpose |
|---------|-------|---------|
| `ssl_protocols` | TLSv1.2 TLSv1.3 | Modern protocols only (no SSLv3, TLSv1.0/1.1) |
| `ssl_prefer_server_ciphers` | on | Server chooses cipher order |
| `ssl_ciphers` | Mozilla Intermediate | Strong AEAD ciphers only |
| `ssl_ecdh_curve` | X25519:secp384r1 | Modern elliptic curves |
| `ssl_session_tickets` | off | Disabled for forward secrecy |
| `server_tokens` | off | Hide nginx version |

Reference: [Mozilla SSL Configuration Generator](https://ssl-config.mozilla.org/)

### Security Headers

Defined in `snippets/security-headers.conf` and included in all server blocks:

| Header | Value | Purpose |
|--------|-------|---------|
| `Strict-Transport-Security` | max-age=31536000; includeSubDomains; preload | Force HTTPS for 1 year |
| `X-Frame-Options` | DENY | Prevent clickjacking |
| `X-Content-Type-Options` | nosniff | Prevent MIME-type sniffing |
| `Referrer-Policy` | strict-origin-when-cross-origin | Control referrer leakage |
| `Permissions-Policy` | geolocation=(), microphone=(), camera=() | Restrict browser APIs |
| `X-XSS-Protection` | 0 | Disable XSS auditor (recommended by MDN) |
| `X-DNS-Prefetch-Control` | off | Prevent DNS prefetch privacy leakage |
| `Cross-Origin-Opener-Policy` | same-origin | Window isolation (Spectre mitigation) |
| `Cross-Origin-Resource-Policy` | same-origin | Resource loading restriction |
| `Content-Security-Policy` | See below | Prevent XSS and injection attacks |

#### Deprecated Headers (Not Included)

| Header | Status | Reason |
|--------|--------|--------|
| `Expect-CT` | **Deprecated** | Certificate Transparency is now enforced by default in all major browsers since 2018. Chrome removed support in version 107 (Oct 2022). Adding this header provides no security benefit and increases response size. Reference: [Chrome Platform Status](https://chromestatus.com/feature/6244547273687040) |

#### Content Security Policy

The CSP in `snippets/security-headers.conf`:

```
default-src 'self';
script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://unpkg.com;
style-src 'self' 'unsafe-inline';
img-src 'self' data: https:;
connect-src 'self' wss:;
frame-ancestors 'none'
```

**Trusted CDNs**: cdn.jsdelivr.net (Chart.js), unpkg.com (common libraries)

**Known limitations**:
- `'unsafe-inline'` is required for some services (Vaultwarden web vault, dashboard inline scripts)
- Removing `'unsafe-inline'` would require refactoring services to use nonces or hashes

### Rate Limiting

Defined in `nginx.conf`:

| Zone | Rate | Burst | Purpose |
|------|------|-------|---------|
| `general` | 20 req/s | 20-30 | Normal app traffic |
| `auth` | 60 req/min | 10-20 | Authentication endpoints (brute force protection) |

Applied per-location in `conf.d/smart-home.conf`:
- `/api/auth/*` - auth zone (1 req/s effective)
- `/passwords/identity/` - auth zone (Vaultwarden login)
- `/guest/baby-gifts/` - auth zone (public guest access)
- Most other routes - general zone

### Authentication

Protected routes use `auth_request` to validate session cookies against the dashboard backend:

```nginx
location /protected-route {
    auth_request /_auth_check;
    auth_request_set $auth_user $upstream_http_x_auth_user;
    error_page 401 = @login_redirect;
    # ... proxy_pass ...
}
```

**Public routes** (no auth_request):
- `/api/health/*` - Health checks
- `/passwords/*` (except `/passwords/admin`) - Vaultwarden (has its own auth)
- `/guest/baby-gifts/*` - Token-based guest access
- `/static/*` - Static assets

### Timeout Configuration

| Setting | Standard | WebSocket | Purpose |
|---------|----------|-----------|---------|
| `proxy_connect_timeout` | 5s | 5s | Time to establish upstream connection |
| `proxy_read_timeout` | 30s | 3600s (1h) | Time waiting for upstream response |
| `proxy_send_timeout` | 30s | 3600s (1h) | Time sending request to upstream |

WebSocket routes (AC service, Vaultwarden notifications, Zigbee2MQTT) use extended timeouts.

## Future Security Improvements

### Recommended Enhancements

1. **Remove 'unsafe-inline' from CSP**
   - Requires refactoring services to use CSP nonces or external scripts
   - Priority: Medium (defense-in-depth improvement)

2. **Enable OCSP Stapling**
   - Currently disabled because we use self-signed certificates
   - Enable when switching to CA-signed certificates:
   ```nginx
   ssl_stapling on;
   ssl_stapling_verify on;
   ```

3. **Add IP allowlisting for admin routes**
   - Consider restricting `/passwords/admin`, `/zigbee/` to Tailscale IPs only
   - Example: `allow 100.64.0.0/10; deny all;`

4. **Implement fail2ban integration**
   - Monitor for 429 (rate limit) responses
   - Temporarily block IPs with repeated violations

## Troubleshooting

### Test TLS configuration
```bash
# From Pi
docker exec nginx nginx -t

# External SSL test
curl -sS https://www.ssllabs.com/ssltest/analyze.html?d=raspberrypi.tailaa37cd.ts.net
```

### Check rate limiting
```bash
# View rate limit hits in logs
ssh pi@raspberrypi.local "docker logs nginx --tail 100 2>&1 | grep 'limiting requests'"
```

### Verify security headers
```bash
curl -sI https://raspberrypi.tailaa37cd.ts.net/ | grep -E '^(Strict|X-Frame|X-Content|Content-Security|Referrer|Permissions)'
```

### Reload configuration
```bash
ssh pi@raspberrypi.local "docker exec nginx nginx -s reload"
```
