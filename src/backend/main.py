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

from api import routes
from humidity_analysis import HumidityAnalysisScheduler
from error_tracker import ErrorTracker
from cleanup import CleanupScheduler
from controllers.ac_controller import ACController, ControlConfig
from melcloud_client import MelCloudClient
from mqtt_handler import MqttHandler
from subscription_manager import SubscriptionManager, SubscriptionConfig
from zigbee2mqtt_client import Zigbee2MQTTClient

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

# --- Global components ---

mqtt_handler: MqttHandler | None = None
melcloud_client: MelCloudClient | None = None
ac_controller: ACController | None = None
cleanup_scheduler: CleanupScheduler | None = None
subscription_manager: SubscriptionManager | None = None
error_tracker: ErrorTracker | None = None
humidity_scheduler: HumidityAnalysisScheduler | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle."""
    global mqtt_handler, melcloud_client, ac_controller, cleanup_scheduler, subscription_manager, error_tracker, humidity_scheduler

    # F0.30 - Create error tracker first (other components need it)
    error_tracker = ErrorTracker()

    logger.info("=== Smart Home Backend starting ===")
    logger.info("MQTT Broker: %s:%d", MQTT_BROKER, MQTT_PORT)
    logger.info("MELCloud URL: %s", MELCLOUD_URL)
    
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
        """Fetcher for outdoor temperature."""
        import httpx
        try:
            resp = httpx.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": LOCATION_LATITUDE,
                    "longitude": LOCATION_LONGITUDE,
                    "current": "temperature_2m,relative_humidity_2m",
                    "timezone": "Europe/Madrid",
                },
                timeout=10.0,
            )
            data = resp.json()
            current = data.get("current", {})
            error_tracker.clear("outdoor_fetch")
            return {
                "temperature": current.get("temperature_2m"),
                "humidity": current.get("relative_humidity_2m"),
            }
        except Exception as e:
            logger.error("Failed to fetch outdoor temperature: %s", e)
            error_tracker.register("outdoor_fetch", "warning", f"Outdoor temperature unavailable: {e}", "outdoor")
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
    humidity_scheduler.stop()
    subscription_manager.stop()
    ac_controller.stop()
    mqtt_handler.stop()
    melcloud_client.close()


# --- FastAPI App ---

app = FastAPI(
    title="Smart Home Control",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS - Configure allowed origins for security
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes
app.include_router(routes.router)

# Special route for index.html with no-cache (force update after bug fix)
@app.get("/")
async def serve_index():
    """Serves index.html with no-cache headers to force update."""
    import time
    frontend_path = Path(__file__).parent / "static" / "index.html"
    
    # Read content and add unique timestamp to force reload
    content = frontend_path.read_text(encoding="utf-8")
    
    # Insert unique timestamp in HTML to guarantee reload
    timestamp_marker = f"<!-- CACHE_BUST: {int(time.time())} -->"
    content = content.replace("</head>", f"{timestamp_marker}\n</head>")
    
    from fastapi.responses import HTMLResponse
    return HTMLResponse(
        content=content,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
            "X-Content-Type-Options": "nosniff"
        }
    )

# Serve other static files normally
frontend_path = Path(__file__).parent / "static"
if frontend_path.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_path)), name="frontend")


@app.get("/health")
def health():
    """Health check."""
    return {"status": "ok"}
