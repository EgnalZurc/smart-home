"""
Base común para todos los scrapers.
Gestiona sesión HTTP, headers, rate limiting y parsing de campos comunes.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Palabras clave que indican ruina / inhabitable (L4)
_INHABITABLE_KEYWORDS = (
    "para rehabilitar", "rehabilitación integral", "en ruinas", "derruid",
    "obra negra", "sin terminar", "sin cédula", "precisa reforma integral",
    "completamente a reformar", "totalmente a reformar",
)

# Palabras clave que indican piscina propia
_POOL_OWN_KEYWORDS = ("piscina propia", "piscina privada", "piscina individual")
# Palabras clave que indican espacio para piscina
_POOL_SPACE_KEYWORDS = ("posibilidad de piscina", "espacio para piscina", "parcela para piscina")
# Palabras clave que indican piscina comunitaria
_POOL_COMMUNITY_KEYWORDS = ("piscina comunitaria", "piscina común", "zona comunitaria con piscina")
# Palabras clave que indican piscina sin especificar (asumir propia si casa independiente)
_POOL_GENERIC_KEYWORDS = ("piscina",)

# Palabras clave que sugieren parcela/jardín (L3)
_GARDEN_KEYWORDS = (
    "jardín", "jardin", "parcela", "finca", "huerto", "patio exterior",
    "terreno", "solar", "corral",
)

# Palabras clave que sugieren garaje/aparcamiento (L2)
_GARAGE_KEYWORDS = (
    "garaje", "garage", "cochera", "aparcamiento", "parking",
    "plaza de garaje", "espacio para coche",
)

# Palabras que indican ausencia de internet (L5)
_NO_INTERNET_KEYWORDS = (
    "sin cobertura", "sin internet", "sin wifi", "sin fibra",
)

_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-ES,es;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


@dataclass
class RawListing:
    """Datos crudos extraídos de un portal antes de normalizar a Property."""
    portal_id: str
    url: str
    title: str
    price_raw: str        # "189.000 €" — se parsea después
    rooms_raw: str | None  # "4 hab." — se parsea después
    size_raw: str | None   # "230 m²" — se parsea después
    description: str
    extras: list[str]     # tags/chips del anuncio: "Jardín", "Garaje", etc.


def parse_price(raw: str) -> int | None:
    """Extrae el precio en € como entero desde strings tipo '189.000 €' o '189000'."""
    digits = re.sub(r"[^\d]", "", raw)
    if not digits:
        return None
    price = int(digits)
    # Sanity check: descartamos precios absurdos
    if price < 5_000 or price > 10_000_000:
        return None
    return price


def parse_rooms(raw: str | None) -> int | None:
    """Extrae número de habitaciones desde '4 hab.' o '4 habitaciones'."""
    if not raw:
        return None
    m = re.search(r"(\d+)", raw)
    return int(m.group(1)) if m else None


def parse_size(raw: str | None) -> float | None:
    """Extrae m² desde '230 m²'."""
    if not raw:
        return None
    m = re.search(r"([\d.,]+)", raw.replace(",", "."))
    return float(m.group(1)) if m else None


def infer_habitable(description: str, title: str) -> bool:
    """L4 — Devuelve False si los textos sugieren ruina o reforma integral."""
    text = (description + " " + title).lower()
    return not any(kw in text for kw in _INHABITABLE_KEYWORDS)


def infer_has_garden(description: str, extras: list[str]) -> bool:
    """L3 — True si hay mención a parcela/jardín."""
    text = (description + " " + " ".join(extras)).lower()
    return any(kw in text for kw in _GARDEN_KEYWORDS)


def infer_has_garage(description: str, extras: list[str]) -> bool:
    """L2 — True si hay mención a garaje/aparcamiento."""
    text = (description + " " + " ".join(extras)).lower()
    return any(kw in text for kw in _GARAGE_KEYWORDS)


def infer_no_internet(description: str) -> bool:
    """L5 — True si la descripción menciona explícitamente falta de internet."""
    text = description.lower()
    return any(kw in text for kw in _NO_INTERNET_KEYWORDS)


def infer_piscina(description: str, extras: list[str]) -> str:
    """P2 — Infiere tipo de piscina desde descripción y extras."""
    from models import Piscina
    text = (description + " " + " ".join(extras)).lower()

    if any(kw in text for kw in _POOL_OWN_KEYWORDS):
        return Piscina.PROPIA
    if any(kw in text for kw in _POOL_SPACE_KEYWORDS):
        return Piscina.ESPACIO
    if any(kw in text for kw in _POOL_COMMUNITY_KEYWORDS):
        return Piscina.COMUNITARIA
    if any(kw in text for kw in _POOL_GENERIC_KEYWORDS):
        # "piscina" sin especificar → asumimos propia si es chalet/casa
        return Piscina.PROPIA
    return Piscina.NINGUNA


def get_html(url: str, client: httpx.Client, delay: float = 2.0) -> BeautifulSoup | None:
    """Descarga una URL y devuelve BeautifulSoup. Respeta un delay entre peticiones."""
    try:
        time.sleep(delay)
        response = client.get(url, follow_redirects=True, timeout=15)
        response.raise_for_status()
        return BeautifulSoup(response.text, "html.parser")
    except httpx.HTTPStatusError as e:
        logger.warning("[scraper] HTTP %s para %s", e.response.status_code, url)
        return None
    except Exception as e:
        logger.error("[scraper] Error descargando %s: %s", url, e)
        return None


def make_client() -> httpx.Client:
    """Crea un cliente HTTP con headers por defecto."""
    return httpx.Client(headers=_DEFAULT_HEADERS, follow_redirects=True)


# ---------------------------------------------------------------------------
# Resultado de scraping — incluye estado de error para notificación
# ---------------------------------------------------------------------------

@dataclass
class ScraperResult:
    """Resultado de ejecutar un scraper sobre una zona."""
    portal: str
    zone_id: str
    properties: list          # lista de Property
    success: bool
    error_message: str = ""   # vacío si success=True

    @classmethod
    def ok(cls, portal: str, zone_id: str, properties: list) -> "ScraperResult":
        return cls(portal=portal, zone_id=zone_id, properties=properties, success=True)

    @classmethod
    def fail(cls, portal: str, zone_id: str, error: str) -> "ScraperResult":
        return cls(portal=portal, zone_id=zone_id, properties=[], success=False, error_message=error)
