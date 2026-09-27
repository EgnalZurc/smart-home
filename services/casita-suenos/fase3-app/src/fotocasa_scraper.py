"""
Scraper para fotocasa.es — DESHABILITADO (agosto 2026).

RAZON: Fotocasa es una Single Page Application (React/Next.js) que carga
todos los listings via JavaScript en el cliente. El HTML que devuelven los
servidores es solo el shell de la app — sin datos de anuncios.

No contiene __NEXT_DATA__ ni ningun JSON con listings.
Las URLs de busqueda (/es/comprar/casas/*/todas-las-zonas/l) dan 404.
La unica URL funcional encontrada es /casas-rurales/ pero tampoco
incluye los datos en el HTML estatico.

Para rehabilitar este portal se necesita:
  - Playwright + stealth en un servidor con navegador (no en la Pi)
  - O una cuenta de ScrapFly con plan de pago (asp=True, country="ES")
  - O un proxy residencial espanol + curl_cffi

Decisión: deshabilitar hasta tener infraestructura adecuada.
"""
from __future__ import annotations
import logging
import httpx
from models import Property
from zones import Zone

logger = logging.getLogger(__name__)


def scrape_zone(zone: Zone, client: httpx.Client | None = None) -> list[Property]:
    """Fotocasa deshabilitado — SPA, datos no disponibles en HTML estatico."""
    logger.debug(
        "[fotocasa] Deshabilitado para zona %s — portal SPA sin datos en HTML. "
        "Necesita Playwright o proxy residencial para funcionar.",
        zone.id,
    )
    return []
