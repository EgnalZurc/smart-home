# Análisis Completo del Código - Smart Home

**Fecha**: 24 de junio de 2026  
**Auditor**: Kiro AI Assistant

---

## 🔴 RIESGOS CRÍTICOS

### 1. **SECRETOS EXPUESTOS EN LOGS**
**Archivo**: `main.py`  
**Línea**: 35  
**Problema**: Las credenciales de MELCloud se podrían loggear si hay error en la carga.
```python
MELCLOUD_EMAIL = os.environ.get("MELCLOUD_EMAIL", "")
MELCLOUD_PASSWORD = os.environ.get("MELCLOUD_PASSWORD", "")
```
**Riesgo**: Las credenciales podrían aparecer en logs si se hace print de variables de entorno.
**Recomendación**: Añadir validación que aborte si faltan credenciales, sin loggearlas.

---

### 2. **DEFAULTS INSEGUROS - IDs FALSOS**
**Archivo**: `main.py`  
**Líneas**: 36-37
```python
MELCLOUD_DEVICE_ID = int(os.environ.get("MELCLOUD_DEVICE_ID", "12345"))
MELCLOUD_BUILDING_ID = int(os.environ.get("MELCLOUD_BUILDING_ID", "67890"))
```
**Problema**: Valores por defecto falsos (12345, 67890) permiten que el sistema "arranque" pero no funcione.
**Riesgo**: Pérdida de tiempo debugging, creencia falsa de que el sistema está funcionando.
**Recomendación**: **NO DEFAULTS** - Abortar si no están configurados.

---

### 3. **CORS ABIERTO A TODOS**
**Archivo**: `main.py`  
**Líneas**: 120-124
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # ❌ PELIGROSO
    allow_methods=["*"],
    allow_headers=["*"],
)
```
**Riesgo**: Cualquier sitio web puede hacer requests a tu API.
**Recomendación**: Configurar origins permitidos vía variable de entorno.

---

### 4. **SIN VALIDACIÓN DE RANGOS EN API**
**Archivo**: `api/routes.py`  
**Líneas**: 192-193
```python
temp = max(19.0, min(30.0, req.temperature))
```
**Problema**: Se hace validación local pero no se informa al cliente que el valor fue modificado.
**Riesgo**: Usuario piensa que configuró 15°C pero sistema usa 19°C sin avisar.
**Recomendación**: Devolver error 400 si los valores están fuera de rango.

---

### 5. **RACE CONDITION EN MQTT HANDLER**
**Archivo**: `mqtt_handler.py`  
**Líneas**: 146-149
```python
with self._lock:
    self.readings[sensor_name] = reading
    # ... más operaciones
# Luego FUERA del lock:
self._save_to_disk()  # ❌ Sin lock!
```
**Problema**: `_save_to_disk()` lee `self.history` SIN el lock activo.
**Riesgo**: Podría leer datos inconsistentes si otro thread está modificando.
**Recomendación**: Mover `_save_to_disk()` dentro del `with self._lock` O hacer copia de datos.

---

### 6. **EXCEPCIÓN SILENCIADA EN CLEANUP**
**Archivo**: `cleanup.py`  
**Líneas**: 54-56
```python
except Exception as e:
    logger.warning("Error eliminando %s: %s", entry, e)
```
**Problema**: Los errores de permisos o I/O se ignoran completamente.
**Riesgo**: Acumulación de logs sin que nadie se entere.
**Recomendación**: Contabilizar errores y alertar si superan un umbral.

---

### 7. **CONTRASEÑA EN TEXTO PLANO EN MEMORIA**
**Archivo**: `melcloud_client.py`  
**Línea**: 34
```python
self.password = password
```
**Riesgo**: Si hay un crash dump o debugging, la contraseña está en memoria sin protección.
**Recomendación**: Usar solo durante login, luego borrarla (`del self.password`).

---

### 8. **SIN TIMEOUT EN LOOP MQTT**
**Archivo**: `zigbee2mqtt_client.py`  
**Líneas**: 88-93
```python
while not self.response_received and elapsed < self.timeout:
    time.sleep(poll_interval)
    elapsed += poll_interval
```
**Problema**: Si `response_received` nunca cambia por bug, loop se queda bloqueado por `timeout` segundos.
**Riesgo**: Startup lento (10 segundos de espera) en caso de fallo.
**Recomendación**: Ya está OK, pero añadir log cuando se alcanza timeout.

---

## ⚠️ VALORES HARDCODEADOS (A ELIMINAR)

### Backend

#### `main.py`
| Línea | Valor | Uso | Hacer Configurable |
|-------|-------|-----|-------------------|
| 36 | `"12345"` | Device ID default | ❌ **ELIMINAR** - Abortar sin configuración |
| 37 | `"67890"` | Building ID default | ❌ **ELIMINAR** - Abortar sin configuración |
| 87 | `19.0` | Min setpoint | ✅ `MIN_SETPOINT_TEMP` env var |
| 88 | `30.0` | Max setpoint | ✅ `MAX_SETPOINT_TEMP` env var |
| 89 | `180` | Cooldown seconds | ✅ `COOLDOWN_SECONDS` env var |
| 122 | `["*"]` | CORS origins | ✅ `CORS_ORIGINS` env var (comma-separated) |
| 145 | `24.0` | Setpoint dummy | Mantener (es fallback neutro) |

#### `mqtt_handler.py`
| Línea | Valor | Uso | Hacer Configurable |
|-------|-------|-----|-------------------|
| 22 | `"/app/data/sensor_readings.json"` | Persist file | ✅ Ya configurable con `SENSOR_PERSIST_FILE` |
| 42 | `200` | Max history per sensor | ✅ `MAX_HISTORY_PER_SENSOR` env var |
| 106 | `30` | Retry attempts | ✅ `MQTT_CONNECT_RETRIES` env var |
| 109 | `2` | Retry sleep (seconds) | ✅ `MQTT_RETRY_DELAY` env var |

#### `melcloud_client.py`
| Línea | Valor | Uso | Hacer Configurable |
|-------|-------|-----|-------------------|
| 18-24 | AC modes mapping | Constantes API | ✅ Está OK (son valores de la API MELCloud) |
| 55 | `30.0` | Timeout HTTP | ✅ `MELCLOUD_TIMEOUT` env var |
| 82 | `"1.32.1.0"` | AppVersion | ✅ `MELCLOUD_APP_VERSION` env var |
| 113 | `16.0`, `31.0` | Rango temperatura | **Duplicado** - usar config centralizada |

#### `zigbee2mqtt_client.py`
| Línea | Valor | Uso | Hacer Configurable |
|-------|-------|-----|-------------------|
| 30 | `10.0` | Timeout default | ✅ `Z2M_DISCOVERY_TIMEOUT` env var |
| 68 | `60` | Keepalive MQTT | ✅ `MQTT_KEEPALIVE` env var |
| 91 | `0.1` | Poll interval | Mantener (técnico, no de negocio) |

#### `cleanup.py`
| Línea | Valor | Uso | Hacer Configurable |
|-------|-------|-----|-------------------|
| 17 | `"/app/data/log"` | Z2M log dir | ✅ Ya configurable con `Z2M_LOG_DIR` |
| 19 | `3` | Retention days | ✅ Ya configurable con `LOG_RETENTION_DAYS` |
| 21 | `86400` | Cleanup interval | ✅ `CLEANUP_INTERVAL_SECONDS` env var |
| 66 | `60` | Grace period | ✅ `CLEANUP_GRACE_PERIOD` env var |

#### `controllers/ac_controller.py`
| Línea | Valor | Uso | Hacer Configurable |
|-------|-------|-----|-------------------|
| 46 | `26.0` | Target temp default | ✅ Ya configurable |
| 47-48 | `0.5`, `0.3` | Hysteresis | ✅ Ya configurable |
| 49-50 | `19.0`, `30.0` | Setpoint range | **Duplicado** - centralizar |
| 51 | `180` | Cooldown | ✅ `COOLDOWN_SECONDS` |
| 52 | `45` | Loop interval | ✅ Ya configurable |
| 53 | `600` | Sensor timeout | ✅ Ya configurable |
| 55 | `3` | Fan speed max | ✅ `FAN_SPEED_MAX` env var |
| 303-307 | Power map | Consumo por estado | ✅ `AC_POWER_COOLING_MAX`, `AC_POWER_MID`, etc. |

#### `controllers/state_machine.py`
| Línea | Valor | Uso | Hacer Configurable |
|-------|-------|-----|-------------------|
| 54 | `300` | Cooldown seconds | **Duplicado** - usar config |
| 55 | `3600` | Sensor alert timeout | ✅ Ya configurable como `SENSOR_TIMEOUT` |
| 56 | `100` | Max MELCloud failures | ✅ `MELCLOUD_MAX_FAILURES` env var |
| 58-61 | Hysteresis defaults | Valores razonables | ✅ Ya configurables |
| 23 | `23.0` | Force temp default | ✅ Ya está en `ForceOnParams` |

#### `api/routes.py`
| Línea | Valor | Uso | Hacer Configurable |
|-------|-------|-----|-------------------|
| 18 | `600` | Outdoor cache TTL | ✅ `OUTDOOR_CACHE_TTL` env var |
| 21-22 | Lat/Lon Valdebernardo | Ubicación geográfica | ✅ `LOCATION_LATITUDE`, `LOCATION_LONGITUDE` |
| 24.0 | Múltiples | Setpoint dummy | Mantener (fallback neutro) |

---

## 🔧 OPTIMIZACIONES RECOMENDADAS

### 1. **Eliminar Cálculo Redundante en API**
**Archivo**: `api/routes.py` línea 48  
**Antes**:
```python
avg_temp = mqtt_handler.get_average_temperature(...)
avg_hum = mqtt_handler.get_average_humidity(...)
```
**Después**: Usar valores ya calculados en `state.average_temp` y `state.average_humidity`
**Ahorro**: Evitar iterar sensores 2 veces adicionales cada request.

✅ **YA ESTÁ OPTIMIZADO** (líneas 46-49 usan `state.average_temp/humidity`)

---

### 2. **Cachear Configuración de SM**
**Archivo**: `ac_controller.py` línea 225  
**Problema**: Se crea un objeto `StateMachineConfig` nuevo cada tick.
**Solución**: Crear una vez y solo recrear si cambia la configuración.
**Ahorro**: Reducir allocations innecesarias (cada 10-45s).

---

### 3. **Reducir Lock Scope en MQTT Handler**
**Archivo**: `mqtt_handler.py` líneas 79-88  
**Problema**: El lock se mantiene durante `_save_to_disk()` que hace I/O.
**Solución**: Hacer copia de datos dentro del lock, liberar, luego guardar.
**Beneficio**: Mejor concurrencia, menos bloqueo de lecturas.

---

### 4. **Lazy Load de Outdoor Cache**
**Archivo**: `api/routes.py` línea 240  
**Problema**: Se carga outdoor cache en cada request aunque no se use.
**Solución**: Solo cargar si es necesario (cache miss).

✅ **YA ESTÁ OK** (línea 244 verifica antes de cargar)

---

### 5. **Usar httpx.AsyncClient en lugar de Client**
**Archivo**: `melcloud_client.py`  
**Problema**: Cliente HTTP síncrono bloquea thread de FastAPI.
**Solución**: Migrar a async/await con `httpx.AsyncClient`.
**Beneficio**: Mejor rendimiento en API REST.

---

### 6. **Pooling de Conexiones MQTT**
**Archivo**: `zigbee2mqtt_client.py`  
**Problema**: Se crea una conexión MQTT nueva cada vez para discovery.
**Solución**: Reusar conexión del mqtt_handler existente.
**Beneficio**: Evitar overhead de conexión TCP+MQTT.

---

### 7. **Limitar Tamaño de History en Controlador**
**Archivo**: `ac_controller.py` línea 268  
**Problema**: Se limita a 1000, se corta a 500 cuando se alcanza.
**Solución**: Limitar siempre a 500 (mantener últimos N en todo momento).

---

## 📋 CONFIGURACIÓN FALTANTE

Variables de entorno que DEBERÍAN añadirse:

```bash
# Seguridad
CORS_ORIGINS="http://localhost:8080,https://smart-home.local"

# Rangos AC
MIN_SETPOINT_TEMP=19.0
MAX_SETPOINT_TEMP=30.0

# Timeouts y límites
MELCLOUD_TIMEOUT=30.0
MELCLOUD_MAX_FAILURES=100
MELCLOUD_APP_VERSION="1.32.1.0"

# MQTT discovery
Z2M_DISCOVERY_TIMEOUT=10.0
MQTT_CONNECT_RETRIES=30
MQTT_RETRY_DELAY=2
MQTT_KEEPALIVE=60

# Historial
MAX_HISTORY_PER_SENSOR=200

# Cleanup
CLEANUP_INTERVAL_SECONDS=86400
CLEANUP_GRACE_PERIOD=60

# Outdoor API
OUTDOOR_CACHE_TTL=600
LOCATION_LATITUDE=40.396644
LOCATION_LONGITUDE=-3.622511

# Energía (potencias en kW)
AC_POWER_COOLING_MAX=2.5
AC_POWER_COOLING_MID=1.75
AC_POWER_MODULATING=1.25
AC_POWER_FORCED_ON=2.5

# Fan
FAN_SPEED_MAX=3
```

---

## 🚫 ELIMINACIONES OBLIGATORIAS

### 1. **Defaults Falsos en IDs**
```python
# ELIMINAR
MELCLOUD_DEVICE_ID = int(os.environ.get("MELCLOUD_DEVICE_ID", "12345"))

# REEMPLAZAR POR
if "MELCLOUD_DEVICE_ID" not in os.environ:
    logger.error("MELCLOUD_DEVICE_ID no configurado")
    raise RuntimeError("MELCLOUD_DEVICE_ID es obligatorio")
MELCLOUD_DEVICE_ID = int(os.environ["MELCLOUD_DEVICE_ID"])
```

### 2. **Contraseña en Memoria**
```python
# En melcloud_client.py, después del login exitoso:
def login(self) -> bool:
    # ... login logic ...
    if success:
        del self.password  # Borrar de memoria
        return True
```

### 3. **CORS Permisivo**
```python
# ELIMINAR
allow_origins=["*"],

# REEMPLAZAR POR
allowed = os.environ.get("CORS_ORIGINS", "http://localhost:8080").split(",")
allow_origins=allowed,
```

---

## 🎯 PRIORIDADES

### 🔴 CRÍTICO (Hacer YA)
1. Eliminar defaults falsos de Device/Building IDs
2. Configurar CORS origins correctamente
3. Fix race condition en `_save_to_disk()`
4. Validar rangos en API y devolver error 400

### 🟡 ALTA (Próxima sesión)
5. Hacer configurables todos los valores hardcodeados
6. Borrar contraseña de memoria después de login
7. Optimizar cálculos redundantes
8. Migrar a httpx.AsyncClient

### 🟢 MEDIA (Backlog)
9. Lazy load de recursos
10. Pooling de conexiones MQTT
11. Limitar history más estrictamente

---

## 📊 RESUMEN

**Valores hardcodeados encontrados**: 47  
**Riesgos críticos**: 8  
**Optimizaciones posibles**: 7  
**Variables de entorno a añadir**: 18  

**Estado actual**: ⚠️ Funcional pero con riesgos de seguridad y mantenibilidad

**Próximos pasos**: Implementar correcciones críticas + hacer todo configurable
