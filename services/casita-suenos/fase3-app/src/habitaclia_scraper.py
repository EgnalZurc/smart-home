"""
Scraper for habitaclia.com real estate portal.

This module implements the scraping logic for Habitaclia, one of Spain's
major real estate listing platforms. It extracts property listings from
search result pages and normalizes them into Property objects.

HTML Structure (verified August 2026):
    - Listing container: article.list-item-container
    - Detail URL: data-href attribute or a[href*='comprar-casa']
    - Price: span.list-item-price or text within article
    - Features: p.list-item-feature (e.g., "55m2 - 2 habitaciones - 1 baño")
    - Description: p.list-item-description

Workaround for L2/L3 Rubric (garden/garage):
    Habitaclia doesn't have garden/garage filters in the listing URL path.
    URLs use st= parameters with equipment codes. If the URL includes
    specific filter codes, garden/garage presence is guaranteed by the
    portal. Otherwise, has_garden/has_garage are inferred from description
    text. The scorer uses L2/L3 as soft-limiters (see scorer.py).

Example:
    >>> from habitaclia_scraper import scrape_zone
    >>> from zones import Zone
    >>> zone = Zone(
    ...     id="horta-nord",
    ...     name="L'Horta Nord",
    ...     habitaclia_search_urls=["https://www.habitaclia.com/comprar/..."]
    ... )
    >>> properties = scrape_zone(zone)
    >>> len(properties)
    42
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

import httpx
from bs4 import BeautifulSoup
from config import BASE_URLS, SCRAPER_CONFIG
from models import Portal, Property
from scraper_base import (
    get_html,
    infer_ac_type,
    infer_garage_type,
    infer_habitability,
    infer_habitable,
    infer_has_garage,
    infer_has_garden,
    infer_internet,
    infer_no_internet,
    infer_piscina,
    infer_terrain_m2,
    make_client,
    parse_price,
    parse_rooms,
    parse_size,
)
from zones import Zone

logger = logging.getLogger(__name__)
_BASE_URL = BASE_URLS["habitaclia"]


def _parse_listing_page(
    soup: BeautifulSoup, zone: Zone, now: datetime, url_used: str = ""
) -> list[Property]:
    """
    Parse a Habitaclia search results page into Property objects.

    Extracts all listing cards from the HTML and converts them to normalized
    Property objects. Handles various HTML structures and gracefully skips
    unparseable listings.

    Args:
        soup: BeautifulSoup object of the search results page.
        zone: Zone configuration for the current search.
        now: Timestamp to use for first_seen/last_seen fields.
        url_used: The URL that was fetched (for logging/debugging).

    Returns:
        List of Property objects extracted from the page. May be empty
        if no valid listings found.

    Note:
        Primary selector verified August 2026: article.list-item-container
        Falls back to article[data-href] if primary selector fails.
    """
    # Selector principal verificado
    articles = soup.select("article.list-item-container")

    if not articles:
        # Fallback a cualquier article con data-href
        articles = soup.select("article[data-href]")

    if not articles:
        logger.debug("[habitaclia] No se encontraron articulos list-item-container")
        return []

    results: list[Property] = []

    for article in articles:
        try:
            # URL: data-href tiene la URL limpia del anuncio
            href = article.get("data-href", "")
            if not href:
                link = article.select_one("a[href*='comprar-casa'], h3 a")
                href = link.get("href", "") if link else ""
            if not href:
                continue
            if not href.startswith("http"):
                href = _BASE_URL + href
            # Limpiar parametros de tracking (?f=&st=...)
            href_clean = href.split("?")[0]

            # portal_id: en data-id o extraido de la URL
            portal_id = article.get("data-id", "")
            if not portal_id:
                m = re.search(r"-i(\d+)\.htm", href_clean)
                portal_id = m.group(1) if m else href_clean

            # Titulo
            title_el = article.select_one(
                "h3.list-item-title a, h3 a, a[itemprop='name']"
            )
            title = title_el.get_text(strip=True) if title_el else ""

            # Precio: puede estar en varias clases
            price_el = article.select_one(
                "span.list-item-price, [class*='list-item-price'], "
                "[itemprop='price'], [class*='price']"
            )
            price_raw = price_el.get_text(strip=True) if price_el else ""
            # Ignorar si es precio/m2 en vez de precio total
            if "/m" in price_raw.lower() or "€/m" in price_raw:
                price_raw = ""
            price = parse_price(price_raw)
            if not price:
                text = article.get_text(" ")
                # Buscar solo precios con ".000 EUR" (precios totales reales)
                m2 = re.search(r"([\d][\d\.]+\.000)\s*€(?!\s*/\s*m)", text)
                if m2:
                    price = parse_price(m2.group(0))
            if not price:
                # buscar en todo el articulo el primer patron de precio
                text = article.get_text(" ")
                m = re.search(r"([\d\.]+)\s*€", text)
                if m:
                    price = parse_price(m.group(0))
            if not price:
                continue

            # Caracteristicas: p.list-item-feature tiene "55m2 - 2 habitaciones - 1 bano"
            feature_el = article.select_one("p.list-item-feature")
            feature_text = feature_el.get_text(" ", strip=True) if feature_el else ""

            rooms_m = re.search(r"(\d+)\s*hab", feature_text, re.IGNORECASE)
            size_m = re.search(r"(\d+)\s*m[²2]", feature_text, re.IGNORECASE)
            rooms_raw = rooms_m.group(0) if rooms_m else None
            size_raw = size_m.group(0) if size_m else None

            # Descripcion
            desc_el = article.select_one(
                "p.list-item-description, [itemprop='description']"
            )
            description = desc_el.get_text(" ", strip=True) if desc_el else title

            # Extras: tags de equipamiento en el listado (si existen)
            extras: list[str] = [
                t.get_text(strip=True)
                for t in article.select("[class*='tag'], [class*='feature-item'], li")
                if t.get_text(strip=True)
            ]

            # Garaje y jardin: inferir de descripcion + extras
            # (Habitaclia no garantiza por URL — ver scorer soft-limiter)
            has_garden = infer_has_garden(description + " " + feature_text, extras)
            has_garage = infer_has_garage(description + " " + feature_text, extras)

            results.append(
                Property(
                    portal=Portal.HABITACLIA,
                    portal_id=portal_id,
                    url=href_clean,
                    zone_id=zone.id,
                    title=title,
                    price=price,
                    size_m2=parse_size(size_raw),
                    rooms=parse_rooms(rooms_raw)
                    or (int(rooms_m.group(1)) if rooms_m else None),
                    has_garden_or_plot=has_garden,
                    terrain_m2=infer_terrain_m2(description, extras),
                    garage_type=infer_garage_type(description, extras),
                    habitability=infer_habitability(description, title),
                    internet=infer_internet(description, extras),
                    has_garage=has_garage,
                    has_ac=(lambda t: t[0])(infer_ac_type(description, extras)),
                    has_ac_preinstalled=(lambda t: t[1])(
                        infer_ac_type(description, extras)
                    ),
                    piscina=infer_piscina(description, extras),
                    has_internet_mention=not infer_no_internet(description),
                    habitable=infer_habitable(description, title),
                    description=description,
                    first_seen=now,
                    last_seen=now,
                    source="habitaclia_scraper",
                )
            )

        except Exception as e:
            logger.debug("[habitaclia] Error en articulo: %s", e)
            continue

    return results


def scrape_zone(zone: Zone, client: httpx.Client | None = None) -> list[Property]:
    """
    Scrape Habitaclia listings for a zone.

    Iterates through all configured search URLs for the zone, paginating
    up to MAX_PAGES per URL. Deduplicates results by portal_id.

    Args:
        zone: Zone configuration with habitaclia_search_urls list.
        client: Optional httpx.Client to reuse. If None, creates and
            closes a new client.

    Returns:
        List of unique Property objects found across all search URLs.
        Empty list if zone has no configured URLs or all requests fail.

    Example:
        >>> zone = Zone(id="test", habitaclia_search_urls=["https://..."])
        >>> properties = scrape_zone(zone)
        >>> print(f"Found {len(properties)} listings")
    """
    if not zone.habitaclia_search_urls:
        logger.info("[habitaclia] Zona %s sin URLs configuradas, skipping.", zone.id)
        return []

    max_pages = SCRAPER_CONFIG["max_pages"]
    own_client = client is None
    if own_client:
        client = make_client()

    results: list[Property] = []
    seen_ids: set[str] = set()
    now = datetime.now()

    try:
        for base_url in zone.habitaclia_search_urls:
            for page in range(1, max_pages + 1):
                if page == 1:
                    url = base_url
                else:
                    # Habitaclia pagina con ?pagina=N
                    separator = "&" if "?" in base_url else "?"
                    url = f"{base_url}{separator}pagina={page}"

                logger.info("[habitaclia] Scraping %s", url)
                soup = get_html(url, client)
                if not soup:
                    logger.warning("[habitaclia] Sin respuesta para %s", url)
                    break

                page_results = _parse_listing_page(soup, zone, now, url_used=url)

                if not page_results:
                    logger.info(
                        "[habitaclia] Zona %s — sin resultados en pagina %d, parando.",
                        zone.id,
                        page,
                    )
                    break

                new_count = 0
                for prop in page_results:
                    if prop.portal_id not in seen_ids:
                        seen_ids.add(prop.portal_id)
                        results.append(prop)
                        new_count += 1

                logger.info(
                    "[habitaclia] Zona %s — pagina %d: %d anuncios (%d nuevos)",
                    zone.id,
                    page,
                    len(page_results),
                    new_count,
                )

                if new_count == 0:
                    break

    finally:
        if own_client:
            client.close()

    logger.info("[habitaclia] Zona %s — total: %d propiedades", zone.id, len(results))
    return results
