"""
Inferencia de zona a partir de pistas de ubicación, URLs y geocoding.

Funciones puras extraídas de ``casita_scheduler.py``. El orquestador delega en
ellas desde sus métodos ``_infer_zone_from_hint`` / ``_infer_zone_nominatim`` /
``_infer_zone_from_url``, que se mantienen como wrappers finos para preservar la
API y los puntos de parcheo de los tests.
"""

from __future__ import annotations

import logging

from zones import ZONE_COORDS, ZONES, Zone

from scheduler.config import NOMINATIM_MAX_DIST_KM

logger = logging.getLogger(__name__)


def infer_zone_from_hint(
    hint: str | None, url: str, *, nominatim_fallback
) -> Zone | None:
    """
    Infiere la zona de un anuncio combinando la pista de ubicación y la URL.

    Orden de resolución:
      1. Municipio exacto en ``fotocasa_municipios``.
      2. ``idealista_alert_keywords`` o palabras del nombre de la zona.
      3. Municipio de Fotocasa como substring de la pista.
      4. Keywords/municipios dentro de la URL.
      5. Fallback geográfico vía ``nominatim_fallback`` (callable con la pista).
    """
    if hint:
        hl = hint.lower().strip()
        # 1. Buscar en fotocasa_municipios (match exacto del municipio)
        for zone in ZONES.values():
            if hasattr(zone, "fotocasa_municipios") and zone.fotocasa_municipios:
                if any(
                    m.lower().replace("-", " ") == hl.replace("-", " ")
                    for m in zone.fotocasa_municipios
                ):
                    return zone
        # 2. Buscar en idealista_alert_keywords
        for zone in ZONES.values():
            if any(kw.lower() in hl for kw in zone.idealista_alert_keywords):
                return zone
            if any(w in hl for w in zone.name.lower().split() if len(w) > 4):
                return zone
        # 3. Buscar municipio de Fotocasa como substring
        for zone in ZONES.values():
            if hasattr(zone, "fotocasa_municipios") and zone.fotocasa_municipios:
                if any(
                    m.lower().replace("-", " ") in hl for m in zone.fotocasa_municipios
                ):
                    return zone
    ul = url.lower()
    for zone in ZONES.values():
        if any(
            kw.lower().replace(" ", "-") in ul for kw in zone.idealista_alert_keywords
        ):
            return zone
        if hasattr(zone, "fotocasa_municipios") and zone.fotocasa_municipios:
            if any(m.lower() in ul for m in zone.fotocasa_municipios):
                return zone
    # 4. Fallback geográfico: Nominatim → zona más cercana
    if hint:
        zone = nominatim_fallback(hint)
        if zone:
            return zone
    return None


def infer_zone_nominatim(hint: str) -> Zone | None:
    """
    Fallback: usa Nominatim (OSM) para obtener coordenadas del municipio,
    luego devuelve la zona más cercana geográficamente.
    Solo se invoca cuando el mapeo por keywords falla.
    Máx distancia: 200 km. Si está más lejos de todas las zonas → None.
    """
    import json
    import math
    import urllib.parse
    import urllib.request

    try:
        q = urllib.parse.urlencode(
            {
                "q": hint.replace("-", " ") + ", España",
                "format": "json",
                "limit": "1",
                "countrycodes": "es",
            }
        )
        req = urllib.request.Request(
            f"https://nominatim.openstreetmap.org/search?{q}",
            headers={"User-Agent": "casita-suenos/1.0 (raspberrypi)"},
        )
        with urllib.request.urlopen(req, timeout=5) as r:  # nosec B310
            data = json.loads(r.read().decode())
        if not data:
            logger.info("[casita] Nominatim: sin resultados para '%s'", hint)
            return None
        lat = float(data[0]["lat"])
        lon = float(data[0]["lon"])
        logger.info(
            "[casita] Nominatim '%s' → (%.3f, %.3f) tipo=%s",
            hint,
            lat,
            lon,
            data[0].get("type", "?"),
        )

        def _haversine(lat1, lon1, lat2, lon2):
            R = 6371.0
            dlat = math.radians(lat2 - lat1)
            dlon = math.radians(lon2 - lon1)
            a = (
                math.sin(dlat / 2) ** 2
                + math.cos(math.radians(lat1))
                * math.cos(math.radians(lat2))
                * math.sin(dlon / 2) ** 2
            )
            return R * 2 * math.asin(math.sqrt(a))

        best_zone = None
        best_dist = float("inf")
        for zone in ZONES.values():
            coords = ZONE_COORDS.get(zone.id)
            if not coords:
                continue
            d = _haversine(lat, lon, coords[0], coords[1])
            if d < best_dist:
                best_dist = d
                best_zone = zone

        if best_zone and best_dist <= NOMINATIM_MAX_DIST_KM:
            logger.info(
                "[casita] Nominatim fallback: '%s' → %s (%.0f km)",
                hint,
                best_zone.id,
                best_dist,
            )
            return best_zone
        elif best_zone:
            logger.info(
                "[casita] Nominatim '%s' demasiado lejos: %.0f km (zona más cercana: %s)",
                hint,
                best_dist,
                best_zone.id,
            )
            return None
    except Exception as e:
        logger.warning("[casita] Nominatim fallback falló para '%s': %s", hint, e)
    return None


def infer_zone_from_url(url: str) -> Zone | None:
    """
    Intenta inferir a qué zona pertenece una URL de Idealista
    buscando keywords de cada zona en la URL.
    Si no se puede inferir, usa ``zamora_meseta`` como fallback.
    """
    url_lower = url.lower()
    for zone in ZONES.values():
        for keyword in zone.idealista_alert_keywords:
            if keyword.lower().replace(" ", "-") in url_lower:
                return zone
    # Si no se puede inferir, usar la zona con más propiedades como fallback
    return ZONES.get("zamora_meseta")
