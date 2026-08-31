"""
Scraper para pisos.com.
Estructura HTML (verificada agosto 2026):
  - Cada anuncio: <div class="ad-preview ...">
  - Precio: <span class="ad-preview__price">
  - Titulo: <a class="ad-preview__title">
  - Subtitulo/zona: <p class="ad-preview__subtitle">
  - Caracteristicas: <p class="ad-preview__char">  (ej: "3 habs.", "120 m2")
  - Descripcion: <p class="ad-preview__description">

Workaround L2/L3 (garaje y jardin):
  Las URLs de busqueda incluyen filtro /jardin/ y /garaje/ en la ruta.
  Si la URL usada contiene estos segmentos, todos los resultados
  estan garantizados por el portal → se marcan has_garden=True, has_garage=True.
"""
from __future__ import annotations
import logging
import re
from datetime import datetime

import httpx

from models import Portal, Property
from scraper_base import (
    get_html,
    infer_ac, infer_ac_type,
    infer_habitable, infer_habitability,
    infer_has_garage, infer_has_garden,
    infer_garage_type,
    infer_internet, infer_no_internet,
    infer_piscina,
    infer_terrain_m2,
    make_client,
    parse_price, parse_rooms, parse_size,
)
from models import GarageType, Habitability, Internet, Piscina, Portal, Property
from zones import Zone

logger = logging.getLogger(__name__)
_BASE_URL = "https://www.pisos.com"


def _url_guarantees_garden(url: str) -> bool:
    """True si la URL ya filtra por jardin en el portal."""
    return "/jardin/" in url.lower() or "jardin=1" in url.lower()


def _url_guarantees_garage(url: str) -> bool:
    """True si la URL ya filtra por garaje en el portal."""
    return "/garaje/" in url.lower() or "garaje=1" in url.lower()


def _extract_listings(soup, base_url: str, zone: Zone, now: datetime) -> list[Property]:
    """Extrae anuncios del HTML de una pagina de resultados de pisos.com."""
    # Selector verificado agosto 2026: div.ad-preview
    containers = soup.select("div.ad-preview")
    if not containers:
        logger.warning("[pisos] No se encontraron contenedores ad-preview")
        return []

    # Si la URL de busqueda incluye filtros de portal, usarlos como garantia
    guaranteed_garden = _url_guarantees_garden(base_url)
    guaranteed_garage = _url_guarantees_garage(base_url)

    results: list[Property] = []
    for container in containers:
        try:
            # URL y portal_id: en data-lnk-href o en el enlace del titulo
            href = container.get("data-lnk-href", "") or container.get("id", "")
            link = container.select_one("a.ad-preview__title, a[href]")
            if link:
                link_href = link.get("href", "")
                if link_href and not href:
                    href = link_href

            if not href:
                continue
            if not href.startswith("http"):
                href = _BASE_URL + href

            # portal_id: segmento numerico al final de la URL o ID del div
            raw_id = container.get("id", "")  # ej: "39223281199.100500"
            portal_id = raw_id if raw_id else re.sub(r"[^0-9]", "", href)[-12:] or href

            # Titulo
            title_el = container.select_one("a.ad-preview__title, h2, h3")
            title = title_el.get_text(strip=True) if title_el else ""

            # Precio
            price_el = container.select_one("span.ad-preview__price, [class*='price']")
            price_raw = price_el.get_text(strip=True) if price_el else ""
            price = parse_price(price_raw)
            if not price:
                continue

            # Habitaciones y m2: en p.ad-preview__char
            chars = [c.get_text(strip=True) for c in container.select("p.ad-preview__char")]
            rooms_raw = next((c for c in chars if re.search(r"hab", c, re.I)), None)
            size_raw = next((c for c in chars if re.search(r"m[²2]", c, re.I)), None)

            # Descripcion
            desc_el = container.select_one("p.ad-preview__description, p.ad-preview__subtitle")
            description = desc_el.get_text(" ", strip=True) if desc_el else title

            # Extras: textos de badges y tags
            extras = [
                t.get_text(strip=True)
                for t in container.select("[class*='tag'], [class*='badge'], [class*='product-top-tag']")
                if t.get_text(strip=True)
            ]

            # Garaje y jardin: si la URL ya filtra, es garantia; si no, inferir del texto
            has_garden = guaranteed_garden or infer_has_garden(description, extras)
            has_garage = guaranteed_garage or infer_has_garage(description, extras)

            results.append(Property(
                portal=Portal.PISOS,
                portal_id=portal_id,
                url=href,
                zone_id=zone.id,
                title=title,
                price=price,
                size_m2=parse_size(size_raw),
                rooms=parse_rooms(rooms_raw),
                has_garden_or_plot=has_garden,
                terrain_m2=infer_terrain_m2(description, extras),
                garage_type=infer_garage_type(description, extras),
                habitability=infer_habitability(description, title),
                internet=infer_internet(description, extras),
                has_garage=has_garage,
                has_ac=(lambda t: t[0])(infer_ac_type(description, extras)),
                has_ac_preinstalled=(lambda t: t[1])(infer_ac_type(description, extras)),
                piscina=infer_piscina(description, extras),
                has_internet_mention=not infer_no_internet(description),
                habitable=infer_habitable(description, title),
                description=description,
                first_seen=now,
                last_seen=now,
                source="pisos_scraper",
            ))

        except Exception as e:
            logger.debug("[pisos] Error parseando anuncio: %s", e)
            continue

    return results


def scrape_zone(zone: Zone, client: httpx.Client | None = None) -> list[Property]:
    """
    Scrape de todas las URLs configuradas en la zona para pisos.com.
    Pagina hasta MAX_PAGES por URL.
    """
    MAX_PAGES = 3
    own_client = client is None
    if own_client:
        client = make_client()

    results: list[Property] = []
    seen_ids: set[str] = set()
    now = datetime.now()

    try:
        for base_url in zone.pisos_search_urls:
            for page in range(1, MAX_PAGES + 1):
                url = base_url if page == 1 else f"{base_url}pagina-{page}/"
                logger.info("[pisos] Scraping %s", url)

                soup = get_html(url, client, delay=2.5)
                if not soup:
                    logger.warning("[pisos] Sin respuesta para %s", url)
                    break

                page_results = _extract_listings(soup, base_url, zone, now)
                if not page_results:
                    logger.info("[pisos] Sin resultados en pagina %d, parando.", page)
                    break

                new_count = 0
                for prop in page_results:
                    if prop.portal_id not in seen_ids:
                        seen_ids.add(prop.portal_id)
                        results.append(prop)
                        new_count += 1

                logger.info(
                    "[pisos] Zona %s — pagina %d: %d anuncios (%d nuevos)",
                    zone.id, page, len(page_results), new_count
                )
                if new_count == 0:
                    break
    finally:
        if own_client:
            client.close()

    logger.info("[pisos] Zona %s — total: %d propiedades", zone.id, len(results))
    return results
