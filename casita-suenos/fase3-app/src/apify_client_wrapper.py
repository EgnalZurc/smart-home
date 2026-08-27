"""
Wrapper del Apify free tier para scraping de Idealista.

Usa el actor `pro100chok/idealista-scraper` a $0.70/1.000 resultados.
El free tier da $5/mes → presupuesto para ~7.100 propiedades/mes.

Estrategia de uso controlado:
  - Se ejecuta 1 vez por semana (lunes) para las 8 zonas con mayor puntuación.
  - Estimación: 8 zonas × 150 props = 1.200 props/semana → ~$0.84/semana → ~$3.5/mes.
  - Queda margen de $1.5/mes de seguridad.

El cliente lleva un contador de propiedades consumidas este mes para
NO superar el límite y nunca gastar dinero real.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, date
from pathlib import Path

from apify_client import ApifyClient

from models import Portal, Property
from scraper_base import (
    infer_habitable,
    infer_has_garage,
    infer_has_garden,
    infer_no_internet,
    infer_piscina,
    parse_price,
    parse_rooms,
    parse_size,
)
from zones import Zone

logger = logging.getLogger(__name__)

# Actor de Idealista en Apify
_ACTOR_ID = "pro100chok/idealista-scraper"

# Límite mensual de propiedades scrapeadas (conservador: $4 de $5 free tier)
# $4 / $0.70 per 1k = ~5.700 propiedades/mes como límite de seguridad
_MONTHLY_PROP_LIMIT = 5_700

# Máx propiedades por zona por ejecución (para no sobrepasar el límite)
_MAX_PROPS_PER_ZONE = 200


class ApifyUsageTracker:
    """
    Rastrea el consumo mensual de propiedades para no superar el free tier.
    Persiste el contador en /app/data/apify_usage.json.
    """

    def __init__(self, data_path: str) -> None:
        self._path = Path(data_path)
        self._state = self._load()

    def _load(self) -> dict:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text())
            except Exception:
                pass
        return {"month": date.today().strftime("%Y-%m"), "count": 0}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._state))

    def _reset_if_new_month(self) -> None:
        current_month = date.today().strftime("%Y-%m")
        if self._state.get("month") != current_month:
            logger.info("[apify] Nuevo mes — reseteando contador de uso")
            self._state = {"month": current_month, "count": 0}
            self._save()

    @property
    def current_count(self) -> int:
        self._reset_if_new_month()
        return self._state["count"]

    @property
    def remaining(self) -> int:
        return max(0, _MONTHLY_PROP_LIMIT - self.current_count)

    def add(self, count: int) -> None:
        self._reset_if_new_month()
        self._state["count"] += count
        self._save()
        logger.info(
            "[apify] Uso mensual: %d / %d propiedades (%.1f%%)",
            self._state["count"],
            _MONTHLY_PROP_LIMIT,
            self._state["count"] / _MONTHLY_PROP_LIMIT * 100,
        )


def _item_to_property(item: dict, zone: Zone, now: datetime) -> Property | None:
    """Convierte un resultado del actor de Apify en un Property normalizado."""
    try:
        # El actor devuelve campos estandarizados
        portal_id = str(item.get("propertyCode") or item.get("id") or "")
        if not portal_id:
            return None

        price_raw = str(item.get("price") or item.get("priceValue") or "")
        price = parse_price(price_raw)
        if not price:
            return None

        url = item.get("url") or item.get("propertyUrl") or ""
        title = item.get("title") or item.get("description", "")[:80] or ""
        description = item.get("description") or item.get("fullDescription") or title

        rooms_raw = str(item.get("rooms") or item.get("bedrooms") or "")
        size_raw = str(item.get("size") or item.get("constructedArea") or "")

        # Extraer features como lista de strings
        features = item.get("features") or []
        extras: list[str] = []
        for f in features:
            if isinstance(f, str):
                extras.append(f)
            elif isinstance(f, dict):
                extras.append(f.get("feature") or f.get("label") or "")

        # Algunos actores de Apify incluyen campos booleanos directamente
        has_garage = item.get("hasParking") or item.get("parkingSpaceIncludedInPrice") or False
        has_garden = item.get("hasGarden") or item.get("exterior") or False
        has_pool = item.get("hasSwimmingPool") or item.get("hasSwimmingpool") or False

        # Sobrescribir con inferencia si los booleanos no están disponibles
        if not has_garage:
            has_garage = infer_has_garage(description, extras)
        if not has_garden:
            has_garden = infer_has_garden(description, extras)

        # Piscina
        if has_pool:
            from models import Piscina
            piscina = Piscina.PROPIA
        else:
            piscina = infer_piscina(description, extras)

        return Property(
            portal=Portal.IDEALISTA,
            portal_id=portal_id,
            url=url,
            zone_id=zone.id,
            title=title,
            price=price,
            size_m2=parse_size(size_raw),
            rooms=parse_rooms(rooms_raw) or (int(rooms_raw) if rooms_raw.isdigit() else None),
            has_garage=has_garage,
            has_garden_or_plot=has_garden,
            piscina=piscina,
            has_internet_mention=not infer_no_internet(description),
            habitable=infer_habitable(description, title),
            description=description,
            first_seen=now,
            last_seen=now,
            source="apify_idealista",
        )
    except Exception as e:
        logger.debug("[apify] Error normalizando item: %s", e)
        return None


class IdealistaApifyClient:
    """
    Cliente para scraping de Idealista usando Apify con control de uso del free tier.
    """

    def __init__(self, api_token: str, usage_tracker: ApifyUsageTracker) -> None:
        self._client = ApifyClient(api_token)
        self._tracker = usage_tracker

    def scrape_zone(self, zone: Zone) -> list[Property]:
        """
        Scrape de una zona en Idealista via Apify.
        Respeta el límite mensual del free tier.
        """
        if self._tracker.remaining <= 0:
            logger.warning(
                "[apify] Límite mensual alcanzado (%d props). "
                "Saltando zona %s hasta el próximo mes.",
                _MONTHLY_PROP_LIMIT, zone.id,
            )
            return []

        max_props = min(_MAX_PROPS_PER_ZONE, self._tracker.remaining)
        now = datetime.now()
        results: list[Property] = []

        # El actor pro100chok/idealista-scraper requiere: location + country
        # locationName sin country hace que el actor no encuentre nada
        location = zone.idealista_alert_keywords[0] if zone.idealista_alert_keywords else zone.name

        run_input = {
            "location": location,
            "country": "es",
            "operation": "sale",
            "propertyType": "homes",
            "maxItems": max_props,
            "minRooms": 3,
            "maxPrice": 320_000,
        }

        logger.info(
            "[apify] Ejecutando actor para zona %s (máx %d props, %d restantes este mes)",
            zone.id, max_props, self._tracker.remaining,
        )

        try:
            run = self._client.actor(_ACTOR_ID).call(run_input=run_input)
            if not run:
                logger.warning("[apify] El actor no devolvió resultado para zona %s", zone.id)
                return []

            items = list(
                self._client.dataset(run.default_dataset_id).iterate_items()
            )

            self._tracker.add(len(items))
            logger.info("[apify] Zona %s — %d propiedades obtenidas", zone.id, len(items))

            for item in items:
                prop = _item_to_property(item, zone, now)
                if prop:
                    results.append(prop)

        except Exception as e:
            logger.error("[apify] Error en zona %s: %s", zone.id, e)

        logger.info("[apify] Zona %s — %d propiedades normalizadas", zone.id, len(results))
        return results

    def scrape_property_url(self, url: str, zone: Zone) -> Property | None:
        """
        Scrape de un anuncio concreto por URL (usado para procesar alertas de Gmail).
        Consume 1 unidad del tracker.
        """
        if self._tracker.remaining <= 0:
            logger.warning("[apify] Límite mensual alcanzado, saltando URL: %s", url)
            return None

        run_input = {
            "startUrls": [{"url": url}],
            "maxItems": 1,
        }

        try:
            run = self._client.actor(_ACTOR_ID).call(run_input=run_input)
            if not run:
                return None

            items = list(self._client.dataset(run.default_dataset_id).iterate_items())
            self._tracker.add(len(items))

            if items:
                return _item_to_property(items[0], zone, datetime.now())

        except Exception as e:
            logger.error("[apify] Error scrapeando URL %s: %s", url, e)

        return None
