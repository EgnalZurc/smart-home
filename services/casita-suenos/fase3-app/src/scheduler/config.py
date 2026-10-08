"""
Constantes y configuración por defecto del scheduler de Casita Sueños.

Agrupa los valores que antes vivían al principio de ``casita_scheduler.py``.
No contiene lógica: solo datos de configuración de los jobs periódicos.
"""

from __future__ import annotations

from datetime import time as dtime

# Zonas top 8 por puntuación — para el scraping semanal de Apify (free tier)
TOP_ZONES_FOR_APIFY: list[str] = [
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
SCRAPING_DAYS: set[int] = {0, 3}
SCRAPING_HOUR: dtime = dtime(7, 0)

# Día del resumen semanal (6=domingo)
SUMMARY_DAY: int = 6
SUMMARY_HOUR: dtime = dtime(9, 0)

# Intervalo del check de Gmail (segundos)
GMAIL_CHECK_INTERVAL_SEC: int = 30 * 60  # 30 minutos

# Intervalo del loop principal (segundos) — cada minuto comprueba si toca algo
LOOP_TICK_SEC: int = 60

# Distancia máxima (km) aceptada por el fallback geográfico de Nominatim
NOMINATIM_MAX_DIST_KM: float = 200.0
