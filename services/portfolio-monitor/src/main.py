"""
Portfolio Monitor Service — Main entry point.
Serves:
  GET  /smart-home/portfolio         → SPA dashboard
  GET  /api/portfolio/summary        → Full portfolio summary
  GET  /api/portfolio/etf            → ETF analysis
  GET  /api/portfolio/crypto         → Crypto staking analysis  
  POST /api/portfolio/refresh        → Trigger full refresh
  POST /api/portfolio/refresh/{name} → Trigger specific monitor refresh
  GET  /api/portfolio/schedule       → Get monitoring schedule
  POST /api/portfolio/reload-config  → Reload configuration
  GET  /health                       → Health check
  GET  /api/health/portfolio         → Health check alias
Port: 8010
"""

import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from api import router as api_router
from config import LOG_LEVEL
from orchestrator import get_orchestrator

# ─────────────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Lifespan
# ─────────────────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
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
app = FastAPI(
    title="Portfolio Monitor",
    description="ETF and Crypto staking portfolio monitoring service",
    version="1.0.0",
    docs_url="/swagger",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Include API routes
app.include_router(api_router)


# ─────────────────────────────────────────────────────────────────────────────
# Health endpoints
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    """Health check — used by nginx and the dashboard."""
    orch = get_orchestrator()
    state = orch.get_state()
    return {
        "online": True,
        "service": "portfolio-monitor",
        "last_etf_run": state.last_etf_run.isoformat() if state.last_etf_run else None,
        "last_crypto_run": state.last_crypto_run.isoformat() if state.last_crypto_run else None,
    }


@app.get("/api/health/portfolio")
async def health_alias():
    """Health check alias — matches path expected by the dashboard."""
    return await health()


# ─────────────────────────────────────────────────────────────────────────────
# SPA Serving
# ─────────────────────────────────────────────────────────────────────────────
def _serve_html(filename: str) -> HTMLResponse:
    """Serve an HTML file with no-cache headers."""
    path = Path(__file__).parent / "static" / filename
    if not path.exists():
        return HTMLResponse(
            content="<h1>404 - Dashboard not found</h1><p>Static files not deployed.</p>",
            status_code=404,
        )
    
    content = path.read_text(encoding="utf-8")
    # Inject cache buster
    content = content.replace("</head>", f"<!-- v:{int(time.time())} -->\n</head>")
    
    return HTMLResponse(
        content=content,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/smart-home/portfolio")
async def serve_dashboard():
    """Serves the portfolio monitor SPA."""
    return _serve_html("portfolio.html")


# ─────────────────────────────────────────────────────────────────────────────
# Static assets
# ─────────────────────────────────────────────────────────────────────────────
_static_dir = Path(__file__).parent / "static"
if _static_dir.exists():
    app.mount("/static/portfolio", StaticFiles(directory=str(_static_dir)), name="static")
