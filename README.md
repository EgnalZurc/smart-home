# Smart Home Control System

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![Docker](https://img.shields.io/badge/docker-ready-blue.svg)](docker-compose.yml)

Modular and expandable home automation system developed in phases. Intelligent air conditioning control with Zigbee sensors, accessible from a modern PWA.

**🚀 Demo:** _Coming soon_  
**⚡ Quick Start:** [QUICKSTART.md](QUICKSTART.md)  
**📖 Deployment Guide:** [DEPLOY.md](DEPLOY.md)  
**📋 Requirements:** [.kiro/docs/REQUIREMENTS.md](.kiro/docs/REQUIREMENTS.md)

---

## ✨ Main Features

### 🌡️ Intelligent AC Control
- Override internal thermostat with average of 5 Zigbee sensors
- Formal state machine with 7 states
- Manual control (force ON/OFF) with system override
- Hysteresis and cooldown to avoid rapid cycles

### 📱 Web Interface
- Modern PWA, mobile-first, responsive
- Chart.js graphs (temperature, humidity)
- Dynamic colors by ranges
- Installable on mobile as native app

### 🏠 Architecture
- Docker + Docker Compose
- Zigbee 3.0 (standard, open protocol)
- MQTT for inter-service communication
- Complete persistence: sensors, controller state
- Automatic recovery after restarts (compressor protection)

---

## Table of Contents

1. [Overview](#overview)
2. [Global Requirements](#global-requirements)
3. [Base Infrastructure](#base-infrastructure)
4. [Project Phases](#project-phases)
5. [Budget](#budget)
6. [Guide for Future Sessions](#guide-for-future-sessions)

---

## Overview

A central server (SBC) runs Docker and manages all home automation services.
Devices communicate via Zigbee (standard, open protocol).
Control is done from a PWA web interface accessible both locally and remotely.

The project is developed in incremental phases. Each phase:
- Has its own design document in `docs/phaseX-name.md`
- Adds functionality without breaking previous ones
- May require additional hardware (documented in the phase)

---

## Global Requirements

These requirements apply to ALL phases:

| # | Requirement | Category |
|---|---|---|
| G1 | Control from mobile phone (iOS/Android) via PWA web | UX |
| G2 | Access from outside home WiFi (Tailscale VPN) | Remote access |
| G3 | Modern web design, mobile-first, responsive | UX |
| G4 | Standard protocols and devices (Zigbee 3.0) to easily add/remove without code changes | Extensibility |
| G5 | Most economical option among efficient ones | Cost |
| G6 | Devices purchasable from Madrid, Spain | Availability |
| G7 | Expandable infrastructure (Docker): add services = add container | Extensibility |
| G8 | Resilience: if a sensor fails, system continues with remaining ones | Resilience |
| G9 | Complete documentation so any session can continue work | Maintainability |

---

## Base Infrastructure

### Shared hardware (all phases)

| Component | Exact model | Real price | Status |
|---|---|---|---|
| Server (SBC) | Raspberry Pi 5 (4GB) — iRasptek Kit | €180.99 | ✅ Purchased (Amazon.es, Jun 2026) |
| Zigbee Coordinator | SONOFF ZBDongle-E V2 (external antenna) | €15.19 | ✅ Purchased |
| Power supply | USB-C PD 27W power supply (included in kit) | — | ✅ Included in kit |
| Storage | MicroSD 64GB (included in kit, Bookworm OS preinstalled) | — | ✅ Included in kit |
| Case + cooler | iRasptek Active Cooler + case (included in kit) | — | ✅ Included in kit |

**Total base infrastructure: ~€196** (Pi kit + Zigbee dongle)

### Server decision

Raspberry Pi 4 has stock shortage and excessive price. Evaluated alternatives:

| Option | RAM | CPU | Price | Status |
|---|---|---|---|---|
| ~~Raspberry Pi 4 (4GB)~~ | 4GB | 4x A72 1.5GHz | ~~€65~~ >€100 | Out of stock / inflated |
| **Raspberry Pi 5 (2GB)** ✓ | 2GB | 4x A76 2.4GHz | ~€55 | Available (RS Online, EU distributors) |
| Raspberry Pi 5 (4GB) | 4GB | 4x A76 2.4GHz | ~€75-85 | Available but more expensive |
| Orange Pi 3B (4GB) | 4GB | 4x A55 2.0GHz | ~€50 | Amazon.es (plan B) |

**Choice: Raspberry Pi 5 (4GB)** (ADR-011)
- A76 2.4GHz CPU, most powerful in SBC at this price.
- 4GB gives margin for future home automation without RAM concerns.
- USB 3.0 for future external storage.
- Mature ecosystem: Docker, Zigbee2MQTT, Tailscale work without hacks.
- Price: €180.99 (complete iRasptek kit on Amazon.es, includes Pi 5 4GB + 27W power supply + case + cooler + 64GB SD).

### Base software

```
Raspberry Pi 5
├── Raspberry Pi OS Bookworm 64-bit (preinstalled on kit SD)
├── Docker + Docker Compose
├── Tailscale (mesh VPN for remote access)
│
└── docker-compose.yml
    ├── zigbee2mqtt       ← Reads all Zigbee devices
    ├── mosquitto         ← Central MQTT broker
    ├── smart-home-app    ← Python backend + Web UI (PWA)
    ├── tailscale         ← Remote access (free)
    └── ... (containers for each phase)
```

### Web UI Architecture (G1, G2, G3)

A **single PWA** serves as unified control panel for all phases:

- **Stack**: FastAPI (Python backend) + vanilla JavaScript (frontend) + Tailwind CSS
- **Mobile-first**: designed for phone, responsive to desktop.
- **Installable**: adds to home screen as native app.
- **Remote access**: via Tailscale from anywhere (G2). Cost: €0.
- **Modular**: each phase adds a section/tab to dashboard.

**Dashboard sections:**
- Home: general summary (average temperature, humidity, AC status)
- Per phase: each phase has its own tab with specific controls
- Settings: global settings, registered sensors, service status

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

## Project Phases

| Phase | Name | Description | Requirements | Status |
|---|---|---|---|---|
| 0 | [AC Override](#phase-0-ac-thermostat-override) | Intelligent AC control | 30 (F0.0-F0.30) | ✅ Implemented |
| 1 | [Humidity Control](#phase-1-humidity-control) | Smart humidifiers with automatic control | - | 📝 Design |
| 2 | [Photo Backup](#phase-2-photo-backup) | Auto sync photos from 2 Android phones | - | 📝 Design |
| N | [Future](#adding-new-phases) | Any additional home automation service | - | - |

---

### Phase 0: AC Thermostat Override

**Detailed document:** `.kiro/docs/REQUIREMENTS.md`

**Problem:** Internal AC thermostat (Mitsubishi PEAD-SM71JA, S/N 3XM10399) receives
cold air directly and turns off before cooling the house.

**Solution:** Use average of 5 temperature sensors distributed throughout the house as
real reference. Force AC (via MELCloud API) to continue cooling until reaching real
target.

**Specific requirements:**

#### Temperature Control (F0.1 - F0.23)

| # | Requirement | Status |
|---|---|---|
| F0.1 | Override internal thermostat using average of 5 external sensors | ✅ |
| F0.2 | Support 5 sensors: 3 bedrooms + living room + office | ✅ |
| F0.3 | Reference temperature = arithmetic mean of active sensors | ✅ |
| F0.4 | AC control via MELCloud API (official WiFi adapter already installed) | ✅ |
| F0.5 | If one sensor fails, average with remaining ones | ✅ |
| F0.6 | Virtualized POC before buying hardware | ✅ |
| F0.7 | Hysteresis and cooldown (5 min) to avoid rapid cycles | ✅ |
| F0.8 | Controller action log | ✅ |
| F0.9 | Access from any device on local network | ✅ |
| F0.10 | Colors by temperature and humidity ranges | ✅ |
| F0.11 | Show outdoor temperature (Madrid, Open-Meteo API) | ✅ |
| F0.12 | Target temperature limits (19-30°C) | ✅ |
| F0.13 | Formal state machine (7 states) | ✅ |
| F0.14-F0.17 | Modern mobile-first UI with real AC status | ✅ |
| F0.18 | Sensor readings persistence | ✅ |
| F0.19 | Connection criteria (1 hour timeout) | ✅ |
| F0.20 | Automatic log cleanup | ✅ |
| F0.21 | Show controller decision in real-time | ✅ |
| F0.22 | Manual control popups (force ON/OFF) | ✅ |
| F0.23 | Deployment on Raspberry Pi | ✅ |

**Implemented features:**
- ✅ Intelligent AC control with state machine
- ✅ Modern responsive PWA web interface
- ✅ **Controller state persistence** (minimizes AC cycles, protects compressor)
- ✅ Sensor data persistence between restarts
- ✅ Interactive graphs (temperature, humidity)
- ✅ Manual control with automatic system override
- ✅ Automatic scheduler (hourly and daily records)
- ✅ **Internationalization (i18n)** - English/Spanish support

**Additional hardware phase 0:**

| Component | Exact model | Qty. | Real price | Status |
|---|---|---|---|---|
| Temperature/humidity sensor | SONOFF SNZB-02D (Zigbee 3.0, LCD display) | 5 | €42.70 (€8.54/unit) | ✅ Purchased |

**Control logic:**

```
Every 45 seconds:
  temps = [read active sensors via MQTT]
  average = mean(temps)

  If average > target + 0.5°C → AC ON, setpoint 19°C, fan=max (force cooling)
  If target - 0.3°C < average < target + 0.5°C → AC ON, proportional setpoint (19-30°C)
  If average ≤ target - 0.3°C → AC OFF (with 5 min cooldown before re-enabling)
```

**Technical documentation:**
- Requirements: `.kiro/docs/REQUIREMENTS.md`
- State persistence: `.kiro/docs/STATE_PERSISTENCE.md` ⭐ **NEW**
- i18n implementation: `.kiro/docs/I18N_PHASE1_COMPLETE.md`, `.kiro/docs/I18N_PHASE2_COMPLETE.md`

**Phase 0 cost: ~€42.70** (sensors) + base infrastructure

---

### Phase 1: Humidity Control

**Detailed document:** `docs/phase1-humidity-control.md` (to be created)

**Objective:** Maintain house humidity in healthy range (40-60%) using
humidifiers automatically controlled by the system.

**Specific requirements:**

| # | Requirement |
|---|---|
| F1.1 | Measure humidity in same 5 zones (already covered: SNZB-02D measure humidity) |
| F1.2 | Control on/off humidifiers via Zigbee |
| F1.3 | Automatic logic: if average humidity < threshold → turn on humidifiers |
| F1.4 | Humidifiers must cover entire house |
| F1.5 | Control devices (smart plugs) must be standard Zigbee |

**Strategy:**
- **Humidity sensors already exist** (phase 0): SONOFF SNZB-02D measure temperature AND humidity.
- Need **Zigbee smart plugs** to turn on/off conventional humidifiers.
- Need **evaporative humidifiers** (most efficient and safe) connected to plugs.

**Why Zigbee plug + normal humidifier?**
- "Smart" humidifiers (WiFi/Zigbee native) are expensive and few are standard.
- Normal evaporative humidifier + Zigbee plug = smart control for 1/3 the price.
- Humidifier turns on/off via plug. Our system provides the logic.
- If humidifier breaks, replace it with any other (not tied to a smart model).

**Additional hardware phase 1:**

| Component | Model | Qty. | Approx. price |
|---|---|---|---|
| Zigbee plug (type F, EU) | SONOFF S26R2ZB | 2-3 | ~€15/unit = €30-45 |
| Evaporative humidifier | Any model 3-5L, >150ml/h | 2-3 | ~€30-50/unit = €60-150 |

**Control logic:**

```
Every 60 seconds:
  humidities = [read active sensors via MQTT]
  average_humidity = mean(humidities)

  If average_humidity < 40% → Humidifier plugs ON
  If average_humidity > 55% → Humidifier plugs OFF
  (hysteresis to avoid rapid cycles)
```

**Phase 1 cost: ~€90-195** (plugs + humidifiers)

---

### Phase 2: Photo Backup

**Detailed document:** `docs/phase2-photo-backup.md` (to be created)

**Objective:** Automatic photo backup from 2 Android phones to central server,
allowing phone storage to be freed safely.

**Specific requirements:**

| # | Requirement |
|---|---|
| F2.1 | Automatic photo sync from 2 Android to server |
| F2.2 | Copy is unidirectional: phone → server (not reverse) |
| F2.3 | Deleting on phone doesn't delete on server |
| F2.4 | Work automatically when phone is on WiFi |
| F2.5 | Standard and lightweight (doesn't require much RAM/CPU) |

**Solution: Syncthing**
- Open-source, P2P, no cloud.
- Free Android app (Syncthing-Fork on F-Droid/Play Store).
- Docker container on server.
- Consumes ~50-100MB RAM.
- "Send Only" configuration on phones, "Receive Only" on server.

**Additional hardware phase 2:**

| Component | Model | Approx. price |
|---|---|---|
| External USB SSD | Kingston XS1000 256GB (or 1TB) | €35-70 |

**Phase 2 cost: ~€35-70** (only the SSD)

---

### Adding New Phases

To add phase N to the project:

1. Create `docs/phaseN-name.md` with:
   - Problem/objective
   - Specific requirements (F{N}.1, F{N}.2, ...)
   - Additional hardware needed
   - Logic/design
   - Infrastructure impact (new Docker container, new Zigbee device, etc.)

2. Update phase table in this README.

3. Add corresponding container to `docker-compose.yml`.

4. Add corresponding section/tab to Web UI.

**Examples of possible future phases:**
- Lighting control (Zigbee bulbs)
- Pi-hole (DNS-level ad blocking)
- Electrical consumption monitoring
- Automatic irrigation
- Alarm/presence sensors
- Motorized blind control

---

## Budget

### Breakdown by phase

| Concept | Price |
|---|---|
| **Base infrastructure** (Pi 5 kit + Zigbee dongle) | **€196** |
| **Phase 0** (5 temperature sensors) | **€42.70** |
| **Phase 1** (2-3 plugs + 2-3 humidifiers) | **€90-195** |
| **Phase 2** (external SSD) | **€35-70** |

### Totals

| Scenario | Total |
|---|---|
| Only Phase 0 (AC override) | **~€239** |
| Phases 0 + 1 (AC + humidity) | **~€329-434** |
| Phases 0 + 1 + 2 (all) | **~€364-504** |

> **Free software in all phases:** Tailscale (VPN), Zigbee2MQTT, Mosquitto, Docker,
> Syncthing, Tailwind CSS, FastAPI. No subscriptions or recurring costs.

---

## Guide for Future Sessions

### Repository structure

```
smart-home/
├── README.md                    ← This file (global vision, phases, budget)
├── .kiro/docs/
│   ├── REQUIREMENTS.md          ← Complete requirements list
│   ├── STATE_PERSISTENCE.md     ← Controller state persistence
│   ├── I18N_*.md                ← Internationalization docs
│   └── ...                      ← Other technical docs
├── infrastructure/
│   ├── docker-compose.yml       ← All services
│   ├── tailscale/               ← Tailscale config
│   ├── zigbee2mqtt/             ← Zigbee2MQTT config
│   └── mosquitto/               ← Mosquitto config
├── src/
│   └── backend/                 ← FastAPI app (logic for all phases)
│       ├── main.py
│       ├── melcloud_client.py
│       ├── mqtt_handler.py
│       ├── state_persistence.py ← Controller state persistence ⭐ NEW
│       ├── controllers/
│       │   ├── ac_controller.py
│       │   ├── state_machine.py
│       │   └── ...
│       ├── api/
│       │   └── routes.py        ← REST endpoints
│       ├── static/
│       │   ├── index.html       ← PWA frontend
│       │   ├── i18n.js          ← i18n translation engine ⭐ NEW
│       │   └── locales/         ← Translation files (en.json, es.json) ⭐ NEW
│       └── config.py
└── config.example.yaml          ← Example configuration
```

### How to continue work in a new session

1. **Read this README** for general context.
2. **Read `.kiro/docs/REQUIREMENTS.md`** to understand implemented requirements.
3. **See current code status** in `src/` and `infrastructure/`.

### Conventions

- **Global requirements**: G1, G2, G3...
- **Requirements per phase**: F{N}.1, F{N}.2... (e.g.: F0.1, F1.3)
- **Config**: everything configurable via env vars without touching code.
- **Inter-service communication**: MQTT (topic pattern: `zigbee2mqtt/{device_name}`)
- **Device control**: publish to Zigbee2MQTT MQTT topics.

### AC Information

- **Model**: Mitsubishi PEAD-SM71JA
- **Serial**: 3XM10399
- **Control**: MELCloud API (official WiFi adapter installed)
- **Setpoint range**: 16°C - 31°C
- **Main API endpoint**: `POST /Mitsubishi.Wifi.Client/Device/SetAta`

### Phase 0 Tech Stack

**Backend:**
- Python 3.12
- FastAPI + Uvicorn
- Paho-MQTT (sensor communication)
- httpx (async HTTP client)

**Frontend:**
- HTML + JavaScript vanilla
- Tailwind CSS (design)
- Chart.js (graphs)
- PWA (installable on mobile)

**Infrastructure:**
- Docker + Docker Compose
- Zigbee2MQTT (Zigbee → MQTT gateway)
- Eclipse Mosquitto (MQTT broker)
- Docker volumes for persistence

**External APIs:**
- MELCloud API (AC control)
- Open-Meteo API (outdoor temperature)

### Project Metrics (Phase 0)

- **Total requirements:** 30 (30 implemented ✅)
- **Python files:** 15+
- **Unit tests:** 53 (state_machine)
- **API endpoints:** 15+
- **Controller states:** 7
- **Zigbee sensors:** 5
- **UI graphs:** 2 (temp, humidity)
- **JSON persistence files:** 4 (sensors, outdoor, controller state, sensor history)
- **Docker volumes:** 2
- **Supported languages:** 2 (English, Spanish)

---

## Next Step

**Deploy on Raspberry Pi 5:**

See complete guide in [DEPLOY.md](DEPLOY.md)

**Quick summary:**

```bash
# 1. Clone repository
git clone https://github.com/EgnalZurc/smart-home.git
cd smart-home

# 2. Configure credentials
cp .env.example .env
nano .env  # Edit with your MELCloud credentials

# 3. Start services (builds image locally)
docker-compose up -d --build

# 4. Access web UI
http://<RASPBERRY_IP>:8080
```

---

## 🔗 Useful Links

- **GitHub Repository:** https://github.com/EgnalZurc/smart-home
- **Deployment Guide:** [DEPLOY.md](DEPLOY.md)
- **Docker Structure:** [DOCKER.md](DOCKER.md)
- **Quick Start:** [QUICKSTART.md](QUICKSTART.md)
- **Complete Requirements:** [.kiro/docs/REQUIREMENTS.md](.kiro/docs/REQUIREMENTS.md)
- **State Persistence:** [.kiro/docs/STATE_PERSISTENCE.md](.kiro/docs/STATE_PERSISTENCE.md)

---

## 📝 License

MIT License - See [LICENSE](LICENSE) for details.

---

**Last update:** June 24, 2026  
**Status:** Phase 0 complete (30/30 requirements implemented)  
**Maintainer:** [@EgnalZurc](https://github.com/EgnalZurc)
