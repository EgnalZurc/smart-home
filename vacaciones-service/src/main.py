"""Vacaciones Service — standalone microservice for Christmas planning.

Serves:
  GET  /smart-home/vacaciones       → vacaciones.html (SPA)
  GET  /api/vacaciones              → all data
  GET  /api/vacaciones/config       → nucleos + personas config
  POST /api/vacaciones/config       → save config
  POST /api/vacaciones/year         → add new year
  POST /api/vacaciones/year/{year}  → save year plan
  DELETE /api/vacaciones/year/{year}→ delete year
  GET  /health                      → health check (used by nginx + dashboard)

Auth: nginx handles auth_request before requests reach this service.
      This service trusts all incoming requests as already authenticated.
      No auth logic here — keep it simple.

Port: 8003
"""
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from vacaciones_controller import (
    add_year,
    delete_year,
    get_config,
    get_vacaciones_data,
    is_healthy,
    save_config,
    save_year,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Vacaciones Service", version="1.0.0")


# ── Pydantic models ───────────────────────────────────────────────────────────

class VacacionesConfigRequest(BaseModel):
    nucleos: list = []
    personas: list = []


class VacacionesYearRequest(BaseModel):
    comidas: list = []
    notas: str = ""


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    """Health check — used by nginx and the dashboard."""
    return {"online": is_healthy(), "service": "vacaciones"}


# ── SPA ───────────────────────────────────────────────────────────────────────

def _serve_html(filename: str) -> HTMLResponse:
    """Serve an HTML file with no-cache headers."""
    import time
    path = Path(__file__).parent / "static" / filename
    content = path.read_text(encoding="utf-8")
    content = content.replace("</head>", f"<!-- v:{int(time.time())} -->\n</head>")
    return HTMLResponse(
        content=content,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/smart-home/vacaciones")
async def serve_vacaciones():
    """Serves the Vacaciones SPA."""
    return _serve_html("vacaciones.html")


# ── API ───────────────────────────────────────────────────────────────────────

@app.get("/api/vacaciones")
def get_vacaciones():
    """Returns all vacaciones data including config and momentos."""
    return get_vacaciones_data()


@app.get("/api/vacaciones/config")
def get_vacaciones_config():
    """Returns vacaciones configuration (nucleos and personas)."""
    return get_config()


@app.post("/api/vacaciones/config")
def post_vacaciones_config(data: VacacionesConfigRequest):
    """Save vacaciones configuration."""
    return save_config(data.nucleos, data.personas)


@app.post("/api/vacaciones/year")
def add_vacaciones_year():
    """Add a new year (next after highest existing)."""
    return add_year()


@app.post("/api/vacaciones/year/{year}")
def post_vacaciones_year(year: int, data: VacacionesYearRequest):
    """Save a year's planning."""
    return save_year(year, data.comidas, data.notas)


@app.delete("/api/vacaciones/year/{year}")
def delete_vacaciones_year(year: int):
    """Delete a year. Only allowed if >1 years and is highest year."""
    result = delete_year(year)
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("message"))
    return result


@app.get("/api/health/vacaciones")
def get_vacaciones_health():
    """Health check alias — matches path expected by the dashboard."""
    return {"online": is_healthy()}


# ── Static assets (CSS etc.) ──────────────────────────────────────────────────

_static_dir = Path(__file__).parent / "static"
if _static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")
