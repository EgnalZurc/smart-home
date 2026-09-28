---
inclusion: auto
---
# Smart Home — Project Standards

## Language
- All code, comments, variable names, and commits: **English only**
- Conventional commits: `feat:`, `fix:`, `refactor:`, `docs:`, `chore:`, `ci:`

## Documentation
- Update `.kiro/docs/REQUIREMENTS.md` for new requirements
- No redundant documentation — git commits provide history
- Session logs only for large multi-session tasks

## Documentation file locations
| Allowed in root | All others |
|----------------|------------|
| README.md, CONTRIBUTING.md, DOCKER.md, LICENSE | `.kiro/docs/` |

## Git & CI/CD
- Remote `github`: main repository with CI/CD
- Pipeline: `.github/workflows/ci.yml` — unified Test and Deploy
- Deploy requires manual approval via GitHub environment `production`
- Approve deploy: `gh run review <run-id> --approve --repo EgnalZurc/smart-home`

## Infrastructure

### CRITICAL: Code Location vs Execution Location
- **Source code**: `C:\Users\acmls\Documents\Development\smart-home` — THIS is where you read/edit code
- **Execution**: Raspberry Pi runs Docker images built from the code
- **NEVER** look for source code on the Pi — it only has `docker-compose.yml` and data volumes
- **NEVER** SSH to Pi to read Python/JS files — they don't exist there, only inside containers

### Connection details
- **Pi SSH**: `ssh pi@raspberrypi.local` — for Docker operations, logs, debugging
- **Pi Tailscale**: `https://raspberrypi.tailaa37cd.ts.net` — public API endpoint
- **Project root on Pi**: `~/smart-home-prod` (only docker-compose.yml and data)
- **Local repo**: `C:\Users\acmls\Documents\Development\smart-home`

---

## Creating a New Service (CHECKLIST)

When creating a new microservice, you MUST complete ALL of the following steps:

> **⚠️ IMPORTANT: Unified Swagger**
> All service APIs MUST be exposed via proxy routes in the dashboard (`dashboard/src/api/routes.py`).
> This ensures a single Swagger UI at `/swagger` documents ALL platform APIs.
> See section 6.6 for details.

### 1. Service Directory Structure
Create in `services/<service-name>/`:
```
services/<service-name>/
├── Dockerfile
├── requirements.txt
├── src/
│   ├── main.py              # FastAPI app
│   └── static/
│       └── <service>.html   # SPA with home button
└── tests/
    └── __init__.py
```

### 2. Main.py Template
```python
"""<Service Name> Service — standalone microservice for <purpose>.

Serves:
  GET  /smart-home/<service>     → SPA
  GET  /api/<service>/*          → API endpoints
  GET  /health                   → health check
  GET  /api/health/<service>     → health check alias

Port: <next-available-port>
"""
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import time

app = FastAPI(
    title="<Service Name> Service",
    version="1.0.0",
    docs_url="/swagger",
    redoc_url="/redoc",
)

@app.get("/health")
def health():
    return {"online": True, "service": "<service>"}

@app.get("/api/health/<service>")
def health_api():
    return {"online": True, "service": "<service>"}

def _serve_html(filename: str) -> HTMLResponse:
    path = Path(__file__).parent / "static" / filename
    content = path.read_text(encoding="utf-8")
    content = content.replace("</head>", f"<!-- v:{int(time.time())} -->\n</head>")
    return HTMLResponse(content, headers={
        "Cache-Control": "no-cache, no-store, must-revalidate",
    })

@app.get("/smart-home/<service>")
async def serve_spa():
    return _serve_html("<service>.html")

# Mount static files - use service-specific path to avoid conflicts with dashboard
_static_dir = Path(__file__).parent / "static"
if _static_dir.exists():
    app.mount("/static/<service>", StaticFiles(directory=str(_static_dir)), name="static")
```

### 3. SPA HTML Template (with home button)
```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title><Service Name> - Cuchi Casa</title>
    <link rel="stylesheet" href="/static/<service>/tailwind.css">
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
    </style>
</head>
<body class="bg-[#0f172a] text-white min-h-screen">
<div class="max-w-md mx-auto px-4 pt-6 pb-10">
    <!-- Header with home button -->
    <header class="flex items-center gap-3 mb-6">
        <a href="/smart-home" class="flex items-center justify-center w-8 h-8 rounded-lg border border-slate-700/50 bg-slate-800/40 hover:border-slate-600 hover:bg-slate-700/40 transition-all" title="Cuchi Casa">
            <img src="/static/icono-cuchi-casa.png" class="w-5 h-5 object-contain rounded" alt="Home">
        </a>
        <h1 class="text-lg font-semibold"><Service Name></h1>
    </header>
    
    <!-- Content -->
    <div class="card rounded-2xl p-6">
        <p class="text-slate-400">Service ready. Add your content here.</p>
    </div>
</div>
</body>
</html>
```

### 4. docker-compose.yml
Add service entry:
```yaml
  <service-name>:
    image: egnal/smart-home-<service-name>:latest
    build:
      context: ./services/<service-name>
    container_name: <service-name>
    restart: unless-stopped
    networks:
      - smart-home
    volumes:
      - <service>-data:/app/data
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:<port>/health"]
      interval: 30s
      timeout: 10s
      retries: 3
```

### 5. nginx Configuration
Add to `infrastructure/nginx/conf.d/smart-home.conf`:
```nginx
    # ── <Service Name> static files (MUST be before general /static/) ─────────
    location /static/<service>/ {
        set $svc_host "<service-name>";
        proxy_pass http://$svc_host:<port>;
        proxy_set_header Host $host;
        proxy_http_version 1.1;
    }

    # ── <Service Name> — port <port> ──────────────────────────────────────────
    location /smart-home/<service> {
        auth_request /_auth_check;
        auth_request_set $auth_user $upstream_http_x_auth_user;
        error_page 401 = @login_redirect;
        set $svc_host "<service-name>";
        proxy_pass http://$svc_host:<port>;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
    }
    location /api/<service>/ {
        auth_request /_auth_check;
        auth_request_set $auth_user $upstream_http_x_auth_user;
        error_page 401 = @login_redirect;
        set $svc_host "<service-name>";
        proxy_pass http://$svc_host:<port>;
        proxy_set_header Host $host;
        proxy_http_version 1.1;
    }
    location = /api/health/<service> {
        set $svc_host "<service-name>";
        proxy_pass http://$svc_host:<port>;
        proxy_set_header Host $host;
        proxy_http_version 1.1;
    }
```

### 6. Dashboard Integration

#### 6.1 APP_REGISTRY (dashboard/src/user_profiles.py)
```python
{
    "key": "<service>",
    "type": "standard",  # or "config" for admin-only
    "view_level": 1,
    "edit_level": 1,
},
```

#### 6.2 APP_CATALOGUE (dashboard/src/static/dashboard.html)
```javascript
<service>: { 
    url: '/smart-home/<service>', 
    nameKey: '<service>_name', 
    descKey: '<service>_desc', 
    statusUrl: '/api/health/<service>', 
    getStatus: d => d?.online === true 
},
```

#### 6.3 Translations (same file, T object)
```javascript
en: {
    // ... existing
    <service>_name: '<Service Name>',
    <service>_desc: '<Short description>',
},
es: {
    // ... existing
    <service>_name: '<Nombre del Servicio>',
    <service>_desc: '<Descripción corta>',
},
```

#### 6.4 CONTROLLABLE_CONTAINERS (dashboard/src/api/routes.py)
```python
CONTROLLABLE_CONTAINERS: dict[str, list[str]] = {
    # ... existing
    "<service>": ["<service-name>"],
}
```

#### 6.5 Health check proxy (dashboard/src/api/routes.py)
```python
@router.get("/health/<service>", tags=["Health"])
async def get_<service>_health():
    """Health check for <Service Name> service."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get("http://<service-name>:<port>/health")
            data = r.json()
            return {"online": data.get("online", False)}
    except Exception:
        return {"online": False}
```

#### 6.6 API Proxy Routes (REQUIRED for unified Swagger)
**All service APIs MUST be exposed via the dashboard for the unified Swagger.**

Add proxy routes in `dashboard/src/api/routes.py`:
```python
# ══════════════════════════════════════════════════════════════════════════════
# <Service Name> Proxy Routes
# All <Service> endpoints are proxied to <service-name>:<port>
# ══════════════════════════════════════════════════════════════════════════════

<SERVICE>_URL = "http://<service-name>:<port>"

@router.get("/<service>/endpoint", tags=["<Service>"])
async def get_<service>_endpoint():
    """Description of endpoint."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{<SERVICE>_URL}/api/<service>/endpoint")
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))

# Add a proxy for EACH endpoint in the service
# Follow this pattern for GET, POST, PUT, DELETE methods
```

#### 6.7 Tag Metadata (dashboard/src/main.py)
Add tag to `tags_metadata`:
```python
{
    "name": "<Service>",
    "description": "<Service description>",
},
```

### 7. CI/CD Pipeline (.github/workflows/ci.yml)

#### 7.1 Add to detect-changes filters
```yaml
    <service>:
      - 'services/<service-name>/**'
```

#### 7.2 Add test job
```yaml
  test-<service>:
    needs: detect-changes
    if: ${{ needs.detect-changes.outputs.<service> == 'true' }}
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: 'pip'
          cache-dependency-path: 'services/<service-name>/requirements.txt'
      - name: Install dependencies
        run: |
          pip install -r services/<service-name>/requirements.txt
          pip install pytest pytest-asyncio
      - name: Run tests
        run: |
          cd services/<service-name>
          python -m pytest tests/ -v --tb=short || echo "No tests found"
        env:
          PYTHONPATH: src
```

#### 7.3 Add to test-summary needs
```yaml
  test-summary:
    needs: [..., test-<service>]
```

#### 7.4 Add to test results check
```yaml
          <SERVICE>="${{ needs.test-<service>.result }}"
          # Add to FAILED check loop
```

#### 7.5 Add build step in deploy job
```yaml
      - name: Build and push <Service Name>
        if: ${{ needs.detect-changes.outputs.<service> == 'true' }}
        uses: docker/build-push-action@v5
        with:
          context: ./services/<service-name>
          push: true
          tags: |
            egnal/smart-home-<service-name>:latest
            egnal/smart-home-<service-name>:${{ github.sha }}
          platforms: linux/arm64
```

---

## Security Standards (ALL services)

### XSS Prevention
- Never insert user data directly into HTML
- Always escape user input before rendering
- Use `escapeHtml()` function in frontend or equivalent

### Input Validation
- Validate all user input on backend
- Use Pydantic models for request validation
- Sanitize strings before database storage

### Token/Data Injection
- Use `json.dumps()` when injecting data into HTML templates
- Never use raw f-strings with user input in HTML context

### Rate Limiting
- Apply rate limiting to public endpoints
- Do not rate-limit static page serving

## Encoding Standards

### File Encoding
- All source files: UTF-8
- JSON data: UTF-8 with `ensure_ascii=False`

### Emojis
- Use HTML entities in HTML files, not raw emojis
- Raw emojis get corrupted during SSH/PowerShell transfer

### Spanish Text
- Prefer ASCII-safe alternatives in data files
- Use proper UTF-8 handling if accents are required

## Frontend Patterns

### Toast Notifications
- Always specify type: `showToast('msg', 'success')` or `showToast('msg', 'error')`

### Function Calls
- Verify functions exist before calling
- Common issue: calling `loadGifts()` instead of `loadAdminData()`

### After Data Modifications
- Always reload relevant data after create/update/delete
- Use the correct load function for the current user context
