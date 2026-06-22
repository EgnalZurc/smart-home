# Fase 1: Control de Humedad

## Objetivo

Mantener la humedad relativa de la casa en un rango saludable (40-60%) de forma automática,
usando humidificadores convencionales controlados por enchufes Zigbee.

## Contexto

El aire acondicionado reseca el ambiente significativamente. En verano con AC activo, la
humedad puede bajar a 25-35%, causando:
- Sequedad de mucosas (nariz, garganta)
- Piel seca
- Electricidad estática
- Deterioro de muebles de madera

## Requerimientos

| # | Requerimiento |
|---|---|
| F1.1 | Medir humedad en 5 zonas (ya cubierto por SNZB-02D de fase 0) |
| F1.2 | Controlar humidificadores on/off vía enchufes Zigbee |
| F1.3 | Lógica automática basada en media de humedad |
| F1.4 | Cobertura suficiente para toda la casa |
| F1.5 | Enchufes de control deben ser Zigbee estándar, tipo F (español) |
| F1.6 | Humidificadores reemplazables por cualquier modelo convencional |
| F1.7 | Configurable: umbrales de humedad, zonas activas |

## Estrategia

### Sensores de humedad

**Ya disponibles desde fase 0.** Los SONOFF SNZB-02D miden temperatura Y humedad relativa.
No se necesita hardware adicional para sensado.

### Control de humidificadores

**Enchufe Zigbee (SONOFF S26R2ZB)** conectado a un humidificador convencional:
- El enchufe corta/da corriente al humidificador.
- El humidificador debe tener un modo que se active automáticamente al recibir corriente
  (la mayoría de los evaporativos lo hacen: "enciendes el enchufe = empieza a funcionar").
- Si un modelo concreto requiere pulsar un botón al encender, buscar uno con switch mecánico
  que recuerde estado.

### Tipo de humidificador

**Evaporativo** (recomendado):
- No produce niebla blanca ni depósitos de cal.
- No sobre-humidifica (se autorregula parcialmente).
- Más higiénico que los ultrasónicos.
- Más silencioso en gamas medias.
- Consumo eléctrico bajo (~20-40W).

**Requisitos del humidificador:**
- Tanque ≥ 3L (para no rellenar cada pocas horas).
- Tasa evaporación > 150ml/h.
- Que se encienda automáticamente al recibir corriente.
- Cobertura: ≥ 20-30m² por unidad.

## Hardware

| Componente | Modelo | Cant. | Precio aprox. | Notas |
|---|---|---|---|---|
| Enchufe Zigbee | SONOFF S26R2ZB (tipo F) | 2-3 | 15€/ud | Amazon.es, compatible Z2M |
| Humidificador evaporativo | A elegir (≥3L, >150ml/h) | 2-3 | 30-50€/ud | Amazon.es |

**Cantidad recomendada:** 2-3 unidades dependiendo del tamaño de la casa.
- Casa < 80m²: 2 humidificadores (salón + zona noche).
- Casa 80-120m²: 3 humidificadores (salón + pasillo noche + despacho).
- Ajustar según experiencia real una vez instalado.

## Lógica de Control

### Parámetros configurables

```yaml
humidity_control:
  target_humidity: 50         # Objetivo (%)
  hysteresis_on: 10           # Enciende si humedad < target - 10 (< 40%)
  hysteresis_off: 5           # Apaga si humedad > target + 5 (> 55%)
  loop_interval: 60           # Segundos entre ciclos (más lento que AC)
  sensor_timeout: 300         # Sensor inactivo si no reporta en 5 min
  zones:                      # Qué enchufes controlar
    - name: "humidificador_salon"
      plug: "enchufe_salon"
    - name: "humidificador_pasillo"
      plug: "enchufe_pasillo"
```

### Pseudocódigo

```python
async def humidity_control_loop():
    while True:
        # 1. Leer humedad de sensores activos
        readings = get_recent_humidity_readings(max_age=config.sensor_timeout)

        if len(readings) == 0:
            log.warning("Sin sensores de humedad activos")
            await sleep(config.loop_interval)
            continue

        # 2. Media de humedad
        media_humedad = sum(readings.values()) / len(readings)

        # 3. Decidir
        if media_humedad < config.target - config.hysteresis_on:
            # Muy seco → encender todos los humidificadores
            for zone in config.zones:
                await mqtt_publish(f"zigbee2mqtt/{zone.plug}/set", {"state": "ON"})
            state = "HUMIDIFYING"

        elif media_humedad > config.target + config.hysteresis_off:
            # Suficiente humedad → apagar
            for zone in config.zones:
                await mqtt_publish(f"zigbee2mqtt/{zone.plug}/set", {"state": "OFF"})
            state = "IDLE"

        else:
            # Zona intermedia → mantener estado actual
            pass

        # 4. Log
        log_humidity(media=media_humedad, sensors=readings, state=state)

        await sleep(config.loop_interval)
```

## MQTT Topics

### Lectura humedad (del sensor)
**Topic:** `zigbee2mqtt/{sensor_name}`
```json
{"temperature": 24.5, "humidity": 42, "battery": 90}
```

### Control enchufe
**Topic (set):** `zigbee2mqtt/{plug_name}/set`
```json
{"state": "ON"}
```
**Topic (estado):** `zigbee2mqtt/{plug_name}`
```json
{"state": "ON", "linkquality": 115}
```

## Integración con Web UI

Nueva sección/tab "Humedad" en la PWA:
- Humedad actual por zona (5 sensores).
- Media general.
- Estado de cada humidificador (on/off).
- Control manual (override: encender/apagar forzado).
- Configuración de umbrales.
- Histórico de humedad (gráfica últimas 24h/7d).

## Dependencias

- **Fase 0 debe estar operativa** (sensores SNZB-02D instalados, Zigbee2MQTT funcionando).
- Los sensores de fase 0 ya proporcionan los datos de humedad necesarios.
- Solo se añade hardware de actuación (enchufes + humidificadores).

## Coste

| Concepto | Mínimo (2 uds) | Máximo (3 uds) |
|---|---|---|
| Enchufes Zigbee | 30€ | 45€ |
| Humidificadores | 60€ | 150€ |
| **Total fase 1** | **90€** | **195€** |
