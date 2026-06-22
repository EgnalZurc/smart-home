# Fase 0: AC Thermostat Override

## Problema

El termostato integrado del AC (Mitsubishi PEAD-SM71JA, S/N 3XM10399) recibe directamente
aire frío del retorno de la unidad. Esto causa que lea una temperatura significativamente
más baja que la temperatura real de las zonas habitables. Como consecuencia, el equipo se
apaga prematuramente sin alcanzar la temperatura objetivo real.

**Ejemplo real:**
- Temperatura ambiente casa: 28°C
- Objetivo configurado: 23°C
- El termostato interno lee ~19°C cuando la casa sigue a ~27°C
- El AC se apaga creyendo que ha llegado al objetivo

## Solución

Un servicio que:
1. Lee la temperatura real de 5 zonas vía sensores Zigbee (MQTT).
2. Calcula la media como referencia fiable.
3. Manipula la consigna del AC vía MELCloud API para forzarlo a seguir enfriando o apagarlo según la temperatura real.

## Requerimientos

| # | Requerimiento | Estado |
|---|---|---|
| F0.0 | La pantalla principal debe mostrar todos los datos correctamente y ser funcional | ✅ Funcional (datos persisten entre reinicios) |
| F0.1 | Sobreescribir termostato interno usando media de 5 sensores externos | ✅ Implementado |
| F0.2 | 5 sensores: Habitación Cen, Habitación Esq, Habitación Papis, Salón, Despacho | ✅ Emparejados |
| F0.3 | Temperatura referencia = media aritmética de todos los sensores con dato disponible (el controlador usa todos los datos persistidos, sin filtrar por timeout, para decidir) | ✅ Implementado |
| F0.4 | Control AC vía MELCloud API con WiFi adapter oficial | ✅ Validado en POC y funcionando |
| F0.5 | Si un sensor no reporta en 10 min, se marca como desconectado en la UI (pero su último dato sigue usándose para la media del controlador) | ✅ Implementado |
| F0.6 | POC virtualizado antes de comprar hardware | ✅ Completado |
| F0.7 | Histéresis configurable para evitar ciclos rápidos on/off | ✅ Implementado (0.5/0.3 + cooldown 5min) |
| F0.8 | Log de todas las acciones tomadas (para diagnóstico y gráficas) | ✅ Implementado (histórico en memoria) |
| F0.9 | La app debe ser accesible desde cualquier dispositivo conectado a la WiFi | ✅ Funcional (0.0.0.0:8080, IP fija 192.168.1.163) |
| F0.10 | Temperaturas y humedad con colores según rango: verde/naranja/rojo/azul/azul oscuro | ✅ Implementado (tempColor/humColor en UI) |
| F0.11 | Mostrar temperatura exterior en Valdebernardo, Madrid (C.P. 28032, coords 40.396644,-3.622511) | ✅ Implementado (Open-Meteo, cache 10min, persistido en disco) |
| F0.12 | La temperatura objetivo debe limitar sus rangos a los del AC (19-30°C) | ✅ Implementado (frontend + backend) |
| F0.13 | Implementar máquina de estados formal que defina la decisión interna del controlador (COOLING_MAX / MODULATING / OFF / COOLDOWN / FORCED_ON / FORCED_OFF / ERROR) con transiciones y cooldown explícitos | ✅ Implementado (state_machine.py + 53 tests unitarios) |
| F0.14 | Mostrar estado real del AC desde MELCloud: ON/OFF, modo, fan, consigna real | ✅ Implementado (ON verde / OFF rojo + detalle modo/fan/consigna) |
| F0.15 | Mostrar fuerza del aire: Bajo (verde), Medio (amarillo), Alto (rojo), Auto (azul) | ✅ Implementado (desde MELCloud SetFanSpeed real) |
| F0.16 | Mostrar consigna AC | ✅ Implementado |
| F0.17 | UI moderna, mobile-first, user-friendly, bonita en móvil | ✅ Implementado (glassmorphism, animaciones, touch targets 48px, PWA) |
| F0.18 | Persistir en disco última medida de cada sensor (temp, humedad, batería, timestamp). Sobrevive reinicios. | ✅ Implementado (volumen Docker + sensor_readings.json) |
| F0.19 | Sensor conectado = última actualización < 1 hora. Desconectado = > 1 hora. | ✅ Implementado (SENSOR_TIMEOUT=3600s) |
| F0.20 | Logs y datos de persistencia mínimos. Limpieza automática diaria de innecesarios. | ✅ Implementado (no testado — rotación Docker + cleanup Z2M cada 24h, retención 3 días) |
| F0.21 | Mostrar decisión del controlador en la UI: renombrar sección "Temperatura objetivo" a "Controlador" con temp objetivo + decisión actual (COOLING MAX/MODULANDO/OFF) con diseño integrado | ✅ Implementado |
| F0.22 | Forzar ON con popup: al pulsar "Forzar ON", mostrar popup para elegir modo, fuerza y temperatura objetivo, y enviar esos datos a MELCloud. Forzar OFF con popup de confirmación. | ✅ Implementado (popup ON con modo/fuerza/temp, popup OFF con confirmación) |
| F0.23 | El software debe correr en una Raspberry Pi (Docker, ARM64) | ⏳ Hardware comprado, pendiente deploy |
| **F0.24** | **Mostrar consumo energético total (24h) y coste en € en la pantalla principal** | ✅ **Implementado (widget clickeable)** |
| **F0.25** | **Obtener precio de energía regulada (PVPC) de API ESIOS (REE España) cada hora** | ✅ **Implementado (con cache + fallback precio mock)** |
| **F0.26** | **Registrar consumo cada hora (:00) en JSON con 24 valores (rolling)** | ✅ **Implementado (scheduler APScheduler)** |
| **F0.27** | **Registrar consumo cada día (00:00) en JSON con hasta 365 valores (rolling)** | ✅ **Implementado (scheduler APScheduler)** |
| **F0.28** | **Popup de estadísticas energéticas con 2 gráficas (click en widget energía)** | ✅ **Implementado (gráfica horaria + mensual)** |
| **F0.29** | **Calcular coste usando precio exacto del momento de consumo** | ✅ **Implementado (precio por hora del consumo)** |
| **F0.30** | **Optimización: usar acumuladores en memoria, no recalcular siempre** | ✅ **Implementado (acumuladores 24h en memoria)** |


## Información del AC (actualizada tras POC)

| Campo | Valor |
|---|---|
| Marca | Mitsubishi Electric |
| Modelo | PEAD-SM71JA |
| Serial | 3XM10399 |
| Control | MELCloud (adaptador WiFi oficial, AdaptorType=3, familia MAC-567/577) |
| DeviceID | 115643811 |
| BuildingID | 809537 |
| **Rango consigna real** | **19°C - 30°C** (confirmado por POC; <19 no se aplica, 31 rechazado) |
| Modos | Cool, Heat, Dry, Fan, Auto |
| Fan speeds | Auto (0), 1, 2, 3 (NumberOfFanSpeeds=3, no 5) |
| RoomTemp mínimo reportado | 19°C (nunca baja de este valor en la API) |
| DemandPercentage | Siempre 100% (campo estático, no indicador de potencia) |
| Ciclo comunicación adapter | ~60s (oscila Offline true/false) |

---

## Conclusiones del POC (validado 2026-06-12)

### Hallazgos confirmados

| # | Hallazgo | Impacto en diseño |
|---|---|---|
| H1 | **El override funciona**: con SetTemp=19°C, el AC sigue enfriando incluso cuando RoomTemp=19°C (no entra en standby) | El workaround es viable. Con consigna al mínimo, el AC nunca para por sí mismo. |
| H2 | **RoomTemp nunca baja de 19°C** en la lectura de la API | Con SetTemp=19°C el AC siempre "cree" que no ha llegado al objetivo → enfría indefinidamente. |
| H3 | **Consigna mínima real = 19°C** (no 16°C). La API acepta 16°C pero el AC no lo aplica. | El rango útil de modulación es 19-30°C, no 16-31°C. |
| H4 | **Consigna máxima real = 30°C**. La API rechaza 31°C en algunos casos. | Limitar el rango superior a 30°C. |
| H5 | **DemandPercentage siempre = 100%**. Es un campo de configuración (límite), NO indicador de potencia instantánea. | No usar este campo para monitorizar potencia. No hay forma de conocer la potencia real vía API. |
| H6 | **SetAta requiere payload completo** (GET estado → modificar → POST todo). Un payload parcial se acepta (HTTP 200) pero no se aplica. | El cliente DEBE hacer GET+modify+POST en cada operación. |
| H7 | **Offline oscila** entre true/false cada ~60s (ciclo del adapter). Cuando Offline=True, los SET no se aplican. | Reintentar comandos hasta confirmar aplicación. No tratar Offline como error fatal. |
| H8 | **Fan speed se obedece correctamente**. Auto (0) y fijo (1-3) se aplican sin problemas. | Usar fan=3 (max) en COOLING_MAX, fan=0 (auto) en modulación. |
| H9 | **Power OFF/ON funciona correctamente**. Apagado y re-encendido se aplican. | Ciclo OFF → ON es viable. |

### Restricciones de diseño (derivadas del POC)

| # | Restricción | Motivo |
|---|---|---|
| D1 | **Consigna mínima = 19°C** en todas las decisiones | El AC ignora valores <19°C |
| D2 | **Consigna máxima = 30°C** en modulación | El AC puede rechazar 31°C |
| D3 | **Cooldown de 5 minutos entre OFF y ON** | Evitar re-encendidos prematuros por oscilación de la media en el borde de histéresis |
| D4 | **Reintentar SET cada tick si la respuesta no coincide** con lo solicitado | Adapter Offline impide aplicación inmediata |
| D5 | **No usar DemandPercentage** como indicador de potencia | Campo estático, siempre 100% |
| D6 | **Usar Power como indicador de estado**, no InStandbyMode | Power=False = apagado confirmado |
| D7 | **Intervalo de polling mínimo 45-60s** | Rate limit MELCloud + ciclo de comunicación del adapter |
| D8 | **Modulación mapea al rango 19-30°C** proporcionalmente | Rango real confirmado |
| D9 | **SetAta siempre con GET previo** (payload completo) | Payloads parciales no se aplican |
|---|---|
| Marca | Mitsubishi Electric |
| Modelo | PEAD-SM71JA |
| Serial | 3XM10399 |
| Control | MELCloud (adaptador WiFi oficial instalado) |
| Rango consigna | 16°C - 31°C |
| Modos | Cool, Heat, Dry, Fan, Auto |
| Fan speeds | Auto (0), 1-5 |

## MELCloud API (verificado por POC)

API no oficial (ingeniería inversa de la app). Endpoints relevantes:

| Operación | Método | Endpoint |
|---|---|---|
| Login | POST | `/Mitsubishi.Wifi.Client/Login/ClientLogin` |
| Listar dispositivos | GET | `/Mitsubishi.Wifi.Client/User/ListDevices` |
| Estado dispositivo | GET | `/Mitsubishi.Wifi.Client/Device/Get?id={id}&buildingID={bid}` |
| Configurar AC | POST | `/Mitsubishi.Wifi.Client/Device/SetAta` |

**Autenticación:** Header `X-MitsContextKey` con token obtenido del login.

**SetAta — Método correcto (confirmado por POC):**
1. GET `/Device/Get` → obtener estado completo del dispositivo (JSON ~800 bytes)
2. Modificar campos deseados en el JSON
3. POST `/Device/SetAta` con el JSON completo modificado

**⚠️ IMPORTANTE:** Enviar un payload parcial (solo los campos a cambiar) NO funciona.
La API responde HTTP 200 pero no aplica los cambios.

**Campos a modificar en SetAta:**
```json
{
  "Power": true,
  "OperationMode": 3,
  "SetTemperature": 19.0,
  "SetFanSpeed": 3,
  "EffectiveFlags": 31,
  "HasPendingCommand": true
}
```

**OperationMode:** 1=Heat, 2=Dry, 3=Cool, 7=Fan, 8=Auto

**Verificación de aplicación:**
- Si la respuesta del POST contiene `SetTemperature` = valor solicitado → aplicado
- Si no coincide → Offline transitorio, reintentar en el siguiente tick

**Campos de la API que NO son útiles:**
- `DemandPercentage`: siempre 100%, es un límite de configuración, no potencia real
- `Offline`: oscila true/false cada ~60s, no indica un problema real

## Hardware

| Componente | Modelo exacto | Cant. | Precio real | Estado |
|---|---|---|---|---|
| Sensor temp/humedad | SONOFF SNZB-02D (Zigbee 3.0, pantalla LCD) | 5 | 42,70€ (8,54€/ud) | ✅ Comprado |
| Coordinador Zigbee | SONOFF ZBDongle-E V2 (antena externa) | 1 | 15,19€ | ✅ Comprado |
| Servidor | Raspberry Pi 5 4GB (kit iRasptek: Pi + fuente 27W + carcasa + cooler + SD 64GB) | 1 | 180,99€ | ✅ Comprado (Amazon.es, jun 2026) |

## Ubicación de sensores

| Sensor | Zona | Notas |
|---|---|---|
| sensor_hab1 | Habitación 1 | Lejos de ventanas y radiación directa |
| sensor_hab2 | Habitación 2 | Idem |
| sensor_hab3 | Habitación 3 | Idem |
| sensor_salon | Salón | Zona central, no cerca del AC |
| sensor_despacho | Despacho | Idem |

## Lógica de Control

### Parámetros configurables

```yaml
control:
  target_temperature: 23.0    # Objetivo real deseado
  hysteresis_on: 0.5          # Margen para encender (target + 0.5)
  hysteresis_off: 0.3         # Margen para apagar (target - 0.3)
  min_setpoint: 19            # Mínimo real del AC (confirmado por POC)
  max_setpoint: 30            # Máximo real del AC (confirmado por POC)
  cooldown_seconds: 300       # Tiempo mínimo entre OFF y ON (5 min)
  loop_interval: 45           # Segundos entre cada ciclo (respeta rate limit)
  sensor_timeout: 300         # Segundos sin dato = sensor inactivo
  ac_mode: "cool"             # Modo de operación
  fan_speed_max: 3            # Fan en COOLING_MAX
  fan_speed_modulate: 0       # Fan en modulación (auto)
```

### Pseudocódigo (corregido tras POC)

```python
async def control_loop():
    last_off_time = 0  # Para cooldown D3

    while True:
        # 1. Leer temperaturas de sensores activos
        readings = get_recent_readings(max_age=config.sensor_timeout)

        if len(readings) == 0:
            log.error("Sin sensores activos. No se actúa.")
            await sleep(config.loop_interval)
            continue

        # 2. Calcular media
        media = sum(readings.values()) / len(readings)

        # 3. Decidir acción
        if media > config.target + config.hysteresis_on:
            # Hace calor → forzar enfriamiento al máximo
            # Respetar cooldown si acabamos de apagar
            if time_since(last_off_time) < config.cooldown_seconds:
                continue  # Esperar cooldown
            action = set_ac(power=ON, setpoint=19, fan=3, mode=COOL)

        elif media < config.target - config.hysteresis_off:
            # Ya está frío → apagar
            action = set_ac(power=OFF)
            last_off_time = now()

        else:
            # Zona intermedia → modular consigna proporcionalmente
            # Respetar cooldown
            if time_since(last_off_time) < config.cooldown_seconds:
                continue
            range_size = config.hysteresis_on + config.hysteresis_off  # 0.8
            position = (media - (config.target - config.hysteresis_off)) / range_size
            # position=1 → calor → consigna baja (19°C)
            # position=0 → frío → consigna alta (30°C)
            setpoint = config.max_setpoint - (position * (config.max_setpoint - config.min_setpoint))
            setpoint = clamp(setpoint, 19, 30)
            action = set_ac(power=ON, setpoint=setpoint, fan=0, mode=COOL)

        # 4. Aplicar (GET+modify+POST) con reintento si Offline
        if action != current_state:
            success = await melcloud.apply_robust(action)  # Reintenta si no se aplica
            if success:
                current_state = action

        # 5. Registrar
        log_action(media=media, sensors=readings, action=action)

        await sleep(config.loop_interval)
```

### Diagrama de estados (corregido)

```
                    media > target + 0.5
                    (+ cooldown 3 min)
    ┌─────────────────────────────────────────┐
    │                                         ▼
┌───┴───┐                              ┌───────────┐
│  OFF  │                              │  COOLING  │
│       │◀─────────────────────────────│ MAX (19°C)│
└───┬───┘   media < target - 0.3       │  fan=3    │
    │                                  └─────┬─────┘
    │                                        │
    │  media en zona intermedia              │
    │  (+ cooldown 3 min)                    │
    │       ┌─────────────────────────┐      │
    └──────▶│      MODULATING         │◀─────┘
            │  (19-30°C proporcional) │
            │  fan=auto               │
            └──────────────────────────┘
```

## MQTT Topics

Los sensores SONOFF SNZB-02D reportan en Zigbee2MQTT con este formato:

**Topic:** `zigbee2mqtt/{friendly_name}`

**Payload ejemplo:**
```json
{
  "temperature": 25.3,
  "humidity": 58,
  "battery": 87,
  "linkquality": 120,
  "voltage": 2900
}
```

## POC (Proof of Concept)

El POC virtualiza todo para validar la lógica sin hardware:

1. **Mock sensors**: script Python que publica temperaturas simuladas en MQTT local.
2. **Mock MELCloud**: servidor HTTP que registra todas las llamadas SetAta.
3. **Controlador real**: la lógica de control exacta que irá en producción.
4. **Web UI real**: PWA funcional con datos simulados.
5. **Escenarios**: casa caliente bajando, sensor caído, temperatura oscilante.

**Ejecutar:**
```bash
# Opción 1: Docker
docker compose -f poc/docker-compose.poc.yml up

# Opción 2: Python directo (requiere mosquitto local)
pip install -r requirements.txt
python -m poc.run
```
