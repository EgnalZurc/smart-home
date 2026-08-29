"""Entry point of the Smart Home Backend application.
Orchestrates all components: MQTT, MELCloud, AC controller, REST API.
"""
import logging
import os
import threading
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
from humidity_analysis import HumidityAnalysisScheduler
from error_tracker import ErrorTracker
from cleanup import CleanupScheduler
from controllers.ac_controller import ACController, ControlConfig
from melcloud_client import MelCloudClient
from mqtt_handler import MqttHandler
from subscription_manager import SubscriptionManager, SubscriptionConfig
from zigbee2mqtt_client import Zigbee2MQTTClient
from ac_temp_scheduler import AcTempScheduler
# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)
# --- Configuration from environment variables ---
# MQTT
MQTT_BROKER = os.environ.get("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_CONNECT_RETRIES = int(os.environ.get("MQTT_CONNECT_RETRIES", "30"))
MQTT_RETRY_DELAY = int(os.environ.get("MQTT_RETRY_DELAY", "2"))
MQTT_KEEPALIVE = int(os.environ.get("MQTT_KEEPALIVE", "60"))
# MELCloud (REQUIRED - no unsafe defaults)
MELCLOUD_URL = os.environ.get("MELCLOUD_URL", "https://app.melcloud.com")
MELCLOUD_EMAIL = os.environ.get("MELCLOUD_EMAIL")
MELCLOUD_PASSWORD = os.environ.get("MELCLOUD_PASSWORD")
MELCLOUD_TIMEOUT = float(os.environ.get("MELCLOUD_TIMEOUT", "30.0"))
MELCLOUD_MAX_FAILURES = int(os.environ.get("MELCLOUD_MAX_FAILURES", "100"))
MELCLOUD_APP_VERSION = os.environ.get("MELCLOUD_APP_VERSION", "1.32.1.0")
# Validate required credentials
if not MELCLOUD_EMAIL or not MELCLOUD_PASSWORD:
    logger.error("MELCLOUD_EMAIL and MELCLOUD_PASSWORD are required")
    raise RuntimeError("MELCloud credentials not configured")
# Device IDs (REQUIRED - no defaults)
if "MELCLOUD_DEVICE_ID" not in os.environ:
    logger.error("MELCLOUD_DEVICE_ID not configured")
    raise RuntimeError("MELCLOUD_DEVICE_ID is required. Get it from MELCloud app.")
if "MELCLOUD_BUILDING_ID" not in os.environ:
    logger.error("MELCLOUD_BUILDING_ID not configured")
    raise RuntimeError("MELCLOUD_BUILDING_ID is required. Get it from MELCloud app.")
MELCLOUD_DEVICE_ID = int(os.environ["MELCLOUD_DEVICE_ID"])
MELCLOUD_BUILDING_ID = int(os.environ["MELCLOUD_BUILDING_ID"])
# Control AC
TARGET_TEMPERATURE = float(os.environ.get("TARGET_TEMPERATURE", "26.0"))
HYSTERESIS_ON = float(os.environ.get("HYSTERESIS_ON", "0.5"))
HYSTERESIS_OFF = float(os.environ.get("HYSTERESIS_OFF", "0.3"))
MIN_SETPOINT_TEMP = float(os.environ.get("MIN_SETPOINT_TEMP", "19.0"))
MAX_SETPOINT_TEMP = float(os.environ.get("MAX_SETPOINT_TEMP", "30.0"))
COOLDOWN_SECONDS = int(os.environ.get("COOLDOWN_SECONDS", "180"))
LOOP_INTERVAL = int(os.environ.get("LOOP_INTERVAL", "10"))
SENSOR_TIMEOUT = int(os.environ.get("SENSOR_TIMEOUT", "3600"))
FAN_SPEED_MAX = int(os.environ.get("FAN_SPEED_MAX", "3"))
# Zigbee2MQTT discovery
Z2M_DISCOVERY_TIMEOUT = float(os.environ.get("Z2M_DISCOVERY_TIMEOUT", "10.0"))
# History
MAX_HISTORY_PER_SENSOR = int(os.environ.get("MAX_HISTORY_PER_SENSOR", "200"))
# CORS (for security, restrict origins)
CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "*").split(",")
# Outdoor API
OUTDOOR_CACHE_TTL = int(os.environ.get("OUTDOOR_CACHE_TTL", "600"))
LOCATION_LATITUDE = float(os.environ.get("LOCATION_LATITUDE", "40.396644"))
LOCATION_LONGITUDE = float(os.environ.get("LOCATION_LONGITUDE", "-3.622511"))
# Subscription intervals
MELCLOUD_UPDATE_INTERVAL = int(os.environ.get("MELCLOUD_UPDATE_INTERVAL", "30"))
OUTDOOR_UPDATE_INTERVAL = int(os.environ.get("OUTDOOR_UPDATE_INTERVAL", "600"))
# Cleanup
CLEANUP_INTERVAL_SECONDS = int(os.environ.get("CLEANUP_INTERVAL_SECONDS", "86400"))
CLEANUP_GRACE_PERIOD = int(os.environ.get("CLEANUP_GRACE_PERIOD", "60"))
# Energy (power in kW per state)
AC_POWER_COOLING_MAX = float(os.environ.get("AC_POWER_COOLING_MAX", "2.5"))
AC_POWER_COOLING_MID = float(os.environ.get("AC_POWER_COOLING_MID", "1.75"))
AC_POWER_MODULATING = float(os.environ.get("AC_POWER_MODULATING", "1.25"))
AC_POWER_FORCED_ON = float(os.environ.get("AC_POWER_FORCED_ON", "2.5"))
# AUTH (REQUIRED)
AUTH_SECRET = os.environ.get("AUTH_SECRET", "")
AUTH_HTPASSWD = os.environ.get("AUTH_HTPASSWD_PATH", "/etc/nginx/.htpasswd")
AUTH_DB_PATH = os.environ.get("AUTH_DB_PATH", "/app/data/auth.db")
AUTH_SESSION_TTL = int(os.environ.get("AUTH_SESSION_TTL", "86400"))
AUTH_TRUSTED_TTL = int(os.environ.get("AUTH_TRUSTED_TTL", "31536000"))
AUTH_SMTP_USER = os.environ.get("AUTH_SMTP_USER", "")
AUTH_SMTP_PASS = os.environ.get("AUTH_SMTP_PASSWORD", "")
AUTH_BASE_URL = os.environ.get("AUTH_BASE_URL", "https://raspberrypi.local")
if not AUTH_SECRET:
    logger.error("AUTH_SECRET is required — generate with: python3 -c \"import secrets; print(secrets.token_hex(32))\"")
    raise RuntimeError("AUTH_SECRET not configured")
# --- Global components ---
mqtt_handler: MqttHandler | None = None
melcloud_client: MelCloudClient | None = None
ac_controller: ACController | None = None
cleanup_scheduler: CleanupScheduler | None = None
subscription_manager: SubscriptionManager | None = None
error_tracker: ErrorTracker | None = None
humidity_scheduler: HumidityAnalysisScheduler | None = None
ac_temp_scheduler: AcTempScheduler | None = None
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle."""
    global mqtt_handler, melcloud_client, ac_controller, cleanup_scheduler, subscription_manager, error_tracker, humidity_scheduler, ac_temp_scheduler
    # F0.30 - Create error tracker first (other components need it)
    error_tracker = ErrorTracker()
    logger.info("=== Smart Home Backend starting ===")
    logger.info("MQTT Broker: %s:%d", MQTT_BROKER, MQTT_PORT)
    logger.info("MELCloud URL: %s", MELCLOUD_URL)
    # AUTH: inject configuration into auth modules
    auth_core.AUTH_SECRET = AUTH_SECRET
    auth_core.AUTH_SESSION_TTL = AUTH_SESSION_TTL
    auth_core.AUTH_TRUSTED_TTL = AUTH_TRUSTED_TTL
    auth_users.HTPASSWD_PATH = AUTH_HTPASSWD
    auth_users.AUTH_DB_PATH = AUTH_DB_PATH
    auth_users.TRUST_SECRET = AUTH_SECRET
    auth_routes.SMTP_USER = AUTH_SMTP_USER
    auth_routes.SMTP_PASSWORD = AUTH_SMTP_PASS
    auth_routes.BASE_URL = AUTH_BASE_URL
    logger.info("AUTH: JWT session auth initialized (htpasswd: %s)", AUTH_HTPASSWD)
    # 0. Auto-discover sensors from Zigbee2MQTT
    logger.info("Discovering sensors from Zigbee2MQTT via MQTT...")
    z2m_client = Zigbee2MQTTClient(MQTT_BROKER, MQTT_PORT, timeout=Z2M_DISCOVERY_TIMEOUT)
    sensor_names = z2m_client.discover_temperature_sensors()
    if not sensor_names:
        logger.warning("No sensors discovered. Check that Zigbee2MQTT is running.")
        logger.warning("System will continue without sensors.")
    else:
        logger.info("Sensors discovered: %s", sensor_names)
    logger.info("Target: %.1f°C (hysteresis: +%.1f/-%.1f)", TARGET_TEMPERATURE, HYSTERESIS_ON, HYSTERESIS_OFF)
    # 1. Start MQTT handler
    mqtt_handler = MqttHandler(
        MQTT_BROKER,
        MQTT_PORT,
        sensor_names,
        connect_retries=MQTT_CONNECT_RETRIES,
        retry_delay=MQTT_RETRY_DELAY,
        keepalive=MQTT_KEEPALIVE,
        max_history=MAX_HISTORY_PER_SENSOR
    )
    mqtt_handler.start()
    mqtt_handler.set_error_tracker(error_tracker)
    # 2. Start MELCloud client
    melcloud_client = MelCloudClient(
        MELCLOUD_URL,
        MELCLOUD_EMAIL,
        MELCLOUD_PASSWORD,
        MELCLOUD_BUILDING_ID,
        timeout=MELCLOUD_TIMEOUT,
        app_version=MELCLOUD_APP_VERSION
    )
    if not melcloud_client.login():
        logger.error("Failed to authenticate with MELCloud. Controller will not act.")
        error_tracker.register("melcloud_auth", "error", "MELCloud authentication failed", "melcloud")
    else:
        error_tracker.clear("melcloud_auth")
    # 3. Configure and start controller
    config = ControlConfig(
        target_temperature=TARGET_TEMPERATURE,
        hysteresis_on=HYSTERESIS_ON,
        hysteresis_off=HYSTERESIS_OFF,
        min_setpoint=MIN_SETPOINT_TEMP,
        max_setpoint=MAX_SETPOINT_TEMP,
        cooldown_seconds=COOLDOWN_SECONDS,
        loop_interval=LOOP_INTERVAL,
        sensor_timeout=SENSOR_TIMEOUT,
        fan_speed_max=FAN_SPEED_MAX,
        device_id=MELCLOUD_DEVICE_ID,
        building_id=MELCLOUD_BUILDING_ID,
        melcloud_max_failures=MELCLOUD_MAX_FAILURES,
        ac_power_cooling_max=AC_POWER_COOLING_MAX,
        ac_power_cooling_mid=AC_POWER_COOLING_MID,
        ac_power_modulating=AC_POWER_MODULATING,
        ac_power_forced_on=AC_POWER_FORCED_ON,
    )
    ac_controller = ACController(mqtt_handler, melcloud_client, config)
    # Restore previous state before starting (minimize AC restarts)
    ac_controller.restore_state()
    ac_controller.set_error_tracker(error_tracker)
    ac_controller.start()
    # 4. Initialize Subscription Manager
    logger.info("=== Initializing Subscription Manager ===")
    sub_config = SubscriptionConfig(
        melcloud_interval=MELCLOUD_UPDATE_INTERVAL,
        outdoor_interval=OUTDOOR_UPDATE_INTERVAL,
    )
    subscription_manager = SubscriptionManager(sub_config)
    # Subscribe to MELCloud (AC state)
    def fetch_melcloud_state():
        """Fetcher for MELCloud AC state."""
        state = melcloud_client.get_device_state(MELCLOUD_DEVICE_ID, MELCLOUD_BUILDING_ID)
        # Update AC controller cache
        if state is not None:
            ac_controller.update_ac_real_cache(state)
        return state
    subscription_manager.subscribe(
        "melcloud",
        fetch_melcloud_state,
        interval=MELCLOUD_UPDATE_INTERVAL
    )
    # Subscribe to outdoor temperature (Open-Meteo)
    def fetch_outdoor_temp():
        """Fetcher for outdoor temperature and air quality (Open-Meteo)."""
        import httpx
        try:
            # Fetch weather and air quality in parallel
            weather_resp = httpx.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": LOCATION_LATITUDE,
                    "longitude": LOCATION_LONGITUDE,
                    "current": "temperature_2m,relative_humidity_2m",
                    "timezone": "Europe/Madrid",
                },
                timeout=10.0,
            )
            aqi_resp = httpx.get(
                "https://air-quality-api.open-meteo.com/v1/air-quality",
                params={
                    "latitude": LOCATION_LATITUDE,
                    "longitude": LOCATION_LONGITUDE,
                    "current": "european_aqi",
                    "timezone": "Europe/Madrid",
                },
                timeout=10.0,
            )
            weather = weather_resp.json().get("current", {})
            aqi_current = aqi_resp.json().get("current", {})
            error_tracker.clear("outdoor_fetch")
            return {
                "temperature": weather.get("temperature_2m"),
                "humidity": weather.get("relative_humidity_2m"),
                "aqi": aqi_current.get("european_aqi"),
            }
        except Exception as e:
            logger.error("Failed to fetch outdoor data: %s", e)
            error_tracker.register("outdoor_fetch", "warning", f"Outdoor data unavailable: {e}", "outdoor")
            return None
    subscription_manager.subscribe(
        "outdoor",
        fetch_outdoor_temp,
        interval=OUTDOOR_UPDATE_INTERVAL
    )
    # Start subscription manager
    subscription_manager.start()
    logger.info("=== Subscription Manager active ===")
    # 5. Inject dependencies into routes
    routes.mqtt_handler = mqtt_handler
    routes.ac_controller = ac_controller
    routes.subscription_manager = subscription_manager
    routes.error_tracker = error_tracker  # F0.30
    routes.outdoor_cache_ttl = OUTDOOR_CACHE_TTL
    routes.location_lat = LOCATION_LATITUDE
    routes.location_lon = LOCATION_LONGITUDE
    # 6. Start daily cleanup scheduler
    cleanup_scheduler = CleanupScheduler(
        interval=CLEANUP_INTERVAL_SECONDS,
        grace_period=CLEANUP_GRACE_PERIOD
    )
    cleanup_scheduler.start()
    # AC-CHART: Hourly AC room temperature recorder
    ac_temp_scheduler = AcTempScheduler(mqtt_handler, ac_controller)
    ac_temp_scheduler.start()
    # HUM-0: Start daily humidity analysis (3-week study)
    humidity_scheduler = HumidityAnalysisScheduler(
        mqtt_handler=mqtt_handler,
        sample_interval_seconds=int(os.environ.get("HUMIDITY_ANALYSIS_INTERVAL", str(1 * 3600))),
        grace_period_seconds=int(os.environ.get("HUMIDITY_GRACE_PERIOD", "300")),
    )
    humidity_scheduler.start()
    routes.humidity_scheduler = humidity_scheduler
    logger.info("=== Smart Home Backend ready ===")
    yield
    # Shutdown
    logger.info("=== Shutting down Smart Home Backend ===")
    cleanup_scheduler.stop()
    ac_temp_scheduler.stop()
    humidity_scheduler.stop()
    subscription_manager.stop()
    ac_controller.stop()
    mqtt_handler.stop()
    melcloud_client.close()


# ── AUTH: paths that bypass authentication ────────────────────────────────────
_AUTH_PUBLIC_PREFIXES = (
    "/auth/",
    "/health",
    "/static/manifest.json",
    "/static/favicon.ico",
    "/favicon.ico",
)

class AuthMiddleware(BaseHTTPMiddleware):
    """Redirect unauthenticated requests to /auth/login.

    All routes are protected by default. Public paths (login page, health
    check, PWA manifest, favicon) are exempted. Static assets are allowed
    through so the login page itself can load its CSS.
    """

    async def dispatch(self, request, call_next):
        path = request.url.path

        # Always allow public paths
        if any(path.startswith(p) for p in _AUTH_PUBLIC_PREFIXES):
            return await call_next(request)

        # Static files: allow through (login page needs tailwind.css etc.)
        if path.startswith("/static/"):
            return await call_next(request)

        # Check for valid session cookie
        user = auth_core.get_current_user(request)
        if user:
            return await call_next(request)

        # Not authenticated — redirect to login preserving destination
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

# AC-URL: AC Control app at /smart-home/ac
@app.get("/smart-home/ac")
async def serve_ac():
    """Serves the AC Control app."""
    return _serve_html("index.html")

# VAC-URL: Vacaciones (Christmas Planning) app at /smart-home/vacaciones
@app.get("/smart-home/vacaciones")
async def serve_vacaciones():
    """Serves the Vacaciones (Christmas Planning) app."""
    return _serve_html("vacaciones.html")

# CASITA-URL: Casita Sueños detail page
@app.get("/smart-home/casita")
async def serve_casita():
    """Serves the Casita Sueños detail page."""
    return _serve_html("casita.html")

# Serve other static files normally
frontend_path = Path(__file__).parent / "static"
if frontend_path.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_path)), name="frontend")

@app.get("/health")
def health():
    """Health check."""
    return {"status": "ok"}
