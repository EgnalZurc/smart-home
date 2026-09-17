"""Entry point of the Smart Home Backend application.
Orchestrates all components: MQTT, MELCloud, AC controller, REST API.
"""
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import RedirectResponse as StarletteRedirect
from api import routes
from api import auth_routes
import auth as auth_core
import auth_users
import auth_devices
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
    logger.info("=== Smart Home Backend ready (auth + dashboard) ===")
    yield
    logger.info("=== Smart Home Backend shutdown ===")


# ── AUTH: paths that bypass authentication ────────────────────────────────────
_AUTH_PUBLIC_PREFIXES = (
    "/auth/",
    "/health",
    "/api/health/",   # Health check endpoints — must be public so dashboard status works
    "/api/proxy/",
    "/static/manifest.json",
    "/static/favicon.ico",
    "/favicon.ico",
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
                login_url = "/auth/login?alert=theft"
                redirect = StarletteRedirect(login_url, status_code=302)
                redirect.delete_cookie(auth_core.COOKIE_NAME, path="/")
                redirect.delete_cookie(auth_devices.DEVICE_COOKIE_NAME, path="/")
                return redirect

            if result.ok:
                # Valid device token — issue fresh JWT and rotate device cookie
                new_jwt = auth_core.create_token(result.username)
                response = await call_next(request)
                auth_core.set_session_cookie(response, new_jwt)
                # Set rotated device cookie
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
        login_url = f"/auth/login?next={request.url.path}"
        return StarletteRedirect(login_url, status_code=302)


# --- FastAPI App ---
app = FastAPI(
    title="Smart Home Control",
    version="0.1.0",
    lifespan=lifespan,
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

# Auth routes (public — login/logout/me/trust)
app.include_router(auth_routes.router)

# API routes
app.include_router(routes.router)

# DASH-2: Root redirects to /smart-home
@app.get("/")
async def serve_root():
    """Redirect / to /smart-home dashboard."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/smart-home", status_code=301)

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
        }
    )

# DASH-1: Platform dashboard
@app.get("/smart-home")
async def serve_dashboard():
    """Serves the Smart Home platform dashboard."""
    return _serve_html("dashboard.html")

# AUTH-LOGIN: Serve login page via static path too
@app.get("/auth/login/page")
async def serve_login():
    """Serves the login page (also served directly by auth_routes)."""
    return _serve_html("login.html")



# CASITA-URL: Casita Sueños detail page
@app.get("/smart-home/casita")
async def serve_casita():
    """Serves the Casita Sueños detail page."""
    return _serve_html("casita.html")

# Serve other static files normally
frontend_path = Path(__file__).parent / "static"
if frontend_path.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_path)), name="frontend")


# ── Proxies para casita.html (CORS) ──────────────────────────────────────────

@app.get("/api/proxy/flood")
async def proxy_flood(lat: float, lon: float):
    """
    Riesgo de inundación multicapa para una coordenada.

    Fuente 1: SNCZI MITECO (oficial España) — peligrosidad fluvial T=10/100/500 años.
      Estrategia bbox progresiva: empieza en ~50m y amplía hasta ~2km si no hay datos.
      Solo acepta valores físicamente coherentes (no fill values, no uniformes entre capas).

    Fuente 2: GloFAS via Open-Meteo Flood API — caudal diario del río más cercano (1984-hoy).
      Siempre disponible, sin key. Da caudal máximo histórico y percentiles p95/p99.
      Se usa para clasificar el riesgo cuando SNCZI no tiene cobertura.

    Respuesta:
      {
        snczi: { t10, t100, t500 } | null,
        glofas: { mean_m3s, max_hist_m3s, p95_m3s, p99_m3s } | null,
        risk_level: "muy_alto"|"alto"|"moderado"|"bajo"|"sin_datos",
        risk_source: "snczi"|"glofas"|"sin_datos",
        calado_m: float | null,
      }
    """
    import re, asyncio, statistics
    import httpx
    from datetime import date

    # ── FUENTE 1: SNCZI con bbox progresivo ─────────────────────────────────
    WMS_BASE  = "https://servicios.idee.es/wms-inspire/riesgos-naturales/inundaciones"
    LAYERS    = ["NZ.Flood.FluvialT10", "NZ.Flood.FluvialT100", "NZ.Flood.FluvialT500"]
    # Deltas en grados: ~50m, 100m, 200m, 500m, 1km, 2km
    DELTAS    = [0.0005, 0.001, 0.002, 0.005, 0.01, 0.02]
    FILL_VALS = {-9999.0, -3.0}  # nodata conocidos

    def _is_fill(v: float) -> bool:
        """Detecta fill values del raster SNCZI."""
        if v is None:
            return True
        if v in FILL_VALS or v < -2:
            return True
        if abs(v - 3.4) < 0.1:   # fill value ~3.4 dentro de demarcación
            return True
        return False

    async def _wms_query(layer: str, delta: float) -> float | None:
        bbox = f"{lon-delta:.5f},{lat-delta:.5f},{lon+delta:.5f},{lat+delta:.5f}"
        url  = (
            f"{WMS_BASE}?SERVICE=WMS&VERSION=1.1.1&REQUEST=GetFeatureInfo"
            f"&BBOX={bbox}&WIDTH=10&HEIGHT=10"
            f"&LAYERS={layer}&QUERY_LAYERS={layer}"
            f"&INFO_FORMAT=text/plain&X=5&Y=5&SRS=EPSG:4326"
        )
        try:
            async with httpx.AsyncClient(timeout=8) as c:
                r = await c.get(url)
            m = re.search(r"GRAY_INDEX\s*=\s*([-\d.]+)", r.text)
            return float(m.group(1)) if m else None
        except Exception:
            return None

    async def _snczi_with_progressive_bbox() -> dict | None:
        """Intenta obtener datos SNCZI ampliando el bbox progresivamente."""
        for delta in DELTAS:
            # Consultar las tres capas en paralelo
            results = await asyncio.gather(*[_wms_query(l, delta) for l in LAYERS])
            t10_raw, t100_raw, t500_raw = results

            # Filtrar fill values
            t10  = None if _is_fill(t10_raw)  else round(t10_raw, 2)
            t100 = None if _is_fill(t100_raw) else round(t100_raw, 2)
            t500 = None if _is_fill(t500_raw) else round(t500_raw, 2)

            # Si los tres son idénticos → artefacto uniforme
            if (t10 is not None and t100 is not None and t500 is not None
                    and t10 == t100 == t500):
                t10 = t100 = t500 = None

            # Si tenemos al menos un valor real → retornar
            if any(v is not None for v in (t10, t100, t500)):
                return {"t10": t10, "t100": t100, "t500": t500,
                        "bbox_delta_deg": delta,
                        "bbox_radius_m": int(delta * 111000)}

        return None  # Sin datos en ningún bbox

    # ── FUENTE 2: GloFAS / Open-Meteo Flood API ──────────────────────────────
    async def _glofas() -> dict | None:
        """Caudal histórico del río más cercano (GloFAS v4, 1984-hoy)."""
        end_date   = date.today().isoformat()
        start_date = f"{date.today().year - 30}-01-01"
        url = (
            f"https://flood-api.open-meteo.com/v1/flood"
            f"?latitude={lat}&longitude={lon}"
            f"&daily=river_discharge"
            f"&start_date={start_date}&end_date={end_date}"
            f"&cell_selection=nearest"
        )
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get(url)
            d = r.json()
            if not d.get("daily"):
                return None
            vals = [v for v in d["daily"]["river_discharge"] if v is not None]
            if len(vals) < 30:
                return None
            vals_sorted = sorted(vals)
            n = len(vals_sorted)
            return {
                "mean_m3s":     round(statistics.mean(vals), 1),
                "max_hist_m3s": round(max(vals), 1),
                "p95_m3s":      round(vals_sorted[int(n * 0.95)], 1),
                "p99_m3s":      round(vals_sorted[int(n * 0.99)], 1),
                "lat_grid":     d.get("latitude"),
                "lon_grid":     d.get("longitude"),
                "years":        30,
            }
        except Exception:
            return None

    # ── Lanzar ambas fuentes en paralelo ────────────────────────────────────
    snczi_data, glofas_data = await asyncio.gather(
        _snczi_with_progressive_bbox(),
        _glofas(),
    )

    # ── Algoritmo de clasificación combinado ─────────────────────────────────
    risk_level  = "sin_datos"
    risk_source = "sin_datos"
    calado_m    = None

    if snczi_data:
        t10, t100, t500 = snczi_data["t10"], snczi_data["t100"], snczi_data["t500"]
        if t10 is not None and t10 >= 0:
            risk_level = "muy_alto"; calado_m = t10
        elif t100 is not None and t100 >= 0:
            risk_level = "alto";     calado_m = t100
        elif t500 is not None and t500 >= 0:
            risk_level = "moderado"; calado_m = t500
        else:
            # SNCZI tiene datos pero todos son null (zona sin riesgo mapeado)
            risk_level = "bajo"
        risk_source = "snczi"

    elif glofas_data:
        # Clasificar por caudal máximo histórico y p99
        # Umbrales empíricos calibrados con los casos de test:
        #   Vicálvaro: max=3.7   → bajo
        #   Jaca:      max=5.8   → bajo
        #   Burgos:    max=324   → moderado
        #   Tudela:    max=2147  → muy_alto
        p99 = glofas_data["p99_m3s"]
        mx  = glofas_data["max_hist_m3s"]
        # Umbrales calibrados: Vicálvaro max=3.7→bajo, Manzanares max=126→moderado,
        # Burgos max=324→moderado, Tudela Ebro max=2147→muy_alto
        if mx > 1500 or p99 > 500:
            risk_level = "muy_alto"   # Ríos mayores en avenidas (Ebro, Tajo)
        elif mx > 500 or p99 > 150:
            risk_level = "alto"       # Ríos grandes con historial
        elif mx > 50 or p99 > 15:
            risk_level = "moderado"   # Ríos medianos
        else:
            risk_level = "bajo"       # Arroyos y ríos pequeños
        risk_source = "glofas"

    return {
        "snczi":       snczi_data,
        "glofas":      glofas_data,
        "risk_level":  risk_level,
        "risk_source": risk_source,
        "calado_m":    calado_m,
    }


@app.get("/api/proxy/firms")
async def proxy_firms(lat: float, lon: float):
    """
    Proxy para NASA FIRMS — focos de calor VIIRS SNPP últimos 3 años.
    Límite API: DAY_RANGE máx 5 días por petición / 5000 transacciones por 10 min.
    Estrategia: consultar meses de riesgo alto (junio-octubre) en bloques de 5 días.
    Total aprox: 3 años × 5 meses × 6 bloques = ~90 peticiones — muy por debajo del límite.
    """
    import os, asyncio
    import httpx
    from datetime import date, timedelta

    key = os.environ.get("FIRMS_MAP_KEY", "")
    if not key:
        return {"status": "no_key", "focos": None}

    delta = 0.27   # ~30 km en España — captura el entorno forestal de la ubicación
    bbox  = f"{lon-delta:.4f},{lat-delta:.4f},{lon+delta:.4f},{lat+delta:.4f}"
    base  = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
    source = "VIIRS_SNPP_SP"  # Standard Processing = histórico completo

    # Construir lista de fechas de inicio para ventanas de 5 días
    # Solo meses jun-oct (riesgo alto de incendio) de los últimos 3 años completos
    today = date.today()
    windows: list[str] = []

    for years_back in range(1, 4):  # 1, 2, 3 años atrás
        year = today.year - years_back
        for month in (6, 7, 8, 9, 10):  # jun, jul, ago, sep, oct
            # Dividir el mes en bloques de 5 días: días 1, 6, 11, 16, 21, 26
            for day_start in range(1, 29, 5):
                try:
                    d = date(year, month, day_start)
                    # No pedir fechas futuras ni anteriores al 2012 (inicio VIIRS)
                    if d < date(2012, 1, 19) or d >= today:
                        continue
                    windows.append(d.strftime("%Y-%m-%d"))
                except ValueError:
                    pass

    if not windows:
        return {"status": "error", "focos": None, "error": "Sin ventanas disponibles"}

    # Lanzar todas las peticiones en paralelo (asyncio.gather)
    # La key tiene 5000 transacciones / 10 min → ~90 peticiones simultáneas: sin problema
    async def _fetch_window(start_date: str) -> int:
        url = f"{base}/{key}/{source}/{bbox}/5/{start_date}"
        try:
            async with httpx.AsyncClient(timeout=12) as client:
                r = await client.get(url)
            if r.status_code != 200:
                return 0
            raw_lines = r.text.strip().split("\n")
            if not raw_lines or len(raw_lines) < 2:
                return 0
            # Parsear cabecera para encontrar columna confidence
            header = raw_lines[0].split(",")
            try:
                ci = header.index("confidence")
            except ValueError:
                ci = None
            count = 0
            for l in raw_lines[1:]:
                if not l.strip():
                    continue
                if ci is not None:
                    parts = l.split(",")
                    if len(parts) > ci:
                        # Excluir 'l' (low) = quemas agrícolas/industriales
                        # Mantener 'h' (high) y 'n' (nominal) = incendios reales
                        if parts[ci].strip().lower() == "l":
                            continue
                count += 1
            return count
        except Exception:
            return 0

    results = await asyncio.gather(*[_fetch_window(w) for w in windows])
    total_focos = sum(results)

    return {
        "status": "ok",
        "focos": total_focos,
        "radio_km": 30,
        "periodo": "jun-oct ultimos 3 anos (confidence h+n)",
        "peticiones": len(windows),
    }

@app.get("/health")
def health():
    """Health check."""
    return {"status": "ok"}
