# Análisis de Recursos: Docker + Servicios

## Consumo de RAM estimado por servicio

Datos basados en mediciones reales reportadas por la comunidad (GitHub issues, foros,
documentación oficial) para cada servicio corriendo en Docker sobre Linux ARM64.

| Servicio | RAM en reposo | RAM pico | Notas |
|---|---|---|---|
| **Docker Engine** (daemon) | ~30 MB | ~50 MB | Overhead fijo del motor |
| **Mosquitto** (MQTT broker) | ~5 MB | ~10 MB | Extremadamente ligero, incluso con cientos de mensajes/s |
| **Zigbee2MQTT** | ~60 MB | ~100 MB | Node.js; crece ligeramente con nº dispositivos (~1MB/device) |
| **Backend (FastAPI + uvicorn)** | ~40 MB | ~70 MB | Python con pocas dependencias, 1 worker |
| **Frontend (archivos estáticos)** | ~0 MB | ~0 MB | Servido por el backend, no es un proceso separado |
| **Tailscale** (daemon) | ~20 MB | ~40 MB | Go binary, muy eficiente en ARM |
| **Syncthing** (fase 2, futuro) | ~50 MB | ~200 MB | Pico al indexar archivos; idle ~50MB |
| **Sistema operativo** (Pi OS Lite) | ~150 MB | ~200 MB | Linux headless sin GUI |

### Total estimado

| Escenario | RAM total estimada |
|---|---|
| **Fase 0 sola** (OS + Docker + Mosquitto + Z2M + Backend + Tailscale) | **~305 MB** reposo / **~470 MB** pico |
| **Fases 0+1** (ídem, humedad usa mismos sensores, lógica en backend) | **~310 MB** reposo / **~480 MB** pico |
| **Fases 0+1+2** (+ Syncthing) | **~360 MB** reposo / **~680 MB** pico |

### Margen de seguridad recomendado

La RAM en un sistema Linux no se usa solo para procesos:
- **Buffer/cache del kernel**: Linux usa RAM libre como caché de disco (~100-200 MB).
- **Swap**: se puede configurar en microSD o SSD, pero degrada rendimiento.
- **Picos inesperados**: Zigbee2MQTT puede pegar saltos al emparejar dispositivos.

**Regla:** La RAM total de procesos no debe superar el 70-75% de la RAM física para
que el sistema funcione con fluidez.

| RAM física | 70% disponible para procesos | ¿Suficiente para todas las fases? |
|---|---|---|
| 1 GB | ~700 MB | ⚠️ Justo para fase 0. Sin margen para fase 2. |
| 2 GB | ~1400 MB | ✅ Sobra con creces para las 3 fases + futuro. |
| 4 GB | ~2800 MB | ✅ Exceso. Solo útil si añades servicios pesados (Immich, HA). |
| 8 GB | ~5600 MB | ✅ Innecesario para este proyecto. |

---

## Consumo de CPU

| Servicio | CPU en reposo | CPU al actuar |
|---|---|---|
| Mosquitto | <1% | <1% |
| Zigbee2MQTT | ~1-2% | ~3-5% (al recibir mensajes) |
| Backend (Python) | <1% | ~5% (cada 30s al calcular + llamar API) |
| Tailscale | <1% | ~2% (al tener tráfico) |
| Syncthing | <1% (idle) | ~20-40% (al sincronizar) |

**Conclusión CPU:** Cualquier SBC con 4 cores ARM moderno sobra. Incluso la Pi 5 (1GB)
tiene un CPU A76 2.4GHz que es más que suficiente.

---

## Consumo de almacenamiento

| Concepto | Tamaño |
|---|---|
| Raspberry Pi OS Lite | ~1.5 GB |
| Docker + imágenes (Mosquitto + Z2M + Python) | ~1.5 GB |
| Datos del proyecto (config, logs, histórico) | <100 MB |
| Swap file (recomendado) | 1 GB |
| **Total en microSD** | **~5 GB** (32GB de sobra) |

---

## Requisitos mínimos calculados

| Recurso | Mínimo viable (fase 0) | Recomendado (todas las fases) |
|---|---|---|
| **RAM** | 1 GB (justo, sin Syncthing) | **2 GB** |
| **CPU** | 2 cores ARM (cualquier) | 4 cores ARM A76 (ideal) |
| **Almacenamiento** | 16 GB microSD | 32 GB microSD |
| **USB** | 1x USB para Zigbee dongle | 2x USB (dongle + SSD futuro) |
| **WiFi** | Sí (para acceso red local) | Sí |
| **Ethernet** | Opcional | Recomendado (más estable) |

---

## Tabla de modelos aptos

Precios actualizados a junio 2026 tras las subidas de RAM. Fuentes: raspberrypi.com,
Amazon, distribuidores EU.

| Modelo | RAM | CPU | USB 3.0 | WiFi | Precio oficial (USD) | Precio real Amazon/EU (€) | Apto fase 0 | Apto todas fases | Notas |
|---|---|---|---|---|---|---|---|---|---|
| Raspberry Pi 5 (1GB) | 1 GB | 4x A76 2.4GHz | ✓ | ✓ | $45 | ~45-50€ | ⚠️ Justo | ❌ Sin Syncthing | Sin subida de precio (protegido) |
| **Raspberry Pi 5 (2GB)** | **2 GB** | **4x A76 2.4GHz** | **✓** | **✓** | **$65** | **~65-75€** | **✅** | **✅** | **Mejor relación calidad/precio** |
| Raspberry Pi 5 (4GB) | 4 GB | 4x A76 2.4GHz | ✓ | ✓ | $85 | ~85-100€ | ✅ | ✅ | RAM sobrante; útil si añades servicios pesados |
| Raspberry Pi 4 (2GB) | 2 GB | 4x A72 1.5GHz | ✓ | ✓ | $55 | ~60-80€ (si hay stock) | ✅ | ✅ | CPU más lento, stock irregular |
| Orange Pi 3B (4GB) | 4 GB | 4x A55 2.0GHz | ✓ | ✓ | $50 | ~50-60€ | ✅ | ✅ | CPU más débil; buen precio; Amazon.es |
| Orange Pi 5 (4GB) | 4 GB | 4x A76 + 4x A55 | ✓ | ❌ (adaptador) | $70 | ~75-90€ | ✅ | ✅ | Potentísima pero sin WiFi integrado |

---

## Recomendación

### **Raspberry Pi 5 (2GB) — ~65-75€**

**Por qué:**
1. **2GB es suficiente** para las 3 fases con margen (consumo pico: ~680MB de 2048MB).
2. **CPU A76 2.4GHz** es el más rápido en este rango de precio. Zigbee2MQTT y Syncthing van fluidos.
3. **USB 3.0** para el SSD externo de la fase 2.
4. **WiFi 5 + Bluetooth 5.0** integrados.
5. **Ecosistema maduro**: Docker, Zigbee2MQTT, Tailscale — todo funciona sin parches.
6. **Precio protegido parcialmente** ($65 frente a los $85 de la 4GB tras las subidas).
7. **Disponible** en distribuidores EU (RS Components, The Pi Hut, TME.eu con envío a España).

### **Plan B: Orange Pi 3B (4GB) — ~50-60€**

Si la Pi 5 2GB no está disponible o el precio sube más:
- 4GB de RAM (más de lo necesario).
- CPU algo más lento (A55 vs A76) pero suficiente.
- Disponible en Amazon.es con Prime.
- Compatible con Docker y Zigbee2MQTT (verificado por comunidad).
- Menor soporte de comunidad que Raspberry Pi.

### **Descartadas:**
- **Pi 5 (1GB)**: funciona para fase 0 sola, pero se queda sin margen para Syncthing (fase 2).
- **Pi 5 (4GB)**: 20€ más que la 2GB sin necesitarlo. Solo si quieres Immich en el futuro.
- **Pi 4**: stock irregular, CPU más lento, misma RAM que la Pi 5 por precio similar.
- **Mini PC N100**: overkill, más caro, más grande, más consumo eléctrico.
