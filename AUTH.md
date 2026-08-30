# Cuchi Casa — Authentication System

> **Audience:** AI agents and maintainers working on `smart-home`.
> Read this before touching any auth-related file.

---

## Overview

Authentication is centralised in the FastAPI **backend** container.
nginx no longer does HTTP Basic Auth — it is a pure TLS terminator and
reverse proxy. Every protected route goes through `AuthMiddleware` in
`src/backend/main.py`.

### Two-cookie model

| Cookie | Name | TTL | Storage | Purpose |
|---|---|---|---|---|
| Session | `smh_session` | 24 h | Stateless JWT | Authenticates every request |
| Device | `smh_device` | 1 year | Opaque token in SQLite | Silently refreshes expired sessions |

Both cookies are **HttpOnly + Secure + SameSite=Strict**. Neither is
accessible from JavaScript.

---

## Request lifecycle

```
Browser → nginx (TLS) → FastAPI AuthMiddleware
                              │
                 ┌────────────┼────────────────────────────────┐
                 │            │                                  │
           Public path   Valid smh_session JWT        No valid JWT
           /auth/*, /health,  │                                  │
           /static/*          │                        smh_device present?
                 │            │                         │              │
               pass        pass                       YES              NO
                                                        │              │
                                              verify_and_rotate()   → 302
                                               │           │       /auth/login
                                             OK          THEFT        ?next=…
                                               │           │
                                    issue new JWT    delete ALL
                                    rotate cookie    device tokens
                                    → pass           → 302 /auth/login
                                                       ?alert=theft
```

---

## File map

```
src/backend/
├── auth.py              JWT helpers (create/decode/cookie)
├── auth_users.py        Password verification (.htpasswd) + trust request DB
├── auth_devices.py      Jaspan device token DB (create/verify/rotate/revoke)
├── api/
│   └── auth_routes.py   FastAPI router: /auth/* endpoints
├── main.py              AuthMiddleware + config injection
└── static/
    └── login.html       Login page (served by auth_routes.py)
```

---

## Module responsibilities

### `auth.py`

- `verify_password(plain, hash)` — checks against `$apr1$` (Apache apr_md5_crypt)
- `create_token(username)` — signs 24h JWT with HS256
- `decode_token(token)` — returns payload or `None` if expired/invalid
- `get_current_user(request)` — reads `smh_session` cookie, returns username or `None`
- `set_session_cookie(response, token)` / `clear_session_cookie(response)`

Configuration globals (injected by `main.py` lifespan, never hardcoded):
`AUTH_SECRET`, `AUTH_SESSION_TTL`

---

### `auth_users.py`

**Password store** — reads `/etc/nginx/.htpasswd` on every login call
(no in-memory cache — file is small, change is instant).

**Trust request table** (`trusted_devices` in `auth.db`):

```sql
id, token (opaque), username, user_agent, ip_address,
requested_at, status (pending|approved|rejected), resolved_at
```

Key functions:
- `authenticate_user(username, password)` — constant-time comparison,
  does a dummy hash check even for unknown usernames (prevents timing attacks)
- `create_trust_request(username, ua, ip)` → returns opaque token
- `has_active_trust_request(username)` → bool (dedup guard)
- `get_approved_trust_request(username)` → row dict or None
- `delete_trust_request(token)` → called after device token is issued
- `resolve_trust_request(token, 'approved'|'rejected')` → called from email links
- `make_action_url(base_url, token, action)` → builds HMAC-signed URL for email
- `verify_action_sig(token, action, sig)` → validates HMAC before acting

The HMAC on email links uses `hmac.compare_digest` (constant-time) and
`AUTH_SECRET` as key. Signature format: `HMAC-SHA256(action:token)`.

Configuration globals: `HTPASSWD_PATH`, `AUTH_DB_PATH`, `TRUST_SECRET`

---

### `auth_devices.py` — Jaspan pattern

**Why not a long-lived JWT?** A JWT cannot be revoked without rotating the
secret for all users. A stolen 1-year JWT gives an attacker full access for
up to a year. Opaque tokens stored in DB can be revoked individually.

**Device token table** (`device_tokens` in `auth.db`):

```sql
series      TEXT PRIMARY KEY   -- stable ID for this device (never changes)
token_hash  TEXT               -- SHA-256 of current one-time token
username    TEXT
user_agent  TEXT
ip_address  TEXT
created_at  REAL
last_used   REAL
expires_at  REAL               -- creation + 1 year
```

**Cookie format:** `smh_device=<series_b64>:<token_b64>`
Only `SHA-256(token)` is stored — a DB leak does not yield usable cookies.

**`verify_and_rotate(cookie_value)`** — the core function:

| Condition | Result |
|---|---|
| Cookie malformed | `ok=False` |
| Series unknown | `ok=False` (silent) |
| Series found, token matches, not expired | Rotate token in DB → `ok=True, new_cookie_value=…` |
| Series found, **token does NOT match** | **Theft detected** — delete ALL device tokens for that user → `ok=False, theft_detected=True` |
| Series found, token matches, expired | Delete row → `ok=False` |

**Race-condition safety:** device cookie is only consumed when the JWT
has expired (session refresh path). Normal parallel API requests never
touch the device cookie → no rotation race condition possible.

Other functions: `create_device_token()`, `revoke_device(series)`,
`revoke_all_devices(username)`, `list_devices(username)`

Configuration global: `AUTH_DB_PATH`

---

### `api/auth_routes.py`

FastAPI router with prefix `/auth`. All endpoints are in `_AUTH_PUBLIC_PREFIXES`
in `main.py` — they bypass `AuthMiddleware`.

| Endpoint | Method | Auth required | Description |
|---|---|---|---|
| `/auth/login` | GET | No | Serves `login.html`; redirects to `/smart-home` if already logged in |
| `/auth/token` | POST | No | Validates credentials, issues `smh_session` cookie (+ `smh_device` if trust approved) |
| `/auth/logout` | POST | No | Revokes device token in DB, clears both cookies |
| `/auth/me` | GET | Yes (via cookie) | Returns `{username, trusted_device}` or 401 |
| `/auth/trust/approve` | GET | No (HMAC-signed URL) | Admin approves a trust request |
| `/auth/trust/reject` | GET | No (HMAC-signed URL) | Admin rejects a trust request |

**`POST /auth/token` logic:**
1. Verify password against `.htpasswd`
2. Always issue fresh 24h `smh_session` JWT
3. If `trusted=true` in form:
   - If `get_approved_trust_request(username)` → issue `smh_device` cookie + delete trust row
   - Else if no active request → create trust request + send approval email
   - Else → skip (dedup)
4. Redirect to `next_url` (sanitised to relative paths only)

Configuration globals (module-level, injected by `main.py`):
`SMTP_USER`, `SMTP_PASSWORD`, `BASE_URL`

---

### `main.py` — `AuthMiddleware`

`BaseHTTPMiddleware` registered before CORS middleware.

Public prefixes that always bypass auth:
```python
"/auth/", "/health", "/static/manifest.json", "/static/favicon.ico", "/favicon.ico"
```
Static assets (`/static/*`) also bypass — login page needs `tailwind.css`.

Session refresh logic (step 4):
```python
result = auth_devices.verify_and_rotate(device_cookie)
if result.theft_detected:
    # clear cookies, redirect to /auth/login?alert=theft
elif result.ok:
    # call_next(request), then set new smh_session + rotated smh_device
```

**Configuration injected in `lifespan()`** — never at module level:
```python
auth_core.AUTH_SECRET      = AUTH_SECRET
auth_core.AUTH_SESSION_TTL = AUTH_SESSION_TTL
auth_users.HTPASSWD_PATH   = AUTH_HTPASSWD
auth_users.AUTH_DB_PATH    = AUTH_DB_PATH
auth_users.TRUST_SECRET    = AUTH_SECRET
auth_devices.AUTH_DB_PATH  = AUTH_DB_PATH
auth_routes.SMTP_USER      = AUTH_SMTP_USER
auth_routes.SMTP_PASSWORD  = AUTH_SMTP_PASS
auth_routes.BASE_URL       = AUTH_BASE_URL
```

---

## Infrastructure

### nginx (`infrastructure/nginx/conf.d/smart-home.conf`)

- HTTP Basic Auth is **removed**. nginx only handles TLS + rate limiting + proxying.
- `/auth/` has `limit_req zone=auth burst=20` — brute-force protection remains.
- All other security headers (HSTS, X-Frame-Options, etc.) are unchanged.

### Docker volumes (`docker-compose.yml`)

The `.htpasswd` file is mounted **read-only** into both `nginx` and `backend`:

```yaml
# nginx service
- ./infrastructure/nginx/.htpasswd:/etc/nginx/.htpasswd:ro
# backend service
- ./infrastructure/nginx/.htpasswd:/etc/nginx/.htpasswd:ro
```

The SQLite auth database is in the backend data volume:
```yaml
- ./data/backend:/app/data   # auth.db lives at /app/data/auth.db
```

---

## Environment variables (`.env`)

| Variable | Required | Description |
|---|---|---|
| `AUTH_SECRET` | **Yes** | JWT signing key + HMAC key. Min 32 hex chars. Generate: `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `AUTH_HTPASSWD_PATH` | No | Path to `.htpasswd` inside container. Default: `/etc/nginx/.htpasswd` |
| `AUTH_DB_PATH` | No | Path to SQLite DB inside container. Default: `/app/data/auth.db` |
| `AUTH_SESSION_TTL` | No | Session JWT lifetime in seconds. Default: `86400` (24h) |
| `AUTH_SMTP_USER` | No* | Gmail address for trust request emails. Default: `acmlsn@gmail.com` |
| `AUTH_SMTP_PASSWORD` | No* | Gmail App Password (not account password). |
| `AUTH_BASE_URL` | No | Base URL for approve/reject links in emails. Default: `https://raspberrypi.tailaa37cd.ts.net` |

*Without `AUTH_SMTP_PASSWORD`, trust requests are created in DB but the
approval email silently fails. The admin can approve manually via the DB.

---

## User management

Users are stored in `/infrastructure/nginx/.htpasswd` (Apache apr_md5_crypt
format). There is no web UI for user management by design.

**Add a user:**
```bash
ssh pi@raspberrypi.local
htpasswd ~/projects/smart-home/infrastructure/nginx/.htpasswd newuser
# No container restart needed — the file is read on every login
```

**Remove a user:**
```bash
htpasswd -D ~/projects/smart-home/infrastructure/nginx/.htpasswd username
```

**Change a password:**
```bash
htpasswd ~/projects/smart-home/infrastructure/nginx/.htpasswd username
```

---

## Trusted device management

The `trusted_devices` table (in `auth.db`) manages the approval workflow.
The `device_tokens` table (also in `auth.db`) holds active Jaspan tokens.

**Full flow:**
1. User logs in with "Recordar dispositivo" checked
2. If no active request exists → email sent to `acmlsn@gmail.com` with Approve/Reject buttons
3. Admin clicks Approve → row status set to `approved`
4. User logs in again with checkbox → `smh_device` cookie issued, trust row deleted
5. On subsequent visits with expired JWT → middleware silently issues new JWT

**Inspect DB:**
```bash
ssh pi@raspberrypi.local
docker exec smart-home-backend python3 -c "
import sqlite3, datetime
conn = sqlite3.connect('/app/data/auth.db')
conn.row_factory = sqlite3.Row
print('=== Trust requests ===')
for r in conn.execute('SELECT id, username, status, substr(token,1,8) token8 FROM trusted_devices').fetchall():
    print(dict(r))
print('=== Device tokens ===')
for r in conn.execute('SELECT username, substr(series,1,8) series8, datetime(last_used,\"unixepoch\") last_used, datetime(expires_at,\"unixepoch\") expires FROM device_tokens').fetchall():
    print(dict(r))
"
```

**Revoke all devices for a user:**
```bash
docker exec smart-home-backend python3 -c "
import auth_devices; auth_devices.AUTH_DB_PATH='/app/data/auth.db'
print(auth_devices.revoke_all_devices('username'), 'tokens revoked')
"
```

**Approve a pending request manually (no email needed):**
```bash
docker exec smart-home-backend python3 -c "
import sqlite3, time
conn = sqlite3.connect('/app/data/auth.db')
conn.execute(\"UPDATE trusted_devices SET status='approved', resolved_at=? WHERE username=? AND status='pending'\", (time.time(), 'username'))
conn.commit(); print(conn.total_changes, 'rows updated')
"
```

---

## Security decisions and rationale

| Decision | Rationale |
|---|---|
| Auth in FastAPI, not nginx | Centralised control, web login page, revocable tokens |
| JWT for session (24h) | Stateless — no DB lookup on every request |
| Jaspan opaque token for device (1 year) | Revocable per device; theft detection via token rotation |
| SHA-256 hash in DB, not plaintext | DB leak doesn't yield usable device cookies |
| HMAC-signed email links | Prevents forging approve/reject without `AUTH_SECRET` |
| `hmac.compare_digest` everywhere | Constant-time — prevents timing attacks |
| Constant-time dummy check for unknown users | Prevents username enumeration via response time |
| `next_url` sanitised to relative paths only | Prevents open redirect attacks |
| `SameSite=Strict` on all cookies | Prevents CSRF |
| `HttpOnly` on all cookies | JavaScript cannot read session or device tokens |
| Device cookie only used on session refresh | Prevents race condition from parallel API requests triggering simultaneous rotations |

---

## Adding a new protected route

Nothing to do. `AuthMiddleware` protects all routes by default.
To make a route **public**, add its prefix to `_AUTH_PUBLIC_PREFIXES` in `main.py`:

```python
_AUTH_PUBLIC_PREFIXES = (
    "/auth/",
    "/health",
    "/static/manifest.json",
    "/static/favicon.ico",
    "/favicon.ico",
    "/your-new-public-path",   # ← add here
)
```

---

## Adding a new app to the dashboard

Edit `src/backend/static/dashboard.html`, array `APPS`:

```javascript
const APPS = [
    { key: 'myapp', url: '/smart-home/myapp',
      nameKey: 'myapp_name', descKey: 'myapp_desc',
      statusUrl: '/api/health/myapp', getStatus: d => d?.online === true },
    // ...
];
```

Add translations to the `T` object (both `es` and `en`), and add the
route to `main.py`:

```python
@app.get("/smart-home/myapp")
async def serve_myapp():
    return _serve_html("myapp.html")
```

The new page is automatically protected by `AuthMiddleware` — no extra
configuration needed.

---

## Deploy cycle

```powershell
# Edit files locally in C:\Users\acmls\Documents\Development\temp\
# SCP to Pi
scp "C:\...\temp\changed_file.py" pi@raspberrypi.local:~/projects/smart-home/src/backend/changed_file.py

# Rebuild backend only (other containers unaffected)
ssh pi@raspberrypi.local "cd ~/projects/smart-home && docker compose up -d --build backend 2>&1 | tail -6"

# Check startup
ssh pi@raspberrypi.local "sleep 5 && docker logs smart-home-backend --tail 10 2>&1"

# HTML/static files — no rebuild needed, served directly
scp "C:\...\temp\page.html" pi@raspberrypi.local:~/projects/smart-home/src/backend/static/page.html

# Commit from Pi
ssh pi@raspberrypi.local "cd ~/projects/smart-home && git add -p && git commit -m 'fix: ...' && git push origin main"
```

**Never push from the Z: drive** (SSHFS mount — unreliable for git).
Always commit from the Pi over SSH.
