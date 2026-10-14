# 🏡 Casita Sueños

Proyecto para encontrar y monitorizar segunda residencia vacacional.
Combina investigación manual de zonas con una app automatizada de alertas de precios.

## Estado actual

| Fase | Nombre | Estado |
|------|--------|--------|
| 0 | Definición de requisitos | ✅ Completada |
| 1 | Definición de localizaciones | ✅ Completada — 13 zonas en `zones.py` |
| 2 | Diseño app de precios | ✅ Completada |
| 3 | Desarrollo app de precios | ✅ **En producción** en Raspberry Pi |
| 4 | Automatización | ✅ **Activa** — scraping L/J + check email cada 30 min |

## Acceso rápido

- **App web:** `https://raspberrypi.tailaa37cd.ts.net/smart-home/casita`
- **Pi:** `ssh pi@raspberrypi.local`
- **Logs:** `docker logs casita-suenos --since=1h`
- **Rebuild:** `cd ~/projects/smart-home && docker compose up -d --build casita-suenos`

## Estructura

```
casita-suenos/
├── README.md                        ← Este fichero
├── fase1-localizaciones/
│   └── estudio-zonas.md             ← Estudio manual de zonas
├── fase3-app/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── src/
│       ├── main.py                  ← Arranque + HTTP server + endpoints REST
│       ├── casita_scheduler.py      ← Orquestador de jobs + check de email
│       ├── models.py                ← Dataclasses: Zone, Property, ScoredProperty...
│       ├── zones.py                 ← 13 zonas + ZONE_COORDS (fallback geográfico)
│       ├── scorer.py                ← Motor de scoring: limitantes + puntuación
│       ├── database.py              ← SQLite: properties, scores, historial precios
│       ├── idealista_email_parser.py← Parser IMAP alertas Idealista
│       ├── fotocasa_email_parser.py ← Parser IMAP alertas Fotocasa
│       ├── notifier.py              ← Telegram: alertas, resúmenes, errores
│       ├── scraper_base.py          ← Utilidades comunes de scraping
│       ├── pisos_scraper.py         ← Scraping Pisos.com (activo)
│       ├── habitaclia_scraper.py    ← Scraping Habitaclia (activo)
│       └── fotocasa_scraper.py      ← Fotocasa scraper (deshabilitado, SPA)
└── fase4-automatizacion/            ← Configuración Docker Compose (en repo raíz)
```

## Portales integrados

| Portal | Método | Notas |
|--------|--------|-------|
| **Idealista** | Email IMAP + scraping de ficha | `noresponder@idealista.com` · 403 frecuente → fallback datos email |
| **Fotocasa** | Email IMAP (solo) | `enviosfotocasa@fotocasa.es` · SPA bloquea scraping |
| **Pisos.com** | Scraping directo | Activo |
| **Habitaclia** | Scraping directo | Activo |

## Notificaciones Telegram

Cada vez que una propiedad **nueva** supera el umbral de score (`ALERT_THRESHOLD = 119`
pts, el 66 % de los 180 posibles) al ser procesada, se envía una notificación
individual por Telegram a todos los chats registrados (fallback a `TELEGRAM_CHAT_ID`).

- Se dispara desde `casita_scheduler.py` en los tres flujos de ingestión: scraping web
  completo (`_run_scraping`), check de email de Idealista (`_do_gmail_check`) y check de
  email de Fotocasa (`_do_fotocasa_check`).
- La notificación se envía **una sola vez por propiedad**: el scheduler marca la casa
  como alertada (`db.mark_alerted`) antes de notificar, de modo que las reejecuciones
  no repiten el aviso.
- El mensaje lo construye `TelegramNotifier.notify_high_scorer(property_dict)` e incluye
  **título, precio, score y enlace** al anuncio (y, si están disponibles, zona,
  habitaciones y superficie).
- Un fallo al enviar la notificación se registra en el log pero no interrumpe el
  procesamiento del resto de propiedades.

Esto es independiente del resumen agregado de cada scraping y del resumen semanal, que
siguen enviándose como antes.

## Referencia técnica completa

- **Requisitos, scoring, zonas, endpoints, operaciones:** `.kiro/steering/casita-suenos.md`
  (carga en Kiro con `#casita-suenos` en el chat)
- **Arquitectura detallada:** `.kiro/docs/CASITA_ARCHITECTURE.md`

## Variables de entorno requeridas (`.env`)

```env
GMAIL_ADDRESS=...
GMAIL_APP_PASSWORD=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
CASITA_DATA_DIR=/app/data
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Service health check (incluye `last_scheduler_tick` y `scheduler_stale`) |
| GET | `/status` | Property listings with status |
| GET | `/api/casita/radar` | Properties above alert threshold |
| GET | `/api/casita/alerts` | **High-scoring properties** for unified dashboard alerts (score ≥119 in last 24h) |
| GET | `/api/casita/zone-trends` | **Per-zone time series** for dashboard charts (`?days=30`, clamped 1–365) |
| GET | `/api/casita/dismissed` | Dismissed properties |
| GET | `/api/casita/schedule` | Scraping schedule |
| POST | `/api/casita/schedule` | Update schedule |
| POST | `/api/casita/dismiss` | Dismiss a property |
| POST | `/api/casita/undismiss` | Restore a property |
| POST | `/api/casita/mark-viewed` | Mark as viewed |
| POST | `/api/casita/save-comment` | Save comment |
| POST | `/run-scraping` | Trigger manual scraping |

### Health check (`GET /health`)

Además del flag `online`, el endpoint expone el estado del loop del scheduler
para detectar cuelgues (el loop se queda parado sin lanzar jobs):

| Field | Type | Description |
|-------|------|-------------|
| `online` | bool | `true` si el servidor HTTP responde |
| `last_scheduler_tick` | string \| null | ISO timestamp del último tick del loop del scheduler. `null` si aún no ha ejecutado ninguno |
| `scheduler_stale` | bool | `true` si han pasado más de 2h desde el último tick (loop colgado) |

El scheduler registra `last_scheduler_tick` en cada iteración de su loop
principal. Durante el grace period de arranque (antes del primer tick)
`last_scheduler_tick` es `null` y `scheduler_stale` es `false` para no reportar
un falso positivo.

Ejemplo de respuesta:

```json
{
  "online": true,
  "last_scheduler_tick": "2026-10-14T10:00:00",
  "scheduler_stale": false
}
```

### Zone trends (`GET /api/casita/zone-trends`)

Devuelve series temporales por zona pensadas para alimentar gráficas en el
dashboard. Acepta el query param `days` (ventana en días, por defecto `30`,
acotado al rango 1–365).

Para cada zona con propiedades vistas por primera vez dentro de la ventana:

| Field | Type | Description |
|-------|------|-------------|
| `zone_id` | string | Identificador de la zona |
| `zone_name` | string | Nombre legible (desde `zones.ZONES`; fallback al `zone_id`) |
| `data_points` | list | Un punto por día: `{date, count, avg_price, avg_score}` |
| `total_properties` | int | Propiedades actuales en radar (puntuadas, no descartadas) |
| `trend` | string | `growing` \| `stable` \| `declining` según el cambio de volumen entre la primera y la segunda mitad de la ventana |

Cada entrada de `data_points` contiene la `date` (YYYY-MM-DD), el `count` de
propiedades vistas por primera vez ese día, el `avg_price` y el `avg_score`
medios de esas propiedades (`null` si no hay score). Los puntos van ordenados
cronológicamente y las zonas por `zone_id`.

Ejemplo de respuesta:

```json
{
  "days": 30,
  "zones": [
    {
      "zone_id": "zamora_meseta",
      "zone_name": "Zamora meseta central (Arcenillas, Villaralbo, Morales del Vino)",
      "data_points": [
        {"date": "2026-10-10", "count": 2, "avg_price": 150000.0, "avg_score": 125.0},
        {"date": "2026-10-13", "count": 1, "avg_price": 180000.0, "avg_score": 131.0}
      ],
      "total_properties": 3,
      "trend": "declining"
    }
  ]
}
```
