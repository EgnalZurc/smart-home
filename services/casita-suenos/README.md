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

## Análisis precio/m² vs media de zona

Cada propiedad del radar se enriquece con un análisis de su precio por metro cuadrado
comparado con la **media de su zona**, para detectar de un vistazo chollos (por debajo
de la media) y sobreprecios.

El cálculo vive en `database.py`:

- **`get_zone_avg_price_per_m2(zone_id)`** — media de `price / size_m2` de las
  propiedades **activas** (no descartadas) de la zona con metros cuadrados válidos
  (`size_m2 > 0`). Devuelve `None` si la zona no tiene datos utilizables.
- **`get_price_per_m2_analysis(uid)`** — análisis de una propiedad concreta. Devuelve:

  | Campo | Descripción |
  |-------|-------------|
  | `price_per_m2` | Precio/m² de esta propiedad (`None` si no hay m²) |
  | `zone_avg_price_per_m2` | Media de la zona (`None` si no hay datos) |
  | `below_zone_avg` | `True` si está por debajo de la media de la zona |
  | `pct_vs_zone_avg` | % respecto a la media; negativo = más barato (ej. `-15.0` = 15 % más barato), positivo = más caro |

Estos cuatro campos se añaden automáticamente a cada item de
`GET /api/casita/radar`. La media por zona se cachea dentro de la llamada para no
repetir la agregación por cada propiedad.

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
| GET | `/health` | Service health check |
| GET | `/status` | Property listings with status |
| GET | `/api/casita/radar` | Properties above alert threshold (incl. price/m² vs zone-average analysis) |
| GET | `/api/casita/alerts` | **High-scoring properties** for unified dashboard alerts (score ≥119 in last 24h) |
| GET | `/api/casita/dismissed` | Dismissed properties |
| GET | `/api/casita/schedule` | Scraping schedule |
| POST | `/api/casita/schedule` | Update schedule |
| POST | `/api/casita/dismiss` | Dismiss a property |
| POST | `/api/casita/undismiss` | Restore a property |
| POST | `/api/casita/mark-viewed` | Mark as viewed |
| POST | `/api/casita/save-comment` | Save comment |
| POST | `/run-scraping` | Trigger manual scraping |
| GET | `/api/casita/zone-trends` | Zone time-series for charts (`?days=30`) |
