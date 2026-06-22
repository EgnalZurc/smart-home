# Requerimientos Completos - Smart Home Control

**Proyecto:** Sistema de Control de Aire Acondicionado  
**Versión:** 1.0  
**Fecha:** 22 de junio de 2026

---

## 📋 Índice de Requerimientos

- [Core - Control AC](#core---control-ac) (F0.1 - F0.4)
- [Sensores Zigbee](#sensores-zigbee) (F0.2, F0.5, F0.18, F0.19)
- [Lógica de Control](#lógica-de-control) (F0.3, F0.7, F0.12, F0.13)
- [Interfaz de Usuario](#interfaz-de-usuario) (F0.0, F0.9, F0.10, F0.14-F0.17, F0.21, F0.22)
- [Persistencia y Logging](#persistencia-y-logging) (F0.8, F0.18, F0.20)
- [Datos Externos](#datos-externos) (F0.11)
- [Seguimiento Energético](#seguimiento-energético) (F0.24 - F0.30) ⭐ NUEVO
- [Infraestructura](#infraestructura) (F0.6, F0.23)

---

## 🎯 Core - Control AC

### F0.1: Override del Termostato Interno
**Estado:** ✅ Implementado  
**Descripción:** Sobreescribir el termostato interno del AC usando la media de 5 sensores externos Zigbee.  
**Implementación:** ACController con máquina de estados que manipula la consigna vía MELCloud API.

### F0.4: Control vía MELCloud API
**Estado:** ✅ Validado y Funcionando  
**Descripción:** Control completo del AC mediante MELCloud API con WiFi adapter oficial Mitsubishi.  
**Endpoints:**
- `POST /Device/SetAta` - Configurar AC
- `GET /Device/Get` - Leer estado real
**Implementación:** `melcloud_client.py` con autenticación y manejo de estados.

---

## 📡 Sensores Zigbee

### F0.2: 5 Sensores de Temperatura/Humedad
**Estado:** ✅ Emparejados  
**Modelo:** SONOFF SNZB-02D (Zigbee 3.0)  
**Ubicaciones:**
1. Despacho
2. Habitación Central
3. Habitación Esquina
4. Habitación Papis
5. Salón

### F0.5: Detección de Sensores Desconectados
**Estado:** ✅ Implementado  
**Descripción:** Si un sensor no reporta en 1 hora (3600s), se marca como desconectado en la UI.  
**Nota:** Su último dato sigue usándose para la media del controlador (F0.3).

### F0.18: Persistencia de Lecturas
**Estado:** ✅ Implementado  
**Descripción:** Última medida de cada sensor (temp, humedad, batería, timestamp) persiste en disco y sobrevive reinicios.  
**Archivo:** `/app/data/sensor_readings.json`  
**Volumen Docker:** `backend_data:/app/data`

### F0.19: Criterio de Conexión
**Estado:** ✅ Implementado  
**Descripción:**
- Sensor conectado = última actualización < 1 hora
- Sensor desconectado = última actualización > 1 hora
**Variable:** `SENSOR_TIMEOUT=3600s`

---

## 🧮 Lógica de Control

### F0.3: Temperatura Media como Referencia
**Estado:** ✅ Implementado  
**Descripción:** Temperatura de referencia = media aritmética de **todos** los sensores con dato disponible (sin filtrar por timeout).  
**Implementación:** El controlador usa todos los datos persistidos para tomar decisiones.

### F0.7: Histéresis y Cooldown
**Estado:** ✅ Implementado  
**Descripción:** Histéresis configurable para evitar ciclos rápidos ON/OFF.  
**Parámetros:**
- Histéresis ON: +0.5°C (encender si temp > objetivo + 0.5)
- Histéresis OFF: -0.3°C (apagar si temp < objetivo - 0.3)
- Cooldown: 5 minutos (300s) entre OFF y ON

### F0.12: Límites de Temperatura Objetivo
**Estado:** ✅ Implementado  
**Descripción:** Temperatura objetivo limitada al rango real del AC: **19-30°C**.  
**Implementación:** Frontend y backend validan y limitan el rango.

### F0.13: Máquina de Estados Formal
**Estado:** ✅ Implementado  
**Descripción:** Máquina de estados explícita que define la decisión del controlador.  
**Estados:**
- `COOLING_MAX` - Enfriamiento máximo (consigna 19°C, fan 3)
- `MODULATING` - Modulación proporcional (consigna 19-30°C, fan auto)
- `OFF` - AC apagado
- `COOLDOWN` - Período de espera (5 min después de apagar)
- `FORCED_ON` - Forzado ON manual
- `FORCED_OFF` - Forzado OFF manual
- `ERROR` - Error (sin sensores o MELCloud falló)

**Archivo:** `src/backend/controllers/state_machine.py`  
**Tests:** 53 tests unitarios

---

## 🎨 Interfaz de Usuario

### F0.0: Pantalla Principal Funcional
**Estado:** ✅ Funcional  
**Descripción:** La pantalla principal muestra todos los datos correctamente.  
**Datos persistentes:** Sobreviven reinicios del backend.

### F0.9: Acceso desde Cualquier Dispositivo
**Estado:** ✅ Funcional  
**Descripción:** App accesible desde cualquier dispositivo en la WiFi local.  
**Acceso:** http://0.0.0.0:8080 (IP fija: 192.168.1.163)

### F0.10: Colores por Rango (Temperatura y Humedad)
**Estado:** ✅ Implementado  
**Temperatura:**
- < 18°C: Azul oscuro (`#1e40af`)
- 18-20°C: Azul (`#3b82f6`)
- 20-26°C: Verde (`#22c55e`)
- 26-28°C: Naranja (`#f97316`)
- > 28°C: Rojo (`#ef4444`)

**Humedad:**
- < 30%: Azul oscuro
- 30-40%: Azul
- 40-60%: Verde
- 60-70%: Naranja
- > 70%: Rojo

### F0.14: Estado Real del AC (MELCloud)
**Estado:** ✅ Implementado  
**Descripción:** Mostrar estado real leído desde MELCloud.  
**Datos:**
- ON/OFF (verde/rojo)
- Modo (COLD/HOT/DRY/FAN/AUTO)
- Fan speed (Bajo/Medio/Alto/Auto)
- Consigna real

### F0.15: Colores de Fuerza del Aire
**Estado:** ✅ Implementado  
**Descripción:**
- Bajo: Verde
- Medio: Amarillo
- Alto: Rojo
- Auto: Azul

### F0.16: Mostrar Consigna AC
**Estado:** ✅ Implementado  
**Descripción:** Mostrar la consigna (setpoint) actual del AC.

### F0.17: UI Moderna Mobile-First
**Estado:** ✅ Implementado  
**Descripción:** Interfaz moderna, mobile-first, user-friendly.  
**Características:**
- Glassmorphism design
- Animaciones suaves
- Touch targets ≥ 48px
- PWA (Progressive Web App)
- Responsive design

### F0.21: Mostrar Decisión del Controlador
**Estado:** ✅ Implementado  
**Descripción:** Sección "Controlador" con temperatura objetivo + decisión actual.  
**Estados mostrados:**
- COOLING MAX (azul)
- MODULANDO (amarillo)
- OFF (gris)
- COOLDOWN (morado)
- FORZADO ON (verde)
- FORZADO OFF (rojo)
- ERROR (rojo)

### F0.22: Popups de Control Manual
**Estado:** ✅ Implementado  
**Descripción:**
- **Forzar ON:** Popup para elegir modo, fuerza y temperatura
- **Forzar OFF:** Popup de confirmación
**Implementación:** Modales con animación bottom sheet.

---

## 💾 Persistencia y Logging

### F0.8: Log de Acciones
**Estado:** ✅ Implementado  
**Descripción:** Log de todas las acciones tomadas por el controlador.  
**Implementación:** Histórico en memoria (últimas 1000 entradas, mantiene últimas 500 al llegar al límite).  
**Endpoint:** `GET /api/history`

### F0.20: Limpieza Automática
**Estado:** ✅ Implementado (no testado)  
**Descripción:** Logs y datos de persistencia mínimos con limpieza automática diaria.  
**Implementación:**
- Rotación de logs Docker
- Cleanup Zigbee2MQTT cada 24h
- Retención: 3 días

---

## 🌍 Datos Externos

### F0.11: Temperatura Exterior
**Estado:** ✅ Implementado  
**Descripción:** Mostrar temperatura exterior de Valdebernardo, Madrid.  
**Ubicación:** C.P. 28032 (coords: 40.396644, -3.622511)  
**API:** Open-Meteo (sin API key)  
**Cache:** 10 minutos  
**Persistencia:** Guardado en disco (`outdoor_reading.json`)

---

## ⚡ Seguimiento Energético ⭐ NUEVO

### F0.24: Widget de Consumo Energético
**Estado:** ✅ Implementado  
**Descripción:** Widget en pantalla principal mostrando consumo total de últimas 24h y coste en €.  
**Ubicación:** Al final de la pantalla principal, después del control manual.  
**Interacción:** Clickeable, abre popup de estadísticas detalladas.

### F0.25: API ESIOS para Precios PVPC
**Estado:** ✅ Implementado  
**Descripción:** Obtener precios de energía regulada (PVPC) de la API ESIOS (REE España).  
**Frecuencia:** Cada hora  
**API:** https://api.esios.ree.es/indicators/1001  
**Autenticación:** API key (gratuita) en `ESIOS_API_KEY`  
**Cache:** Precios de 24h guardados en disco  
**Fallback:** Precio mock €0.15/kWh si no hay API key

**Archivo:** `src/backend/energy/esios_client.py`

### F0.26: Registro Horario de Consumo
**Estado:** ✅ Implementado  
**Descripción:** Registrar consumo cada hora en punto (:00) en JSON con 24 valores (rolling window).  
**Archivo:** `/app/data/energy_hourly.json`  
**Estructura:**
```json
{
  "last_update": 1719097200,
  "data": {
    "00": {"kwh": 0.5, "price_per_kwh": 0.15, "cost": 0.075, "timestamp": 1719014400},
    "01": {"kwh": 0.6, "price_per_kwh": 0.14, "cost": 0.084, "timestamp": 1719018000},
    ...
    "23": {"kwh": 0.4, "price_per_kwh": 0.13, "cost": 0.052, "timestamp": 1719097200}
  }
}
```
**Scheduler:** APScheduler con cron `minute=0`

### F0.27: Registro Diario de Consumo
**Estado:** ✅ Implementado  
**Descripción:** Registrar consumo cada día a las 00:00 en JSON con hasta 365 valores (rolling window).  
**Archivo:** `/app/data/energy_daily.json`  
**Estructura:**
```json
{
  "last_update": 1719014400,
  "data": {
    "2026-01-01": {"kwh": 12.5, "cost": 1.85, "timestamp": 1704067200},
    "2026-01-02": {"kwh": 14.2, "cost": 2.13, "timestamp": 1704153600},
    ...
  }
}
```
**Scheduler:** APScheduler con cron `hour=0, minute=0`

### F0.28: Popup de Estadísticas Energéticas
**Estado:** ✅ Implementado  
**Descripción:** Popup con 2 gráficas de consumo (click en widget de energía).  
**Contenido:**
1. **Resumen:**
   - Últimas 24h: X.XX kWh (€Y.YY)
   - Promedio diario: X.XX kWh (€Y.YY)

2. **Gráfica Horaria (últimas 24h):**
   - Eje X: Hora (00-23)
   - Eje Y izquierdo: kWh (barras azules)
   - Eje Y derecho: Coste € (línea verde)

3. **Gráfica Mensual (últimos 12 meses):**
   - Eje X: Mes (Ene-Dic)
   - Eje Y izquierdo: kWh totales del mes (barras moradas)
   - Eje Y derecho: Coste € total del mes (línea naranja)

**Tecnología:** Chart.js con configuración de 2 ejes Y

### F0.29: Coste con Precio Exacto del Momento
**Estado:** ✅ Implementado  
**Descripción:** Calcular coste usando el precio exacto del momento de consumo (no precio promedio).  
**Lógica:**
- Al registrar hora 10:00, usa precio de 09:00-10:00 (hora en que se consumió)
- Cache de precios por hora permite lookup preciso
- Fallback a último precio conocido si ESIOS falla

**Implementación:** `energy_tracker.py` método `record_hourly()`

### F0.30: Optimización con Acumuladores en Memoria
**Estado:** ✅ Implementado  
**Descripción:** Usar acumuladores en memoria para evitar recalcular totales en cada petición.  
**Implementación:**
- Variables `_current_24h_kwh` y `_current_24h_cost` en `EnergyTracker`
- Actualizadas en `record_hourly()` usando diferencial (añadir nueva hora, restar hora que sale)
- Endpoint `/api/energy/current` lee directamente del acumulador (O(1))
- Recalculadas desde disco al iniciar backend

**Beneficio:** Respuesta API instantánea sin iterar sobre 24 valores cada vez.

---

## 🏗️ Infraestructura

### F0.6: POC Virtualizado
**Estado:** ✅ Completado  
**Descripción:** Proof of Concept virtualizado antes de comprar hardware.  
**Componentes:**
- Mock sensors (Python script publica temperaturas simuladas en MQTT)
- Mock MELCloud (servidor HTTP que simula API MELCloud)
- Controlador real (lógica exacta de producción)
- Web UI real (PWA funcional con datos simulados)

**Resultado:** POC validó el diseño completo antes de inversión en hardware.

### F0.23: Deployment en Raspberry Pi
**Estado:** ⏳ Pendiente  
**Descripción:** Software debe correr en Raspberry Pi (Docker, ARM64).  
**Hardware:** Raspberry Pi 5 4GB (comprado)  
**Pendiente:** Deploy real en la Raspberry Pi

---

## 📊 Resumen por Estado

| Estado | Cantidad | Requerimientos |
|--------|----------|----------------|
| ✅ Implementado | 29 | F0.0-F0.22, F0.24-F0.30 |
| ⏳ Pendiente | 1 | F0.23 (deploy en Raspberry Pi) |
| **TOTAL** | **30** | **Requerimientos completos** |

---

## 🔧 Tecnologías Utilizadas

### Backend
- **Lenguaje:** Python 3.12
- **Framework:** FastAPI + Uvicorn
- **MQTT:** Paho-MQTT
- **HTTP Client:** httpx
- **Scheduler:** APScheduler
- **Estado:** Máquina de estados pura (state_machine.py)

### Frontend
- **Framework CSS:** Tailwind CSS
- **Gráficas:** Chart.js
- **PWA:** manifest.json + service worker
- **Design:** Glassmorphism + animaciones CSS

### Infraestructura
- **Contenedores:** Docker + Docker Compose
- **Zigbee:** Zigbee2MQTT + Coordinador SONOFF ZBDongle-E V2
- **MQTT Broker:** Eclipse Mosquitto
- **Persistencia:** Volúmenes Docker + JSON files

### APIs Externas
- **MELCloud:** API no oficial (ingeniería inversa)
- **Open-Meteo:** API pública para temperatura exterior
- **ESIOS (REE):** API oficial para precios PVPC

---

## 📈 Métricas del Proyecto

### Código
- **Archivos Python:** 15+
- **Archivos Frontend:** 2 (HTML, manifest.json)
- **Tests Unitarios:** 53 (state_machine)
- **Líneas de Código:** ~3500 (backend) + ~800 (frontend)

### Funcionalidad
- **Endpoints API:** 15+
- **Estados del Controlador:** 7
- **Sensores Zigbee:** 5
- **Gráficas en UI:** 4 (temp, hum, energía horaria, energía mensual)
- **Popups/Modales:** 4 (sensores, force ON, force OFF, energía)

### Persistencia
- **JSON Files:** 6 (sensor_readings, outdoor_reading, energy_hourly, energy_daily, energy_prices_cache, coordinator_backup)
- **Volúmenes Docker:** 2 (backend_data, zigbee2mqtt_data)

---

## 🎯 Objetivos Cumplidos

✅ **Control preciso del AC** sin depender del termostato interno defectuoso  
✅ **5 sensores Zigbee** distribuidos por toda la casa  
✅ **Máquina de estados formal** con lógica probada  
✅ **UI moderna y responsive** optimizada para móvil  
✅ **Persistencia completa** de datos entre reinicios  
✅ **Seguimiento energético** con coste en tiempo real  
✅ **Sistema de gráficas** para visualización de datos  
✅ **Override manual** con controles granulares  
✅ **Temperatura exterior** para contexto  
✅ **PWA instalable** en dispositivos móviles  

---

**Fecha de última actualización:** 22 de junio de 2026  
**Versión del documento:** 1.0  
**Estado del proyecto:** ✅ Fase 0 Completa - Listo para Deploy en Raspberry Pi
