"""
Paquete de módulos cohesivos del scheduler de Casita Sueños.

El orquestador principal (CasitaScheduler) vive en ``casita_scheduler.py``.
Este paquete agrupa la lógica extraída en módulos enfocados:

  - :mod:`scheduler.config`         — constantes y configuración de scheduling.
  - :mod:`scheduler.models`         — dataclasses de estado (ScraperError, SchedulerStatus).
  - :mod:`scheduler.zone_inference` — inferencia de zona a partir de hints/URLs/Nominatim.
  - :mod:`scheduler.formatters`     — construcción de los mensajes de Telegram.
  - :mod:`scheduler.idealista`      — scraping de la ficha de una propiedad de Idealista.

La API pública del scheduler (CasitaScheduler y sus métodos) no cambia: estos
módulos contienen funciones puras que el orquestador invoca o delega.
"""

from __future__ import annotations

from scheduler.models import SchedulerStatus, ScraperError

__all__ = ["ScraperError", "SchedulerStatus"]
