# Guía de Configuración de Reportes Zigbee

## Problema Identificado

Los sensores SONOFF SNZB-02D son dispositivos **EndDevice** alimentados por batería que entran en modo de bajo consumo (sleep) la mayor parte del tiempo. Esto significa:

1. **No están siempre "escuchando"** - Solo se despiertan periódicamente o cuando presionas su botón físico
2. **La configuración de reporting solo se aplica cuando están despiertos** - Si envías comandos de configuración mientras duermen, no los reciben
3. **Por eso solo reportan cuando presionas el botón** - Al presionar el botón, se despiertan y envían una lectura, pero luego vuelven a dormir

## Configuración Aplicada

He actualizado `infrastructure/zigbee2mqtt/configuration.yaml` con la configuración correcta para los 5 sensores:

```yaml
reporting:
  temperature:
    min_report_interval: 0        # Reportar INMEDIATAMENTE cuando cambie
    max_report_interval: 3600     # Reportar AL MENOS cada 1 hora si no hay cambios
    reportable_change: 0.1        # Reportar si cambia ≥0.1°C
  humidity:
    min_report_interval: 0        # Reportar INMEDIATAMENTE cuando cambie
    max_report_interval: 3600     # Reportar AL MENOS cada 1 hora si no hay cambios
    reportable_change: 1          # Reportar si cambia ≥1%
```

### Cambios realizados:
- **min_report_interval**: 60 → **0** (para reportar inmediatamente en cambios)
- **max_report_interval**: 300 (5 min) → **3600** (1 hora - coincide con timeout de sensor)

## Cómo Aplicar la Configuración

⚠️ **IMPORTANTE**: La configuración del archivo YAML se aplica **automáticamente cuando el sensor se despierta**, PERO puede tardar en aplicarse completamente. Para acelerar el proceso:

### Opción 1: Forzar Reconfigure (Recomendado)

Para cada sensor, cuando esté despierto, enviar comando de reconfiguración vía MQTT o desde el frontend de Zigbee2MQTT:

1. **Presiona el botón del sensor** (para despertarlo)
2. **Inmediatamente después** (mientras está despierto ~5-10 segundos), ejecuta uno de estos métodos:

#### Desde Frontend Zigbee2MQTT (http://localhost:8081)
- Ve a la pestaña "Devices"
- Busca el sensor (ej: "Despacho")
- Click en "Reconfigure"

#### Vía MQTT
Publicar a `zigbee2mqtt/bridge/request/device/configure` con payload:
```json
{"id": "Despacho"}
```

### Opción 2: Esperar Ciclo Natural

Los sensores aplicarán la configuración naturalmente cuando:
- Se despierten para su reporte periódico
- Detecten un cambio de temperatura/humedad
- Presiones el botón físico

**Tiempo estimado**: Puede tardar hasta 24 horas en aplicarse completamente en todos los sensores.

## Verificación de la Configuración

### Comprobar si se aplicó la configuración

1. **Presiona el botón del sensor**
2. **Lee la configuración de reporting** vía MQTT:

Publicar a `zigbee2mqtt/bridge/request/device/reporting/read` con payload:
```json
{
  "id": "Despacho",
  "endpoint": 1,
  "cluster": "msTemperatureMeasurement",
  "configs": [{"attribute": "measuredValue"}]
}
```

### Señales de que funciona correctamente

1. **Recibes lecturas cuando la temperatura cambia** (no solo al presionar botón)
2. **Recibes al menos 1 lectura por hora** de cada sensor
3. **El timestamp entre lecturas es variable** (no fijo cada 5 min)

## Solución a Problemas Comunes

### "Los sensores no reportan automáticamente"

**Causa**: La configuración aún no se ha aplicado o el sensor está durmiendo
**Solución**: 
1. Presiona el botón del sensor
2. Espera 2-3 segundos
3. Ejecuta "Reconfigure" desde el frontend Z2M o vía MQTT
4. Espera 1-2 horas para ver reportes automáticos

### "Al reconectar el hub USB recibo datos antiguos"

**Causa**: Zigbee2MQTT tiene `cache_state: true` y al reconectarse el coordinador, los sensores EndDevice reportan su último estado conocido. NO es culpa del serial_bridge.
**Solución**: Esto es comportamiento normal de Zigbee. Los datos frescos llegarán cuando:
- Los sensores se despierten y reporten (max 1h según nueva configuración)
- Presiones el botón de algún sensor
- Haya un cambio de temperatura >0.1°C o humedad >1%

### "cache_state_send_on_startup: false pero sigue enviando"

**Estado**: Esta opción está correctamente configurada en `configuration.yaml`
**Efecto**: Zigbee2MQTT no reenvía estados cacheados al arrancar, solo cuando hay nuevos reportes

## Sensores Configurados

| IEEE Address | Friendly Name | Estado |
|---|---|---|
| 0xcc36bbfffe7fc69f | Despacho | ✅ Configurado |
| 0xcc36bbfffe7d2ce9 | Habitación Papis | ✅ Configurado |
| 0xcc36bbfffe7fc692 | Salón | ✅ Configurado |
| 0xcc36bbfffe7fc617 | Habitación Esq | ✅ Configurado |
| 0xcc36bbfffe7d4754 | Habitación Cen | ✅ Configurado |

## Referencias

- [Zigbee2MQTT - Configure Reporting](https://www.zigbee2mqtt.io/guide/usage/mqtt_topics_and_messages.html#zigbee2mqtt-bridge-request-device-reporting-configure)
- [SONOFF SNZB-02D Device Page](https://www.zigbee2mqtt.io/devices/SNZB-02D.html)
- Documentación oficial recomienda:
  - min_report_interval: 0 para reportes inmediatos en cambios
  - max_report_interval: 3600 (1h) para sensores de batería
  - reportable_change apropiado al tipo de sensor

## Próximos Pasos

1. **Reiniciar Zigbee2MQTT** para cargar la nueva configuración
2. **Presionar cada botón sensor uno por uno** (espera 30s entre cada uno)
3. **Ejecutar "Reconfigure"** en el frontend para cada sensor
4. **Esperar 1-2 horas** y verificar que los sensores reporten automáticamente
5. **Monitorear logs** de Zigbee2MQTT para ver confirmaciones de reporting configurado

## Comandos Útiles

### Reiniciar Zigbee2MQTT
```bash
docker-compose -f docker-compose.dev.yml restart zigbee2mqtt
```

### Ver logs en tiempo real
```bash
docker-compose -f docker-compose.dev.yml logs -f zigbee2mqtt
```

### Reconfigure todos los sensores (ejecutar cuando estén despiertos)
Publicar a MQTT para cada sensor:
```bash
mosquitto_pub -t 'zigbee2mqtt/bridge/request/device/configure' -m '{"id":"Despacho"}'
mosquitto_pub -t 'zigbee2mqtt/bridge/request/device/configure' -m '{"id":"Habitación Papis"}'
mosquitto_pub -t 'zigbee2mqtt/bridge/request/device/configure' -m '{"id":"Salón"}'
mosquitto_pub -t 'zigbee2mqtt/bridge/request/device/configure' -m '{"id":"Habitación Esq"}'
mosquitto_pub -t 'zigbee2mqtt/bridge/request/device/configure' -m '{"id":"Habitación Cen"}'
```
