"""API REST endpoints para la Web UI."""

import time

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

# Estas referencias se inyectan desde main.py
mqtt_handler = None
ac_controller = None
energy_tracker = None

# Configuraciones inyectadas
outdoor_cache_ttl = 600
location_lat = 40.396644
location_lon = -3.622511

# Cache para temperatura exterior (no llamar a la API cada 5s)
_outdoor_cache = {"temperature": None, "humidity": None, "timestamp": 0}

router = APIRouter(prefix="/api")


class ConfigUpdate(BaseModel):
    target_temperature: float | None = None
    hysteresis_on: float | None = None
    hysteresis_off: float | None = None
    loop_interval: int | None = None


class OverrideRequest(BaseModel):
    mode: str | None  # "on", "off", None (auto)


@router.get("/status")
def get_status():
    """Estado general del sistema."""
    state = ac_controller.current_state

    # Usar valores YA CALCULADOS por el controlador (optimización)
    # El controlador calcula temp/hum media cada tick (10s) y las guarda en state
    # No recalcular aquí para evitar duplicación innecesaria
    return {
        "average_temperature": state.average_temp,  # Ya calculado y redondeado
        "average_humidity": state.average_humidity,  # Ya calculado y redondeado
        "target_temperature": ac_controller.config.target_temperature,
        "ac_state": {
            "action": state.state,
            "setpoint": state.setpoint,
            "active_sensors": state.active_sensors,
            "total_sensors": state.total_sensors,
            "override": state.override,
            "sensor_alert": state.sensor_alert,
            "melcloud_error": state.melcloud_error,
        },
        "last_update": state.last_update,
        "mqtt_connected": mqtt_handler.is_connected,
    }


@router.get("/sensors")
def get_sensors():
    """Información de cada sensor."""
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
                "name": name,
                "online": False,
                "temperature": None,
                "humidity": None,
                "battery": None,
                "last_seen_seconds": None,
                "timestamp": None,
            })

    return {"sensors": sensors}


@router.get("/history")
def get_history(limit: int = 100):
    """Histórico de acciones del controlador."""
    return {"history": ac_controller.get_history(limit)}


@router.get("/sensors/history")
def get_sensors_history(start: float | None = None, end: float | None = None, last: int | None = None):
    """Historial de lecturas de todos los sensores.

    Modos:
    - Sin argumentos: snapshot completo (todos los datos disponibles, max 200 por sensor)
    - ?last=N: últimos N valores por sensor
    - ?start=X&end=Y: valores en el rango de timestamps [start, end]
    - ?start=X: valores desde start hasta ahora
    """
    result = {}
    with mqtt_handler._lock:
        for name, readings_list in mqtt_handler.history.items():
            # Filtrar por rango temporal
            if start is not None or end is not None:
                filtered = []
                for r in readings_list:
                    if start is not None and r.timestamp < start:
                        continue
                    if end is not None and r.timestamp > end:
                        continue
                    filtered.append(r)
                entries = filtered
            elif last is not None:
                entries = readings_list[-last:]
            else:
                # Snapshot completo
                entries = readings_list

            result[name] = [
                {"temperature": r.temperature, "humidity": r.humidity, "timestamp": r.timestamp}
                for r in entries
            ]
    return result


@router.get("/config")
def get_config():
    """Configuración actual."""
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


@router.post("/config")
def update_config(update: ConfigUpdate):
    """Actualiza la configuración."""
    changes = update.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(400, "No hay cambios")

    # Validar rangos (devolver error 400 si están fuera de rango)
    if "target_temperature" in changes:
        temp = changes["target_temperature"]
        if temp < ac_controller.config.min_setpoint or temp > ac_controller.config.max_setpoint:
            raise HTTPException(
                400, 
                f"Temperatura objetivo debe estar entre {ac_controller.config.min_setpoint}°C y {ac_controller.config.max_setpoint}°C"
            )

    ac_controller.update_config(**changes)
    return {"status": "updated", "changes": changes}


@router.post("/override")
def set_override(req: OverrideRequest):
    """Control manual del AC."""
    if req.mode not in (None, "on", "off"):
        raise HTTPException(400, "mode debe ser 'on', 'off' o null (auto)")

    ac_controller.set_override(req.mode)
    return {"status": "ok", "override": req.mode}


class ForceOnRequest(BaseModel):
    ac_mode: str = "cool"  # cool, heat, dry, fan, auto
    fan_speed: int = 0     # 0=auto, 1-3
    temperature: float = 23.0  # 19-30


@router.post("/force_on")
def force_on(req: ForceOnRequest):
    """Forzar encendido del AC con parámetros personalizados."""
    # Validar rangos (devolver error 400 si están fuera de rango)
    min_temp = ac_controller.config.min_setpoint
    max_temp = ac_controller.config.max_setpoint
    
    if req.temperature < min_temp or req.temperature > max_temp:
        raise HTTPException(
            400,
            f"Temperatura debe estar entre {min_temp}°C y {max_temp}°C"
        )
    
    if req.fan_speed < 0 or req.fan_speed > ac_controller.config.fan_speed_max:
        raise HTTPException(
            400,
            f"Velocidad de ventilador debe estar entre 0 (auto) y {ac_controller.config.fan_speed_max}"
        )
    
    valid_modes = ("cool", "heat", "dry", "fan", "auto")
    if req.ac_mode not in valid_modes:
        raise HTTPException(
            400,
            f"Modo debe ser uno de: {', '.join(valid_modes)}"
        )

    # Actualizar temperatura objetivo del controlador (sincronizar)
    ac_controller.update_config(target_temperature=req.temperature)

    # Guardar parámetros de forzar encendido
    ac_controller.set_force_on_params(temperature=req.temperature, fan_speed=req.fan_speed)

    # Activar override ON en el controlador
    ac_controller.set_override("on")

    # Enviar directamente a MELCloud con los parámetros elegidos
    success = ac_controller.melcloud.set_temperature(
        ac_controller.config.device_id,
        req.temperature,
        power=True,
        mode=req.ac_mode,
        fan_speed=req.fan_speed,
    )

    return {
        "status": "ok" if success else "error", 
        "applied": {
            "mode": req.ac_mode, 
            "fan_speed": req.fan_speed, 
            "temperature": req.temperature
        }
    }


@router.post("/force_off")
def force_off():
    """Forzar apagado del AC."""
    ac_controller.set_override("off")

    success = ac_controller.melcloud.set_temperature(
        ac_controller.config.device_id,
        24.0,
        power=False,
        fan_speed=0,
    )

    return {"status": "ok" if success else "error"}


@router.get("/ac_real")
def get_ac_real():
    """Estado real del AC leído de MELCloud."""
    try:
        from melcloud_client import MelCloudClient
        state = ac_controller.melcloud.get_device_state(
            ac_controller.config.device_id,
            ac_controller.config.building_id,
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


@router.get("/outdoor")
def get_outdoor():
    """Temperatura exterior en Valdebernardo (Open-Meteo, sin API key).
    Persiste en el mismo volumen que los sensores."""
    global _outdoor_cache
    now = time.time()

    # Cargar de disco si cache vacío (tras reinicio)
    if _outdoor_cache["temperature"] is None:
        _load_outdoor_from_disk()

    # Devolver cache si es reciente
    if (now - _outdoor_cache["timestamp"]) < outdoor_cache_ttl and _outdoor_cache["temperature"] is not None:
        return _outdoor_cache

    # Llamar a Open-Meteo
    try:
        resp = httpx.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": location_lat,
                "longitude": location_lon,
                "current": "temperature_2m,relative_humidity_2m",
                "timezone": "Europe/Madrid",
            },
            timeout=10.0,
        )
        data = resp.json()
        current = data.get("current", {})

        _outdoor_cache = {
            "temperature": current.get("temperature_2m"),
            "humidity": current.get("relative_humidity_2m"),
            "timestamp": now,
        }

        # Persistir a disco
        _save_outdoor_to_disk()

        return _outdoor_cache

    except Exception:
        return _outdoor_cache


def _load_outdoor_from_disk():
    """Carga temperatura exterior persistida."""
    global _outdoor_cache
    try:
        import json
        from pathlib import Path
        path = Path("/app/data/outdoor_reading.json")
        if path.exists():
            _outdoor_cache = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass


def _save_outdoor_to_disk():
    """Guarda temperatura exterior a disco."""
    try:
        import json
        from pathlib import Path
        path = Path("/app/data/outdoor_reading.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_outdoor_cache, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass



@router.get("/energy/current")
def get_energy_current():
    """Consumo y coste de últimas 24h."""
    if energy_tracker is None:
        return {"kwh": 0.0, "cost": 0.0, "last_update": 0, "error": "Energy tracker not initialized"}
    
    totals = energy_tracker.get_current_24h()
    return {
        "kwh": totals["kwh"],
        "cost": totals["cost"],
        "last_update": time.time()
    }


@router.get("/energy/hourly")
def get_energy_hourly():
    """Datos para gráfica horaria (24h)."""
    if energy_tracker is None:
        return {"data": {}}
    
    return {"data": energy_tracker.get_hourly_stats()}


@router.get("/energy/monthly")
def get_energy_monthly():
    """Datos para gráfica mensual (12 meses)."""
    if energy_tracker is None:
        return {"data": {}}
    
    return {"data": energy_tracker.get_monthly_stats()}
