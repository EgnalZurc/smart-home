# Smart Home Control System

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![Docker](https://img.shields.io/badge/docker-ready-blue.svg)](docker-compose.yml)

Sistema de domótica modular y expandible por fases. Control inteligente de aire acondicionado con sensores Zigbee, tracking de energía y costes, todo accesible desde una PWA moderna.

**🚀 Demo:** _Próximamente_  
**⚡ Quick Start:** [QUICKSTART.md](QUICKSTART.md)  
**📖 Guía de Despliegue:** [DEPLOY.md](DEPLOY.md)  
**📋 Requerimientos:** [docs/REQUERIMIENTOS-COMPLETOS.md](docs/REQUERIMIENTOS-COMPLETOS.md)

---

## ✨ Características Principales

### 🌡️ Control Inteligente de AC
- Override del termostato interno con media de 5 sensores Zigbee
- Máquina de estados formal con 7 estados
- Control manual (forzar ON/OFF) con override del sistema
- Histéresis y cooldown para evitar ciclos rápidos

### ⚡ Tracking de Energía
- Consumo en kWh y coste en € (últimas 24h)
- Integración con API ESIOS para precios PVPC reales
- Gráficas interactivas (horarias y mensuales)
- Registros históricos (24h rolling + 365 días)

### 📱 Interface Web
- PWA moderna, mobile-first, responsive
- Gráficas Chart.js (temperatura, humedad, energía)
- Colores dinámicos por rangos
- Instalable en móvil como app nativa

### 🏠 Arquitectura
- Docker + Docker Compose
- Zigbee 3.0 (protocolo estándar, abierto)
- MQTT para comunicación entre servicios
- Persistencia completa: sensores, estado controlador, energía
- Recuperación automática tras reinicios (protección compresor)

---

## Índice

1. [Visión General](#visión-general)
2. [Requerimientos Globales](#requerimientos-globales)
3. [Infraestructura Base](#infraestructura-base)
4. [Fases del Proyecto](#fases-del-proyecto)
5. [Presupuesto](#presupuesto)
6. [Guía para futuras sesiones](#guía-para-futuras-sesiones)

---

## Visión General

Un servidor central (SBC) corre Docker y gestiona todos los servicios domóticos.
Los dispositivos se comunican vía Zigbee (protocolo estándar, abierto).
El control se hace desde una web PWA accesible tanto en local como en remoto.

El proyecto se desarrolla en fases incrementales. Cada fase:
- Tiene su propio documento de diseño en `docs/faseX-nombre.md`
- Añade funcionalidad sin romper las anteriores
- Puede requerir hardware adicional (documentado en la fase)

---

## Requerimientos Globales

Estos requerimientos aplican a TODAS las fases:

| # | Requerimiento | Categoría |
|---|---|---|
| G1 | Control desde teléfono móvil (iOS/Android) vía web PWA | UX |
| G2 | Acceso desde fuera de la red WiFi de casa (Tailscale VPN) | Acceso remoto |
| G3 | Web con diseño moderno, mobile-first, responsive | UX |
| G4 | Protocolos y dispositivos estándar (Zigbee 3.0) para facilitar añadir/quitar sin modificar código | Extensibilidad |
| G5 | Opción más económica dentro de las eficientes | Coste |
| G6 | Dispositivos comprables desde Madrid, España | Disponibilidad |
| G7 | Infraestructura expandible (Docker): añadir servicios = añadir contenedor | Extensibilidad |
| G8 | Resiliencia: si un sensor falla, el sistema sigue funcionando con los restantes | Resiliencia |
| G9 | Documentación completa para que cualquier sesión pueda continuar el trabajo | Mantenibilidad |

---

## Infraestructura Base

### Hardware compartido (todas las fases)

| Componente | Modelo exacto | Precio real | Estado |
|---|---|---|---|
| Servidor (SBC) | Raspberry Pi 5 (4GB) — Kit iRasptek | 180,99€ | ✅ Comprado (Amazon.es, jun 2026) |
| Coordinador Zigbee | SONOFF ZBDongle-E V2 (antena externa) | 15,19€ | ✅ Comprado |
| Alimentación | Fuente USB-C PD 27W (incluida en kit) | — | ✅ Incluido en kit |
| Almacenamiento | MicroSD 64GB (incluida en kit, OS Bookworm preinstalado) | — | ✅ Incluido en kit |
| Carcasa + cooler | iRasptek Active Cooler + carcasa (incluida en kit) | — | ✅ Incluido en kit |

**Total infraestructura base: ~196€** (kit Pi + dongle Zigbee)

### Decisión de servidor

La Raspberry Pi 4 tiene rotura de stock y precio excesivo. Alternativas evaluadas:

| Opción | RAM | CPU | Precio | Estado |
|---|---|---|---|---|
| ~~Raspberry Pi 4 (4GB)~~ | 4GB | 4x A72 1.5GHz | ~~65€~~ >100€ | Sin stock / inflado |
| **Raspberry Pi 5 (2GB)** ✓ | 2GB | 4x A76 2.4GHz | ~55€ | Disponible (RS Online, distribuidores EU) |
| Raspberry Pi 5 (4GB) | 4GB | 4x A76 2.4GHz | ~75-85€ | Disponible pero más caro |
| Orange Pi 3B (4GB) | 4GB | 4x A55 2.0GHz | ~50€ | Amazon.es (plan B) |

**Elección: Raspberry Pi 5 (4GB)** (ADR-011)
- CPU A76 2.4GHz, la más potente en SBC a este precio.
- 4GB da margen para domótica futura sin preocuparse por RAM.
- USB 3.0 para almacenamiento externo futuro.
- Ecosistema maduro: Docker, Zigbee2MQTT, Tailscale funcionan sin hacks.
- Precio: 180,99€ (kit completo iRasptek en Amazon.es, incluye Pi 5 4GB + fuente 27W + carcasa + cooler + SD 64GB).

### Software base

```
Raspberry Pi 5
├── Raspberry Pi OS Bookworm 64-bit (preinstalado en SD del kit)
├── Docker + Docker Compose
├── Tailscale (VPN mesh para acceso remoto)
│
└── docker-compose.yml
    ├── zigbee2mqtt       ← Lee todos los dispositivos Zigbee
    ├── mosquitto         ← Broker MQTT central
    ├── smart-home-app    ← Backend Python + Web UI (PWA)
    ├── tailscale         ← Acceso remoto (gratuito)
    └── ... (contenedores de cada fase)
```

### Arquitectura de la Web UI (G1, G2, G3)

Una **única PWA** sirve como panel de control unificado para todas las fases:

- **Stack**: FastAPI (Python backend) + Preact + Tailwind CSS (frontend)
- **Mobile-first**: diseñada para teléfono, responsive a desktop.
- **Instalable**: se añade a la pantalla de inicio como app nativa.
- **Acceso remoto**: vía Tailscale desde cualquier lugar (G2). Coste: 0€.
- **Modular**: cada fase añade una sección/tab al dashboard.

**Secciones del dashboard:**
- Inicio: resumen general (temperatura media, humedad, estado AC)
- Por fase: cada fase tiene su propia pestaña con controles específicos
- Configuración: ajustes globales, sensores registrados, estado de servicios

---

## Project Structure

### ⚠️ Data Directory Rule

**ALL runtime files and configuration files MUST be generated in `/data/`**

The ONLY exception is `.env` which remains in the project root for Docker Compose compatibility.

```
smart-home/
├── infrastructure/          # Service configurations (in git)
│   ├── mosquitto/
│   │   └── mosquitto.conf
│   └── zigbee2mqtt/
│       └── config/
│           ├── configuration.example.yaml
│           └── README.md
├── data/                    # ALL runtime data (NOT in git)
│   ├── backend/             # Backend data files
│   ├── mosquitto/           # MQTT broker data & logs
│   └── zigbee2mqtt/         # Zigbee config, database, logs
├── src/                     # Source code (in git)
│   └── backend/
│       └── *.py
├── .env                     # Environment variables (ONLY exception to data/ rule)
└── docker-compose.yml
```

**Why this structure?**
- **Centralized backups**: Just backup `/data/`
- **Clean repository**: Only source code in git  
- **Docker best practice**: Data separate from application
- **Easy deployment**: Clone repo + add .env + restore /data/

See `/data/README.md` for more details.

---

## Fases del Proyecto

| Fase | Nombre | Descripción | Requerimientos | Estado |
|---|---|---|---|---|
| 0 | [AC Override](#fase-0-ac-thermostat-override) | Control inteligente del AC + tracking energético | 30 (F0.0-F0.30) | ✅ 29/30 implementados |
| 1 | [Control Humedad](#fase-1-control-de-humedad) | Humidificadores inteligentes con control automático | - | 📝 Diseño |
| 2 | [Backup Fotos](#fase-2-backup-de-fotos) | Sync automático de fotos de 2 Android | - | 📝 Diseño |
| N | [Futuras](#añadir-nuevas-fases) | Cualquier servicio domótico adicional | - | - |

---

### Fase 0: AC Thermostat Override

**Documento detallado:** `docs/fase0-ac-override.md`

**Problema:** El termostato interno del AC (Mitsubishi PEAD-SM71JA, S/N 3XM10399) recibe
aire frío directamente y se apaga antes de enfriar la casa.

**Solución:** Usar la media de 5 sensores de temperatura repartidos por la casa como
referencia real. Forzar al AC (vía MELCloud API) a seguir enfriando hasta alcanzar el
objetivo real.

**Requerimientos específicos:**

#### Control de Temperatura (F0.1 - F0.23)

| # | Requerimiento | Estado |
|---|---|---|
| F0.1 | Sobreescribir termostato interno usando media de 5 sensores externos | ✅ |
| F0.2 | Soportar 5 sensores: 3 habitaciones + salón + despacho | ✅ |
| F0.3 | Temperatura de referencia = media aritmética de sensores activos | ✅ |
| F0.4 | Control del AC vía MELCloud API (WiFi adapter oficial ya instalado) | ✅ |
| F0.5 | Si un sensor falla, media con los restantes | ✅ |
| F0.6 | POC virtualizado antes de comprar hardware | ✅ |
| F0.7 | Histéresis y cooldown (5 min) para evitar ciclos rápidos | ✅ |
| F0.8 | Log de acciones del controlador | ✅ |
| F0.9 | Acceso desde cualquier dispositivo en la red local | ✅ |
| F0.10 | Colores por rango de temperatura y humedad | ✅ |
| F0.11 | Mostrar temperatura exterior (Madrid, Open-Meteo API) | ✅ |
| F0.12 | Límites de temperatura objetivo (19-30°C) | ✅ |
| F0.13 | Máquina de estados formal (7 estados) | ✅ |
| F0.14-F0.17 | UI moderna mobile-first con estado real del AC | ✅ |
| F0.18 | Persistencia de lecturas de sensores | ✅ |
| F0.19 | Criterio de conexión (timeout 1 hora) | ✅ |
| F0.20 | Limpieza automática de logs | ✅ |
| F0.21 | Mostrar decisión del controlador en tiempo real | ✅ |
| F0.22 | Popups de control manual (forzar ON/OFF) | ✅ |
| F0.23 | Deployment en Raspberry Pi | ⏳ Pendiente |

#### Seguimiento Energético (F0.24 - F0.30)

| # | Requerimiento | Estado |
|---|---|---|
| F0.24 | Widget de consumo energético (24h) con kWh y coste en € | ✅ |
| F0.25 | API ESIOS para precios PVPC (energía regulada España) | ✅ |
| F0.26 | Registro horario de consumo (JSON con 24 valores rolling) | ✅ |
| F0.27 | Registro diario de consumo (JSON con hasta 365 valores rolling) | ✅ |
| F0.28 | Popup de estadísticas con 2 gráficas (horaria y mensual) | ✅ |
| F0.29 | Coste calculado con precio exacto del momento de consumo | ✅ |
| F0.30 | Optimización con acumuladores en memoria | ✅ |

**Funcionalidades implementadas:**
- ✅ Control inteligente del AC con máquina de estados
- ✅ Interface web PWA responsive y moderna
- ✅ **Persistencia de estado del controlador** (minimiza ciclos AC, protege compresor)
- ✅ Persistencia de datos de sensores entre reinicios
- ✅ Tracking de energía con coste en tiempo real
- ✅ Gráficas interactivas (temperatura, humedad, energía)
- ✅ Control manual con override del sistema automático
- ✅ Integración con API ESIOS para precios PVPC
- ✅ Scheduler automático (registros horarios y diarios)

**Hardware adicional fase 0:**

| Componente | Modelo exacto | Cant. | Precio real | Estado |
|---|---|---|---|---|
| Sensor temperatura/humedad | SONOFF SNZB-02D (Zigbee 3.0, pantalla LCD) | 5 | 42,70€ (8,54€/ud) | ✅ Comprado |

**Lógica de control:**

```
Cada 45 segundos:
  temps = [leer sensores activos via MQTT]
  media = promedio(temps)

  Si media > objetivo + 0.5°C → AC ON, consigna 19°C, fan=max (forzar enfriamiento)
  Si objetivo - 0.3°C < media < objetivo + 0.5°C → AC ON, consigna proporcional (19-30°C)
  Si media ≤ objetivo - 0.3°C → AC OFF (con cooldown 5 min antes de re-encender)
```

**Tracking de energía:**

```
Transiciones de estado → Calcular consumo (potencia × tiempo)
Cada hora (:00) → Registrar kWh + obtener precio ESIOS + calcular coste
Cada día (00:00) → Registrar total diario
Widget → Mostrar últimas 24h (kWh + €)
Popup → Gráficas horarias (24h) y mensuales (12 meses)
```

**Documentación técnica:**
- Diseño: `docs/DISEÑO-ENERGIA-F0.md`
- Implementación: `docs/IMPLEMENTACION-ENERGIA-COMPLETA.md`
- Requerimientos completos: `docs/REQUERIMIENTOS-COMPLETOS.md`
- Persistencia de estado: `docs/STATE_PERSISTENCE.md` ⭐ **NEW**

**Coste fase 0: ~42,70€** (sensores) + infraestructura base

---

### Fase 1: Control de Humedad

**Documento detallado:** `docs/fase1-control-humedad.md`

**Objetivo:** Mantener la humedad de la casa en un rango saludable (40-60%) usando
humidificadores controlados automáticamente por el sistema.

**Requerimientos específicos:**

| # | Requerimiento |
|---|---|
| F1.1 | Medir humedad en las mismas 5 zonas (ya cubierto: los SNZB-02D miden humedad) |
| F1.2 | Controlar humidificadores on/off vía Zigbee |
| F1.3 | Lógica automática: si humedad media < umbral → encender humidificadores |
| F1.4 | Los humidificadores deben cubrir toda la casa |
| F1.5 | Los dispositivos de control (enchufes) deben ser Zigbee estándar |

**Estrategia:**
- Los **sensores de humedad ya existen** (fase 0): los SONOFF SNZB-02D miden temperatura Y humedad.
- Se necesitan **enchufes inteligentes Zigbee** para encender/apagar humidificadores convencionales.
- Se necesitan **humidificadores evaporativos** (los más eficientes y seguros) conectados a los enchufes.

**¿Por qué enchufe Zigbee + humidificador normal?**
- Los humidificadores "inteligentes" (WiFi/Zigbee nativos) son caros y pocos son estándar.
- Un humidificador evaporativo normal + enchufe Zigbeew = control inteligente por 1/3 del precio.
- El humidificador se enciende/apaga vía enchufe. La lógica la pone nuestro sistema.
- Si el humidificador se rompe, lo cambias por cualquier otro (no estás atado a un modelo smart).

**Hardware adicional fase 1:**

| Componente | Modelo | Cant. | Precio aprox. |
|---|---|---|---|
| Enchufe Zigbee (tipo F, EU) | SONOFF S26R2ZB | 2-3 | ~15€/ud = 30-45€ |
| Humidificador evaporativo | Cualquier modelo 3-5L, >150ml/h | 2-3 | ~30-50€/ud = 60-150€ |

**Nota sobre cantidad de humidificadores:**
- Para una casa estándar (80-120m²) con aire acondicionado (que reseca), 2-3 humidificadores
  repartidos en zonas principales (salón + pasillo/zona noche) suelen ser suficientes.
- La decisión final depende del layout concreto de la casa.

**Lógica de control:**

```
Cada 60 segundos:
  humedades = [leer sensores activos via MQTT]
  media_humedad = promedio(humedades)

  Si media_humedad < 40% → Enchufes humidificadores ON
  Si media_humedad > 55% → Enchufes humidificadores OFF
  (histéresis para evitar ciclos rápidos)
```

**Coste fase 1: ~90-195€** (enchufes + humidificadores)

---

### Fase 2: Backup de Fotos

**Documento detallado:** `docs/fase2-backup-fotos.md`

**Objetivo:** Backup automático de fotos de 2 teléfonos Android al servidor central,
permitiendo liberar espacio en los teléfonos con seguridad.

**Requerimientos específicos:**

| # | Requerimiento |
|---|---|
| F2.1 | Sincronización automática de fotos de 2 Android al servidor |
| F2.2 | La copia es unidireccional: teléfono → servidor (no al revés) |
| F2.3 | Borrar en el teléfono no borra en el servidor |
| F2.4 | Funcionar automáticamente cuando el teléfono está en WiFi |
| F2.5 | Estándar y ligero (no requiere mucha RAM/CPU) |

**Solución: Syncthing**
- Open-source, P2P, sin nube.
- App Android gratuita (Syncthing-Fork en F-Droid/Play Store).
- Contenedor Docker en el servidor.
- Consume ~50-100MB RAM.
- Configuración "Send Only" en teléfonos, "Receive Only" en servidor.

**Hardware adicional fase 2:**

| Componente | Modelo | Precio aprox. |
|---|---|---|
| SSD externo USB | Kingston XS1000 256GB (o 1TB) | 35-70€ |

**Coste fase 2: ~35-70€** (solo el SSD)

---

### Añadir nuevas fases

Para añadir una fase N al proyecto:

1. Crear `docs/faseN-nombre.md` con:
   - Problema/objetivo
   - Requerimientos específicos (F{N}.1, F{N}.2, ...)
   - Hardware adicional necesario
   - Lógica/diseño
   - Impacto en la infraestructura (nuevo contenedor Docker, nuevo dispositivo Zigbee, etc.)

2. Actualizar la tabla de fases en este README.

3. Añadir el contenedor correspondiente a `docker-compose.yml`.

4. Añadir la sección/tab correspondiente a la Web UI.

**Ejemplos de fases futuras posibles:**
- Control de iluminación (bombillas Zigbee)
- Pi-hole (bloqueo publicidad a nivel DNS)
- Monitorización de consumo eléctrico
- Riego automático
- Alarma/sensores de presencia
- Control de persianas motorizadas

---

## Presupuesto

### Desglose por fase

| Concepto | Precio |
|---|---|
| **Infraestructura base** (kit Pi 5 + Zigbee dongle) | **196€** |
| **Fase 0** (5 sensores temperatura) | **42,70€** |
| **Fase 1** (2-3 enchufes + 2-3 humidificadores) | **90-195€** |
| **Fase 2** (SSD externo) | **35-70€** |

### Totales

| Escenario | Total |
|---|---|
| Solo Fase 0 (AC override) | **~239€** |
| Fases 0 + 1 (AC + humedad) | **~329-434€** |
| Fases 0 + 1 + 2 (todo) | **~364-504€** |

> **Software gratuito en todas las fases:** Tailscale (VPN), Zigbee2MQTT, Mosquitto, Docker,
> Syncthing, Preact, Tailwind CSS, FastAPI. Sin suscripciones ni costes recurrentes.

---

## Guía para futuras sesiones

### Estructura del repositorio

```
smart-home/
├── README.md                    ← Este archivo (visión global, fases, presupuesto)
├── docs/
│   ├── fase0-ac-override.md     ← Diseño detallado fase 0
│   ├── fase1-control-humedad.md ← Diseño detallado fase 1
│   ├── fase2-backup-fotos.md    ← Diseño detallado fase 2
│   ├── REQUERIMIENTOS-COMPLETOS.md ← Lista completa de 30 requerimientos
│   ├── DISEÑO-ENERGIA-F0.md     ← Diseño sistema de energía
│   ├── IMPLEMENTACION-ENERGIA-COMPLETA.md ← Guía implementación energía
│   └── decisiones.md            ← Registro de decisiones de diseño (ADR)
├── infrastructure/
│   ├── docker-compose.yml       ← Todos los servicios
│   ├── tailscale/               ← Config Tailscale
│   ├── zigbee2mqtt/             ← Config Zigbee2MQTT
│   └── mosquitto/               ← Config Mosquitto
├── src/
│   ├── backend/                 ← FastAPI app (lógica de todas las fases)
│   │   ├── main.py
│   │   ├── melcloud_client.py
│   │   ├── mqtt_handler.py
│   │   ├── state_persistence.py ← Persistencia estado controlador ⭐ NEW
│   │   ├── controllers/
│   │   │   ├── ac_controller.py
│   │   │   ├── state_machine.py
│   │   │   └── ...
│   │   ├── energy/              ← Módulo de tracking energético
│   │   │   ├── esios_client.py  ← Cliente API ESIOS (precios PVPC)
│   │   │   └── tracker.py       ← Tracker de consumo y coste
│   │   ├── api/
│   │   │   └── routes.py        ← Endpoints REST (incl. /api/energy/*)
│   │   ├── static/
│   │   │   └── index.html       ← PWA frontend con gráficas Chart.js
│   │   └── config.py
├── poc/                         ← Proof of Concept (virtualizado)
│   ├── mock_sensors.py
│   ├── mock_melcloud.py
│   └── docker-compose.poc.yml
└── config.example.yaml          ← Configuración de ejemplo
```

### Cómo continuar el trabajo en una nueva sesión

1. **Leer este README** para contexto general.
2. **Leer `docs/decisiones.md`** para entender las decisiones ya tomadas.
3. **Leer la fase específica** en `docs/faseX-nombre.md` para el detalle.
4. **Ver el estado actual** del código en `src/` y `infrastructure/`.
5. **El POC** está en `poc/` y puede ejecutarse para validar cambios.

### Convenciones

- **Requerimientos globales**: G1, G2, G3...
- **Requerimientos por fase**: F{N}.1, F{N}.2... (ej: F0.1, F1.3)
- **Decisiones de diseño**: documentadas en `docs/decisiones.md` con fecha y contexto.
- **Config**: todo configurable vía YAML sin tocar código.
- **Comunicación entre servicios**: MQTT (topic pattern: `zigbee2mqtt/{device_name}`)
- **Control de dispositivos**: publicar en MQTT topics de Zigbee2MQTT.

### Información del AC

- **Modelo**: Mitsubishi PEAD-SM71JA
- **Serial**: 3XM10399
- **Control**: MELCloud API (WiFi adapter oficial instalado)
- **Rango consigna**: 16°C - 31°C
- **API endpoint principal**: `POST /Mitsubishi.Wifi.Client/Device/SetAta`

### Stack Tecnológico Fase 0

**Backend:**
- Python 3.12
- FastAPI + Uvicorn
- Paho-MQTT (comunicación con sensores)
- httpx (cliente HTTP async)
- APScheduler (jobs horarios/diarios para energía)

**Frontend:**
- HTML + JavaScript vanilla
- Tailwind CSS (diseño)
- Chart.js (gráficas)
- PWA (instalable en móvil)

**Infraestructura:**
- Docker + Docker Compose
- Zigbee2MQTT (gateway Zigbee → MQTT)
- Eclipse Mosquitto (broker MQTT)
- Volúmenes Docker para persistencia

**APIs Externas:**
- MELCloud API (control AC)
- Open-Meteo API (temperatura exterior)
- ESIOS API (precios PVPC energía regulada España)

### Métricas del Proyecto (Fase 0)

- **Requerimientos totales:** 30 (29 implementados ✅, 1 pendiente ⏳)
- **Archivos Python:** 15+
- **Tests unitarios:** 53 (state_machine)
- **Endpoints API:** 15+
- **Estados del controlador:** 7
- **Sensores Zigbee:** 5
- **Gráficas en UI:** 4 (temp, humedad, energía horaria, energía mensual)
- **JSON de persistencia:** 7 (sensores, outdoor, estado controlador, energía 24h/diaria)
- **Volúmenes Docker:** 2

---

## Siguiente paso

**Despliegue en Raspberry Pi 5:**

Ver guía completa en [DEPLOY.md](DEPLOY.md)

**Resumen rápido:**

```bash
# 1. Clonar repositorio
git clone https://github.com/EgnalZurc/smart-home.git
cd smart-home

# 2. Configurar credenciales
cp .env.example .env
nano .env  # Editar con tus credenciales MELCloud

# 3. Iniciar servicios (construye imagen localmente)
docker-compose up -d --build

# 4. Acceder a la web UI
http://<IP_DE_LA_RASPBERRY>:8080
```

---

## 🔗 Enlaces Útiles

- **Repositorio GitHub:** https://github.com/EgnalZurc/smart-home
- **Guía de Despliegue:** [DEPLOY.md](DEPLOY.md)
- **Estructura Docker:** [DOCKER.md](DOCKER.md) ⭐ **NEW**
- **Inicio Rápido:** [QUICKSTART.md](QUICKSTART.md)
- **Requerimientos Completos:** [docs/REQUERIMIENTOS-COMPLETOS.md](docs/REQUERIMIENTOS-COMPLETOS.md)
- **Diseño Fase 0:** [docs/fase0-ac-override.md](docs/fase0-ac-override.md)

---

## 📝 Licencia

MIT License - Ver [LICENSE](LICENSE) para más detalles.

---

**Última actualización:** 22 de junio de 2026  
**Estado:** Fase 0 completa (29/30 requerimientos implementados)  
**Mantenedor:** [@EgnalZurc](https://github.com/EgnalZurc)
