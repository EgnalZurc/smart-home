# 📊 Portfolio Monitor Service

Servicio de monitorización de cartera de inversiones para el ecosistema Smart Home. Monitoriza ETFs y posiciones de staking de criptomonedas.

## ⚠️ Disclaimer

Este servicio proporciona **información descriptiva**, no asesoramiento financiero. Las señales y métricas son herramientas de análisis técnico con limitaciones conocidas:

- **Fear & Greed**: Indicador de sentimiento, no predictor de precios
- **Golden/Death Cross**: Indicadores retrasados, mejor para confirmar tendencias que para timing de entrada
- **Proximidad a ATH**: Informativo, no implica necesidad de vender
- **Cálculos IRPF**: Estimaciones basadas en legislación vigente, consulta con un asesor fiscal

La filosofía del servicio es **informar sin prescribir**. Las decisiones de inversión son tuyas.

## Características

### Monitor de ETFs
- Descarga datos de Yahoo Finance
- Análisis técnico (medias móviles 50/200 días, Golden/Death Cross)
- Alertas de caída desde máximos y pérdidas vs precio medio
- Cálculo de impuestos IRPF sobre plusvalías
- Seguimiento de plan de inversión por fases
- Comparación con hitos proyectados

### Monitor de Crypto Staking
- Datos de precios via CoinGecko API
- Índice Fear & Greed
- Seguimiento de posiciones flexibles y a plazo fijo
- Cálculo de recompensas diarias y acumuladas
- Alertas de mercado (cambios 24h/30d, proximidad a ATH)
- Días hasta redención/vencimiento

## Configuración

El servicio lee su configuración de `/app/data/settings.toml`. Ver `settings.example.toml` para la estructura completa.

### Variables de entorno

| Variable | Descripción | Default |
|----------|-------------|---------|
| `MONITOR_LANG` | Idioma de los reportes (`es` o `en`) | `es` |
| `LOG_LEVEL` | Nivel de logging (`DEBUG`, `INFO`, `WARNING`) | `INFO` |
| `DATA_DIR` | Directorio de datos | `/app/data` |
| `TELEGRAM_BOT_TOKEN` | Token del bot de Telegram (requerido para alertas) | - |
| `TELEGRAM_CHAT_ID` | ID del chat de Telegram (requerido para alertas) | - |

### Notificaciones Telegram

El servicio envía alertas a Telegram **solo cuando hay señales WARN o DANGER**. 
Esto evita spam y te notifica solo cuando necesitas revisar algo.

Para configurar:
1. Usa el mismo bot que casita-suenos (ya configurado en `.env`)
2. Las variables `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` se leen del `.env`
3. Puedes probar con `POST /api/portfolio/notifications/test`

## API Endpoints

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/smart-home/portfolio` | Dashboard SPA |
| GET | `/api/portfolio/summary` | Resumen completo |
| GET | `/api/portfolio/etf` | Análisis ETFs |
| GET | `/api/portfolio/crypto` | Análisis Crypto |
| POST | `/api/portfolio/refresh` | Actualizar todos los monitores |
| POST | `/api/portfolio/refresh/{name}` | Actualizar monitor específico |
| GET | `/api/portfolio/schedule` | Ver programación |
| POST | `/api/portfolio/reload-config` | Recargar configuración |
| GET | `/api/portfolio/notifications/status` | Estado del notificador |
| POST | `/api/portfolio/notifications/test` | Enviar notificación de prueba |
| GET | `/health` | Health check |

## Desarrollo local

```bash
cd services/portfolio-monitor
pip install -r requirements.txt
uvicorn src.main:app --reload --port 8010
```

## Docker

```bash
docker build -t portfolio-monitor .
docker run -p 8010:8010 -v ./data:/app/data portfolio-monitor
```

## Arquitectura

```
portfolio-monitor/
├── src/
│   ├── main.py              # FastAPI app + endpoints
│   ├── config.py            # Carga de configuración TOML
│   ├── models.py            # Dataclasses y enums
│   ├── i18n.py              # Traducciones es/en
│   ├── orchestrator.py      # Orquestador + scheduler
│   ├── api/
│   │   └── routes.py        # API routes
│   ├── monitors/
│   │   ├── __init__.py      # Registry de monitores
│   │   ├── etf_monitor.py   # Monitor ETFs
│   │   └── crypto_monitor.py # Monitor Crypto
│   └── static/
│       └── portfolio.html   # Dashboard SPA
├── Dockerfile
├── requirements.txt
└── README.md
```

## Extensibilidad

Para añadir un nuevo monitor:

1. Crear archivo en `monitors/new_monitor.py`
2. Extender `BaseMonitor` e implementar `run()`, `get_level()`, `get_last_update()`
3. Usar el decorador `@register_monitor`
4. El orquestador lo detectará automáticamente

```python
from monitors import BaseMonitor, register_monitor


@register_monitor
class NewMonitor(BaseMonitor):
    name = "new"

    async def run(self) -> dict:
        # Tu lógica aquí
        pass
```
