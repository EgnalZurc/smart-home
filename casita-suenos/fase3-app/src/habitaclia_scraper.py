"""
Scraper para habitaclia.com.
Estructura HTML (verificada agosto 2026):
  - Listado: article.list-item-container
  - URL detalle: data-href o a[href*='comprar-casa']
  - Precio: span.list-item-price o texto en el articulo
  - Caracteristicas: p.list-item-feature  (ej: "55m2 - 2 habitaciones - 1 bano")
  - Descripcion: p.list-item-description

Workaround L2/L3:
  Habitaclia no tiene filtro de jardin/garaje en la URL de listado.
  Las URLs se construyen con parametros de filtro st= que incluyen
  equipamiento: st contiene codigos para caracteristicas.
  Alternativamente, si la URL incluye "jardin" o "garaje" en los parametros
  ya es garantia de que el portal ha filtrado.
  Si no hay garantia por URL, has_garden/has_garage quedan como inferencia
  de descripcion. El scorer usa L2/L3 como soft-limiters (ver scorer.py).
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
_BASE_URL = "https://www.habitaclia.com"


def _parse_listing_page(soup: BeautifulSoup, zone: Zone, now: datetime,
                         url_used: str = "") -> list[Property]:
    """
    Parsea una pagina de resultados de Habitaclia.
    Selector verificado agosto 2026: article.list-item-container
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
            title_el = article.select_one("h3.list-item-title a, h3 a, a[itemprop='name']")
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
                import re as _re
                m2 = _re.search(r"([\d][\d\.]+\.000)\s*€(?!\s*/\s*m)", text)
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

            rooms_m = re.search(r"(\d+)\s*hab", feature_text, re.I)
            size_m = re.search(r"(\d+)\s*m[²2]", feature_text, re.I)
            rooms_raw = rooms_m.group(0) if rooms_m else None
            size_raw = size_m.group(0) if size_m else None

            # Descripcion
            desc_el = article.select_one("p.list-item-description, [itemprop='description']")
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

            results.append(Property(
                portal=Portal.HABITACLIA,
                portal_id=portal_id,
                url=href_clean,
                zone_id=zone.id,
                title=title,
                price=price,
                size_m2=parse_size(size_raw),
                rooms=parse_rooms(rooms_raw) or (int(rooms_m.group(1)) if rooms_m else None),
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
                source="habitaclia_scraper",
            ))

        except Exception as e:
            logger.debug("[habitaclia] Error en articulo: %s", e)
            continue

    return results


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
                if page == 1:
                    url = base_url
                else:
                    # Habitaclia pagina con ?pagina=N
                    separator = "&" if "?" in base_url else "?"
                    url = f"{base_url}{separator}pagina={page}"

                logger.info("[habitaclia] Scraping %s", url)
                soup = get_html(url, client, delay=2.5)
                if not soup:
                    logger.warning("[habitaclia] Sin respuesta para %s", url)
                    break

                page_results = _parse_listing_page(soup, zone, now, url_used=url)

                if not page_results:
                    logger.info(
                        "[habitaclia] Zona %s — sin resultados en pagina %d, parando.",
                        zone.id, page
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
                    zone.id, page, len(page_results), new_count
                )

                if new_count == 0:
                    break

    finally:
        if own_client:
            client.close()

    logger.info("[habitaclia] Zona %s — total: %d propiedades", zone.id, len(results))
    return results
