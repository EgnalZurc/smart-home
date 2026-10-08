"""
Scraping de la ficha de una propiedad de Idealista a partir de una alerta de correo.

Extraído de ``casita_scheduler._scrape_idealista_property``. El orquestador
mantiene un método del mismo nombre que delega aquí, de modo que los tests que
parchean ``httpx.Client`` y llaman ``scheduler._scrape_idealista_property``
siguen funcionando sin cambios.
"""

from __future__ import annotations

import logging
from datetime import datetime

from models import Piscina, Portal, Property
from scraper_base import (
    infer_ac,
    infer_ac_type,
    infer_garage_type,
    infer_habitability,
    infer_habitable,
    infer_has_garage,
    infer_has_garden,
    infer_internet,
    infer_piscina,
    infer_terrain_m2,
    parse_price,
    parse_rooms,
    parse_size,
)

logger = logging.getLogger(__name__)


def scrape_idealista_property(alert, zone) -> Property | None:
    """
    Descarga y parsea la ficha de Idealista de ``alert``. Si Idealista bloquea
    el scraping (403) o faltan datos, cae en los datos del correo. Devuelve
    ``None`` si no hay precio ni en la ficha ni en el correo.
    """
    import httpx
    from bs4 import BeautifulSoup

    title, price, rooms, size_m2, desc = (
        alert.title,
        alert.price,
        alert.rooms,
        alert.size_m2,
        "",
    )
    has_garage, has_garden, has_ac_v, piscina = False, False, False, Piscina.NINGUNA
    feats: list[str] = []
    try:
        hdrs = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept-Language": "es-ES,es;q=0.9",
        }
        with httpx.Client(headers=hdrs, follow_redirects=True, timeout=15) as client:
            r = client.get(alert.url)
            if r.status_code == 200 and len(r.text) > 5000:
                soup = BeautifulSoup(r.text, "html.parser")
                h1 = soup.select_one("h1 .main-info__title-main, h1")
                if h1:
                    title = h1.get_text(strip=True)
                pe = soup.select_one(".info-data-price span, [class*=info-data-price]")
                if pe:
                    pp = parse_price(pe.get_text(strip=True))
                    if pp:
                        price = pp
                de = soup.select_one("div.comment, .adCommentsLanguage")
                if de:
                    desc = de.get_text(" ", strip=True)
                feats = [
                    f.get_text(strip=True)
                    for f in soup.select(
                        ".details-property-feature li, .feature-details li"
                    )
                ]
                ft = desc + " " + " ".join(feats)
                r2 = parse_rooms(ft)
                if r2:
                    rooms = r2
                s2 = parse_size(ft)
                if s2:
                    size_m2 = s2
                has_garage = infer_has_garage(ft, feats)
                has_garden = infer_has_garden(ft, feats)
                has_ac_v = infer_ac(ft, feats)
                piscina = Piscina(infer_piscina(ft, feats))
                logger.info("[casita] Ficha Idealista OK: %s", alert.url)
            else:
                logger.warning(
                    "[casita] Idealista bloqueo status=%d: %s",
                    r.status_code,
                    alert.url,
                )
    except Exception as e:
        logger.warning("[casita] Error scraping %s: %s", alert.url, e)
    # Fallback al precio del email si el scraping fue bloqueado (403)
    if not price and alert.price:
        price = alert.price
        logger.info("[casita] Precio del email como fallback: %d EUR", price)
    if not rooms and alert.rooms:
        rooms = alert.rooms
    if not size_m2 and alert.size_m2:
        size_m2 = alert.size_m2
    if not price:
        logger.debug("[casita] Sin precio para %s, descartando", alert.url)
        return None
    if not has_garden:
        has_garden = True  # Idealista ya filtro jardin
    if not has_garage:
        has_garage = True  # Idealista ya filtro garaje
    return Property(
        portal=Portal.IDEALISTA,
        portal_id=alert.property_id,
        url=alert.url,
        zone_id=zone.id,
        title=title or f"Idealista {alert.property_id}",
        price=price,
        size_m2=size_m2,
        rooms=rooms,
        has_garage=has_garage,
        has_garden_or_plot=has_garden,
        terrain_m2=infer_terrain_m2(desc, feats) if desc else None,
        garage_type=infer_garage_type(desc, feats)
        if desc
        else ("edificio" if has_garage else "ninguno"),
        habitability=infer_habitability(desc, title or "") if desc else None,
        internet=infer_internet(desc, feats) if desc else None,
        has_ac=(lambda t: t[0])(infer_ac_type(desc, feats)) if desc else has_ac_v,
        has_ac_preinstalled=(lambda t: t[1])(infer_ac_type(desc, feats))
        if desc
        else False,
        piscina=piscina,
        has_internet_mention=True,
        habitable=infer_habitable(desc, title or "") if desc else True,
        description=desc,
        source="gmail_idealista",
        first_seen=datetime.now(),
        last_seen=datetime.now(),
    )
