"""REST API endpoints for the Web UI."""

import time

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

# These references are injected from main.py
mqtt_handler = None
ac_controller = None
energy_tracker = None
subscription_manager = None

# Injected configurations
outdoor_cache_ttl = 600
location_lat = 40.396644
location_lon = -3.622511

router = APIRouter(prefix="/api")


class ConfigUpdate(BaseModel):
    target_temperature: float | None = None
    hysteresis_on: float | None = None
    hysteresis_off: float | None = None
    loop_interval: int | None = None


class ControlModeRequest(BaseModel):
    mode: str  # "auto", "manual", "off"


class ManualParamsRequest(BaseModel):
    mode: str = "cool"  # "cool" or "heat"
    fan_speed: int = 0  # 0=auto, 1=low, 2=mid, 3=high
    temperature: float = 23.0  # 19-30°C


@router.get("/status")
def get_status():
    """General system status (includes cached AC real state)."""
    state = ac_controller.current_state

    # Use values ALREADY CALCULATED by controller (optimization)
    # Controller calculates avg temp/hum every tick (10s) and saves them in state
    # Don't recalculate here to avoid unnecessary duplication
    return {
        "average_temperature": state.average_temp,  # Already calculated and rounded
        "average_humidity": state.average_humidity,  # Already calculated and rounded
        "target_temperature": ac_controller.config.target_temperature,
        "ac_state": {
            "action": state.state,
            "setpoint": state.setpoint,
            "mode": state.ac_mode,  # "cool" or "heat"
            "fan_speed": state.fan_speed,
            "active_sensors": state.active_sensors,
            "total_sensors": state.total_sensors,
            "control_mode": state.control_mode,  # "auto", "manual", "off"
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
        },  # Always return, even when not in manual mode
        "last_update": state.last_update,
        "mqtt_connected": mqtt_handler.is_connected,
    }


@router.get("/sensors")
def get_sensors():
    """Information from each sensor."""
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
    """Controller action history."""
    return {"history": ac_controller.get_history(limit)}


@router.get("/sensors/history")
def get_sensors_history(start: float | None = None, end: float | None = None, last: int | None = None):
    """Reading history from all sensors.

    Modes:
    - No arguments: complete snapshot (all available data, max 200 per sensor)
    - ?last=N: last N values per sensor
    - ?start=X&end=Y: values in timestamp range [start, end]
    - ?start=X: values from start until now
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
    """Current configuration."""
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
    """Updates configuration."""
    changes = update.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(400, "No changes")

    # Validate ranges (return error 400 if out of range)
    if "target_temperature" in changes:
        temp = changes["target_temperature"]
        if temp < ac_controller.config.min_setpoint or temp > ac_controller.config.max_setpoint:
            raise HTTPException(
                400, 
                f"Target temperature must be between {ac_controller.config.min_setpoint}°C and {ac_controller.config.max_setpoint}°C"
            )

    ac_controller.update_config(**changes)
    return {"status": "updated", "changes": changes}


@router.post("/control_mode")
def set_control_mode(req: ControlModeRequest):
    """Set control mode: auto, manual, or off."""
    if req.mode not in ("auto", "manual", "off"):
        raise HTTPException(400, "mode must be 'auto', 'manual', or 'off'")

    # When switching TO manual mode, initialize manual_params with current AC state
    if req.mode == "manual":
        state = ac_controller.current_state
        # Use current AC state as starting point for manual control
        ac_controller.set_manual_params(
            temperature=state.setpoint,  # Current setpoint from controller
            fan_speed=state.fan_speed,    # Current fan speed from controller
            mode=state.ac_mode            # Current mode from controller
        )

    ac_controller.set_control_mode(req.mode)
    return {"status": "ok", "control_mode": req.mode}


@router.post("/manual_params")
def set_manual_params(req: ManualParamsRequest):
    """Set manual mode parameters (mode, fan_speed, temperature)."""
    # Validate ranges
    min_temp = ac_controller.config.min_setpoint
    max_temp = ac_controller.config.max_setpoint
    
    if req.temperature < min_temp or req.temperature > max_temp:
        raise HTTPException(
            400,
            f"Temperature must be between {min_temp}°C and {max_temp}°C"
        )
    
    if req.fan_speed < 0 or req.fan_speed > 3:
        raise HTTPException(400, "Fan speed must be between 0 (auto) and 3 (high)")
    
    if req.mode not in ("cool", "heat"):
        raise HTTPException(400, "Mode must be 'cool' or 'heat'")

    # Update manual parameters
    ac_controller.set_manual_params(
        temperature=req.temperature,
        fan_speed=req.fan_speed,
        mode=req.mode
    )
    
    # If already in manual mode, apply immediately
    state = ac_controller.current_state
    if state.control_mode == "manual":
        success = ac_controller.melcloud.set_temperature(
            ac_controller.config.device_id,
            req.temperature,
            power=True,
            mode=req.mode,
            fan_speed=req.fan_speed,
        )
        
        return {
            "status": "ok" if success else "error",
            "applied": {
                "mode": req.mode,
                "fan_speed": req.fan_speed,
                "temperature": req.temperature
            }
        }
    
    return {"status": "ok", "message": "Parameters saved"}


@router.post("/manual_param")
def update_manual_param(param: str, value: str):
    """Update a single manual parameter (for real-time UI)."""
    state = ac_controller.current_state
    
    if state.control_mode != "manual":
        raise HTTPException(400, "Not in manual mode")
    
    # Validate param
    if param not in ("mode", "fan_speed", "temperature"):
        raise HTTPException(400, f"Invalid parameter: {param}")
    
    # Convert value to correct type and validate
    if param == "temperature":
        try:
            temp_value = float(value)
        except ValueError:
            raise HTTPException(400, "Temperature must be a number")
        
        min_temp = ac_controller.config.min_setpoint
        max_temp = ac_controller.config.max_setpoint
        if temp_value < min_temp or temp_value > max_temp:
            raise HTTPException(400, f"Temperature must be between {min_temp}°C and {max_temp}°C")
        converted_value = temp_value
        
    elif param == "fan_speed":
        try:
            fan_value = int(value)
        except ValueError:
            raise HTTPException(400, "Fan speed must be an integer")
        
        if fan_value < 0 or fan_value > 3:
            raise HTTPException(400, "Fan speed must be between 0 and 3")
        converted_value = fan_value
        
    elif param == "mode":
        if value not in ("cool", "heat"):
            raise HTTPException(400, "Mode must be 'cool' or 'heat'")
        converted_value = value
    
    # Update the parameter
    ac_controller.update_manual_param(param, converted_value)
    
    # Get current manual params
    manual_params = state.manual_params
    if param == "mode":
        mode = converted_value
        fan_speed = manual_params.fan_speed
        temperature = manual_params.temperature
    elif param == "fan_speed":
        mode = manual_params.mode
        fan_speed = converted_value
        temperature = manual_params.temperature
    else:  # temperature
        mode = manual_params.mode
        fan_speed = manual_params.fan_speed
        temperature = converted_value
    
    # Apply to MELCloud
    success = ac_controller.melcloud.set_temperature(
        ac_controller.config.device_id,
        temperature,
        power=True,
        mode=mode,
        fan_speed=fan_speed,
    )
    
    # Force immediate cache update from subscription manager
    if success and subscription_manager is not None:
        subscription_manager.force_update("melcloud")
    
    return {
        "status": "ok" if success else "error",
        "applied": {
            "mode": mode,
            "fan_speed": fan_speed,
            "temperature": temperature
        }
    }

    success = ac_controller.melcloud.set_temperature(
        ac_controller.config.device_id,
        24.0,
        power=False,
        fan_speed=0,
    )

    return {"status": "ok" if success else "error"}


@router.get("/ac_real")
def get_ac_real():
    """Real AC state read from MELCloud."""
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
    """Outdoor temperature in Valdebernardo (Open-Meteo, cached)."""
    # Get cached data from subscription manager (NEVER fetches directly)
    outdoor_data = subscription_manager.get_cached("outdoor", default={})
    
    if outdoor_data is None or not outdoor_data:
        return {"temperature": None, "humidity": None, "timestamp": 0}
    
    # Get timestamp from cache metadata
    cache_entry = subscription_manager.cache.get("outdoor")
    timestamp = cache_entry.timestamp if cache_entry else 0
    
    return {
        "temperature": outdoor_data.get("temperature"),
        "humidity": outdoor_data.get("humidity"),
        "timestamp": timestamp
    }


def _load_outdoor_from_disk():
    """Deprecated - now handled by subscription manager."""
    pass


def _save_outdoor_to_disk():
    """Deprecated - now handled by subscription manager."""
    pass



@router.get("/energy/current")
def get_energy_current():
    """Consumption and cost of last 24h."""
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
    """Data for hourly chart (24h)."""
    if energy_tracker is None:
        return {"data": {}}
    
    return {"data": energy_tracker.get_hourly_stats()}


@router.get("/energy/monthly")
def get_energy_monthly():
    """Data for monthly chart (12 months)."""
    if energy_tracker is None:
        return {"data": {}}
    
    return {"data": energy_tracker.get_monthly_stats()}


@router.get("/subscriptions/stats")
def get_subscription_stats():
    """Subscription manager statistics (cache usage, update intervals, etc.)."""
    if subscription_manager is None:
        return {"error": "Subscription manager not initialized"}
    
    return subscription_manager.get_stats()
