"""
Scraper para pisos.com.

Estructura HTML observada (agosto 2026):
  - Listado: cada anuncio en un <article> o <li> con class que contiene "item-"
  - Precio: <span class="price-row__price"> o texto con "€"
  - Habitaciones / m²: en el subtítulo o en spans separados
  - Título: <a class="item-link"> o <h2 class="item-title">
  - URL: href del enlace principal del anuncio

Estrategia:
  - Buscar todos los bloques de anuncio por selector CSS robusto
  - Extraer precio, título, URL, habitaciones, m²
  - Inferir campos booleanos de la descripción / tags
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

import httpx

from models import Piscina, Portal, Property
from scraper_base import (
    RawListing,
    get_html,
    infer_habitable,
    infer_has_garage,
    infer_has_garden,
    infer_no_internet,
    infer_piscina,
    make_client,
    parse_price,
    parse_rooms,
    parse_size,
)
from zones import Zone

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.pisos.com"


def _extract_listings(soup) -> list[RawListing]:
    """Extrae anuncios crudos del HTML de una página de resultados de pisos.com."""
    listings: list[RawListing] = []

    # pisos.com usa contenedores de anuncio identificables por clase o estructura
    # Probamos varios selectores para ser resilientes a cambios de layout
    containers = (
        soup.select("li[class*='item']")
        or soup.select("article[class*='item']")
        or soup.select("div[class*='item-info']")
    )

    if not containers:
        logger.warning("[pisos] No se encontraron contenedores de anuncio")
        return listings

    for container in containers:
        try:
            # URL y portal_id
            link = container.select_one("a[href*='/venta/']") or container.select_one("a[href]")
            if not link:
                continue
            href = link.get("href", "")
            if not href.startswith("http"):
                href = _BASE_URL + href
            # ID del portal: último segmento numérico de la URL
            portal_id_match = re.search(r"/(\d+)/?$", href)
            portal_id = portal_id_match.group(1) if portal_id_match else href

            # Título
            title_el = (
                container.select_one("h2")
                or container.select_one("[class*='title']")
                or link
            )
            title = title_el.get_text(strip=True) if title_el else ""

            # Precio
            price_el = container.select_one("[class*='price']")
            price_raw = price_el.get_text(strip=True) if price_el else ""

            # Habitaciones y m²
            detail_els = container.select("[class*='detail'], [class*='feature'], span")
            rooms_raw = None
            size_raw = None
            for el in detail_els:
                text = el.get_text(strip=True)
                if re.search(r"\d+\s*(hab|dorm)", text, re.I):
                    rooms_raw = text
                elif re.search(r"\d+\s*m[²2]", text, re.I):
                    size_raw = text

            # Descripción corta (si existe)
            desc_el = container.select_one("[class*='desc'], p")
            description = desc_el.get_text(" ", strip=True) if desc_el else title

            # Extras/tags
            extras = [
                t.get_text(strip=True)
                for t in container.select("[class*='tag'], [class*='feature'], [class*='extra']")
                if t.get_text(strip=True)
            ]

            if price_raw and title:
                listings.append(RawListing(
                    portal_id=portal_id,
                    url=href,
                    title=title,
                    price_raw=price_raw,
                    rooms_raw=rooms_raw,
                    size_raw=size_raw,
                    description=description,
                    extras=extras,
                ))
        except Exception as e:
            logger.debug("[pisos] Error parseando contenedor: %s", e)
            continue

    return listings


def _to_property(raw: RawListing, zone: Zone, now: datetime) -> Property | None:
    """Convierte un RawListing en un Property normalizado."""
    price = parse_price(raw.price_raw)
    if not price:
        return None

    return Property(
        portal=Portal.PISOS,
        portal_id=raw.portal_id,
        url=raw.url,
        zone_id=zone.id,
        title=raw.title,
        price=price,
        size_m2=parse_size(raw.size_raw),
        rooms=parse_rooms(raw.rooms_raw),
        has_garage=infer_has_garage(raw.description, raw.extras),
        has_garden_or_plot=infer_has_garden(raw.description, raw.extras),
        piscina=infer_piscina(raw.description, raw.extras),
        has_internet_mention=not infer_no_internet(raw.description),
        habitable=infer_habitable(raw.description, raw.title),
        description=raw.description,
        first_seen=now,
        last_seen=now,
        source="pisos_scraper",
    )


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
    now = datetime.now()

    try:
        for base_url in zone.pisos_search_urls:
            for page in range(1, MAX_PAGES + 1):
                url = base_url if page == 1 else f"{base_url}pagina-{page}/"
                logger.info("[pisos] Scraping %s", url)
                soup = get_html(url, client, delay=2.5)
                if not soup:
                    break

                raw_listings = _extract_listings(soup)
                if not raw_listings:
                    logger.info("[pisos] Sin más resultados en página %d", page)
                    break

                for raw in raw_listings:
                    prop = _to_property(raw, zone, now)
                    if prop:
                        results.append(prop)

                logger.info("[pisos] Zona %s — página %d: %d anuncios", zone.id, page, len(raw_listings))

    finally:
        if own_client:
            client.close()

    logger.info("[pisos] Zona %s — total: %d propiedades", zone.id, len(results))
    return results
