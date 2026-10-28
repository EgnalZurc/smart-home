"""
Constantes y configuración por defecto del scheduler de Casita Sueños.

Agrupa los valores que antes vivían al principio de ``casita_scheduler.py``.
No contiene lógica: solo datos de configuración de los jobs periódicos.
"""

from __future__ import annotations

from datetime import time as dtime
from typing import Final

# Zonas top 8 por puntuación — para el scraping semanal de Apify (free tier)
TOP_ZONES_FOR_APIFY: Final[list[str]] = [
    "zamora_meseta",
    "castellon_costa_norte",
    "salamanca_alrededores",
    "la_rioja_valle",
    "valencia_costa_norte",
    "palencia_alrededores",
    "navarra_ribera",
    "burgos_sur",
]

# Días de la semana para scraping completo (0=lunes, 3=jueves)
SCRAPING_DAYS: Final[set[int]] = {0, 3}
SCRAPING_HOUR: Final[dtime] = dtime(7, 0)

# Día del resumen semanal (6=domingo)
SUMMARY_DAY: Final[int] = 6
SUMMARY_HOUR: Final[dtime] = dtime(9, 0)

# Intervalo del check de Gmail (segundos)
GMAIL_CHECK_INTERVAL_SEC: Final[int] = 30 * 60  # 30 minutos

# Intervalo del loop principal (segundos) — cada minuto comprueba si toca algo
LOOP_TICK_SEC: Final[int] = 60

# Distancia máxima (km) aceptada por el fallback geográfico de Nominatim
NOMINATIM_MAX_DIST_KM: Final[float] = 200.0


# Timeout para las peticiones a Nominatim (segundos)
NOMINATIM_TIMEOUT_SEC: Final[int] = 5

# Período de gracia inicial antes de que el scheduler empiece a procesar (segundos)
STARTUP_GRACE_PERIOD_SEC: Final[int] = 10

# Días hacia atrás para buscar alertas de Gmail
GMAIL_LOOKBACK_DAYS: Final[int] = 3
