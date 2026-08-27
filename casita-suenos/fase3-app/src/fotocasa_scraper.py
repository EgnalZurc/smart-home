"""
Scraper para fotocasa.es.

Fotocasa carga los resultados vía JSON embebido en el HTML (Next.js/SSR).
El bloque de datos se encuentra en un <script id="__NEXT_DATA__"> como JSON.
Esto es más estable que parsear HTML directamente y resistente a cambios de layout.

Estructura del JSON (ruta aproximada):
  props.pageProps.initialProps.properties[].

Campos extraídos por anuncio:
  - id, title, price, rooms, size, description, features, url
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any

import httpx

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

_BASE_URL = "https://www.fotocasa.es"


def _extract_next_data(soup) -> dict | None:
    """Extrae el JSON del bloque __NEXT_DATA__ de la página."""
    script = soup.find("script", {"id": "__NEXT_DATA__"})
    if not script:
        logger.debug("[fotocasa] No se encontró __NEXT_DATA__")
        return None
    try:
        return json.loads(script.string)
    except json.JSONDecodeError as e:
        logger.warning("[fotocasa] Error parseando __NEXT_DATA__: %s", e)
        return None


def _find_properties(data: dict) -> list[dict]:
    """
    Navega el árbol JSON de Next.js para encontrar la lista de propiedades.
    Fotocasa puede anidar los datos en distintas rutas según la versión.
    """
    candidates: list[dict] = []

    def _walk(node: Any, depth: int = 0) -> None:
        if depth > 8:
            return
        if isinstance(node, list):
            # Si es una lista con dicts que tienen 'id' y 'price' → propiedades
            if node and isinstance(node[0], dict) and "id" in node[0] and "price" in node[0]:
                candidates.append({"__list": node})
                return
            for item in node:
                _walk(item, depth + 1)
        elif isinstance(node, dict):
            if "id" in node and "price" in node and "title" in node:
                candidates.append(node)
                return
            for v in node.values():
                _walk(v, depth + 1)

    _walk(data)

    # Preferir listas sobre items sueltos
    for c in candidates:
        if "__list" in c:
            return c["__list"]
    return candidates


def _raw_to_property(item: dict, zone: Zone, now: datetime) -> Property | None:
    """Convierte un dict del JSON de Fotocasa en un Property normalizado."""
    try:
        portal_id = str(item.get("id", ""))
        if not portal_id:
            return None

        price_raw = str(item.get("price", "") or item.get("priceMain", ""))
        price = parse_price(price_raw)
        if not price:
            return None

        title = item.get("title", "") or item.get("name", "")
        url_path = item.get("url", "") or item.get("link", "")
        url = url_path if url_path.startswith("http") else (_BASE_URL + url_path)

        rooms_raw = str(item.get("rooms", "") or item.get("bedrooms", "") or "")
        size_raw = str(item.get("surface", "") or item.get("size", "") or "")

        description = item.get("description", "") or item.get("subtitle", "") or title

        # Extraer features/tags como lista de strings
        features_raw = item.get("features", []) or item.get("tags", []) or []
        extras: list[str] = []
        for f in features_raw:
            if isinstance(f, str):
                extras.append(f)
            elif isinstance(f, dict):
                extras.append(f.get("label", "") or f.get("name", "") or "")

        return Property(
            portal=Portal.FOTOCASA,
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
            source="fotocasa_scraper",
        )
    except Exception as e:
        logger.debug("[fotocasa] Error normalizando item %s: %s", item.get("id"), e)
        return None


def _scrape_page_html_fallback(soup, zone: Zone, now: datetime) -> list[Property]:
    """
    Fallback de parsing HTML si no está disponible __NEXT_DATA__.
    Busca artículos de anuncio directamente en el DOM.
    """
    results: list[Property] = []
    articles = soup.select("article[data-testid*='property'], article[class*='re-Card']")

    for article in articles:
        try:
            link = article.select_one("a[href]")
            if not link:
                continue
            href = link["href"]
            url = href if href.startswith("http") else (_BASE_URL + href)
            portal_id_m = re.search(r"/(\d+)/?", href)
            portal_id = portal_id_m.group(1) if portal_id_m else href

            price_el = article.select_one("[class*='price'], [data-testid*='price']")
            price_raw = price_el.get_text(strip=True) if price_el else ""
            price = parse_price(price_raw)
            if not price:
                continue

            title_el = article.select_one("h2, h3, [class*='title']")
            title = title_el.get_text(strip=True) if title_el else ""

            desc_el = article.select_one("[class*='description'], p")
            description = desc_el.get_text(" ", strip=True) if desc_el else title

            extras = [t.get_text(strip=True) for t in article.select("[class*='tag'], [class*='feature']")]

            results.append(Property(
                portal=Portal.FOTOCASA,
                portal_id=portal_id,
                url=url,
                zone_id=zone.id,
                title=title,
                price=price,
                size_m2=None,
                rooms=None,
                has_garage=infer_has_garage(description, extras),
                has_garden_or_plot=infer_has_garden(description, extras),
                piscina=infer_piscina(description, extras),
                has_internet_mention=not infer_no_internet(description),
                habitable=infer_habitable(description, title),
                description=description,
                first_seen=now,
                last_seen=now,
                source="fotocasa_scraper_fallback",
            ))
        except Exception as e:
            logger.debug("[fotocasa] Error en fallback HTML: %s", e)

    return results


def scrape_zone(zone: Zone, client: httpx.Client | None = None) -> list[Property]:
    """
    Scrape de todas las URLs configuradas en la zona para fotocasa.es.
    Pagina hasta MAX_PAGES por URL.
    """
    MAX_PAGES = 3
    own_client = client is None
    if own_client:
        client = make_client()

    results: list[Property] = []
    now = datetime.now()

    try:
        for base_url in zone.fotocasa_search_urls:
            for page in range(1, MAX_PAGES + 1):
                separator = "&" if "?" in base_url else "?"
                url = base_url if page == 1 else f"{base_url}{separator}page={page}"

                logger.info("[fotocasa] Scraping %s", url)
                soup = get_html(url, client, delay=3.0)
                if not soup:
                    break

                # Intentar vía __NEXT_DATA__ primero
                next_data = _extract_next_data(soup)
                if next_data:
                    items = _find_properties(next_data)
                    if not items:
                        logger.info("[fotocasa] Sin más resultados en página %d", page)
                        break
                    for item in items:
                        prop = _raw_to_property(item, zone, now)
                        if prop:
                            results.append(prop)
                    logger.info("[fotocasa] Zona %s — página %d: %d anuncios via JSON", zone.id, page, len(items))
                else:
                    # Fallback HTML
                    page_results = _scrape_page_html_fallback(soup, zone, now)
                    if not page_results:
                        logger.info("[fotocasa] Sin resultados HTML en página %d", page)
                        break
                    results.extend(page_results)
                    logger.info("[fotocasa] Zona %s — página %d: %d anuncios via HTML", zone.id, page, len(page_results))

    finally:
        if own_client:
            client.close()

    logger.info("[fotocasa] Zona %s — total: %d propiedades", zone.id, len(results))
    return results
