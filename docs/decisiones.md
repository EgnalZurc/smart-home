# Registro de Decisiones de Diseño (ADR)

Cada decisión relevante se documenta aquí para que futuras sesiones entiendan el contexto.

---

## ADR-001: Servidor central — Raspberry Pi 5 (2GB)

**Fecha:** 2025-06-12
**Estado:** Aprobada

**Contexto:**
La Raspberry Pi 4 tiene rotura de stock y precios inflados (>100€ por 4GB). Se necesita un
SBC con Docker, USB 3.0, WiFi, y soporte para Zigbee2MQTT.

**Alternativas evaluadas:**
- Pi 4 (4GB): sin stock, >100€. Descartada.
- Pi 5 (2GB): 55€, CPU A76 2.4GHz, USB 3.0, ecosistema maduro.
- Pi 5 (4GB): 75-85€, innecesariamente cara para este uso.
- Orange Pi 3B (4GB): ~50€, pero peor soporte de comunidad/Docker.
- Mini PC N100: >90€, sobrepasado para este uso.

**Decisión:** Raspberry Pi 5 (2GB). CPU más potente de las SBC a este precio. 2GB suficiente
para el stack (verificado: Docker + Z2M + Mosquitto + Python + web + Tailscale ≈ 1.2GB).

**Plan B:** Si no hay stock de Pi 5 2GB, usar Orange Pi 3B (4GB) de Amazon.es.

---

## ADR-002: Protocolo de sensores — Zigbee 3.0

**Fecha:** 2025-06-12
**Estado:** Aprobada

**Contexto:**
Se necesitan 5+ sensores de temperatura/humedad baratos, fiables, de bajo consumo, y que
sean fáciles de añadir/quitar sin modificar código.

**Alternativas evaluadas:**
- Zigbee: estándar abierto, bajo consumo (pila 1 año), ~12€/sensor, Zigbee2MQTT.
- WiFi (ESP32): requiere alimentación permanente, firmware custom, ~15-20€/sensor montado.
- Bluetooth (Switchbot): alcance limitado, gateway propietario.
- Z-Wave: más caro, menos dispositivos disponibles en España.

**Decisión:** Zigbee 3.0 con coordinador SONOFF ZBDongle-E. Añadir sensor = emparejar +
línea en config. Sin código.

---

## ADR-003: Sensor de temperatura — SONOFF SNZB-02D

**Fecha:** 2025-06-12
**Estado:** Aprobada

**Contexto:**
Necesitamos 5 sensores de temperatura+humedad Zigbee, económicos, precisos, disponibles en
Amazon.es.

**Decisión:** SONOFF SNZB-02D (~12€/ud). Zigbee 3.0, ±0.2°C, mide también humedad
(reutilizable en fase 1), pantalla LCD, CR2450 (~12 meses), compatible Zigbee2MQTT.

---

## ADR-004: Acceso remoto — Tailscale

**Fecha:** 2025-06-12
**Estado:** Aprobada

**Contexto:**
La web de control debe ser accesible desde fuera de casa. Opciones: abrir puertos (inseguro),
DDNS + reverse proxy (complejo), VPN (seguro pero puede ser difícil).

**Decisión:** Tailscale. VPN mesh basada en WireGuard. Gratuita hasta 100 dispositivos.
Sin abrir puertos, sin configurar router, cifrado E2E. Instalar en Pi + móvil.

---

## ADR-005: Arquitectura — Docker Compose

**Fecha:** 2025-06-12
**Estado:** Aprobada

**Contexto:**
El sistema debe ser expandible con fases ilimitadas sin conflictos entre servicios.

**Decisión:** Todo corre en Docker Compose. Cada servicio = contenedor aislado. Añadir
servicios futuros = añadir al compose. Fácil backup (volúmenes), fácil restauración.

---

## ADR-006: Web UI — PWA con Preact + Tailwind

**Fecha:** 2025-06-12
**Estado:** Aprobada

**Contexto:**
La interfaz debe ser moderna, mobile-first, accesible sin app store, e instalable como app.

**Decisión:** Progressive Web App. Preact (3KB, compatible React). Tailwind CSS (utility-first,
rápido de prototipar). FastAPI como backend. Una sola app unificada con tabs por fase.

---

## ADR-007: Control de humidificadores — Enchufe Zigbee + humidificador normal

**Fecha:** 2025-06-12
**Estado:** Aprobada

**Contexto:**
Fase 1 necesita controlar humidificadores. Opciones: humidificador smart (caro, propietario)
vs enchufe Zigbee + humidificador convencional.

**Decisión:** SONOFF S26R2ZB (enchufe Zigbee tipo F, ~15€) + humidificador evaporativo
cualquiera. Razones: más barato, estándar, reemplazable, no atado a marca.

---

## ADR-008: Backup fotos — Syncthing

**Fecha:** 2025-06-12
**Estado:** Aprobada

**Contexto:**
Backup automático de fotos de 2 Android. Opciones: Immich (pesado, 6GB RAM mín.), Google
Photos (nube, pago), Syncthing (ligero, P2P, gratis).

**Decisión:** Syncthing. Consume ~50-100MB RAM, app Android nativa, sync automático en WiFi,
send-only en teléfonos. No requiere base de datos ni ML.

---

## ADR-009: POC validado — Rango real del AC = 19-30°C

**Fecha:** 2026-06-12
**Estado:** Aprobada

**Contexto:**
El POC se ejecutó contra el AC real (Mitsubishi PEAD-SM71JA) durante 30 minutos con 4
escenarios. Se descubrió que el rango de consigna especificado (16-31°C) no coincide con
el rango realmente aceptado por el AC vía API.

**Hallazgo:**
- Consignas <19°C: la API acepta (HTTP 200) pero el AC no las aplica.
- Consignas 19-30°C: se aplican correctamente.
- Consigna 31°C: rechazada en algunos casos.
- RoomTemp nunca baja de 19°C en los reportes de la API.

**Decisión:** El rango de control válido es 19-30°C. Toda la lógica de modulación
y COOLING_MAX usa estos límites. Documentado en `docs/fase0-ac-override.md`.

---

## ADR-010: POC validado — SetAta requiere payload completo

**Fecha:** 2026-06-12
**Estado:** Aprobada

**Contexto:**
Al intentar configurar el AC con un payload parcial (solo campos a cambiar + EffectiveFlags),
la API respondía HTTP 200 pero no aplicaba los cambios. Tras investigar, se confirmó que
la API requiere el estado completo del dispositivo.

**Decisión:** El flujo correcto es: GET Device/Get → modificar campos → POST Device/SetAta
con el JSON completo (~800 bytes). Implementado en `melcloud_client.py`.

---

## ADR-011: Servidor central — Raspberry Pi 5 (4GB)

**Fecha:** 2026-06-12
**Estado:** Aprobada (sustituye ADR-001)

**Contexto:**
El usuario planea añadir más domótica continuamente. 2GB es suficiente para las 3 fases
definidas, pero no deja margen para servicios futuros no planificados.

**Decisión:** Raspberry Pi 5 (4GB) a ~140€ en RaspiPC. Los 47€ extra se amortizan en
tranquilidad: nunca tendrás que preguntar "¿esto cabe?" antes de añadir algo nuevo.

---

## Plantilla para nuevas decisiones

```markdown
## ADR-XXX: [Título]

**Fecha:** YYYY-MM-DD
**Estado:** Propuesta / Aprobada / Rechazada / Sustituida por ADR-YYY

**Contexto:**
[Qué problema se resuelve y qué restricciones hay]

**Alternativas evaluadas:**
- [Opción 1]: [pros y contras]
- [Opción 2]: [pros y contras]

**Decisión:** [Qué se decidió y por qué]
```
