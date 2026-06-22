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

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

# --- Configuración desde variables de entorno ---

MQTT_BROKER = os.environ.get("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MELCLOUD_URL = os.environ.get("MELCLOUD_URL", "https://app.melcloud.com")
MELCLOUD_EMAIL = os.environ.get("MELCLOUD_EMAIL", "")
MELCLOUD_PASSWORD = os.environ.get("MELCLOUD_PASSWORD", "")
MELCLOUD_DEVICE_ID = int(os.environ.get("MELCLOUD_DEVICE_ID", "12345"))
MELCLOUD_BUILDING_ID = int(os.environ.get("MELCLOUD_BUILDING_ID", "67890"))
TARGET_TEMPERATURE = float(os.environ.get("TARGET_TEMPERATURE", "23.0"))
HYSTERESIS_ON = float(os.environ.get("HYSTERESIS_ON", "0.5"))
HYSTERESIS_OFF = float(os.environ.get("HYSTERESIS_OFF", "0.3"))
LOOP_INTERVAL = int(os.environ.get("LOOP_INTERVAL", "10"))
SENSOR_TIMEOUT = int(os.environ.get("SENSOR_TIMEOUT", "3600"))
SENSOR_NAMES = os.environ.get(
    "SENSOR_NAMES", "sensor_hab1,sensor_hab2,sensor_hab3,sensor_salon,sensor_despacho"
).split(",")
ESIOS_API_KEY = os.environ.get("ESIOS_API_KEY", "")  # API key para precios PVPC

# --- Componentes globales ---

mqtt_handler: MqttHandler | None = None
melcloud_client: MelCloudClient | None = None
ac_controller: ACController | None = None
cleanup_scheduler: CleanupScheduler | None = None
energy_tracker = None  # EnergyTracker
scheduler = None  # APScheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Ciclo de vida de la aplicación."""
    global mqtt_handler, melcloud_client, ac_controller, cleanup_scheduler, energy_tracker, scheduler

    logger.info("=== Smart Home Backend iniciando ===")
    logger.info("MQTT Broker: %s:%d", MQTT_BROKER, MQTT_PORT)
    logger.info("MELCloud URL: %s", MELCLOUD_URL)
    logger.info("Sensores: %s", SENSOR_NAMES)
    logger.info("Objetivo: %.1f°C (histéresis: +%.1f/-%.1f)", TARGET_TEMPERATURE, HYSTERESIS_ON, HYSTERESIS_OFF)

    # 1. Iniciar handler MQTT
    mqtt_handler = MqttHandler(MQTT_BROKER, MQTT_PORT, SENSOR_NAMES)
    mqtt_handler.start()

    # 2. Iniciar cliente MELCloud
    melcloud_client = MelCloudClient(MELCLOUD_URL, MELCLOUD_EMAIL, MELCLOUD_PASSWORD, MELCLOUD_BUILDING_ID)
    if not melcloud_client.login():
        logger.error("No se pudo autenticar en MELCloud. El controlador no actuará.")

    # 3. Configurar e iniciar controlador
    config = ControlConfig(
        target_temperature=TARGET_TEMPERATURE,
        hysteresis_on=HYSTERESIS_ON,
        hysteresis_off=HYSTERESIS_OFF,
        min_setpoint=19.0,
        max_setpoint=30.0,
        cooldown_seconds=180,
        loop_interval=LOOP_INTERVAL,
        sensor_timeout=SENSOR_TIMEOUT,
        device_id=MELCLOUD_DEVICE_ID,
        building_id=MELCLOUD_BUILDING_ID,
    )

    ac_controller = ACController(mqtt_handler, melcloud_client, config)
    ac_controller.start()

    # 4. Inicializar tracking de energía
    from energy.esios_client import ESIOSClient
    from energy.tracker import EnergyTracker
    
    data_dir = Path("/app/data")
    esios_client = ESIOSClient(ESIOS_API_KEY, data_dir / "energy_prices_cache.json")
    energy_tracker = EnergyTracker(ac_controller, esios_client, data_dir)
    logger.info("Energy tracking inicializado")
    
    # 5. Inicializar scheduler para registros horarios/diarios
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    
    scheduler = AsyncIOScheduler()
    
    # Job horario: cada hora en punto (:00)
    scheduler.add_job(
        energy_tracker.record_hourly,
        trigger='cron',
        minute=0,
        id='record_hourly'
    )
    
    # Job diario: cada día a las 00:00
    scheduler.add_job(
        energy_tracker.record_daily,
        trigger='cron',
        hour=0,
        minute=0,
        id='record_daily'
    )
    
    scheduler.start()
    logger.info("Scheduler de energía iniciado (registro cada :00 y diario a las 00:00)")

    # 6. Inyectar dependencias en las rutas
    routes.mqtt_handler = mqtt_handler
    routes.ac_controller = ac_controller
    routes.energy_tracker = energy_tracker

    # 7. Iniciar scheduler de limpieza diaria
    cleanup_scheduler = CleanupScheduler()
    cleanup_scheduler.start()

    logger.info("=== Smart Home Backend listo ===")

    yield

    # Shutdown
    logger.info("=== Apagando Smart Home Backend ===")
    if scheduler:
        scheduler.shutdown()
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

# CORS para desarrollo
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
