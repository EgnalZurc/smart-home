"""
Scraper para fotocasa.es — DESHABILITADO.

Fotocasa ha cambiado su estructura de URLs y todas las variantes probadas
devuelven 404. Se deshabilita temporalmente para no bloquear el scraping.
Los portales activos son: pisos.com, habitaclia.com y Apify/Idealista.

Para rehabilitar: implementar nuevas URLs válidas en zones.py y descomentar
la lógica de scraping en este archivo.
"""
from __future__ import annotations
import logging
import httpx
from models import Property
from zones import Zone

logger = logging.getLogger(__name__)


def scrape_zone(zone: Zone, client: httpx.Client | None = None) -> list[Property]:
    """Fotocasa deshabilitado — retorna lista vacía."""
    logger.info("[fotocasa] Deshabilitado para zona %s (URLs 404). Skipping.", zone.id)
    return []
