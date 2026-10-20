"""Entry point of the Smart Home Backend application.

Orchestrates all components: MQTT, MELCloud, AC controller, REST API.
"""

import logging
import os
import re
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path

import auth as auth_core
import auth_devices
import auth_users
from api import alert_reads_db, auth_routes, routes, trust_routes
from api.auth import admin as auth_admin
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from middleware import CSPNonceMiddleware, get_csp_nonce
from profiles import db as profiles_db
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse as StarletteRedirect
from starlette.responses import Response

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)
# --- Configuration from environment variables ---
# CORS
# CORS: require explicit origins in production
_cors_origins_raw = os.environ.get("CORS_ORIGINS", "")
CORS_ORIGINS = [o.strip() for o in _cors_origins_raw.split(",") if o.strip()]

# AUTH (REQUIRED)
AUTH_SECRET = os.environ.get("AUTH_SECRET", "")
AUTH_HTPASSWD = os.environ.get("AUTH_HTPASSWD_PATH", "/etc/nginx/.htpasswd")
AUTH_DB_PATH = os.environ.get("AUTH_DB_PATH", "/app/data/auth.db")
AUTH_SESSION_TTL = int(os.environ.get("AUTH_SESSION_TTL", "86400"))
AUTH_SMTP_USER = os.environ.get("AUTH_SMTP_USER", "")
AUTH_SMTP_PASS = os.environ.get("AUTH_SMTP_PASSWORD", "")
AUTH_ADMIN_EMAIL = os.environ.get(
    "AUTH_ADMIN_EMAIL", AUTH_SMTP_USER
)  # Defaults to SMTP user
AUTH_BASE_URL = os.environ.get("AUTH_BASE_URL", "https://raspberrypi.tailaa37cd.ts.net")
FIRMS_MAP_KEY = os.environ.get("FIRMS_MAP_KEY", "")

if not AUTH_SECRET:
    logger.error("AUTH_SECRET is required")
    raise RuntimeError("AUTH_SECRET not configured")

if len(AUTH_SECRET) < 32:
    logger.error("AUTH_SECRET must be at least 32 bytes (got %d)", len(AUTH_SECRET))
    raise RuntimeError("AUTH_SECRET too short (minimum 32 bytes)")


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
    profiles_db.AUTH_DB_PATH = AUTH_DB_PATH
    alert_reads_db.AUTH_DB_PATH = AUTH_DB_PATH
    auth_routes.SMTP_USER = AUTH_SMTP_USER
    auth_routes.SMTP_PASSWORD = AUTH_SMTP_PASS
    auth_routes.ADMIN_EMAIL = AUTH_ADMIN_EMAIL
    auth_routes.BASE_URL = AUTH_BASE_URL
    routes.set_firms_key(FIRMS_MAP_KEY)

    # DB initialisation (must run AFTER AUTH_DB_PATH is injected above).
    # Previously these ran at import time, before the path was set, so they
    # initialised the wrong (default) database file.
    try:
        auth_users._migrate_from_htpasswd()
    except Exception as exc:
        logger.warning("User migration from .htpasswd failed: %s", exc)
    profiles_db.init_database()

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
    "/api/monitoring/",  # Memory monitoring — internal use from cron scripts
    # NOTE: /api/ws/ is intentionally NOT public — WebSocket auth is handled
    # in ws.py via session cookie validation during the handshake.
)


class AuthMiddleware(BaseHTTPMiddleware):
    """Central authentication gate for all requests.

    Decision tree for every incoming request:
    1. Public path (/auth/*, /health, PWA assets) → pass through
    2. Static files (/static/*) → pass through (login page needs CSS)
    3. Valid JWT session cookie:
       a. Check if user has pending device token → deliver it as cookie
       b. Pass through
    4. Expired JWT + valid device cookie (Jaspan token):
       a. Verify and rotate the device token
       b. Issue a fresh 24h JWT
       c. Attach both updated cookies to the response
       d. Pass through — user never sees a login prompt
       e. If theft detected → clear all cookies, redirect to login with warning
    5. No valid session and no valid device token → redirect to /auth/login
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Response]
    ) -> Response:
        """Dispatch request through the authentication pipeline."""
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
            # Check for pending device token to deliver (must match this device's UA)
            user_agent = request.headers.get("User-Agent", "")
            pending_cookie = auth_devices.get_pending_token(user, user_agent)
            if pending_cookie:
                response = await call_next(request)
                response.set_cookie(
                    key=auth_devices.DEVICE_COOKIE_NAME,
                    value=pending_cookie,
                    max_age=auth_devices.DEVICE_TOKEN_TTL,
                    httponly=True,
                    secure=True,
                    samesite="strict",
                    path="/",
                )
                auth_devices.mark_token_delivered(user, user_agent)
                logger.info("Delivered pending device token to user %r", user)
                return response
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
                logger.info(
                    "Session silently refreshed via device token for user %r",
                    result.username,
                )
                return response

        # 5. Not authenticated — redirect to login
        login_url = f"/api/auth/login?next={request.url.path}"
        logger.debug("Unauthenticated request to %s — redirecting to login", path)
        return StarletteRedirect(login_url, status_code=302)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses.

    Headers added:
    - X-Content-Type-Options: nosniff — Prevents MIME-type sniffing
    - X-Frame-Options: DENY — Prevents clickjacking via iframes
    - Referrer-Policy: strict-origin-when-cross-origin — Limits referrer info
    - Permissions-Policy: geolocation=(), microphone=(), camera=() — Disables features
    - X-XSS-Protection: 0 — Disabled (legacy, can cause issues; rely on CSP instead)
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Response]
    ) -> Response:
        """Process request and add security headers to the response."""
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "geolocation=(), microphone=(), camera=()"
        )
        # X-XSS-Protection disabled: legacy header that can introduce vulnerabilities
        # Modern browsers use CSP instead
        response.headers["X-XSS-Protection"] = "0"
        return response


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
        "name": "Deploy",
        "description": "Manual GitHub Actions deploy triggers (SUPER only)",
    },
    {
        "name": "System",
        "description": "Raspberry Pi system stats and mode control",
    },
    {
        "name": "Proxy",
        "description": "External API proxies (flood risk, fire data)",
    },
    {
        "name": "Portfolio",
        "description": "Investment portfolio monitoring (ETFs, crypto)",
    },
    {
        "name": "Metrics",
        "description": "Pi host, container and service-health time-series metrics",
    },
    {
        "name": "Alerts",
        "description": "Unified alerts feed aggregated from all services",
    },
]

# Disable interactive API docs in production
_is_production = os.environ.get("ENVIRONMENT", "production") == "production"

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
| **Portfolio** | `/api/portfolio/*` | Investment portfolio monitoring |
| **System** | `/api/system/*` | Pi stats, containers, modes |
| **Proxy** | `/api/proxy/*` | External APIs (flood, fire risk) |
    """,
    version="2.0.0",
    lifespan=lifespan,
    docs_url=None if _is_production else "/swagger",
    redoc_url=None if _is_production else "/redoc",
    openapi_url=None if _is_production else "/openapi.json",
    openapi_tags=tags_metadata,
)

# AUTH middleware (must be added before CORS so unauthenticated requests
# are redirected before CORS headers are processed)
app.add_middleware(AuthMiddleware)

# Security headers middleware — adds X-Content-Type-Options, X-Frame-Options, etc.
app.add_middleware(SecurityHeadersMiddleware)

# CSP nonce middleware — generates per-request nonces for inline scripts/styles
app.add_middleware(CSPNonceMiddleware)

# CORS - Configure allowed origins for security
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "Authorization", "X-Requested-With"],
    allow_credentials=bool(CORS_ORIGINS),  # Only with explicit origins
)

# Auth routes (API endpoints under /api/auth)
app.include_router(auth_routes.router)

# Trust-device email-link routes (under /api/auth/trust)
app.include_router(trust_routes.router)

# Admin routes (user/profile management under /api/auth/admin)
app.include_router(auth_admin.router)

# API routes (all under /api)
app.include_router(routes.router)


# ═══════════════════════════════════════════════════════════════════════════════
# UI ROUTES - These serve HTML pages, NOT included in Swagger
# ═══════════════════════════════════════════════════════════════════════════════


def _serve_html(filename: str, request: Request) -> HTMLResponse:
    """Serve an HTML file with no-cache headers and CSP nonce injection.

    Injects the CSP nonce (from CSPNonceMiddleware) into inline <style> and
    <script> tags so they pass the Content-Security-Policy checks.

    Args:
        filename: Name of the HTML file in the static directory.
        request: The incoming request (needed for CSP nonce retrieval).

    Returns:
        HTMLResponse with injected nonce and cache-control headers.
    """
    frontend_path = Path(__file__).parent / "static" / filename
    content = frontend_path.read_text(encoding="utf-8")

    # Inject version comment for cache busting
    content = content.replace("</head>", f"<!-- v:{int(time.time())} -->\n</head>")

    # Inject CSP nonce into inline <style> and <script> tags (those without src=)
    nonce = get_csp_nonce(request)
    if nonce:
        # Add nonce to <style> tags (none have attributes typically)
        content = re.sub(r"<style>", f'<style nonce="{nonce}">', content)
        # Add nonce to inline <script> tags (those without src=)
        # Match <script> but not <script src="...">
        content = re.sub(
            r"<script(?![^>]*\bsrc\s*=)([^>]*)>",
            rf'<script nonce="{nonce}"\1>',
            content,
        )

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
async def serve_dashboard(request: Request):
    """Serves the Smart Home platform dashboard."""
    return _serve_html("dashboard.html", request)


# Login page served via auth_routes (GET /auth/login)
# This is also excluded from schema in auth_routes.py


# Casita detail page (not in Swagger)
@app.get("/smart-home/casita", include_in_schema=False)
async def serve_casita(request: Request):
    """Serves the Casita Sueños detail page."""
    return _serve_html("casita.html", request)


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
