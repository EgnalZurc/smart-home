"""
Portfolio Monitor Service â€” Main entry point.
Serves:
  GET  /smart-home/portfolio             â†’ SPA dashboard
  GET  /api/portfolio/summary            â†’ Full portfolio summary
  GET  /api/portfolio/etf                â†’ ETF analysis
  GET  /api/portfolio/crypto             â†’ Crypto staking analysis
  GET  /api/portfolio/savings            â†’ Savings accounts
  POST /api/portfolio/refresh            â†’ Trigger full refresh
  POST /api/portfolio/refresh/{monitor_name} â†’ Trigger specific monitor refresh
  POST /api/portfolio/reload-config      â†’ Reload configuration
  GET  /api/portfolio/schedule           â†’ Get monitoring schedule
  GET  /api/portfolio/alerts             â†’ List scheduled alerts
  POST /api/portfolio/alerts/{alert_id}/complete â†’ Mark an alert complete
  POST /api/portfolio/notifications/test â†’ Send a test notification
  GET  /api/portfolio/notifications/status â†’ Notification config status
  GET  /api/portfolio/health/external    â†’ External service health checks
  GET  /api/health/portfolio             â†’ Health check alias
  GET  /health                           â†’ Health check
Port: 8010
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from api import router as api_router
from config import LOG_LEVEL
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from orchestrator import get_orchestrator
from starlette.middleware.base import BaseHTTPMiddleware

# Add libs to path for shared library import (mirrors monitors/crypto_monitor.py)
_LIBS_PATH: str = os.environ.get("LIBS_PATH", "/app/libs")
if _LIBS_PATH not in sys.path:
    sys.path.insert(0, _LIBS_PATH)

from html_serving import serve_html  # noqa: E402

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Logging
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger: logging.Logger = logging.getLogger(__name__)

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Environment configuration
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# SECURITY: ENVIRONMENT controls Swagger/ReDoc exposure.
# - "production" (default): Swagger/ReDoc DISABLED - no API documentation exposed
# - Any other value: Swagger/ReDoc ENABLED at /docs and /redoc
#
# WARNING: In production deployments, NEVER set ENVIRONMENT to a non-production
# value. Exposing API documentation can reveal endpoint structure, parameters,
# and response schemas to potential attackers. The Tailscale VPN provides
# network-level isolation, but defense-in-depth requires disabling docs.
#
# For local development, set ENVIRONMENT=development in your shell or .env file.
ENVIRONMENT: str = os.environ.get("ENVIRONMENT", "production")

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# CSRF Protection via Origin Validation
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Allowed origins for CSRF protection. Requests from these origins are trusted.
# Internal API behind Tailscale VPN - only allow known hosts.
#
# Additional origins can be added via the ALLOWED_ORIGINS environment variable
# as a comma-separated list (e.g., "https://custom.domain,http://other:8080").
_BASE_ALLOWED_ORIGINS: set[str] = {
    "https://raspberrypi.tailaa37cd.ts.net",  # Tailscale hostname
    "http://raspberrypi.local",  # Local network
    "http://localhost",
    "http://localhost:8010",
    "http://127.0.0.1",
    "http://127.0.0.1:8010",
}


def _load_allowed_origins() -> set[str]:
    """Load allowed origins from base set plus environment variable.

    The ALLOWED_ORIGINS env var accepts a comma-separated list of additional
    origins to trust. Empty entries and whitespace are ignored.

    Returns:
        Set of all allowed origins (base + environment).
    """
    origins = _BASE_ALLOWED_ORIGINS.copy()
    env_origins = os.environ.get("ALLOWED_ORIGINS", "")
    if env_origins:
        for origin in env_origins.split(","):
            origin = origin.strip()
            if origin:
                origins.add(origin)
                logger.info("Added custom allowed origin from env: %s", origin)
    return origins


_ALLOWED_ORIGINS: set[str] = _load_allowed_origins()


def _validate_origin(request: Request) -> bool:
    """Validate request Origin header for CSRF protection.

    For POST/PUT/DELETE requests, validates that the Origin header matches
    an allowed origin. This prevents CSRF attacks where a malicious site
    tries to make requests on behalf of the user.

    For internal APIs behind Tailscale VPN, Origin validation combined with
    Sec-Fetch-Mode provides defense-in-depth:
    - Origin header validates the source domain
    - Sec-Fetch-Mode=cors indicates a cross-origin fetch (requires CORS)
    - Sec-Fetch-Mode=navigate/same-origin are trusted browser navigations

    Security note on missing Origin:
    - Browsers ALWAYS send Origin for cross-origin POST requests
    - Missing Origin typically means: same-origin request, or non-browser client
    - We check Sec-Fetch-Mode to distinguish browser same-origin from scripts
    - If Sec-Fetch-Mode=cors but no Origin, block (malformed browser request)

    Args:
        request: The incoming HTTP request.

    Returns:
        True if the request is allowed, False if it should be blocked.
    """
    # Only check state-changing methods
    if request.method not in ("POST", "PUT", "DELETE", "PATCH"):
        return True

    origin = request.headers.get("origin")
    sec_fetch_mode = request.headers.get("sec-fetch-mode")

    # If browser sends Sec-Fetch-Mode=cors, Origin MUST be present and valid
    # A cors request without Origin is malformed or stripped by a proxy
    if sec_fetch_mode == "cors":
        if not origin:
            return False
        return origin in _ALLOWED_ORIGINS

    # No Origin header - could be same-origin request or non-browser client
    # Sec-Fetch-Mode helps distinguish:
    # - "navigate", "same-origin", "nested-navigate" = trusted browser navigation
    # - None = non-browser client (curl, scripts, internal services) - allowed
    # - Unknown Sec-Fetch-Mode without Origin - block to be safe
    if not origin:
        return sec_fetch_mode in ("navigate", "same-origin", "nested-navigate", None)

    # Check if origin is in the allowed list
    return origin in _ALLOWED_ORIGINS


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Security Headers Middleware
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware that adds security headers to all responses.

    Headers added:
    - X-Content-Type-Options: Prevents MIME type sniffing
    - X-Frame-Options: Prevents clickjacking
    - X-XSS-Protection: Legacy XSS filter (for older browsers)
    - Content-Security-Policy: Restricts resource loading sources
    - Referrer-Policy: Controls referrer information
    - Cache-Control: Prevents caching of sensitive API responses
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Process request and add security headers to response."""
        response: Response = await call_next(request)

        # Security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Content-Security-Policy"] = (
            # SECURITY: unsafe-inline required for SPA inline scripts/styles (chart.js, etc.)
            # This is an ACCEPTED_RISK documented in docs/SECURITY_FIXES.md under
            # "[infrastructure] CSP unsafe-inline". Mitigations:
            # - All other CSP directives are strict
            # - Application served via Tailscale VPN only (not public internet)
            # - Other security headers provide defense-in-depth
            # Future: Consider nonce-based CSP migration (dashboard already migrated)
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "connect-src 'self'"
        )
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Cache control for API endpoints (not static files)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store, max-age=0"

        return response


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Lifespan
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan handler."""
    logger.info("Starting Portfolio Monitor service...")

    # Start orchestrator
    orch = get_orchestrator()
    await orch.start()

    yield

    # Shutdown
    logger.info("Shutting down Portfolio Monitor service...")
    await orch.stop()


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# FastAPI App
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Disable Swagger/ReDoc in production for security
_docs_url: str | None = None if ENVIRONMENT == "production" else "/docs"
_redoc_url: str | None = None if ENVIRONMENT == "production" else "/redoc"

app: FastAPI = FastAPI(
    title="Portfolio Monitor",
    description="ETF and Crypto staking portfolio monitoring service",
    version="1.0.0",
    docs_url=_docs_url,
    redoc_url=_redoc_url,
    lifespan=lifespan,
)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# CSRF Protection Middleware
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.middleware("http")
async def csrf_protection_middleware(
    request: Request, call_next: Any
) -> Response | JSONResponse:
    """CSRF protection via Origin header validation.

    Blocks POST/PUT/DELETE/PATCH requests with an Origin header that doesn't
    match the allowed origins list. Requests without Origin header are allowed
    to support non-browser clients (curl, scripts, internal services).

    Returns:
        403 Forbidden if Origin is present but not allowed.
        Normal response otherwise.
    """
    if not _validate_origin(request):
        origin = request.headers.get("origin", "unknown")
        logger.warning(
            "[http] CSRF protection: blocked request from origin %s to %s",
            origin,
            request.url.path,
        )
        return JSONResponse(
            status_code=403,
            content={"error": "Forbidden: invalid origin"},
        )
    return await call_next(request)


# Add security headers middleware
app.add_middleware(SecurityHeadersMiddleware)

# Include API routes
app.include_router(api_router)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Health endpoints
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.get("/health")
async def health() -> dict[str, Any]:
    """Health check â€” used by nginx and the dashboard."""
    orch = get_orchestrator()
    state = orch.get_state()
    return {
        "online": True,
        "service": "portfolio-monitor",
        "last_etf_run": state.last_etf_run.isoformat() if state.last_etf_run else None,
        "last_crypto_run": state.last_crypto_run.isoformat()
        if state.last_crypto_run
        else None,
    }


@app.get("/api/health/portfolio")
async def health_alias() -> dict[str, Any]:
    """Health check alias â€” matches path expected by the dashboard."""
    return await health()


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# SPA Serving
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
_STATIC_DIR: Path = Path(__file__).parent / "static"
_NOT_FOUND_HTML: str = (
    "<h1>404 - Dashboard not found</h1><p>Static files not deployed.</p>"
)


@app.get("/smart-home/portfolio")
async def serve_dashboard() -> Response:
    """Serves the portfolio monitor SPA."""
    return serve_html(_STATIC_DIR, "portfolio.html", not_found_html=_NOT_FOUND_HTML)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Static assets
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
if _STATIC_DIR.exists():
    app.mount(
        "/static/portfolio", StaticFiles(directory=str(_STATIC_DIR)), name="static"
    )
