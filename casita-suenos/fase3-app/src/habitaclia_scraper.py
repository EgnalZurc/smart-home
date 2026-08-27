"""
Scraper para habitaclia.com.

Usa las URLs directas del campo habitaclia_search_urls de cada zona,
con el patron /casas-{ciudad}.htm (verificado OK agosto 2026).

La pagina .htm de Habitaclia es HTML clasico (no Next.js), por lo que
se parsea el DOM directamente sin __NEXT_DATA__.
"""
from __future__ import annotations
import logging
import re
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from models import Portal, Property
from scraper_base import (
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
_BASE_URL = "https://www.habitaclia.com"


def _parse_listing_page(soup: BeautifulSoup, zone: Zone, now: datetime) -> list[Property]:
    """
    Parsea una pagina de resultados de Habitaclia (.htm).
    Busca los articulos de cada anuncio en el DOM.
    """
    results: list[Property] = []

    # Habitaclia usa <article> con clase 'list-item' o similar
    articles = soup.select(
        "article.list-item, "
        "article[class*='item'], "
        "li[class*='item'], "
        "div[class*='property-item'], "
        "article"
    )

    if not articles:
        logger.debug("[habitaclia] No se encontraron articulos en la pagina")
        return results

    for article in articles:
        try:
            # URL y portal_id
            link = article.select_one("a[href]")
            if not link:
                continue
            href = str(link.get("href", ""))
            if not href or href == "#":
                continue
            url = href if href.startswith("http") else (_BASE_URL + href)

            # Extraer ID numerico de la URL (ej: /casa-en-zamora-12345678.htm)
            portal_id_m = re.search(r"-(\d{6,})(?:\.htm)?", href)
            if not portal_id_m:
                portal_id_m = re.search(r"/(\d{6,})", href)
            portal_id = portal_id_m.group(1) if portal_id_m else href

            # Precio
            price_el = article.select_one(
                "[class*='price'], [class*='precio'], span[class*='Price']"
            )
            price_raw = price_el.get_text(strip=True) if price_el else ""
            price = parse_price(price_raw)
            if not price:
                continue

            # Titulo
            title_el = article.select_one("h2, h3, [class*='title'], [class*='titulo']")
            title = title_el.get_text(strip=True) if title_el else ""

            # Descripcion
            desc_el = article.select_one("[class*='description'], [class*='descripcion'], p")
            description = desc_el.get_text(" ", strip=True) if desc_el else title

            # Features / extras (m2, habitaciones, etc.)
            extras: list[str] = [
                t.get_text(strip=True)
                for t in article.select(
                    "[class*='feature'], [class*='tag'], [class*='detail'], "
                    "[class*='characteristic'], li"
                )
            ]
            full_text = description + " " + " ".join(extras)

            # Habitaciones y superficie desde extras o texto
            rooms_raw = ""
            size_raw = ""
            rooms_m = re.search(r"(\d+)\s*hab", full_text, re.IGNORECASE)
            size_m = re.search(r"(\d+)\s*m[²2]", full_text, re.IGNORECASE)
            if rooms_m:
                rooms_raw = rooms_m.group(1)
            if size_m:
                size_raw = size_m.group(1)

            results.append(Property(
                portal=Portal.HABITACLIA,
                portal_id=portal_id,
                url=url,
                zone_id=zone.id,
                title=title,
                price=price,
                size_m2=parse_size(size_raw),
                rooms=parse_rooms(rooms_raw) or (int(rooms_raw) if rooms_raw.isdigit() else None),
                has_garage=infer_has_garage(description, extras),
                has_garden_or_plot=infer_has_garden(description, extras),
                piscina=infer_piscina(description, extras),
                has_internet_mention=not infer_no_internet(description),
                habitable=infer_habitable(description, title),
                description=description,
                first_seen=now,
                last_seen=now,
                source="habitaclia_scraper",
            ))
        except Exception as e:
            logger.debug("[habitaclia] Error en articulo: %s", e)
            continue

    return results


def _next_page_url(soup: BeautifulSoup, current_url: str, page: int) -> str | None:
    """Construye la URL de la siguiente pagina de Habitaclia."""
    # Habitaclia usa ?pagina=N o /pagina-N en la URL
    if "pagina=" in current_url:
        return re.sub(r"pagina=\d+", f"pagina={page}", current_url)
    if re.search(r"/pagina-\d+", current_url):
        return re.sub(r"/pagina-\d+", f"/pagina-{page}", current_url)
    # Primera vez: anadir pagina
    separator = "&" if "?" in current_url else "?"
    return f"{current_url}{separator}pagina={page}"


def scrape_zone(zone: Zone, client: httpx.Client | None = None) -> list[Property]:
    """Scrape de habitaclia.com para una zona usando habitaclia_search_urls."""
    if not zone.habitaclia_search_urls:
        logger.info("[habitaclia] Zona %s sin URLs configuradas, skipping.", zone.id)
        return []

    MAX_PAGES = 3
    own_client = client is None
    if own_client:
        client = make_client()

    results: list[Property] = []
    seen_ids: set[str] = set()
    now = datetime.now()

    try:
        for base_url in zone.habitaclia_search_urls:
            for page in range(1, MAX_PAGES + 1):
                url = base_url if page == 1 else _next_page_url(None, base_url, page)
                logger.info("[habitaclia] Scraping %s", url)

                soup = get_html(url, client, delay=2.5)
                if not soup:
                    logger.warning("[habitaclia] Sin respuesta para %s", url)
                    break

                page_results = _parse_listing_page(soup, zone, now)

                if not page_results:
                    logger.info("[habitaclia] Zona %s — sin resultados en pagina %d, parando.", zone.id, page)
                    break

                # Deduplicar por portal_id
                new_count = 0
                for prop in page_results:
                    if prop.portal_id not in seen_ids:
                        seen_ids.add(prop.portal_id)
                        results.append(prop)
                        new_count += 1

                logger.info(
                    "[habitaclia] Zona %s — pagina %d: %d anuncios (%d nuevos)",
                    zone.id, page, len(page_results), new_count
                )

                if new_count == 0:
                    break  # pagina sin novedades, no merece la pena seguir

    finally:
        if own_client:
            client.close()

    logger.info("[habitaclia] Zona %s — total: %d propiedades", zone.id, len(results))
    return results
