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

Security:
    CSRF protection via Origin/Referer header validation on state-changing
    requests (POST, PUT, DELETE). Since this is a JSON API consumed by an
    SPA (no HTML forms, no session cookies), traditional token-based CSRF
    is not applicable. Origin validation prevents cross-origin requests
    from malicious sites.

Port: 8003

Typical usage:
    The service is run via uvicorn in the Docker container::

        uvicorn main:app --host 0.0.0.0 --port 8003
"""

import logging
import os
import time
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi import Path as PathParam
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from smart_home_common.rate_limiter import InMemoryRateLimiter
from starlette.middleware.base import BaseHTTPMiddleware
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

# ── CSRF Protection ───────────────────────────────────────────────────────────

# Allowed origins for state-changing requests (POST/PUT/DELETE).
# Configured via ALLOWED_ORIGINS env var (comma-separated) or defaults to
# the production Tailscale domain. In development/testing, set to "*" to disable.
_DEFAULT_ORIGINS = "https://raspberrypi.tailaa37cd.ts.net"
_allowed_origins_raw = os.environ.get("ALLOWED_ORIGINS", _DEFAULT_ORIGINS)
ALLOWED_ORIGINS: set[str] = (
    set()
    if _allowed_origins_raw == "*"
    else {o.strip().rstrip("/") for o in _allowed_origins_raw.split(",") if o.strip()}
)


def _extract_origin(header_value: str | None) -> str | None:
    """Extract the origin (scheme://host[:port]) from Origin or Referer header.

    Args:
        header_value: The value of the Origin or Referer header.

    Returns:
        The origin string (e.g., "https://example.com") or None if invalid.
    """
    if not header_value:
        return None
    try:
        parsed = urlparse(header_value)
        if parsed.scheme and parsed.netloc:
            # Reconstruct origin without path
            origin = f"{parsed.scheme}://{parsed.netloc}"
            return origin.rstrip("/")
    except (ValueError, TypeError):
        pass
    return None


def _check_csrf(request: Request) -> None:
    """Validate Origin/Referer header for CSRF protection.

    For state-changing methods (POST, PUT, DELETE, PATCH), verifies that
    the request comes from an allowed origin. This prevents cross-site
    request forgery attacks where a malicious site submits requests on
    behalf of an authenticated user.

    Args:
        request: The FastAPI request object.

    Raises:
        HTTPException: 403 if the origin is not allowed.
    """
    # Skip CSRF check if disabled (ALLOWED_ORIGINS="*")
    if not ALLOWED_ORIGINS:
        return

    # Only check state-changing methods
    if request.method not in ("POST", "PUT", "DELETE", "PATCH"):
        return

    # Try Origin header first, then Referer
    origin = _extract_origin(request.headers.get("origin"))
    if origin is None:
        origin = _extract_origin(request.headers.get("referer"))

    # If neither header is present, reject (could be a direct curl/script call,
    # but in a browser context this would be suspicious)
    if origin is None:
        # GDPR note: Client IP is logged for security monitoring (legitimate interest
        # under GDPR Art. 6(1)(f)). IPs are not stored long-term and are only used
        # to detect and prevent abuse. Consider log rotation policies.
        logger.warning(
            "CSRF check failed: no Origin/Referer header from %s",
            _get_client_ip(request),
        )
        raise HTTPException(
            status_code=403,
            detail="Missing Origin or Referer header",
        )

    if origin not in ALLOWED_ORIGINS:
        # GDPR note: see above - IP logged for security monitoring purposes.
        logger.warning(
            "CSRF check failed: origin %s not in allowed list from %s",
            origin,
            _get_client_ip(request),
        )
        raise HTTPException(
            status_code=403,
            detail="Origin not allowed",
        )


# ── Rate limiting ─────────────────────────────────────────────────────────────

# Rate limiter using smart_home_common for consistency across services
_rate_limiter = InMemoryRateLimiter(
    max_requests=30, window_seconds=60, max_entries=10000
)


def _get_client_ip(request: Request) -> str:
    """Extract the client IP address from an HTTP request.

    Handles the X-Forwarded-For header set by reverse proxies (nginx)
    to get the real client IP instead of the proxy's IP.

    Security Note:
        This function trusts X-Forwarded-For unconditionally because in our
        deployment architecture, ONLY nginx can set this header:
        - The service binds to Docker's internal network (not exposed publicly)
        - All external traffic flows through nginx reverse proxy
        - nginx overwrites X-Forwarded-For with the real client IP
        - Direct access to the service (bypassing nginx) is not possible
        If the deployment architecture changes to expose this service directly,
        this function MUST be updated to validate or ignore X-Forwarded-For.

    Args:
        request: The FastAPI request object.

    Returns:
        The client's IP address as a string. Returns "unknown" if
        the IP cannot be determined.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        # Take the first IP in the chain (leftmost = original client)
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
        # GDPR note: Client IP is logged for security monitoring (legitimate interest
        # under GDPR Art. 6(1)(f)). IPs are not stored long-term and are only used
        # to detect and prevent abuse. Consider log rotation policies.
        logger.warning("Rate limit exceeded for IP: %s", client_ip)
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


# ── Security Headers Middleware ───────────────────────────────────────────────


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware that adds security headers to all responses.

    Headers added:
    - X-Content-Type-Options: Prevents MIME type sniffing
    - X-Frame-Options: Prevents clickjacking via iframes
    - X-XSS-Protection: Legacy XSS filter (for older browsers)
    - Content-Security-Policy: Restricts resource loading sources
    - Referrer-Policy: Controls referrer information sent to other sites

    CSP Policy Note:
        The CSP is aligned with nginx's csp-static.conf to support SPA frontends
        that use inline scripts/styles. This is an accepted risk documented in
        SECURITY_FIXES.md — the service is only accessible via Tailscale VPN
        with nginx auth_request protection.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        """Process request and add security headers to response."""
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        # CSP aligned with nginx csp-static.conf for SPA compatibility.
        # Allows inline scripts/styles needed by the SPA frontend.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "connect-src 'self'"
        )
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response


# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="Vacaciones Service",
    version="1.0.0",
    docs_url="/swagger",
    redoc_url="/redoc",
)

# Register security headers middleware
app.add_middleware(SecurityHeadersMiddleware)


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
        HTTPException: 404 if the HTML file does not exist or cannot be read.
    """
    path = Path(__file__).parent / "static" / filename
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.warning("Static file not found: %s", filename)
        raise HTTPException(status_code=404, detail="Page not found")
    except OSError as e:
        logger.error("Error reading static file %s: %s", filename, e)
        raise HTTPException(status_code=404, detail="Page not found")
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
        HTTPException: 403 if CSRF check fails, 429 if rate limit exceeded.
    """
    _check_csrf(request)
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
        HTTPException: 403 if CSRF check fails, 429 if rate limit exceeded.
    """
    _check_csrf(request)
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
        HTTPException: 400 if year is out of range, 403 if CSRF check fails,
            429 if rate limit exceeded.
    """
    _validate_year(year)
    _check_csrf(request)
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
            allowed, 403 if CSRF check fails, 429 if rate limit exceeded.
    """
    _validate_year(year)
    _check_csrf(request)
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
