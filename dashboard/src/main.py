"""Entry point of the Smart Home Backend application.
Orchestrates all components: MQTT, MELCloud, AC controller, REST API.
"""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import auth as auth_core
import auth_devices
import auth_users
from api import auth_routes, routes
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import RedirectResponse as StarletteRedirect

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)
# --- Configuration from environment variables ---
# CORS
CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "*").split(",")

# AUTH (REQUIRED)
AUTH_SECRET = os.environ.get("AUTH_SECRET", "")
AUTH_HTPASSWD = os.environ.get("AUTH_HTPASSWD_PATH", "/etc/nginx/.htpasswd")
AUTH_DB_PATH = os.environ.get("AUTH_DB_PATH", "/app/data/auth.db")
AUTH_SESSION_TTL = int(os.environ.get("AUTH_SESSION_TTL", "86400"))
AUTH_SMTP_USER = os.environ.get("AUTH_SMTP_USER", "")
AUTH_SMTP_PASS = os.environ.get("AUTH_SMTP_PASSWORD", "")
AUTH_BASE_URL = os.environ.get("AUTH_BASE_URL", "https://raspberrypi.tailaa37cd.ts.net")
FIRMS_MAP_KEY = os.environ.get("FIRMS_MAP_KEY", "")

if not AUTH_SECRET:
    logger.error("AUTH_SECRET is required")
    raise RuntimeError("AUTH_SECRET not configured")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle — auth configuration only.
    AC logic is in ac-service. Vacaciones logic is in vacaciones-service.
    """
    # AUTH: inject configuration into auth modules
    auth_core.AUTH_SECRET = AUTH_SECRET
    auth_core.AUTH_SESSION_TTL = AUTH_SESSION_TTL
    auth_users.HTPASSWD_PATH = AUTH_HTPASSWD
    auth_users.AUTH_DB_PATH = AUTH_DB_PATH
    auth_users.TRUST_SECRET = AUTH_SECRET
    auth_devices.AUTH_DB_PATH = AUTH_DB_PATH
    auth_routes.SMTP_USER = AUTH_SMTP_USER
    auth_routes.SMTP_PASSWORD = AUTH_SMTP_PASS
    auth_routes.BASE_URL = AUTH_BASE_URL
    routes.FIRMS_MAP_KEY = FIRMS_MAP_KEY
    logger.info("=== Smart Home Backend ready (auth + dashboard) ===")
    yield
    logger.info("=== Smart Home Backend shutdown ===")


# ── AUTH: paths that bypass authentication ────────────────────────────────────
_AUTH_PUBLIC_PREFIXES = (
    "/auth/",
    "/api/auth/",  # API auth endpoints
    "/health",
    "/api/health",  # Health check endpoints — must be public so dashboard status works
    "/api/proxy/",
    "/static/manifest.json",
    "/static/favicon.ico",
    "/favicon.ico",
    "/swagger",  # Swagger UI
    "/redoc",  # ReDoc UI
    "/openapi.json",  # OpenAPI spec
)


class AuthMiddleware(BaseHTTPMiddleware):
    """Central authentication gate for all requests.

    Decision tree for every incoming request:
    1. Public path (/auth/*, /health, PWA assets) → pass through
    2. Static files (/static/*) → pass through (login page needs CSS)
    3. Valid JWT session cookie → pass through
    4. Expired JWT + valid device cookie (Jaspan token):
       a. Verify and rotate the device token
       b. Issue a fresh 24h JWT
       c. Attach both updated cookies to the response
       d. Pass through — user never sees a login prompt
       e. If theft detected → clear all cookies, redirect to login with warning
    5. No valid session and no valid device token → redirect to /auth/login
    """

    async def dispatch(self, request, call_next):
        path = request.url.path

        # 1. Public paths
        if any(path.startswith(p) for p in _AUTH_PUBLIC_PREFIXES):
            return await call_next(request)

        # 2. Static assets
        if path.startswith("/static/"):
            return await call_next(request)

        # 3. Valid JWT
        user = auth_core.get_current_user(request)
        if user:
            return await call_next(request)

        # 4. Expired/missing JWT — check device cookie
        device_cookie = auth_devices.get_device_cookie_from_request(request)
        if device_cookie:
            result = auth_devices.verify_and_rotate(device_cookie)

            if result.theft_detected:
                # Cookie stolen — clear everything, send to login with alert
                logger.warning(
                    "Cookie theft detected for user %r — invalidating all device tokens",
                    result.username,
                )
                login_url = "/api/auth/login?alert=theft"
                redirect = StarletteRedirect(login_url, status_code=302)
                redirect.delete_cookie(auth_core.COOKIE_NAME, path="/")
                redirect.delete_cookie(auth_devices.DEVICE_COOKIE_NAME, path="/")
                return redirect

            if result.ok:
                # Valid device token — issue fresh JWT and rotate device cookie
                new_jwt = auth_core.create_token(result.username)
                response = await call_next(request)
                auth_core.set_session_cookie(response, new_jwt)
                # Set rotated device cookie (unless grace window hit → empty string)
                if result.new_cookie_value:
                    response.set_cookie(
                        key=auth_devices.DEVICE_COOKIE_NAME,
                        value=result.new_cookie_value,
                        max_age=auth_devices.DEVICE_TOKEN_TTL,
                        httponly=True,
                        secure=True,
                        samesite="strict",
                        path="/",
                    )
                logger.debug("Session silently refreshed for user %r", result.username)
                return response

        # 5. Not authenticated — redirect to login
        login_url = f"/api/auth/login?next={request.url.path}"
        return StarletteRedirect(login_url, status_code=302)


# --- FastAPI App ---
# OpenAPI tags for organized documentation
tags_metadata = [
    {
        "name": "Auth",
        "description": "Authentication and session management",
    },
    {
        "name": "Health",
        "description": "Health check endpoints for all services",
    },
    {
        "name": "AC",
        "description": "Air conditioning control and sensor monitoring",
    },
    {
        "name": "Vacaciones",
        "description": "Christmas vacation planning",
    },
    {
        "name": "Baby Gifts",
        "description": "Baby gift registry management",
    },
    {
        "name": "Casita",
        "description": "Property search and monitoring (Casita Sueños)",
    },
    {
        "name": "Containers",
        "description": "Docker container management",
    },
    {
        "name": "System",
        "description": "Raspberry Pi system stats and mode control",
    },
    {
        "name": "Proxy",
        "description": "External API proxies (flood risk, fire data)",
    },
]

app = FastAPI(
    title="Smart Home API",
    description="""
## Smart Home Control Platform — Unified API

All microservice APIs are accessible through this single gateway.

### Authentication

Most endpoints require authentication. Use `POST /api/auth/token` to obtain a session cookie.

### Services

| Service | Endpoints | Description |
|---------|-----------|-------------|
| **Auth** | `/api/auth/*` | Login, logout, session management |
| **AC** | `/api/ac/*` | Climate control, sensors, energy |
| **Vacaciones** | `/api/vacaciones/*` | Christmas vacation planning |
| **Baby Gifts** | `/api/baby-gifts/*` | Gift registry with guest access |
| **Casita** | `/api/casita/*` | Property search and monitoring |
| **System** | `/api/system/*` | Pi stats, containers, modes |
| **Proxy** | `/api/proxy/*` | External APIs (flood, fire risk) |
    """,
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/swagger",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    openapi_tags=tags_metadata,
)

# AUTH middleware (must be added before CORS so unauthenticated requests
# are redirected before CORS headers are processed)
app.add_middleware(AuthMiddleware)

# CORS - Configure allowed origins for security
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

# Auth routes (API endpoints under /api/auth)
app.include_router(auth_routes.router)

# API routes (all under /api)
app.include_router(routes.router)


# ═══════════════════════════════════════════════════════════════════════════════
# UI ROUTES - These serve HTML pages, NOT included in Swagger
# ═══════════════════════════════════════════════════════════════════════════════


def _serve_html(filename: str):
    """Serve an HTML file with no-cache headers."""
    import time

    from fastapi.responses import HTMLResponse

    frontend_path = Path(__file__).parent / "static" / filename
    content = frontend_path.read_text(encoding="utf-8")
    content = content.replace("</head>", f"<!-- v:{int(time.time())} -->\n</head>")
    return HTMLResponse(
        content=content,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


# Root redirect (not in Swagger)
@app.get("/", include_in_schema=False)
async def serve_root():
    """Redirect / to /smart-home dashboard."""
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url="/smart-home", status_code=301)


# Dashboard page (not in Swagger)
@app.get("/smart-home", include_in_schema=False)
async def serve_dashboard():
    """Serves the Smart Home platform dashboard."""
    return _serve_html("dashboard.html")


# Login page served via auth_routes (GET /auth/login)
# This is also excluded from schema in auth_routes.py


# Casita detail page (not in Swagger)
@app.get("/smart-home/casita", include_in_schema=False)
async def serve_casita():
    """Serves the Casita Sueños detail page."""
    return _serve_html("casita.html")


# Serve other static files normally
frontend_path = Path(__file__).parent / "static"
if frontend_path.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_path)), name="frontend")


# Simple health endpoint (public, not in main API docs - use /api/health instead)
@app.get("/health", include_in_schema=False)
def health():
    """Health check for the dashboard service (used by nginx)."""
    return {"status": "ok"}


# Legacy route: /auth/login redirects to /api/auth/login for backwards compatibility
@app.get("/auth/login", include_in_schema=False)
async def legacy_auth_login():
    """Redirect old /auth/login to /api/auth/login."""
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url="/api/auth/login", status_code=301)
