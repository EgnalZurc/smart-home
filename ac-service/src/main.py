"""AC Service — standalone microservice for air conditioning control.

Serves:
  GET  /smart-home/ac              → index.html (SPA)
  GET  /api/status                 → AC + sensor status
  GET  /api/sensors                → per-sensor readings
  GET  /api/sensors/history        → sensor reading history
  GET  /api/history                → controller action history
  GET  /api/config                 → controller config
  POST /api/config                 → update config
  POST /api/control_mode           → set auto/manual/off
  POST /api/manual_params          → set manual parameters
  POST /api/manual_param           → update single manual parameter
  GET  /api/ac_real                → real AC state from MELCloud
  GET  /api/outdoor                → outdoor temperature (cached)
  GET  /api/errors                 → active errors
  GET  /api/humidity/study         → humidity analysis
  POST /api/humidity/study/run     → trigger manual analysis
  GET  /api/energy/current         → energy consumption 24h
  GET  /api/energy/hourly          → hourly energy chart data
  GET  /api/energy/monthly         → monthly energy chart data
  GET  /api/subscriptions/stats    → subscription manager stats
  GET  /api/health/zigbee          → zigbee health check
  GET  /health                     → service health check

Auth: nginx handles auth_request before requests reach this service.
      This service trusts all incoming requests as already authenticated.

Port: 8002
Depends on: mosquitto:1883 (MQTT broker, core infrastructure)
"""
import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ac_temp_scheduler import AcTempScheduler
from controllers.ac_controller import ACController, ControlConfig
from error_tracker import ErrorTracker
from humidity_analysis import HumidityAnalysisScheduler
from melcloud_client import MelCloudClient
from mqtt_handler import MqttHandler
from state_persistence import load_state
from subscription_manager import SubscriptionManager, SubscriptionConfig
from zigbee2mqtt_client import Zigbee2MQTTClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── Configuration from environment ───────────────────────────────────────────

MQTT_BROKER             = os.environ.get("MQTT_BROKER", "mosquitto")
MQTT_PORT               = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_CONNECT_RETRIES    = int(os.environ.get("MQTT_CONNECT_RETRIES", "30"))
MQTT_RETRY_DELAY        = int(os.environ.get("MQTT_RETRY_DELAY", "2"))
MQTT_KEEPALIVE          = int(os.environ.get("MQTT_KEEPALIVE", "60"))

MELCLOUD_URL            = os.environ.get("MELCLOUD_URL", "https://app.melcloud.com")
MELCLOUD_EMAIL          = os.environ.get("MELCLOUD_EMAIL")
MELCLOUD_PASSWORD       = os.environ.get("MELCLOUD_PASSWORD")
MELCLOUD_TIMEOUT        = float(os.environ.get("MELCLOUD_TIMEOUT", "30.0"))
MELCLOUD_MAX_FAILURES   = int(os.environ.get("MELCLOUD_MAX_FAILURES", "100"))
MELCLOUD_APP_VERSION    = os.environ.get("MELCLOUD_APP_VERSION", "1.32.1.0")

if not MELCLOUD_EMAIL or not MELCLOUD_PASSWORD:
    raise RuntimeError("MELCLOUD_EMAIL and MELCLOUD_PASSWORD are required")
if "MELCLOUD_DEVICE_ID" not in os.environ:
    raise RuntimeError("MELCLOUD_DEVICE_ID is required")
if "MELCLOUD_BUILDING_ID" not in os.environ:
    raise RuntimeError("MELCLOUD_BUILDING_ID is required")

MELCLOUD_DEVICE_ID      = int(os.environ["MELCLOUD_DEVICE_ID"])
MELCLOUD_BUILDING_ID    = int(os.environ["MELCLOUD_BUILDING_ID"])

TARGET_TEMPERATURE      = float(os.environ.get("TARGET_TEMPERATURE", "26.0"))
HYSTERESIS_ON           = float(os.environ.get("HYSTERESIS_ON", "0.5"))
HYSTERESIS_OFF          = float(os.environ.get("HYSTERESIS_OFF", "0.3"))
MIN_SETPOINT_TEMP       = float(os.environ.get("MIN_SETPOINT_TEMP", "19.0"))
MAX_SETPOINT_TEMP       = float(os.environ.get("MAX_SETPOINT_TEMP", "30.0"))
COOLDOWN_SECONDS        = int(os.environ.get("COOLDOWN_SECONDS", "180"))
LOOP_INTERVAL           = int(os.environ.get("LOOP_INTERVAL", "10"))
SENSOR_TIMEOUT          = int(os.environ.get("SENSOR_TIMEOUT", "3600"))
FAN_SPEED_MAX           = int(os.environ.get("FAN_SPEED_MAX", "3"))

Z2M_DISCOVERY_TIMEOUT   = float(os.environ.get("Z2M_DISCOVERY_TIMEOUT", "10.0"))
MAX_HISTORY_PER_SENSOR  = int(os.environ.get("MAX_HISTORY_PER_SENSOR", "200"))
CORS_ORIGINS            = os.environ.get("CORS_ORIGINS", "*").split(",")
LOCATION_LATITUDE       = float(os.environ.get("LOCATION_LATITUDE", "40.396644"))
LOCATION_LONGITUDE      = float(os.environ.get("LOCATION_LONGITUDE", "-3.622511"))
MELCLOUD_UPDATE_INTERVAL = int(os.environ.get("MELCLOUD_UPDATE_INTERVAL", "30"))
OUTDOOR_UPDATE_INTERVAL  = int(os.environ.get("OUTDOOR_UPDATE_INTERVAL", "600"))
OUTDOOR_CACHE_TTL        = int(os.environ.get("OUTDOOR_CACHE_TTL", "600"))
CLEANUP_INTERVAL_SECONDS = int(os.environ.get("CLEANUP_INTERVAL_SECONDS", "86400"))

AC_POWER_COOLING_MAX    = float(os.environ.get("AC_POWER_COOLING_MAX", "2.5"))
AC_POWER_COOLING_MID    = float(os.environ.get("AC_POWER_COOLING_MID", "1.75"))
AC_POWER_MODULATING     = float(os.environ.get("AC_POWER_MODULATING", "1.25"))
AC_POWER_FORCED_ON      = float(os.environ.get("AC_POWER_FORCED_ON", "2.5"))

# ── Global components (injected into routes) ──────────────────────────────────

mqtt_handler: MqttHandler | None = None
melcloud_client: MelCloudClient | None = None
ac_controller: ACController | None = None
subscription_manager: SubscriptionManager | None = None
error_tracker: ErrorTracker | None = None
humidity_scheduler: HumidityAnalysisScheduler | None = None
ac_temp_scheduler: AcTempScheduler | None = None


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global mqtt_handler, melcloud_client, ac_controller
    global subscription_manager, error_tracker, humidity_scheduler, ac_temp_scheduler

    error_tracker = ErrorTracker()
    logger.info("=== AC Service starting ===")

    # 0. Discover sensors from Zigbee2MQTT
    z2m = Zigbee2MQTTClient(MQTT_BROKER, MQTT_PORT, timeout=Z2M_DISCOVERY_TIMEOUT)
    sensor_names = z2m.discover_temperature_sensors()
    if not sensor_names:
        logger.warning("No sensors discovered — continuing without sensors")

    # 1. MQTT
    mqtt_handler = MqttHandler(
        MQTT_BROKER, MQTT_PORT, sensor_names,
        connect_retries=MQTT_CONNECT_RETRIES,
        retry_delay=MQTT_RETRY_DELAY,
        keepalive=MQTT_KEEPALIVE,
        max_history=MAX_HISTORY_PER_SENSOR,
    )
    mqtt_handler.start()
    mqtt_handler.set_error_tracker(error_tracker)

    # 2. MELCloud
    melcloud_client = MelCloudClient(
        MELCLOUD_URL, MELCLOUD_EMAIL, MELCLOUD_PASSWORD,
        MELCLOUD_BUILDING_ID,
        timeout=MELCLOUD_TIMEOUT,
        app_version=MELCLOUD_APP_VERSION,
    )
    if not melcloud_client.login():
        logger.error("MELCloud login failed — controller will not act")
        error_tracker.register("melcloud_auth", "error", "MELCloud authentication failed", "melcloud")
    else:
        error_tracker.clear("melcloud_auth")

    # 3. AC Controller
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
    ac_controller.restore_state()
    ac_controller.set_error_tracker(error_tracker)
    ac_controller.start()

    # 4. Subscription Manager
    sub_config = SubscriptionConfig(
        melcloud_interval=MELCLOUD_UPDATE_INTERVAL,
        outdoor_interval=OUTDOOR_UPDATE_INTERVAL,
    )
    subscription_manager = SubscriptionManager(sub_config)

    def fetch_melcloud_state():
        state = melcloud_client.get_device_state(MELCLOUD_DEVICE_ID, MELCLOUD_BUILDING_ID)
        if state is not None:
            ac_controller.update_ac_real_cache(state)
        return state

    subscription_manager.subscribe("melcloud", fetch_melcloud_state, interval=MELCLOUD_UPDATE_INTERVAL)

    def fetch_outdoor_temp():
        import httpx
        try:
            weather_resp = httpx.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": LOCATION_LATITUDE, "longitude": LOCATION_LONGITUDE,
                    "current": "temperature_2m,relative_humidity_2m", "timezone": "Europe/Madrid",
                }, timeout=10.0,
            )
            aqi_resp = httpx.get(
                "https://air-quality-api.open-meteo.com/v1/air-quality",
                params={
                    "latitude": LOCATION_LATITUDE, "longitude": LOCATION_LONGITUDE,
                    "current": "european_aqi", "timezone": "Europe/Madrid",
                }, timeout=10.0,
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

    subscription_manager.subscribe("outdoor", fetch_outdoor_temp, interval=OUTDOOR_UPDATE_INTERVAL)
    subscription_manager.start()

    # 5. Schedulers
    ac_temp_scheduler = AcTempScheduler(mqtt_handler, ac_controller)
    ac_temp_scheduler.start()

    humidity_scheduler = HumidityAnalysisScheduler(
        mqtt_handler=mqtt_handler,
        sample_interval_seconds=int(os.environ.get("HUMIDITY_ANALYSIS_INTERVAL", str(3600))),
        grace_period_seconds=int(os.environ.get("HUMIDITY_GRACE_PERIOD", "300")),
    )
    humidity_scheduler.start()

    logger.info("=== AC Service ready ===")
    yield

    # Shutdown
    logger.info("=== AC Service shutting down ===")
    ac_temp_scheduler.stop()
    humidity_scheduler.stop()
    subscription_manager.stop()
    ac_controller.stop()
    mqtt_handler.stop()
    melcloud_client.close()


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="AC Service", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)


# ── Pydantic models ───────────────────────────────────────────────────────────

class ConfigUpdate(BaseModel):
    target_temperature: float | None = None
    hysteresis_on: float | None = None
    hysteresis_off: float | None = None
    loop_interval: int | None = None


class ControlModeRequest(BaseModel):
    mode: str  # "auto", "manual", "off"


class ManualParamsRequest(BaseModel):
    mode: str = "cool"
    fan_speed: int = 0
    temperature: float = 23.0


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"online": True, "service": "ac"}


# ── SPA ───────────────────────────────────────────────────────────────────────

def _serve_html(filename: str) -> HTMLResponse:
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


@app.get("/smart-home/ac")
async def serve_ac():
    return _serve_html("index.html")


# ── API routes (same paths as before — nginx proxies these) ───────────────────

@app.get("/api/status")
def get_status():
    state = ac_controller.current_state
    return {
        "average_temperature": state.average_temp,
        "average_humidity": state.average_humidity,
        "target_temperature": ac_controller.config.target_temperature,
        "ac_state": {
            "action": state.state,
            "setpoint": state.setpoint,
            "mode": state.ac_mode,
            "fan_speed": state.fan_speed,
            "active_sensors": state.active_sensors,
            "total_sensors": state.total_sensors,
            "control_mode": state.control_mode,
            "sensor_alert": state.sensor_alert,
            "melcloud_error": state.melcloud_error,
        },
        "ac_real": {
            "power": state.ac_real_power,
            "mode": state.ac_real_mode,
            "fan_speed": state.ac_real_fan_speed,
            "setpoint": state.ac_real_setpoint,
            "room_temp": state.ac_real_room_temp,
            "last_update": state.ac_real_last_update,
        },
        "manual_params": {
            "mode": state.manual_params.mode if state.manual_params else "cool",
            "fan_speed": state.manual_params.fan_speed if state.manual_params else 0,
            "temperature": state.manual_params.temperature if state.manual_params else 23.0,
        },
        "last_update": state.last_update,
        "mqtt_connected": mqtt_handler.is_connected,
    }


@app.get("/api/sensors")
def get_sensors():
    all_sensors = mqtt_handler.sensor_names
    now = time.time()
    sensors = []
    for name in all_sensors:
        reading = mqtt_handler.readings.get(name)
        if reading:
            age = now - reading.timestamp
            sensors.append({
                "name": name,
                "online": age < ac_controller.config.sensor_timeout,
                "temperature": reading.temperature,
                "humidity": reading.humidity,
                "battery": reading.battery,
                "last_seen_seconds": round(age, 1),
                "timestamp": reading.timestamp,
            })
        else:
            sensors.append({
                "name": name, "online": False,
                "temperature": None, "humidity": None, "battery": None,
                "last_seen_seconds": None, "timestamp": None,
            })
    return {"sensors": sensors}


@app.get("/api/sensors/history")
def get_sensors_history(start: float | None = None, end: float | None = None, last: int | None = None):
    result = {}
    with mqtt_handler._lock:
        for name, readings_list in mqtt_handler.history.items():
            if start is not None or end is not None:
                filtered = [
                    r for r in readings_list
                    if (start is None or r.timestamp >= start) and (end is None or r.timestamp <= end)
                ]
                entries = filtered
            elif last is not None:
                entries = readings_list[-last:]
            else:
                entries = readings_list
            result[name] = [
                {"temperature": r.temperature, "humidity": r.humidity, "timestamp": r.timestamp}
                for r in entries
            ]
    return result


@app.get("/api/history")
def get_history(limit: int = 100):
    return {"history": ac_controller.get_history(limit)}


@app.get("/api/config")
def get_config():
    cfg = ac_controller.config
    return {
        "target_temperature": cfg.target_temperature,
        "hysteresis_on": cfg.hysteresis_on,
        "hysteresis_off": cfg.hysteresis_off,
        "min_setpoint": cfg.min_setpoint,
        "max_setpoint": cfg.max_setpoint,
        "loop_interval": cfg.loop_interval,
        "sensor_timeout": cfg.sensor_timeout,
        "ac_mode": cfg.ac_mode,
        "fan_speed_max": cfg.fan_speed_max,
        "fan_speed_modulate": cfg.fan_speed_modulate,
    }


@app.post("/api/config")
def update_config(update: ConfigUpdate):
    changes = update.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(400, "No changes")
    if "target_temperature" in changes:
        temp = changes["target_temperature"]
        if temp < ac_controller.config.min_setpoint or temp > ac_controller.config.max_setpoint:
            raise HTTPException(400, f"Temperature must be between {ac_controller.config.min_setpoint} and {ac_controller.config.max_setpoint}")
    ac_controller.update_config(**changes)
    return {"status": "updated", "changes": changes}


@app.post("/api/control_mode")
def set_control_mode(req: ControlModeRequest):
    if req.mode not in ("auto", "manual", "off"):
        raise HTTPException(400, "mode must be 'auto', 'manual', or 'off'")
    if req.mode == "manual":
        state = ac_controller.current_state
        ac_controller.set_manual_params(
            temperature=state.setpoint,
            fan_speed=state.fan_speed,
            mode=state.ac_mode,
        )
    ac_controller.set_control_mode(req.mode)
    return {"status": "ok", "control_mode": req.mode}


@app.post("/api/manual_params")
def set_manual_params(req: ManualParamsRequest):
    min_temp = ac_controller.config.min_setpoint
    max_temp = ac_controller.config.max_setpoint
    if req.temperature < min_temp or req.temperature > max_temp:
        raise HTTPException(400, f"Temperature must be between {min_temp} and {max_temp}")
    if req.fan_speed < 0 or req.fan_speed > 3:
        raise HTTPException(400, "Fan speed must be between 0 and 3")
    if req.mode not in ("cool", "heat"):
        raise HTTPException(400, "Mode must be 'cool' or 'heat'")
    ac_controller.set_manual_params(temperature=req.temperature, fan_speed=req.fan_speed, mode=req.mode)
    state = ac_controller.current_state
    if state.control_mode == "manual":
        success = ac_controller.melcloud.set_temperature(
            ac_controller.config.device_id, req.temperature,
            power=True, mode=req.mode, fan_speed=req.fan_speed,
        )
        return {"status": "ok" if success else "error", "applied": {"mode": req.mode, "fan_speed": req.fan_speed, "temperature": req.temperature}}
    return {"status": "ok", "message": "Parameters saved"}


@app.post("/api/manual_param")
def update_manual_param(param: str, value: str):
    state = ac_controller.current_state
    if state.control_mode != "manual":
        raise HTTPException(400, "Not in manual mode")
    if param not in ("mode", "fan_speed", "temperature"):
        raise HTTPException(400, f"Invalid parameter: {param}")
    if param == "temperature":
        try:
            converted_value = float(value)
        except ValueError:
            raise HTTPException(400, "Temperature must be a number")
        min_temp = ac_controller.config.min_setpoint
        max_temp = ac_controller.config.max_setpoint
        if converted_value < min_temp or converted_value > max_temp:
            raise HTTPException(400, f"Temperature must be between {min_temp} and {max_temp}")
    elif param == "fan_speed":
        try:
            converted_value = int(value)
        except ValueError:
            raise HTTPException(400, "Fan speed must be an integer")
        if converted_value < 0 or converted_value > 3:
            raise HTTPException(400, "Fan speed must be between 0 and 3")
    else:
        if value not in ("cool", "heat"):
            raise HTTPException(400, "Mode must be 'cool' or 'heat'")
        converted_value = value
    ac_controller.update_manual_param(param, converted_value)
    manual_params = state.manual_params
    mode = converted_value if param == "mode" else manual_params.mode
    fan_speed = converted_value if param == "fan_speed" else manual_params.fan_speed
    temperature = converted_value if param == "temperature" else manual_params.temperature
    success = ac_controller.melcloud.set_temperature(
        ac_controller.config.device_id, temperature,
        power=True, mode=mode, fan_speed=fan_speed,
    )
    if success and subscription_manager is not None:
        subscription_manager.force_update("melcloud")
    return {"status": "ok" if success else "error", "applied": {"mode": mode, "fan_speed": fan_speed, "temperature": temperature}}


@app.get("/api/ac_real")
def get_ac_real():
    try:
        state = ac_controller.melcloud.get_device_state(
            ac_controller.config.device_id, ac_controller.config.building_id,
        )
        if state is None:
            return {"power": None, "mode": None, "fan_speed": None, "set_temp": None, "room_temp": None}
        mode_names = {1: "HOT", 2: "DRY", 3: "COLD", 7: "FAN", 8: "AUTO"}
        fan_names = {0: "Auto", 1: "Bajo", 2: "Medio", 3: "Alto"}
        return {
            "power": state.get("Power", False),
            "mode": mode_names.get(state.get("OperationMode"), "?"),
            "fan_speed": fan_names.get(state.get("SetFanSpeed"), "—"),
            "set_temp": state.get("SetTemperature"),
            "room_temp": state.get("RoomTemperature"),
        }
    except Exception:
        return {"power": None, "mode": None, "fan_speed": None, "set_temp": None, "room_temp": None}


@app.get("/api/outdoor")
def get_outdoor():
    outdoor_data = subscription_manager.get_cached("outdoor", default={})
    if not outdoor_data:
        return {"temperature": None, "humidity": None, "timestamp": 0}
    cache_entry = subscription_manager.cache.get("outdoor")
    timestamp = cache_entry.timestamp if cache_entry else 0
    return {
        "temperature": outdoor_data.get("temperature"),
        "humidity": outdoor_data.get("humidity"),
        "aqi": outdoor_data.get("aqi"),
        "timestamp": timestamp,
    }


@app.get("/api/errors")
def get_errors():
    if error_tracker is None:
        return {"errors": [], "has_errors": False}
    active = error_tracker.get_active()
    return {"errors": active, "has_errors": bool(active)}


@app.get("/api/humidity/study")
def get_humidity_study():
    from humidity_analysis import get_summary
    summary = get_summary()
    if summary is None:
        return {"status": "no_data", "message": "Analysis not started yet"}
    return summary


@app.post("/api/humidity/study/run")
def trigger_humidity_analysis():
    if humidity_scheduler is None:
        return {"status": "error", "message": "Humidity scheduler not initialized"}
    humidity_scheduler.run_now()
    return {"status": "ok", "message": "Analysis triggered"}


@app.get("/api/energy/current")
def get_energy_current():
    return {"kwh": 0.0, "cost": 0.0, "last_update": time.time(), "note": "energy tracker not in ac-service"}


@app.get("/api/energy/hourly")
def get_energy_hourly():
    return {"data": {}}


@app.get("/api/energy/monthly")
def get_energy_monthly():
    return {"data": {}}


@app.get("/api/subscriptions/stats")
def get_subscription_stats():
    if subscription_manager is None:
        return {"error": "not initialized"}
    return subscription_manager.get_stats()


@app.get("/api/health/zigbee")
def get_zigbee_health():
    mqtt_ok = mqtt_handler is not None and mqtt_handler.is_connected
    active = {}
    if mqtt_handler is not None:
        active = mqtt_handler.get_active_readings(max_age_seconds=7200)
    return {
        "online": mqtt_ok,
        "mqtt_connected": mqtt_ok,
        "active_sensors": len(active),
    }


# ── Static assets ─────────────────────────────────────────────────────────────

_static_dir = Path(__file__).parent / "static"
if _static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")
