"""
casita-orquestador — Proceso principal de Casita Sueños.

Nombre del proceso: casita-orquestador
Función: orquesta el scraping inmobiliario, la puntuación de propiedades,
         las alertas Telegram y el servidor HTTP de estado.

Responsabilidades:
  - Garantiza ejecución única mediante lockfile (singleton)
  - Arranca y supervisa el CasitaScheduler (scraping lunes/jueves, check Gmail 30min)
  - Expone servidor HTTP con FastAPI en :8001 para el dashboard smart-home
    · GET /health  → {"online": true}
    · GET /status  → estado completo (propiedades, errores scrapers, top casas)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from casita_scheduler import CasitaScheduler
    from database import Database

import logging
import os
import sys
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from scorer import ALERT_THRESHOLD as _ALERT_THRESHOLD
from smart_home_common.rate_limiter import InMemoryRateLimiter

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── Rate limiters ────────────────────────────────────────────────────────────
# Redis URL from env or default to compose service name
_REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")


def _create_rate_limiters() -> tuple[InMemoryRateLimiter, InMemoryRateLimiter]:
    """Create rate limiters, preferring Redis with fallback to in-memory.

    Attempts to connect to Redis for distributed rate limiting. If Redis is
    unavailable (connection error, import error, or client initialization
    failure), falls back to in-memory rate limiting.

    Returns:
        A tuple of (global_limiter, manual_trigger_limiter) where:
        - global_limiter: 120 requests/minute for general API endpoints
        - manual_trigger_limiter: 10 requests/minute for manual trigger endpoints
    """
    try:
        from smart_home_common.redis_rate_limiter import RedisRateLimiter

        global_limiter = RedisRateLimiter(
            redis_url=_REDIS_URL,
            max_requests=120,
            window_seconds=60,
            key_prefix="casita:global:",
        )
        manual_limiter = RedisRateLimiter(
            redis_url=_REDIS_URL,
            max_requests=10,
            window_seconds=60,
            key_prefix="casita:manual:",
        )
        # Verify Redis is actually connected (RedisRateLimiter falls back silently)
        if global_limiter._client is not None:
            logger.info("Rate limiters using Redis at %s", _REDIS_URL)
            return global_limiter, manual_limiter

        # Redis client is None means connection failed during init
        logger.warning(
            "Redis connection not available, falling back to in-memory rate limiting"
        )
    except ImportError:
        logger.warning(
            "RedisRateLimiter not available, falling back to in-memory rate limiting"
        )
    except ConnectionError as e:
        logger.warning(
            "Redis connection failed (%s), falling back to in-memory rate limiting", e
        )
    except OSError as e:
        logger.warning(
            "Redis socket error (%s), falling back to in-memory rate limiting", e
        )

    return (
        InMemoryRateLimiter(max_requests=120, window_seconds=60),
        InMemoryRateLimiter(max_requests=10, window_seconds=60),
    )


_global_rate_limiter, _manual_trigger_limiter = _create_rate_limiters()


def _get_client_ip(request: Request) -> str:
    """Extract client IP from request, respecting X-Forwarded-For if present.

    In a reverse proxy setup (nginx), the real client IP is in the
    X-Forwarded-For header. This function extracts the first IP in that
    chain, which is the original client.

    Args:
        request: The incoming FastAPI request object.

    Returns:
        The client IP address as a string. Returns "unknown" if the IP
        cannot be determined.
    """
    # Trust X-Forwarded-For from nginx reverse proxy
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        # Take the first IP in the chain (original client)
        return forwarded.split(",")[0].strip()
    if request.client is not None:
        return request.client.host
    return "unknown"


def _check_manual_trigger_rate_limit(request: Request) -> None:
    """Check rate limit for manual trigger endpoints.

    Manual trigger endpoints (run-scraping, run-gmail-check, etc.) have a
    stricter rate limit (10/minute) to prevent abuse of expensive operations.

    Args:
        request: The incoming FastAPI request object.

    Raises:
        HTTPException: 429 status if rate limit exceeded.
    """
    client_ip = _get_client_ip(request)
    if not _manual_trigger_limiter.is_allowed(client_ip):
        logger.warning(
            "[http] Manual trigger rate limit exceeded for client IP: %s", client_ip
        )
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Try again in a minute.",
        )


# ── Configuración desde variables de entorno ─────────────────────────────────

# Telegram
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
# Notificación de arranque en Telegram: desactivada por defecto para evitar spam
# en cada reinicio del contenedor. Las alertas reales de propiedades no se ven
# afectadas. Pon CASITA_NOTIFY_ON_STARTUP=true para reactivarla.
NOTIFY_ON_STARTUP = os.environ.get("CASITA_NOTIFY_ON_STARTUP", "false").lower() in (
    "1",
    "true",
    "yes",
)

# Apify
APIFY_API_TOKEN = os.environ.get("APIFY_API_TOKEN", "")

# Gmail
GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS", "")
DATA_DIR = os.environ.get("CASITA_DATA_DIR", "/app/data")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")

# Base de datos
DB_PATH = os.environ.get("CASITA_DB_PATH", f"{DATA_DIR}/casita.db")

# Apify usage tracker
APIFY_USAGE_PATH = os.environ.get("APIFY_USAGE_PATH", f"{DATA_DIR}/apify_usage.json")

# Puerto
try:
    STATUS_PORT = int(os.environ.get("CASITA_STATUS_PORT", "8001"))
except ValueError:
    logging.error(
        "[main] CASITA_STATUS_PORT debe ser numérico, se encontró: %r. "
        "Usando valor por defecto 8001.",
        os.environ.get("CASITA_STATUS_PORT"),
    )
    STATUS_PORT = 8001

# ── Validación ────────────────────────────────────────────────────────────────


def _validate_config() -> None:
    """Validate that critical environment variables are set.

    Checks for required variables (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
    GMAIL_ADDRESS) and exits with error if any are missing.

    Optional variables (APIFY_API_TOKEN, GMAIL_APP_PASSWORD) produce
    warnings but don't prevent startup.

    Raises:
        SystemExit: If any required variable is missing.
    """
    logger.info("[main] Validating configuration...")
    errors: list[str] = []
    if not TELEGRAM_BOT_TOKEN:
        errors.append("TELEGRAM_BOT_TOKEN no configurado")
    if not TELEGRAM_CHAT_ID:
        errors.append("TELEGRAM_CHAT_ID no configurado")
    if not GMAIL_ADDRESS:
        errors.append("GMAIL_ADDRESS no configurado")
    if errors:
        for e in errors:
            logger.error("[main] %s", e)
        logger.error("[main] Configuration validation failed, exiting")
        sys.exit(1)

    # APIFY_API_TOKEN es opcional: el módulo Idealista/Apify está deshabilitado
    # (DataDome bloquea el scraping). Sin token el servicio funciona igual, así que
    # no debe provocar un crashloop — solo avisamos.
    if not APIFY_API_TOKEN:
        logger.warning(
            "[main] APIFY_API_TOKEN no configurado. "
            "El scraping de Idealista está deshabilitado de todas formas; "
            "se continúa sin él."
        )

    if not GMAIL_APP_PASSWORD:
        logger.warning(
            "[main] GMAIL_APP_PASSWORD no configurado. "
            "El check de alertas de Idealista no funcionará. "
            "Genera una App Password en myaccount.google.com/apppasswords"
        )

    logger.info("[main] Configuration validation passed")


# ── Nombre del proceso ────────────────────────────────────────────────────────

PROCESS_NAME = "casita-orquestador"


def _set_process_name() -> None:
    """Fija el nombre del proceso para identificarlo en ps/top/htop."""
    try:
        import setproctitle

        setproctitle.setproctitle(PROCESS_NAME)
    except ImportError:
        if sys.argv:
            sys.argv[0] = PROCESS_NAME
    threading.current_thread().name = PROCESS_NAME


# ── Instancia global del scheduler (deprecated, use app.state) ────────────────
# These are kept for backward compatibility with main()
# New code should use request.app.state.scheduler and request.app.state.db
_scheduler_instance: CasitaScheduler | None = None
_db_instance: Database | None = None


# ── Lifespan context manager ──────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize scheduler and database on startup, clean up on shutdown.

    This async context manager handles the application lifecycle:
    - On startup: initializes Database, TelegramNotifier, ApifyUsageTracker,
      IdealistaApifyClient, and CasitaScheduler instances
    - Stores instances in app.state for access via request handlers
    - Optionally sends startup notification to Telegram
    - Starts the scheduler and Telegram polling background thread
    - On shutdown: stops scheduler and closes database connection

    Args:
        app: The FastAPI application instance.

    Yields:
        Control back to the application after initialization.
    """
    global _scheduler_instance, _db_instance

    from apify_client_wrapper import ApifyUsageTracker, IdealistaApifyClient
    from casita_scheduler import CasitaScheduler
    from database import Database
    from notifier import TelegramNotifier

    logger.info("[main] Starting application lifecycle initialization")

    # Instanciar componentes
    db = Database(DB_PATH)
    notifier = TelegramNotifier(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, db=db)
    tracker = ApifyUsageTracker(APIFY_USAGE_PATH)
    apify = IdealistaApifyClient(APIFY_API_TOKEN, tracker)

    scheduler = CasitaScheduler(
        db=db,
        notifier=notifier,
        apify=apify,
        gmail_address=GMAIL_ADDRESS,
        gmail_app_password=GMAIL_APP_PASSWORD,
    )

    # Store in app.state for access via request.app.state
    app.state.scheduler = scheduler
    app.state.db = db

    # Also keep globals for backward compatibility
    _scheduler_instance = scheduler
    _db_instance = db

    # Notificar arranque
    if NOTIFY_ON_STARTUP:
        try:
            radar_count = len(
                db.get_radar_properties(min_score=_ALERT_THRESHOLD, limit=500).get(
                    "items", []
                )
            )
            notifier.send_status(
                f"🚀 Casita Sueños arrancado · {radar_count} casas en el radar"
            )
            logger.info("[main] Startup notification sent to Telegram")
        except (KeyError, TypeError) as e:
            logger.warning(
                "[main] Could not get radar count for startup message: %s", e
            )
    else:
        logger.info(
            "[main] Notificación de arranque Telegram omitida "
            "(CASITA_NOTIFY_ON_STARTUP no activado)"
        )

    # Arrancar scheduler
    scheduler.start()
    logger.info("[main] Scheduler activo")

    # Arrancar polling de Telegram (db is now available)
    threading.Thread(
        target=_telegram_polling, args=(db,), daemon=True, name="telegram-polling"
    ).start()
    logger.info("[main] Telegram polling thread started")

    yield

    # Cleanup on shutdown
    logger.info("[main] Cerrando scheduler y base de datos")
    scheduler.stop()
    db.close()
    logger.info("[main] Application shutdown complete")


# ── FastAPI App ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="Casita Sueños",
    description="Orquestador de búsqueda inmobiliaria",
    version="2.0.0",
    docs_url=None,  # Deshabilitar docs en producción
    redoc_url=None,
    lifespan=lifespan,
)


# ── Global rate limiting middleware ───────────────────────────────────────────


# ── CSRF Protection via Origin Validation ────────────────────────────────────
# Allowed origins for CSRF protection. Requests from these origins are trusted.
# Internal API behind Tailscale VPN - only allow known hosts.
# Using frozenset for immutability (security best practice).
_ALLOWED_ORIGINS: frozenset[str] = frozenset(
    {
        "https://raspberrypi.tailaa37cd.ts.net",  # Tailscale hostname
        "http://raspberrypi.local",  # Local network
        "http://localhost",
        "http://localhost:8001",
        "http://127.0.0.1",
        "http://127.0.0.1:8001",
        # Note: Telegram API calls originate from our server, not browsers,
        # so they don't send Origin headers and are allowed by default.
    }
)


def _validate_origin(request: Request) -> bool:
    """Validate request Origin header for CSRF protection.

    For POST/PUT/DELETE requests, validates that the Origin header matches
    an allowed origin. This prevents CSRF attacks where a malicious site
    tries to make requests on behalf of the user.

    For internal APIs behind Tailscale VPN, Origin validation is sufficient
    because browsers always send Origin for cross-origin requests.

    Args:
        request: The incoming HTTP request.

    Returns:
        True if the request is allowed, False if it should be blocked.
    """
    # Only check state-changing methods
    if request.method not in ("POST", "PUT", "DELETE", "PATCH"):
        return True

    origin = request.headers.get("origin")

    # Check if origin is in the allowed list when present
    return not (origin and origin not in _ALLOWED_ORIGINS)


# Sensitive endpoints that require X-Requested-With header for CSRF protection.
# These endpoints modify state and should only be called from our frontend JS.
# Using frozenset for immutability and O(1) lookup.
_CSRF_PROTECTED_PATHS: frozenset[str] = frozenset(
    {
        "/api/casita/dismiss",
        "/api/casita/undismiss",
        "/api/casita/mark-viewed",
        "/api/casita/save-comment",
        "/api/casita/schedule",
        "/api/casita/run-scraping",
        "/api/casita/run-gmail-check",
        "/api/casita/run-fotocasa-check",
        "/api/casita/run-summary",
    }
)


def _validate_csrf_header(request: Request) -> bool:
    """Validate X-Requested-With header for sensitive POST endpoints.

    For endpoints in _CSRF_PROTECTED_PATHS, requires X-Requested-With header.
    This is a defense-in-depth measure: browsers don't allow setting custom
    headers in cross-origin requests without CORS preflight, so the presence
    of this header proves the request came from JavaScript on an allowed origin.

    This protects against CSRF even when Origin header is missing (same-origin
    requests from browsers don't always include Origin).

    Args:
        request: The incoming HTTP request.

    Returns:
        True if the request is allowed, False if it should be blocked.
    """
    # Only check state-changing methods on protected paths
    if request.method not in ("POST", "PUT", "DELETE", "PATCH"):
        return True

    if request.url.path not in _CSRF_PROTECTED_PATHS:
        return True

    # Require X-Requested-With header for protected endpoints
    # Value doesn't matter, just needs to be present (conventionally "XMLHttpRequest")
    return request.headers.get("x-requested-with") is not None


@app.middleware("http")
async def csrf_protection_middleware(request: Request, call_next):
    """CSRF protection via Origin header and X-Requested-With validation.

    Two-layer protection:
    1. Blocks requests with an Origin header not in the allowed list
    2. For sensitive endpoints, requires X-Requested-With header

    Returns:
        403 Forbidden if Origin is present but not allowed, or if
        X-Requested-With is missing on a protected endpoint.
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

    if not _validate_csrf_header(request):
        logger.warning(
            "[http] CSRF protection: missing X-Requested-With header for %s",
            request.url.path,
        )
        return JSONResponse(
            status_code=403,
            content={"error": "Forbidden: missing X-Requested-With header"},
        )

    return await call_next(request)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    """Add security headers to all responses.

    Headers added:
    - X-Content-Type-Options: nosniff - Prevents MIME type sniffing
    - X-Frame-Options: DENY - Prevents clickjacking via iframe embedding
    - Content-Security-Policy: default-src 'self' - Restricts resource loading
    - X-XSS-Protection: 1; mode=block - Legacy XSS filter (for older browsers)
    - Referrer-Policy: strict-origin-when-cross-origin - Controls referrer info

    Returns:
        Response with security headers added.
    """
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; "
        "connect-src 'self'"
    )
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """Apply global rate limiting to all API endpoints.

    Exempts:
    - /health endpoint (needed by Docker healthcheck and monitoring)
    - /static/* paths (static file serving)

    Args:
        request: The incoming HTTP request.
        call_next: The next middleware or route handler.

    Returns:
        Response from the next handler, or 429 if rate limited.
    """
    path = request.url.path

    # Skip rate limiting for health check (needed by Docker/monitoring)
    if path == "/health":
        return await call_next(request)

    # Skip rate limiting for static files
    if path.startswith("/static/"):
        return await call_next(request)

    # Apply global rate limit to API endpoints
    if path.startswith("/api/"):
        client_ip = _get_client_ip(request)
        if not _global_rate_limiter.is_allowed(client_ip):
            logger.warning(
                "[http] Rate limit exceeded for client IP: %s on path: %s",
                client_ip,
                path,
            )
            return JSONResponse(
                status_code=429,
                content={"error": "Too many requests. Try again later."},
            )

    return await call_next(request)


# ── Pydantic Models ───────────────────────────────────────────────────────────


class PropertyUid(BaseModel):
    uid: str


class CommentRequest(BaseModel):
    uid: str
    comment: str


class ScheduleConfig(BaseModel):
    scraping_enabled: bool | None = None
    scraping_days: list[int] | None = None
    scraping_hour: int | None = None
    gmail_check_enabled: bool | None = None
    gmail_interval_min: int | None = None
    summary_enabled: bool | None = None
    summary_day: int | None = None
    summary_hour: int | None = None


# ── Middleware de errores ─────────────────────────────────────────────────────


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle uncaught exceptions with a generic 500 response.

    Logs the full exception traceback for debugging while returning
    a sanitized error message to the client to avoid leaking internal
    details.

    Args:
        request: The request that caused the exception.
        exc: The uncaught exception.

    Returns:
        JSONResponse with 500 status and generic error message.
    """
    logger.exception("[http] Unhandled exception on %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error"},
    )


# ── Static files ──────────────────────────────────────────────────────────────

STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/static/casita", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ── API Router con prefijo /api/casita ────────────────────────────────────────
# El frontend espera las rutas en /api/casita/status, /api/casita/radar, etc.
# nginx hace proxy de /api/casita/* a casita-suenos:8001/api/casita/*

api = APIRouter(prefix="/api/casita")


# ── Health endpoint (sin prefijo, para Docker healthcheck) ────────────────────


@app.get("/health")
async def health(request: Request) -> dict[str, bool | str | None]:
    """Health check endpoint with scheduler status detection.

    Used by Docker healthcheck and monitoring systems to verify the
    service is responsive. Includes scheduler liveness detection to
    identify hung scheduler loops.

    Args:
        request: The incoming HTTP request.

    Returns:
        dict with:
        - online: Always True if the HTTP server responds
        - last_scheduler_tick: ISO timestamp of last scheduler loop tick,
          or None if scheduler hasn't run yet
        - scheduler_stale: True if >2 hours since last tick (indicates
          scheduler may be hung)
    """
    scheduler = getattr(request.app.state, "scheduler", None)

    last_tick: str | None = None
    scheduler_stale = False
    if scheduler is not None:
        tick = scheduler.get_last_tick()
        last_tick = tick.isoformat() if tick else None
        scheduler_stale = scheduler.is_stale(max_age_hours=2)

    return {
        "online": True,
        "last_scheduler_tick": last_tick,
        "scheduler_stale": scheduler_stale,
    }


# ── Status endpoint ───────────────────────────────────────────────────────────


@api.get("/status")
async def status(request: Request) -> dict:
    """Get comprehensive service status information.

    Returns operational status, scheduling information, statistics,
    and top-scoring properties for the dashboard display.

    Args:
        request: The incoming HTTP request.

    Returns:
        dict with service status including:
        - online/running state
        - last operation timestamps (scraping, gmail check, summary)
        - property counts (total, radar, dismissed)
        - scraper error information
        - scoring thresholds
        - schedule configuration
        - top 5 properties by score

    Raises:
        HTTPException: 503 if scheduler not initialized.
    """
    scheduler = request.app.state.scheduler
    if scheduler is None:
        raise HTTPException(status_code=503, detail="Scheduler not ready")

    import scorer

    status_obj = scheduler.get_status()
    scraper_errors = [
        {
            "portal": e.portal,
            "zone_id": e.zone_id,
            "error": e.error,
            "detected_at": e.detected_at.isoformat(),
        }
        for e in status_obj.scraper_errors
    ]
    cfg = scheduler.get_schedule_config()

    return {
        "online": True,
        "running": status_obj.running,
        "last_scraping": status_obj.last_scraping.isoformat()
        if status_obj.last_scraping
        else None,
        "last_gmail_check": status_obj.last_gmail_check.isoformat()
        if status_obj.last_gmail_check
        else None,
        "last_summary": status_obj.last_summary.isoformat()
        if status_obj.last_summary
        else None,
        "last_scraping_result": status_obj.last_scraping_result,
        "total_properties": status_obj.total_properties,
        "radar_count": status_obj.radar_count,
        "dismissed_count": status_obj.dismissed_count,
        "scraper_errors": scraper_errors,
        "scraper_errors_count": len(scraper_errors),
        "score_max": scorer.MAX_SCORE,
        "alert_threshold": scorer.ALERT_THRESHOLD,
        "alert_threshold_pct": round(scorer.ALERT_THRESHOLD / scorer.MAX_SCORE * 100),
        "schedule": cfg,
        "top_properties": [
            {
                "uid": p.get("uid", ""),
                "title": p.get("title", ""),
                "price": p.get("price", 0),
                "score": round(p.get("score_total", 0), 1),
                "zone_id": p.get("zone_id", ""),
                "url": p.get("url", ""),
                "rooms": p.get("rooms"),
                "size_m2": p.get("size_m2"),
                "first_seen": p.get("first_seen", ""),
            }
            for p in status_obj.top_properties
        ],
    }


# ── Radar & Properties endpoints ──────────────────────────────────────────────


@api.get("/alerts")
async def get_casita_alerts(request: Request):
    """Return high-scoring properties for the unified alerts system.

    Lists properties scored above the alert threshold in the last 24h as
    normalized alert objects consumed by the smart-home dashboard.
    """
    from datetime import datetime, timedelta

    import scorer

    db = request.app.state.db
    if db is None:
        raise HTTPException(status_code=503, detail="Not ready")

    cutoff_iso = (datetime.now() - timedelta(hours=24)).isoformat()
    high_scorers = db.get_recent_high_scorers(cutoff_iso, scorer.ALERT_THRESHOLD)

    alerts = []
    for prop in high_scorers:
        title = prop.get("title") or ""
        price = prop.get("price") or 0
        score = prop.get("score_total") or 0
        scored_at = prop.get("scored_at")
        uid = prop.get("uid")
        trend = db.get_price_trend(uid) if uid else {}
        alerts.append(
            {
                "source": "casita",
                "severity": "info",
                "id": uid,  # Used by dashboard to build dismiss key
                "title": title[:50] if title else "Propiedad interesante",
                "detail": f"Score: {score:.0f}/{scorer.MAX_SCORE:.0f} - {price:,.0f}€",
                "timestamp": scored_at if scored_at else datetime.now().isoformat(),
                "link": prop.get("url"),
                "previous_price": trend.get("previous_price"),
                "price_change": trend.get("price_change"),
                "price_change_pct": trend.get("price_change_pct"),
                "trend": trend.get("trend"),
            }
        )
    return {"alerts": alerts}


@api.get("/zone-trends")
async def get_zone_trends(request: Request, days: int = 30):
    """Return per-zone time series for dashboard charts.

    For each zone with properties in the window, returns daily data points
    (count, average price and average score), the number of properties
    currently on the radar, and a growing/stable/declining trend flag.
    """
    db = request.app.state.db
    if db is None:
        raise HTTPException(status_code=503, detail="Not ready")

    # Clamp the window to a sane range: at least 1 day, at most ~1 year.
    days = max(1, min(days, 365))

    return {"days": days, "zones": db.get_zone_trends(days=days)}


@api.get("/radar")
async def get_radar(
    request: Request,
    limit: int = 20,
    offset: int = 0,
    sort_by: str = "score",
    sort_dir: str = "desc",
    filter: str | None = None,
    portal: str | None = None,
) -> dict:
    """Get paginated list of properties on the radar.

    Returns properties that score above the alert threshold, with support
    for pagination, sorting, and filtering.

    Args:
        request: The incoming HTTP request.
        limit: Maximum number of properties to return (max 100).
        offset: Number of properties to skip for pagination.
        sort_by: Field to sort by (score, price, first_seen).
        sort_dir: Sort direction (asc, desc).
        filter: Optional text filter for title/zone.
        portal: Optional portal filter (idealista, fotocasa, etc.).

    Returns:
        dict with items list, total count, pagination info, and has_more flag.

    Raises:
        HTTPException: 503 if scheduler not initialized.
    """
    scheduler = request.app.state.scheduler
    if scheduler is None:
        raise HTTPException(status_code=503, detail="Not ready")

    limit = min(limit, 100)
    offset = max(offset, 0)

    return scheduler.get_radar(
        limit=limit,
        offset=offset,
        sort_by=sort_by,
        sort_dir=sort_dir,
        filter_by=filter,
        portal_filter=portal,
    )


@api.get("/dismissed")
async def get_dismissed(request: Request) -> dict[str, list]:
    """Get list of dismissed properties.

    Returns properties that the user has marked as dismissed (not interested).

    Args:
        request: The incoming HTTP request.

    Returns:
        dict with 'properties' key containing list of dismissed properties.

    Raises:
        HTTPException: 503 if scheduler not initialized.
    """
    scheduler = request.app.state.scheduler
    if scheduler is None:
        raise HTTPException(status_code=503, detail="Not ready")
    return {"properties": scheduler.get_dismissed()}


@api.post("/dismiss")
async def dismiss_property(req: PropertyUid, request: Request) -> dict[str, bool | str]:
    """Mark a property as dismissed (not interested).

    Rate limited to 10 requests/minute per client IP to prevent abuse.

    Args:
        req: Request body with property UID.
        request: The incoming HTTP request.

    Returns:
        dict with ok=True and the dismissed UID.

    Raises:
        HTTPException: 404 if property not found, 429 if rate limited, 503 if not ready.
    """
    _check_manual_trigger_rate_limit(request)
    scheduler = request.app.state.scheduler
    if scheduler is None:
        raise HTTPException(status_code=503, detail="Not ready")
    ok = scheduler.dismiss_property(req.uid)
    if not ok:
        raise HTTPException(status_code=404, detail="Property not found")
    logger.info("[api] Property dismissed: %s", req.uid)
    return {"ok": True, "uid": req.uid}


@api.post("/undismiss")
async def undismiss_property(
    req: PropertyUid, request: Request
) -> dict[str, bool | str]:
    """Restore a dismissed property back to the radar.

    Rate limited to 10 requests/minute per client IP to prevent abuse.

    Args:
        req: Request body with property UID.
        request: The incoming HTTP request.

    Returns:
        dict with ok=True and the restored UID.

    Raises:
        HTTPException: 404 if property not found, 429 if rate limited, 503 if not ready.
    """
    _check_manual_trigger_rate_limit(request)
    scheduler = request.app.state.scheduler
    if scheduler is None:
        raise HTTPException(status_code=503, detail="Not ready")
    ok = scheduler.undismiss_property(req.uid)
    if not ok:
        raise HTTPException(status_code=404, detail="Property not found")
    logger.info("[api] Property undismissed: %s", req.uid)
    return {"ok": True, "uid": req.uid}


@api.post("/mark-viewed")
async def mark_viewed(req: PropertyUid, request: Request) -> dict[str, bool | str]:
    """Mark a property as viewed.

    Args:
        req: Request body with property UID.
        request: The incoming HTTP request.

    Returns:
        dict with ok=True and the marked UID.

    Raises:
        HTTPException: 404 if property not found, 503 if not ready.
    """
    scheduler = request.app.state.scheduler
    if scheduler is None:
        raise HTTPException(status_code=503, detail="Not ready")
    ok = scheduler.mark_viewed(req.uid)
    if not ok:
        raise HTTPException(status_code=404, detail="Property not found")
    return {"ok": True, "uid": req.uid}


@api.post("/save-comment")
async def save_comment(req: CommentRequest, request: Request) -> dict[str, bool | str]:
    """Save a user comment on a property.

    Args:
        req: Request body with property UID and comment text.
        request: The incoming HTTP request.

    Returns:
        dict with ok=True and the property UID.

    Raises:
        HTTPException: 404 if property not found, 503 if not ready.
    """
    scheduler = request.app.state.scheduler
    if scheduler is None:
        raise HTTPException(status_code=503, detail="Not ready")
    ok = scheduler.save_comment(req.uid, req.comment)
    if not ok:
        raise HTTPException(status_code=404, detail="Property not found")
    logger.info("[api] Comment saved for property: %s", req.uid)
    return {"ok": True, "uid": req.uid}


# ── Schedule endpoints ────────────────────────────────────────────────────────


@api.get("/schedule")
async def get_schedule(request: Request) -> dict:
    """Get current schedule configuration.

    Args:
        request: The incoming HTTP request.

    Returns:
        dict with schedule settings (scraping days/hour, gmail interval, etc.).

    Raises:
        HTTPException: 503 if scheduler not initialized.
    """
    scheduler = request.app.state.scheduler
    if scheduler is None:
        raise HTTPException(status_code=503, detail="Not ready")
    return scheduler.get_schedule_config()


@api.post("/schedule")
async def save_schedule(config: ScheduleConfig, request: Request) -> dict[str, bool]:
    """Update schedule configuration.

    Only updates fields that are provided (non-None). Allows partial updates.

    Args:
        config: Schedule configuration with optional fields.
        request: The incoming HTTP request.

    Returns:
        dict with ok=True on success.

    Raises:
        HTTPException: 503 if scheduler not initialized.
    """
    scheduler = request.app.state.scheduler
    if scheduler is None:
        raise HTTPException(status_code=503, detail="Not ready")

    # Only save non-None fields
    validated = {k: v for k, v in config.model_dump().items() if v is not None}
    if validated:
        scheduler.save_schedule_config(validated)
        logger.info("[api] Schedule config updated: %s", list(validated.keys()))
    return {"ok": True}


@api.get("/summary")
async def get_summary(request: Request) -> dict[str, str | None]:
    """Get the last weekly summary that was sent.

    Args:
        request: The incoming HTTP request.

    Returns:
        dict with 'content' (summary text) and 'sent_at' (ISO timestamp),
        or both None if no summary has been sent yet.

    Raises:
        HTTPException: 503 if scheduler not initialized.
    """
    scheduler = request.app.state.scheduler
    if scheduler is None:
        raise HTTPException(status_code=503, detail="Not ready")
    summary = scheduler.get_last_summary()
    return summary or {"content": None, "sent_at": None}


# ── Manual trigger endpoints ──────────────────────────────────────────────────


@api.post("/run-scraping")
async def run_scraping(request: Request) -> dict[str, bool | str]:
    """Manually trigger a scraping run.

    Starts scraping in a background thread. Rate limited to 10/minute.

    Args:
        request: The incoming HTTP request.

    Returns:
        dict with ok=True and confirmation message.

    Raises:
        HTTPException: 429 if rate limited, 503 if not ready.
    """
    _check_manual_trigger_rate_limit(request)
    scheduler = request.app.state.scheduler
    if scheduler is None:
        raise HTTPException(status_code=503, detail="Not ready")
    logger.info("[api] Manual scraping triggered by %s", _get_client_ip(request))
    threading.Thread(
        target=scheduler.run_scraping_now,
        daemon=True,
        name="manual-scraping",
    ).start()
    return {"ok": True, "message": "Scraping iniciado"}


@api.post("/run-gmail-check")
async def run_gmail_check(request: Request) -> dict[str, bool | str]:
    """Manually trigger a Gmail check.

    Checks Gmail for Idealista alerts in a background thread.
    Rate limited to 10/minute.

    Args:
        request: The incoming HTTP request.

    Returns:
        dict with ok=True and confirmation message.

    Raises:
        HTTPException: 429 if rate limited, 503 if not ready.
    """
    _check_manual_trigger_rate_limit(request)
    scheduler = request.app.state.scheduler
    if scheduler is None:
        raise HTTPException(status_code=503, detail="Not ready")
    logger.info("[api] Manual Gmail check triggered by %s", _get_client_ip(request))
    threading.Thread(
        target=scheduler.run_gmail_check_now,
        daemon=True,
        name="manual-gmail",
    ).start()
    return {"ok": True, "message": "Gmail check iniciado"}


@api.post("/run-fotocasa-check")
async def run_fotocasa_check(request: Request) -> dict[str, bool | str]:
    """Manually trigger a Fotocasa email check.

    Checks Gmail for Fotocasa alerts in a background thread.
    Rate limited to 10/minute.

    Args:
        request: The incoming HTTP request.

    Returns:
        dict with ok=True and confirmation message.

    Raises:
        HTTPException: 429 if rate limited, 503 if not ready.
    """
    _check_manual_trigger_rate_limit(request)
    scheduler = request.app.state.scheduler
    if scheduler is None:
        raise HTTPException(status_code=503, detail="Not ready")
    logger.info("[api] Manual Fotocasa check triggered by %s", _get_client_ip(request))
    threading.Thread(
        target=scheduler.run_fotocasa_check_now,
        daemon=True,
        name="manual-fotocasa",
    ).start()
    return {"ok": True, "message": "Fotocasa check iniciado"}


@api.post("/run-summary")
async def run_summary(request: Request) -> dict[str, bool | str]:
    """Manually trigger sending the weekly summary.

    Generates and sends the weekly summary in a background thread.
    Rate limited to 10/minute.

    Args:
        request: The incoming HTTP request.

    Returns:
        dict with ok=True and confirmation message.

    Raises:
        HTTPException: 429 if rate limited, 503 if not ready.
    """
    _check_manual_trigger_rate_limit(request)
    scheduler = request.app.state.scheduler
    if scheduler is None:
        raise HTTPException(status_code=503, detail="Not ready")
    logger.info("[api] Manual summary triggered by %s", _get_client_ip(request))
    threading.Thread(
        target=scheduler.run_summary_now,
        daemon=True,
        name="manual-summary",
    ).start()
    return {"ok": True, "message": "Resumen iniciado"}


# ── Telegram webhook ──────────────────────────────────────────────────────────


@api.post("/telegram-webhook")
async def telegram_webhook(request: Request) -> dict[str, bool | str]:
    """Handle incoming Telegram webhook updates.

    Processes /start commands to register new chat IDs for notifications.
    Silently ignores other message types.

    Args:
        request: The incoming HTTP request with Telegram update payload.

    Returns:
        dict with ok=True, and optionally 'registered' with the chat_id.
    """
    scheduler = request.app.state.scheduler
    if scheduler is None:
        return {"ok": True}

    try:
        body = await request.json()
        message = body.get("message", {})
        chat = message.get("chat", {})
        chat_id = str(chat.get("id", ""))
        text = message.get("text", "")
        username = chat.get("username", "") or chat.get("first_name", "")

        if chat_id and text.startswith("/start"):
            scheduler._notifier.register_chat(chat_id, username)
            logger.info("[telegram] New chat registered via webhook: %s", chat_id)
            return {"ok": True, "registered": chat_id}
    except (ValueError, KeyError, TypeError) as e:
        logger.debug("[telegram] Webhook parse error: %s", e)

    return {"ok": True}


# ── Incluir router API ────────────────────────────────────────────────────────
app.include_router(api)


# ── Frontend routes ───────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
@app.get("/smart-home/casita", response_class=HTMLResponse)
@app.get("/smart-home/casita/", response_class=HTMLResponse)
async def serve_frontend() -> FileResponse:
    """Serve the Casita Sueños frontend HTML.

    Serves the single-page application from multiple routes to support
    both direct access and nginx proxy routing.

    Returns:
        FileResponse with the casita.html file.

    Raises:
        HTTPException: 404 if frontend file not found.
    """
    html_path = STATIC_DIR / "casita.html"
    if not html_path.exists():
        raise HTTPException(status_code=404, detail="Frontend not found")
    return FileResponse(html_path, media_type="text/html")


# ── Telegram polling (background thread) ──────────────────────────────────────


def _sanitize_telegram_error(exc: Exception) -> str:
    """Strip Telegram bot token from exception messages to prevent leaks in logs.

    Args:
        exc: The exception to sanitize.

    Returns:
        A sanitized error string with any bot token replaced by <REDACTED>.
    """
    import re

    msg = str(exc)
    # Telegram bot tokens look like: 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
    # Match /bot<token>/ in URLs and standalone tokens
    sanitized = re.sub(r"/bot[0-9]+:[A-Za-z0-9_-]+/", "/bot<REDACTED>/", msg)
    sanitized = re.sub(r"\b[0-9]+:[A-Za-z0-9_-]{20,}\b", "<REDACTED>", sanitized)
    return sanitized


def _telegram_polling(db) -> None:
    """Background thread that polls Telegram for /start commands.

    Continuously polls the Telegram API for updates, processing /start
    commands to register new chat IDs. Runs indefinitely as a daemon thread.

    Args:
        db: Database instance for registering chat IDs.

    Note:
        This thread handles all exceptions to ensure it never crashes.
        Connection errors are expected (network issues) and logged at debug level.
        Unexpected errors are logged at warning level for monitoring.
    """
    import httpx

    token: str = TELEGRAM_BOT_TOKEN
    offset: int = 0
    url: str = f"https://api.telegram.org/bot{token}/getUpdates"
    logger.info("[main] Polling Telegram iniciado")

    while True:
        try:
            resp = httpx.get(url, params={"offset": offset, "timeout": 30}, timeout=35)
            updates: list[dict] = resp.json().get("result", [])
            for upd in updates:
                offset = upd["update_id"] + 1
                msg = upd.get("message", {})
                text: str = msg.get("text", "")
                chat = msg.get("chat", {})
                chat_id: str = str(chat.get("id", ""))
                username: str = chat.get("username", "") or chat.get("first_name", "")

                if chat_id and text.startswith("/start") and db is not None:
                    db.register_telegram_chat(chat_id, username)
                    logger.info(
                        "[main] Nuevo chat registrado via /start: %s (%s)",
                        chat_id,
                        username,
                    )
                    # Mensaje de bienvenida — wrap in try/except to avoid token leak
                    try:
                        httpx.post(
                            f"https://api.telegram.org/bot{token}/sendMessage",
                            json={
                                "chat_id": chat_id,
                                "text": "Bienvenido/a a Casita Sueños! Recibirás alertas de nuevas casas en el radar.",
                            },
                            timeout=10,
                        )
                        logger.debug("[main] Welcome message sent to chat %s", chat_id)
                    except httpx.TimeoutException as send_err:
                        logger.warning(
                            "[main] Timeout enviando bienvenida a %s: %s",
                            chat_id,
                            _sanitize_telegram_error(send_err),
                        )
                    except httpx.HTTPError as send_err:
                        logger.warning(
                            "[main] HTTP error enviando bienvenida a %s: %s",
                            chat_id,
                            _sanitize_telegram_error(send_err),
                        )
        except httpx.TimeoutException:
            # Timeout is expected with long-polling, just retry
            pass
        except httpx.HTTPError as e:
            logger.debug(
                "[main] Telegram polling HTTP error: %s", _sanitize_telegram_error(e)
            )
        except httpx.ConnectError as e:
            # Network connectivity issues - expected during network changes
            logger.debug(
                "[main] Telegram polling connection error: %s",
                _sanitize_telegram_error(e),
            )
        except OSError as e:
            # Socket-level errors (DNS, connection refused, etc.)
            logger.debug("[main] Telegram polling OS error: %s", e)
        except (ValueError, KeyError) as e:
            logger.debug("[main] Telegram polling parse error: %s", e)
        except Exception as e:
            # Fallback for any unexpected exception - ensure thread never crashes
            # Log at warning level for monitoring, but continue running
            logger.warning(
                "[main] Telegram polling unexpected error: %s",
                _sanitize_telegram_error(e),
            )
        time.sleep(1)


# ── Bootstrap ─────────────────────────────────────────────────────────────────


def main() -> None:
    """Bootstrap and run the Casita Sueños service.

    Performs startup sequence:
    1. Validates required configuration
    2. Creates data directory if needed
    3. Sets process name for identification
    4. Ensures singleton instance via lockfile
    5. Starts uvicorn HTTP server

    The lifespan context manager handles scheduler and database
    initialization/cleanup.
    """
    logger.info("[main] ══════════════════════════════════════════════════════")
    logger.info("[main] Starting %s bootstrap sequence", PROCESS_NAME)

    _validate_config()
    Path(DATA_DIR).mkdir(parents=True, exist_ok=True)
    logger.info("[main] Data directory ensured: %s", DATA_DIR)

    # ── Nombre del proceso ───────────────────────────────────────────────────
    _set_process_name()
    logger.info("[main] Process name set to: %s", PROCESS_NAME)

    # ── Singleton: una sola instancia ────────────────────────────────────────
    from smart_home_common.singleton import ensure_singleton

    LOCK_PATH = os.environ.get("CASITA_LOCK_PATH", f"{DATA_DIR}/casita.lock")
    ensure_singleton(LOCK_PATH)
    logger.info("[main] Singleton lock acquired: %s", LOCK_PATH)

    logger.info("[main] ── Iniciando %s ──────────────────────────", PROCESS_NAME)

    # Arrancar servidor con uvicorn - lifespan maneja init/shutdown del scheduler
    # y arranca el thread de telegram polling con db disponible
    logger.info("[main] Servidor HTTP en puerto %d", STATUS_PORT)
    # SECURITY NOTE: Host 0.0.0.0 is intentional for container networking.
    # This service runs inside Docker on the Pi and is NOT exposed to the
    # internet directly. Access is restricted by:
    # 1. Docker network isolation (only nginx can reach casita-suenos:8001)
    # 2. nginx reverse proxy with Tailscale auth_request
    # 3. Tailscale VPN (only authenticated devices can reach the Pi)
    # See: docker-compose.prod.yml (networks), infrastructure/nginx/conf.d/smart-home.conf
    uvicorn.run(
        app,
        host="0.0.0.0",  # nosec B104 - internal container network, see comment above
        port=STATUS_PORT,
        log_level="warning",
        access_log=False,
    )


if __name__ == "__main__":
    main()
