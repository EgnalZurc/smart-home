"""
Wrapper para scraping de Idealista — DESHABILITADO (agosto 2026).

RAZON: Idealista usa DataDome como sistema anti-bot. Bloquea con 403
todas las peticiones desde IPs de datacenter o IPs residenciales
previamente identificadas como scrapers.

Intentos realizados:
  1. Apify actor pro100chok/idealista-scraper — 403 en todas las zonas
  2. httpx directo — 403 inmediato
  3. curl_cffi impersonando Chrome/Safari — 403 con DataDome activo
  4. curl_cffi impersonando Safari — 404 en las URLs de busqueda

Para rehabilitar este portal se necesita UNA de estas opciones:
  a) Proxy residencial espanol (IPRoyal, Brightdata, Oxylabs) + curl_cffi
  b) ScrapFly con plan de pago (asp=True devuelve HTML real desde ES)
     https://scrapfly.io/pricing — plan Discovery $30/mes, ~333k creditos
     Con ASP+residencial ~25 creditos/req → ~13.000 requests/mes
  c) Cuenta Apify con proxies residenciales propios configurados

Arquitectura preparada: cuando se disponga de proxy/ScrapFly,
reactivar IdealistaDirectScraper.scrape_zone() que implementa
el scraping HTML con los selectores correctos de Idealista.

Selectores verificados (scrapfly.io/blog/posts/how-to-scrape-idealista):
  - Listados: article.item
  - Link:     .item-link::attr(href)
  - Precio:   span[class*='item-price']::text
  - Detalles: .item-detail-char span::text  (hab, m2, etc.)
  - Tags:     .listing-tags-container span::text
  - Parking:  span.item-parking (presencia = tiene parking)

URL de busqueda con filtros (sin DataDome desde browser normal):
  https://www.idealista.com/venta-viviendas/{provincia}-provincia/
  con-garaje,con-jardin,3-habitaciones-o-mas/
  Paginacion: pagina-N.htm al final

Decision: deshabilitar hasta tener proxy residencial o ScrapFly de pago.
El free tier de ScrapFly (1000 creditos) es insuficiente para uso regular
(13 zonas x 3 paginas x ~25 creditos = ~975 creditos, agota en 1 run).
"""
from __future__ import annotations
import logging
from models import Property
from zones import Zone

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Tracker de uso mensual (conservado para cuando se reactive)
# ─────────────────────────────────────────────────────────────────────────────
class ApifyUsageTracker:
    """Stub conservado por compatibilidad. No hace nada mientras Apify esta deshabilitado."""
    def __init__(self, data_path: str) -> None:
        self._path = data_path

    @property
    def current_count(self) -> int:
        return 0

    @property
    def remaining(self) -> int:
        return 0

    def add(self, count: int) -> None:
        pass


class IdealistaApifyClient:
    """
    Cliente para Idealista — DESHABILITADO.
    Devuelve lista vacia en todas las zonas.
    Ver docstring del modulo para opciones de reactivacion.
    """

    def __init__(self, api_token: str, usage_tracker: ApifyUsageTracker) -> None:
        self._token = api_token
        self._tracker = usage_tracker
        logger.info(
            "[idealista] Portal deshabilitado — DataDome bloquea scraping. "
            "Ver apify_client_wrapper.py para opciones de reactivacion."
        )

    def scrape_zone(self, zone: Zone) -> list[Property]:
        """Idealista deshabilitado — DataDome activo."""
        logger.debug(
            "[idealista] Deshabilitado para zona %s — DataDome activo, se necesita "
            "proxy residencial o ScrapFly de pago.",
            zone.id,
        )
        return []

    def scrape_property_url(self, url: str, zone: Zone) -> Property | None:
        """Idealista deshabilitado."""
        logger.debug("[idealista] scrape_property_url deshabilitado: %s", url)
        return None
