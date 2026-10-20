"""
Portfolio Monitor Service — Main entry point.
Serves:
  GET  /smart-home/portfolio             → SPA dashboard
  GET  /api/portfolio/summary            → Full portfolio summary
  GET  /api/portfolio/etf                → ETF analysis
  GET  /api/portfolio/crypto             → Crypto staking analysis
  GET  /api/portfolio/savings            → Savings accounts
  POST /api/portfolio/refresh            → Trigger full refresh
  POST /api/portfolio/refresh/{monitor_name} → Trigger specific monitor refresh
  POST /api/portfolio/reload-config      → Reload configuration
  GET  /api/portfolio/schedule           → Get monitoring schedule
  GET  /api/portfolio/alerts             → List scheduled alerts
  POST /api/portfolio/alerts/{alert_id}/complete → Mark an alert complete
  POST /api/portfolio/notifications/test → Send a test notification
  GET  /api/portfolio/notifications/status → Notification config status
  GET  /api/portfolio/health/external    → External service health checks
  GET  /api/health/portfolio             → Health check alias
  GET  /health                           → Health check
Port: 8010
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from api import router as api_router
from config import LOG_LEVEL
from fastapi import FastAPI, Request
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from orchestrator import get_orchestrator
from starlette.middleware.base import BaseHTTPMiddleware

# Add libs to path for shared library import (mirrors monitors/crypto_monitor.py)
_LIBS_PATH: str = os.environ.get("LIBS_PATH", "/app/libs")
if _LIBS_PATH not in sys.path:
    sys.path.insert(0, _LIBS_PATH)

from html_serving import serve_html  # noqa: E402

# ─────────────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger: logging.Logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Security Headers Middleware
# ─────────────────────────────────────────────────────────────────────────────
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware that adds security headers to all responses.

    Headers added:
    - X-Content-Type-Options: Prevents MIME type sniffing
    - X-Frame-Options: Prevents clickjacking
    - X-XSS-Protection: Legacy XSS filter (for older browsers)
    - Referrer-Policy: Controls referrer information
    - Cache-Control: Prevents caching of sensitive API responses
    """

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        """Process request and add security headers to response."""
        response: Response = await call_next(request)

        # Security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Cache control for API endpoints (not static files)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store, max-age=0"

        return response


# ─────────────────────────────────────────────────────────────────────────────
# Lifespan
# ─────────────────────────────────────────────────────────────────────────────
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


# ─────────────────────────────────────────────────────────────────────────────
# FastAPI App
# ─────────────────────────────────────────────────────────────────────────────
app: FastAPI = FastAPI(
    title="Portfolio Monitor",
    description="ETF and Crypto staking portfolio monitoring service",
    version="1.0.0",
    docs_url="/swagger",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Add security headers middleware
app.add_middleware(SecurityHeadersMiddleware)

# Include API routes
app.include_router(api_router)


# ─────────────────────────────────────────────────────────────────────────────
# Health endpoints
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/health")
async def health() -> dict[str, Any]:
    """Health check — used by nginx and the dashboard."""
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
    """Health check alias — matches path expected by the dashboard."""
    return await health()


# ─────────────────────────────────────────────────────────────────────────────
# SPA Serving
# ─────────────────────────────────────────────────────────────────────────────
_STATIC_DIR: Path = Path(__file__).parent / "static"
_NOT_FOUND_HTML: str = (
    "<h1>404 - Dashboard not found</h1><p>Static files not deployed.</p>"
)


@app.get("/smart-home/portfolio")
async def serve_dashboard() -> Response:
    """Serves the portfolio monitor SPA."""
    return serve_html(_STATIC_DIR, "portfolio.html", not_found_html=_NOT_FOUND_HTML)


# ─────────────────────────────────────────────────────────────────────────────
# Static assets
# ─────────────────────────────────────────────────────────────────────────────
if _STATIC_DIR.exists():
    app.mount(
        "/static/portfolio", StaticFiles(directory=str(_STATIC_DIR)), name="static"
    )
