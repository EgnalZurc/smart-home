"""
Dataclasses de estado del scheduler de Casita Sueños.

Se extraen de ``casita_scheduler.py`` para separar los modelos de datos del
estado del orquestador de la lógica. Se re-exportan desde ``casita_scheduler``
para no romper los imports existentes (``from casita_scheduler import ...``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ScraperError:
    """Registro de un fallo de scraper para el estado del dashboard."""

    portal: str
    zone_id: str
    error: str
    detected_at: datetime = field(default_factory=datetime.now)


@dataclass
class SchedulerStatus:
    """Estado del scheduler para el endpoint del dashboard."""

    running: bool
    last_scraping: datetime | None
    last_gmail_check: datetime | None
    last_fotocasa_check: datetime | None
    last_summary: datetime | None
    last_scraping_result: str  # "ok", "ok_with_errors", "error", "never"
    total_properties: int
    radar_count: int
    dismissed_count: int
    scraper_errors: list[ScraperError]
    top_properties: list[dict]
