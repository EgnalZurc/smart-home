"""Vacaciones Service — standalone microservice for Christmas planning.

This service provides a REST API and SPA for planning family Christmas
gatherings across multiple years. It tracks which family nucleus hosts
each meal and which persons attend.

Serves:
    GET  /smart-home/vacaciones       → vacaciones.html (SPA)
    GET  /api/vacaciones              → all data
    GET  /api/vacaciones/config       → nucleos + personas config
    POST /api/vacaciones/config       → save config
    POST /api/vacaciones/year         → add new year
    POST /api/vacaciones/year/{year}  → save year plan
    DELETE /api/vacaciones/year/{year}→ delete year
    GET  /health                      → health check (used by nginx + dashboard)

Auth:
    nginx handles auth_request before requests reach this service.
    This service trusts all incoming requests as already authenticated.
    No auth logic here — keep it simple.

Port: 8003

Typical usage:
    The service is run via uvicorn in the Docker container::

        uvicorn main:app --host 0.0.0.0 --port 8003
"""

import logging
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi import Path as PathParam
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from smart_home_common.rate_limiter import InMemoryRateLimiter
from vacaciones_controller import (
    MAX_NUCLEOS,
    MAX_PERSONAS,
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

# ── Constants ─────────────────────────────────────────────────────────────────

MIN_YEAR = 2000
MAX_YEAR = 2100

# ── Rate limiting ─────────────────────────────────────────────────────────────

# Rate limiter using smart_home_common for consistency across services
_rate_limiter = InMemoryRateLimiter(max_requests=30, window_seconds=60)


def _get_client_ip(request: Request) -> str:
    """Extract the client IP address from an HTTP request.

    Handles the X-Forwarded-For header set by reverse proxies (nginx)
    to get the real client IP instead of the proxy's IP.

    Args:
        request: The FastAPI request object.

    Returns:
        The client's IP address as a string. Returns "unknown" if
        the IP cannot be determined.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _check_rate_limit(request: Request) -> None:
    """Check rate limit for the request. Raises 429 if exceeded.

    Args:
        request: The FastAPI request object.

    Raises:
        HTTPException: 429 if rate limit exceeded.
    """
    client_ip = _get_client_ip(request)
    if not _rate_limiter.is_allowed(client_ip):
        raise HTTPException(status_code=429, detail="Too many requests")


def _validate_year(year: int) -> None:
    """Validate that a year is within acceptable bounds.

    Args:
        year: The year to validate.

    Raises:
        HTTPException: If year is outside the valid range (2000-2100).
    """
    if year < MIN_YEAR or year > MAX_YEAR:
        raise HTTPException(
            status_code=400,
            detail=f"Year must be between {MIN_YEAR} and {MAX_YEAR}",
        )


# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="Vacaciones Service",
    version="1.0.0",
    docs_url="/swagger",
    redoc_url="/redoc",
)


# ── Pydantic models ───────────────────────────────────────────────────────────


class NucleoInput(BaseModel):
    """Input model for a family nucleus.

    A nucleus represents a family unit or gathering location, such as
    "Padres de Angel" or "Casa de los abuelos".

    Attributes:
        id: Unique identifier (lowercase alphanumeric with underscores).
        nombre: Human-readable name of the nucleus.
        color: Hex color code for UI display (default: indigo).
        hijo_id: Optional ID linking to a child person in this nucleus.
    """

    id: str = Field(max_length=64, pattern=r"^[a-z0-9_]+$")
    nombre: str = Field(max_length=100)
    color: str = Field(default="#6366f1", max_length=20)
    hijo_id: str = Field(default="", max_length=64)


class PersonaInput(BaseModel):
    """Input model for a person.

    Represents an individual family member who attends gatherings.

    Attributes:
        id: Unique identifier (lowercase alphanumeric with underscores).
        nombre: Full name of the person.
        inicial: Short initial(s) for compact display in the UI.
        nucleo_id: ID of the nucleus this person belongs to.
    """

    id: str = Field(max_length=64, pattern=r"^[a-z0-9_]+$")
    nombre: str = Field(max_length=100)
    inicial: str = Field(default="", max_length=5)
    nucleo_id: str = Field(default="", max_length=64)


class VacacionesConfigRequest(BaseModel):
    """Request model for saving vacaciones configuration.

    Contains the complete list of family nuclei and persons to be saved.

    Attributes:
        nucleos: List of family nuclei (max: MAX_NUCLEOS).
        personas: List of persons (max: MAX_PERSONAS).
    """

    nucleos: list[NucleoInput] = Field(default_factory=list, max_length=MAX_NUCLEOS)
    personas: list[PersonaInput] = Field(default_factory=list, max_length=MAX_PERSONAS)


class ComidaInput(BaseModel):
    """Input model for a meal entry.

    Represents a single meal event (breakfast, lunch, or dinner) on a
    specific day during the Christmas period.

    Attributes:
        momento: Meal identifier (e.g., "cena_24", "comida_25").
        nucleo_id: ID of the hosting nucleus, or None if unassigned.
        personas: List of person IDs attending this meal.
        personas_por_nucleo: Mapping of nucleus ID to list of attending
            person IDs from that nucleus.
        notas: Optional notes about this meal (max 500 chars).
    """

    momento: str = Field(max_length=32)
    nucleo_id: str | None = Field(default=None, max_length=64)
    personas: list[str] = Field(default_factory=list, max_length=MAX_PERSONAS)
    personas_por_nucleo: dict[str, list[str]] = Field(default_factory=dict)
    notas: str = Field(default="", max_length=500)


class VacacionesYearRequest(BaseModel):
    """Request model for saving a year's planning.

    Contains all meal assignments and notes for a single year.

    Attributes:
        comidas: List of meal entries for the year (max: 10 meals).
        notas: General notes for the year (max 1000 chars).
    """

    comidas: list[ComidaInput] = Field(default_factory=list, max_length=10)
    notas: str = Field(default="", max_length=1000)


# ── Health ────────────────────────────────────────────────────────────────────


@app.get("/health")
def health() -> dict[str, str | bool]:
    """Health check endpoint for nginx and dashboard monitoring.

    Verifies that the service is running and the data directory is
    accessible.

    Returns:
        Dictionary with 'online' status and 'service' name.
    """
    return {"online": is_healthy(), "service": "vacaciones"}


# ── SPA ───────────────────────────────────────────────────────────────────────


def _serve_html(filename: str) -> HTMLResponse:
    """Serve an HTML file with cache-busting headers.

    Reads the HTML file, injects a version comment for cache-busting,
    and returns it with no-cache headers to ensure the browser always
    fetches the latest version.

    Args:
        filename: Name of the HTML file in the static directory.

    Returns:
        HTMLResponse with the file content and no-cache headers.

    Raises:
        FileNotFoundError: If the HTML file does not exist.
    """
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
async def serve_vacaciones() -> HTMLResponse:
    """Serve the Vacaciones single-page application.

    Returns:
        HTMLResponse containing the vacaciones.html SPA.
    """
    return _serve_html("vacaciones.html")


# ── API ───────────────────────────────────────────────────────────────────────


@app.get("/api/vacaciones")
def get_vacaciones() -> dict:
    """Get all vacaciones data.

    Returns the complete dataset including configuration (nucleos and
    personas), all year plans, and the list of valid momentos.

    Returns:
        Dictionary containing 'nucleos', 'personas', 'years', and
        'momentos' keys.
    """
    return get_vacaciones_data()


@app.get("/api/vacaciones/config")
def get_vacaciones_config() -> dict:
    """Get vacaciones configuration.

    Returns only the configuration data (nucleos and personas) without
    year plans.

    Returns:
        Dictionary with 'nucleos' and 'personas' lists.
    """
    return get_config()


@app.post("/api/vacaciones/config")
def post_vacaciones_config(request: Request, data: VacacionesConfigRequest) -> dict:
    """Save vacaciones configuration.

    Replaces the entire configuration with the provided nucleos and
    personas. Rate-limited to prevent abuse.

    Args:
        request: The FastAPI request object (for rate limiting).
        data: The new configuration to save.

    Returns:
        Dictionary with 'status' key ('ok' on success).

    Raises:
        HTTPException: 429 if rate limit exceeded.
    """
    _check_rate_limit(request)
    nucleos = [n.model_dump() for n in data.nucleos]
    personas = [p.model_dump() for p in data.personas]
    return save_config(nucleos, personas)


@app.post("/api/vacaciones/year")
def add_vacaciones_year(request: Request) -> dict:
    """Add a new year to the planning.

    Creates a new year plan for the year after the highest existing
    year, initialized with empty meals for all momentos.

    Args:
        request: The FastAPI request object (for rate limiting).

    Returns:
        Dictionary with 'status' and 'year' (the newly created year).

    Raises:
        HTTPException: 429 if rate limit exceeded.
    """
    _check_rate_limit(request)
    return add_year()


@app.post("/api/vacaciones/year/{year}")
def post_vacaciones_year(
    year: int = PathParam(ge=MIN_YEAR, le=MAX_YEAR),
    *,
    request: Request,
    data: VacacionesYearRequest,
) -> dict:
    """Save a year's planning.

    Updates or creates the meal assignments and notes for the specified
    year.

    Args:
        year: The year to save (must be between 2000 and 2100).
        request: The FastAPI request object (for rate limiting).
        data: The year plan data containing meals and notes.

    Returns:
        Dictionary with 'status' key ('ok' on success).

    Raises:
        HTTPException: 400 if year is out of range, 429 if rate limit
            exceeded.
    """
    _validate_year(year)
    _check_rate_limit(request)
    comidas = [c.model_dump() for c in data.comidas]
    return save_year(year, comidas, data.notas)


@app.delete("/api/vacaciones/year/{year}")
def delete_vacaciones_year(
    year: int = PathParam(ge=MIN_YEAR, le=MAX_YEAR),
    *,
    request: Request,
) -> dict:
    """Delete a year from the planning.

    Removes the specified year. Only allowed if there is more than one
    year and the year being deleted is the highest (most recent).

    Args:
        year: The year to delete (must be between 2000 and 2100).
        request: The FastAPI request object (for rate limiting).

    Returns:
        Dictionary with 'status' key ('ok' on success).

    Raises:
        HTTPException: 400 if year is out of range or deletion is not
            allowed, 429 if rate limit exceeded.
    """
    _validate_year(year)
    _check_rate_limit(request)
    result = delete_year(year)
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("message"))
    return result


@app.get("/api/health/vacaciones")
def get_vacaciones_health() -> dict[str, bool]:
    """Health check alias for dashboard compatibility.

    Provides the same health status in the format expected by the
    central dashboard's health monitoring.

    Returns:
        Dictionary with 'online' boolean status.
    """
    return {"online": is_healthy()}


# ── Static assets (CSS etc.) ──────────────────────────────────────────────────

_static_dir = Path(__file__).parent / "static"
if _static_dir.exists():
    app.mount(
        "/static/vacaciones", StaticFiles(directory=str(_static_dir)), name="static"
    )
