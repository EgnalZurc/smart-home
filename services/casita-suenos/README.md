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
