# Smart Home - Lista de Requisitos

## Estado General del Proyecto

**Última actualización**: 24 de junio de 2026

Este documento lista todos los requisitos del proyecto Smart Home y su estado de implementación.

---

## REQUISITOS COMPLETADOS ✅

### 1. Control automático de AC basado en temperatura
**Estado**: ✅ COMPLETADO  
**Descripción**: Sistema de control automático del aire acondicionado basado en lecturas de sensores de temperatura Zigbee.
- Máquina de estados (FORCED_OFF, FORCED_ON, AUTO)
- Histéresis configurable
- Override manual desde frontend
- Cooldown entre cambios de estado

### 2. Integración con MELCloud
**Estado**: ✅ COMPLETADO  
**Descripción**: Cliente para controlar AC Mitsubishi vía API MELCloud.
- Autenticación con credenciales
- Control de encendido/apagado
- Control de temperatura setpoint
- Lectura de estado actual del dispositivo

### 3. Monitoreo de sensores Zigbee
**Estado**: ✅ COMPLETADO  
**Descripción**: Sistema de lectura de sensores SONOFF SNZB-02D vía MQTT.
- 5 sensores de temperatura/humedad
- Configuración de reporting (cada 1h o cambio >0.1°C)
- Timeout de sensores (3600s)
- Persistencia de datos históricos

### 4. API REST para frontend
**Estado**: ✅ COMPLETADO  
**Descripción**: API FastAPI con endpoints para control y monitoreo.
- `/api/status` - Estado del sistema
- `/api/sensors` - Lecturas actuales de sensores
- `/api/sensors/history` - Histórico de temperaturas
- `/api/ac_real` - Estado real del AC (MELCloud)
- `/api/outdoor` - Temperatura exterior
- `/api/override` - Control manual del AC

### 5. Frontend web responsive
**Estado**: ✅ COMPLETADO  
**Descripción**: Interfaz web para visualización y control.
- Visor de estado del sistema
- Panel de sensores con temperaturas actuales
- Gráfico histórico de temperaturas
- Controles de override (Force ON/OFF/AUTO)
- Responsive para móvil y desktop

### 6. Containerización con Docker
**Estado**: ✅ COMPLETADO  
**Descripción**: Todo el sistema desplegable con Docker Compose.
- Backend Python en contenedor
- Mosquitto MQTT broker
- Zigbee2MQTT para coordinador
- Persistencia de datos con volúmenes
- Soporte para Windows (serial bridge TCP)

### 7. Configuración de reporting de sensores
**Estado**: ✅ COMPLETADO  
**Descripción**: Configuración óptima de sensores para ahorro de batería.
- min_report_interval: 0 (inmediato en cambios)
- max_report_interval: 3600s (1 hora máximo)
- reportable_change: 0.1°C temperatura, 1% humedad

### 8. Limpieza automática de logs antiguos
**Estado**: ✅ COMPLETADO  
**Descripción**: Scheduler que limpia logs antiguos diariamente.
- Ejecuta cada 24 horas
- Retención de 3 días
- Limpia logs de Zigbee2MQTT

### 9. Temperatura objetivo por defecto 26°C
**Estado**: ✅ COMPLETADO  
**Descripción**: Valor por defecto de temperatura objetivo configurado a 26°C.
- Configurable vía variable de entorno `TARGET_TEMPERATURE`
- Valor por defecto: 26.0°C

### 10. Estado inicial FORCED_OFF
**Estado**: ✅ COMPLETADO  
**Descripción**: Al arrancar el sistema, el AC inicia en estado forzado apagado.
- Estado inicial: `ControllerState.FORCED_OFF`
- Override inicial: `"off"`
- AC se apaga automáticamente al arrancar

### 11. **Auto-discovery de sensores desde Zigbee2MQTT** 🆕
**Estado**: ✅ COMPLETADO  
**Descripción**: El sistema descubre automáticamente sensores conectados en Zigbee2MQTT al arrancar.
- Conexión MQTT al startup
- Query de dispositivos vía topic `zigbee2mqtt/bridge/request/devices`
- Filtrado automático de sensores con capacidad de temperatura
- Sin configuración hardcodeada de nombres de sensores
- Log de sensores descubiertos con fabricante y modelo
- Fallback seguro si Zigbee2MQTT no está disponible

**Implementación**:
- Nuevo cliente `Zigbee2MQTTClient` usando MQTT (no HTTP API)
- Integrado en `main.py` durante startup
- Sensores descubiertos automáticamente: Despacho, Habitación Papis, Habitación Cen, Habitación Esq, Salón

---

## REQUISITOS ELIMINADOS ❌

### ~~Módulo de monitoreo de energía~~
**Estado**: ❌ ELIMINADO  
**Razón**: Requisito descartado por el usuario. Todo el código relacionado con energía fue eliminado del proyecto.

---

## REQUISITOS PENDIENTES ⏳

### Fase 1: Control de humedad con deshumidificador
**Estado**: ⏳ PENDIENTE  
**Descripción**: Sistema de control de humedad para mantenerla entre 50-60%.
- Lecturas de humedad desde sensores existentes
- Control de dispositivo deshumidificador
- Límites de humedad configurables
- Integración con estado del sistema

### Fase 2: Backup automático de fotos
**Estado**: ⏳ PENDIENTE  
**Descripción**: Sistema de backup automático de fotos desde teléfonos móviles.
- Sincronización automática vía WiFi
- Almacenamiento en NAS local
- Notificaciones de backups completados
- Compresión opcional de fotos

---

## DECISIONES TÉCNICAS

### Arquitectura
- **Backend**: Python 3.12 + FastAPI
- **MQTT Broker**: Eclipse Mosquitto
- **Zigbee**: Zigbee2MQTT con coordinador Ember (EZSP)
- **Frontend**: HTML + JavaScript vanilla (sin frameworks)
- **Deployment**: Docker Compose

### Configuración de Hardware
- **Coordinador Zigbee**: Silicon Labs CP210x USB-UART Bridge (COM3 en Windows)
- **Serial Bridge**: TCP en puerto 8282 (host.docker.internal)
- **Sensores**: 5x SONOFF SNZB-02D (EndDevice, batería)
- **AC**: Mitsubishi controlado vía MELCloud

### Patrones y Estándares
- **Auto-discovery**: Sensores se descubren automáticamente desde Zigbee2MQTT vía MQTT
- **Máquina de estados**: Para control del AC (FORCED_OFF, FORCED_ON, AUTO)
- **Sin hardcoded values**: Toda configuración vía variables de entorno
- **Datos reales únicamente**: NUNCA se inventan valores de temperatura
- **Persistencia**: Datos históricos en JSON, logs persistentes con volúmenes Docker

### Variables de Entorno Disponibles
```bash
# MQTT
MQTT_BROKER=mosquitto
MQTT_PORT=1883

# MELCloud (obligatorio)
MELCLOUD_EMAIL=usuario@ejemplo.com
MELCLOUD_PASSWORD=password
MELCLOUD_DEVICE_ID=115643811
MELCLOUD_BUILDING_ID=809537

# Control AC
TARGET_TEMPERATURE=26.0        # Temperatura objetivo (default: 26°C)
HYSTERESIS_ON=0.5              # Histéresis para encender (default: 0.5°C)
HYSTERESIS_OFF=0.3             # Histéresis para apagar (default: 0.3°C)
LOOP_INTERVAL=10               # Intervalo del control loop (default: 10s)
SENSOR_TIMEOUT=3600            # Timeout de sensores (default: 3600s)
```

---

## CHANGELOG

### 2026-06-24
- ✅ Implementado auto-discovery de sensores desde Zigbee2MQTT vía MQTT
- ✅ Eliminada variable `ZIGBEE2MQTT_URL` (ya no se usa HTTP API)
- ✅ Cliente `Zigbee2MQTTClient` migrado de HTTP a MQTT
- ✅ Sensores ahora se descubren automáticamente en startup
- ✅ Fallback seguro si Zigbee2MQTT no responde

### 2026-06-23
- ✅ Cambiada temperatura objetivo por defecto a 26°C
- ✅ Estado inicial cambiado a FORCED_OFF
- ✅ Eliminada variable hardcodeada `SENSOR_NAMES`

### 2026-06-22
- ✅ Eliminado módulo de energía completo
- ✅ Limpieza de referencias a energía en backend y frontend

### 2026-06-21
- ✅ Preparado proyecto para publicación en GitHub
- ✅ Documentación creada (README, DEPLOY, QUICKSTART, CONTRIBUTING)
- ✅ `.gitignore` configurado correctamente

---

## NOTAS IMPORTANTES

### Sensores Zigbee
- Los sensores SNZB-02D son **EndDevice** con batería
- Reportan cada 1 hora O cuando detectan cambio >0.1°C
- Para aplicar nueva configuración, presionar botón físico + "Reconfigure" en Zigbee2MQTT UI
- Timeout configurado a 3600s (1 hora) para marcar sensor como offline

### Windows Compatibility
- Usa `serial_bridge.py` para exponer COM3 vía TCP (puerto 8282)
- Zigbee2MQTT se conecta a `tcp://host.docker.internal:8282`
- El serial bridge DEBE estar ejecutándose antes de Zigbee2MQTT

### MELCloud
- Requiere cuenta activa en app Mitsubishi MELCloud
- Device ID y Building ID se obtienen desde la app o API
- Sin credenciales válidas, el controlador NO actuará

### Datos Históricos
- Persistidos en `/app/data/sensor_readings.json` dentro del contenedor
- Mapeado a volumen Docker `backend_data`
- NO se inventan valores - solo datos reales de sensores

---

## REFERENCIAS

- [Zigbee2MQTT Documentation](https://www.zigbee2mqtt.io/)
- [SONOFF SNZB-02D Device Page](https://www.zigbee2mqtt.io/devices/SNZB-02D.html)
- [MELCloud API (unofficial)](https://github.com/vilppuvuorinen/pymelcloud)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Paho MQTT Python](https://eclipse.dev/paho/index.php?page=clients/python/index.php)

---

**Documento mantenido por**: Sistema Smart Home  
**Ubicación**: `/REQUIREMENTS.md`
