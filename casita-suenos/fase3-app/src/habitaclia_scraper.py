"""
Scraper para habitaclia.com.

Habitaclia (grupo Adevinta, mismo que Fotocasa) también usa Next.js y
expone un __NEXT_DATA__ en el HTML. La estructura del JSON es similar
a Fotocasa pero con ligeras diferencias en los nombres de campo.

Se reutiliza la misma lógica de extracción con adaptaciones.
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

_BASE_URL = "https://www.habitaclia.com"


def _extract_next_data(soup) -> dict | None:
    script = soup.find("script", {"id": "__NEXT_DATA__"})
    if not script:
        return None
    try:
        return json.loads(script.string)
    except json.JSONDecodeError:
        return None


def _find_properties(data: dict) -> list[dict]:
    """Navega el JSON de Habitaclia buscando listas de propiedades."""
    candidates: list[dict] = []

    def _walk(node: Any, depth: int = 0) -> None:
        if depth > 8:
            return
        if isinstance(node, list):
            if node and isinstance(node[0], dict) and (
                "id" in node[0] or "propertyCode" in node[0]
            ):
                candidates.append({"__list": node})
                return
            for item in node:
                _walk(item, depth + 1)
        elif isinstance(node, dict):
            for v in node.values():
                _walk(v, depth + 1)

    _walk(data)
    for c in candidates:
        if "__list" in c:
            return c["__list"]
    return []


def _raw_to_property(item: dict, zone: Zone, now: datetime) -> Property | None:
    try:
        portal_id = str(
            item.get("id") or item.get("propertyCode") or item.get("listingId") or ""
        )
        if not portal_id:
            return None

        price_raw = str(item.get("price") or item.get("priceInfo", {}).get("amount", "") or "")
        price = parse_price(price_raw)
        if not price:
            return None

        title = item.get("title") or item.get("propertyTitle") or ""
        url_path = item.get("url") or item.get("detailUrl") or ""
        url = url_path if url_path.startswith("http") else (_BASE_URL + url_path)

        rooms_raw = str(item.get("rooms") or item.get("bedrooms") or "")
        size_raw = str(item.get("surface") or item.get("area") or "")
        description = item.get("description") or item.get("subtitle") or title

        features_raw = item.get("features") or item.get("tags") or []
        extras: list[str] = []
        for f in features_raw:
            if isinstance(f, str):
                extras.append(f)
            elif isinstance(f, dict):
                extras.append(f.get("label") or f.get("name") or "")

        return Property(
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
        )
    except Exception as e:
        logger.debug("[habitaclia] Error normalizando item %s: %s", item.get("id"), e)
        return None


def _build_search_url(zone: Zone, page: int) -> list[str]:
    """
    Genera URLs de búsqueda para Habitaclia a partir de las keywords de Idealista
    como aproximación (Habitaclia usa búsqueda por nombre de ciudad/provincia).
    """
    urls = []
    for keyword in zone.idealista_alert_keywords[:2]:  # máx 2 keywords por zona
        keyword_slug = keyword.lower().replace(" ", "-").replace("'", "")
        base = f"{_BASE_URL}/compra-casas/{keyword_slug}/"
        url = base if page == 1 else f"{base}?pagina={page}"
        urls.append(url)
    return urls


def scrape_zone(zone: Zone, client: httpx.Client | None = None) -> list[Property]:
    """Scrape de habitaclia.com para una zona."""
    MAX_PAGES = 2
    own_client = client is None
    if own_client:
        client = make_client()

    results: list[Property] = []
    now = datetime.now()

    try:
        for page in range(1, MAX_PAGES + 1):
            urls = _build_search_url(zone, page)
            for url in urls:
                logger.info("[habitaclia] Scraping %s", url)
                soup = get_html(url, client, delay=3.0)
                if not soup:
                    continue

                next_data = _extract_next_data(soup)
                if next_data:
                    items = _find_properties(next_data)
                    for item in items:
                        prop = _raw_to_property(item, zone, now)
                        if prop:
                            results.append(prop)
                    logger.info("[habitaclia] Zona %s — %d anuncios", zone.id, len(items))
                else:
                    # Fallback: buscar artículos directamente
                    articles = soup.select("article, li[class*='item']")
                    for article in articles:
                        try:
                            link = article.select_one("a[href]")
                            if not link:
                                continue
                            href = link["href"]
                            url_prop = href if href.startswith("http") else (_BASE_URL + href)
                            portal_id_m = re.search(r"/(\d+)/?", href)
                            portal_id = portal_id_m.group(1) if portal_id_m else href

                            price_el = article.select_one("[class*='price']")
                            price_raw = price_el.get_text(strip=True) if price_el else ""
                            price = parse_price(price_raw)
                            if not price:
                                continue

                            title_el = article.select_one("h2, h3")
                            title = title_el.get_text(strip=True) if title_el else ""
                            description = title
                            extras: list[str] = []

                            results.append(Property(
                                portal=Portal.HABITACLIA,
                                portal_id=portal_id,
                                url=url_prop,
                                zone_id=zone.id,
                                title=title,
                                price=price,
                                size_m2=None,
                                rooms=None,
                                has_garage=infer_has_garage(description, extras),
                                has_garden_or_plot=infer_has_garden(description, extras),
                                piscina=infer_piscina(description, extras),
                                has_internet_mention=True,
                                habitable=infer_habitable(description, title),
                                description=description,
                                first_seen=now,
                                last_seen=now,
                                source="habitaclia_scraper_fallback",
                            ))
                        except Exception:
                            continue

    finally:
        if own_client:
            client.close()

    logger.info("[habitaclia] Zona %s — total: %d propiedades", zone.id, len(results))
    return results
