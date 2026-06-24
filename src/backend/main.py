"""Punto de entrada de la aplicación Smart Home Backend.

Orquesta todos los componentes: MQTT, MELCloud, controlador AC, API REST.
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
from cleanup import CleanupScheduler
from controllers.ac_controller import ACController, ControlConfig
from melcloud_client import MelCloudClient
from mqtt_handler import MqttHandler
from zigbee2mqtt_client import Zigbee2MQTTClient

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

# --- Configuración desde variables de entorno ---

# MQTT
MQTT_BROKER = os.environ.get("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_CONNECT_RETRIES = int(os.environ.get("MQTT_CONNECT_RETRIES", "30"))
MQTT_RETRY_DELAY = int(os.environ.get("MQTT_RETRY_DELAY", "2"))
MQTT_KEEPALIVE = int(os.environ.get("MQTT_KEEPALIVE", "60"))

# MELCloud (OBLIGATORIOS - sin defaults inseguros)
MELCLOUD_URL = os.environ.get("MELCLOUD_URL", "https://app.melcloud.com")
MELCLOUD_EMAIL = os.environ.get("MELCLOUD_EMAIL")
MELCLOUD_PASSWORD = os.environ.get("MELCLOUD_PASSWORD")
MELCLOUD_TIMEOUT = float(os.environ.get("MELCLOUD_TIMEOUT", "30.0"))
MELCLOUD_MAX_FAILURES = int(os.environ.get("MELCLOUD_MAX_FAILURES", "100"))
MELCLOUD_APP_VERSION = os.environ.get("MELCLOUD_APP_VERSION", "1.32.1.0")

# Validar credenciales obligatorias
if not MELCLOUD_EMAIL or not MELCLOUD_PASSWORD:
    logger.error("MELCLOUD_EMAIL y MELCLOUD_PASSWORD son obligatorios")
    raise RuntimeError("Credenciales MELCloud no configuradas")

# Device IDs (OBLIGATORIOS - sin defaults)
if "MELCLOUD_DEVICE_ID" not in os.environ:
    logger.error("MELCLOUD_DEVICE_ID no configurado")
    raise RuntimeError("MELCLOUD_DEVICE_ID es obligatorio. Obtenerlo de la app MELCloud.")
if "MELCLOUD_BUILDING_ID" not in os.environ:
    logger.error("MELCLOUD_BUILDING_ID no configurado")
    raise RuntimeError("MELCLOUD_BUILDING_ID es obligatorio. Obtenerlo de la app MELCloud.")

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

# Historial
MAX_HISTORY_PER_SENSOR = int(os.environ.get("MAX_HISTORY_PER_SENSOR", "200"))

# CORS (por seguridad, restringir origins)
CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "*").split(",")

# Outdoor API
OUTDOOR_CACHE_TTL = int(os.environ.get("OUTDOOR_CACHE_TTL", "600"))
LOCATION_LATITUDE = float(os.environ.get("LOCATION_LATITUDE", "40.396644"))
LOCATION_LONGITUDE = float(os.environ.get("LOCATION_LONGITUDE", "-3.622511"))

# Cleanup
CLEANUP_INTERVAL_SECONDS = int(os.environ.get("CLEANUP_INTERVAL_SECONDS", "86400"))
CLEANUP_GRACE_PERIOD = int(os.environ.get("CLEANUP_GRACE_PERIOD", "60"))

# Energía (potencias en kW por estado)
AC_POWER_COOLING_MAX = float(os.environ.get("AC_POWER_COOLING_MAX", "2.5"))
AC_POWER_COOLING_MID = float(os.environ.get("AC_POWER_COOLING_MID", "1.75"))
AC_POWER_MODULATING = float(os.environ.get("AC_POWER_MODULATING", "1.25"))
AC_POWER_FORCED_ON = float(os.environ.get("AC_POWER_FORCED_ON", "2.5"))

# --- Componentes globales ---

mqtt_handler: MqttHandler | None = None
melcloud_client: MelCloudClient | None = None
ac_controller: ACController | None = None
cleanup_scheduler: CleanupScheduler | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Ciclo de vida de la aplicación."""
    global mqtt_handler, melcloud_client, ac_controller, cleanup_scheduler

    logger.info("=== Smart Home Backend iniciando ===")
    logger.info("MQTT Broker: %s:%d", MQTT_BROKER, MQTT_PORT)
    logger.info("MELCloud URL: %s", MELCLOUD_URL)
    
    # 0. Descubrir sensores automáticamente desde Zigbee2MQTT
    logger.info("Descubriendo sensores desde Zigbee2MQTT vía MQTT...")
    z2m_client = Zigbee2MQTTClient(MQTT_BROKER, MQTT_PORT, timeout=Z2M_DISCOVERY_TIMEOUT)
    sensor_names = z2m_client.discover_temperature_sensors()
    
    if not sensor_names:
        logger.warning("No se descubrieron sensores. Verifica que Zigbee2MQTT esté funcionando.")
        logger.warning("El sistema continuará sin sensores.")
    else:
        logger.info("Sensores descubiertos: %s", sensor_names)
    
    logger.info("Objetivo: %.1f°C (histéresis: +%.1f/-%.1f)", TARGET_TEMPERATURE, HYSTERESIS_ON, HYSTERESIS_OFF)

    # 1. Iniciar handler MQTT
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

    # 2. Iniciar cliente MELCloud
    melcloud_client = MelCloudClient(
        MELCLOUD_URL, 
        MELCLOUD_EMAIL, 
        MELCLOUD_PASSWORD, 
        MELCLOUD_BUILDING_ID,
        timeout=MELCLOUD_TIMEOUT,
        app_version=MELCLOUD_APP_VERSION
    )
    if not melcloud_client.login():
        logger.error("No se pudo autenticar en MELCloud. El controlador no actuará.")

    # 3. Configurar e iniciar controlador
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
    ac_controller.start()

    # 4. Inyectar dependencias en las rutas
    routes.mqtt_handler = mqtt_handler
    routes.ac_controller = ac_controller
    routes.outdoor_cache_ttl = OUTDOOR_CACHE_TTL
    routes.location_lat = LOCATION_LATITUDE
    routes.location_lon = LOCATION_LONGITUDE

    # 5. Iniciar scheduler de limpieza diaria
    cleanup_scheduler = CleanupScheduler(
        interval=CLEANUP_INTERVAL_SECONDS,
        grace_period=CLEANUP_GRACE_PERIOD
    )
    cleanup_scheduler.start()

    logger.info("=== Smart Home Backend listo ===")

    yield

    # Shutdown
    logger.info("=== Apagando Smart Home Backend ===")
    cleanup_scheduler.stop()
    ac_controller.stop()
    mqtt_handler.stop()
    melcloud_client.close()


# --- App FastAPI ---

app = FastAPI(
    title="Smart Home Control",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS - Configurar origins permitidos por seguridad
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rutas API
app.include_router(routes.router)

# Ruta especial para index.html con no-cache (forzar actualización después de bug fix)
@app.get("/")
async def serve_index():
    """Sirve index.html con headers no-cache para forzar actualización."""
    import time
    frontend_path = Path(__file__).parent / "static" / "index.html"
    
    # Leer el contenido y añadir timestamp único para forzar recarga
    content = frontend_path.read_text(encoding="utf-8")
    
    # Insertar timestamp único en el HTML para garantizar recarga
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

# Servir otros archivos estáticos normalmente
frontend_path = Path(__file__).parent / "static"
if frontend_path.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_path)), name="frontend")


@app.get("/health")
def health():
    """Health check."""
    return {"status": "ok"}
