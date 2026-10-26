"""
Base module for all real estate portal scrapers.

This module provides shared functionality for scraping Spanish real estate
portals (Habitaclia, Pisos.com, Fotocasa, Idealista). It handles:

- HTTP session management with browser-like headers
- Rate limiting to avoid IP blocks
- Common field parsing (price, rooms, size)
- Feature inference from listing text (habitability, garage, garden, AC, etc.)
- Keyword matching for Spanish real estate terminology

The inference functions map Spanish real estate descriptions to structured
data fields used by the scoring algorithm (see scorer.py for rubric details).

Example:
    from scraper_base import make_client, get_html, parse_price

    with make_client() as client:
        soup = get_html("https://portal.com/listing", client)
        price = parse_price("125.000 €")

Attributes:
    _DEFAULT_HEADERS: Browser-mimicking HTTP headers.
    _RUINA_KEYWORDS: Keywords indicating uninhabitable properties.
    _REFORMADO_KEYWORDS: Keywords indicating recently renovated properties.

Note:
    All keyword tuples use lowercase for case-insensitive matching.
    Portal-specific scraping logic is in individual scraper modules.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx
from bs4 import BeautifulSoup
from config import DEFAULT_HEADERS, SCRAPER_CONFIG

if TYPE_CHECKING:
    from models import GarageType, Habitability, Internet

logger = logging.getLogger(__name__)

__all__ = [
    "RawListing",
    "ScraperResult",
    "parse_price",
    "parse_rooms",
    "parse_size",
    "infer_habitability",
    "infer_internet",
    "infer_garage_type",
    "infer_terrain_m2",
    "infer_ac_type",
    "infer_habitable",
    "infer_has_garden",
    "infer_has_garage",
    "infer_no_internet",
    "infer_ac",
    "infer_piscina",
    "get_html",
    "make_client",
]

# ---------------------------------------------------------------------------
# Keywords
# ---------------------------------------------------------------------------

# R4 — Habitabilidad: ruina/reforma total → -10 pts
_RUINA_KEYWORDS = (
    "en ruinas",
    "derruid",
    "en estado ruinoso",
    "para rehabilitar",
    "rehabilitación integral",
    "rehabilitacion integral",
    "obra negra",
    "sin terminar",
    "sin cédula",
    "precisa reforma integral",
    "completamente a reformar",
    "totalmente a reformar",
    "casa a rehabilitar",
    "chalet a rehabilitar",
    "para reformar",
    "a reformar",
    "proyecto de reforma",
    "necesita reforma",
    "requiere reforma",
    "ideal para reformar",
    "oportunidad para reformar",
    "gran oportunidad para reformar",
    "vivienda a reformar",
    "vivienda para reformar",
    "para restaurar",
    "a restaurar",
    "estado de reforma",
    "necesitada de reforma",
    "precisa de reforma",
    "obra a reformar",
    "casa a restaurar",
)

# R4 — Pendiente de alguna reforma menor → 4 pts
_PENDIENTE_REFORMA_KEYWORDS = (
    "pendiente de reforma",
    "necesita alguna reforma",
    "pequeña reforma",
    "requiere pequeña reforma",
    "alguna mejora",
    "necesita actualización",
    "necesita actualizar",
    "reformar cocina",
    "reformar baño",
    "pintura",
    "actualizar cocina",
)

# R4 — Recién reformado → 10 pts
_REFORMADO_KEYWORDS = (
    "recién reformado",
    "recien reformado",
    "totalmente reformado",
    "completamente reformado",
    "reforma integral reciente",
    "reforma total",
    "recién renovado",
    "recien renovado",
    "totalmente renovado",
    "a estrenar",
    "obra nueva",
    "nuevo a estrenar",
    "sin estrenar",
    "llave en mano",
    "reformado en",
    "reformado recientemente",
    "reciente reforma",
    "reforma reciente",
    "perfectas condiciones",
    "impecable estado",
    "inmaculado",
    "completamente rehabilitado",
)

# R4 — Buen estado → 7 pts (se asume si no hay keywords de ruina/reforma/reformado)
# No hace falta lista separada: es el fallback

# R2 — Indicadores de terreno/parcela
_GARDEN_KEYWORDS = (
    "jardín",
    "jardin",
    "parcela",
    "finca",
    "huerto",
    "patio exterior",
    "terreno",
    "solar",
    "corral",
    "patio amplio",
)

# R3 — Garaje en edificio (cubierto, plaza)
_GARAGE_EDIFICIO_KEYWORDS = (
    "garaje en edificio",
    "plaza de garaje",
    "garaje cerrado",
    "garaje cubierto",
    "plaza cubierta",
    "garaje propio",
    "garaje individual",
    "parking cerrado",
    "cochera cerrada",
    "garaje incluido",
    "garaje en planta",
)

# R3 — Garaje exterior / cochera abierta
_GARAGE_EXTERIOR_KEYWORDS = (
    "garaje",
    "garage",
    "cochera",
    "aparcamiento",
    "parking",
    "espacio para coche",
    "plaza de parking",
    "zona de aparcamiento",
)

# R11 — Fibra óptica
_FIBRA_KEYWORDS = (
    "fibra óptica",
    "fibra optica",
    "internet por fibra",
    "fibra hasta el hogar",
    "ftth",
    "ftto",
    "fibra instalada",
    "conexión de fibra",
)

# R11 — Instalación básica (ADSL, 4G, etc.)
_INTERNET_INSTALACION_KEYWORDS = (
    "internet",
    "adsl",
    "wifi",
    "banda ancha",
    "4g",
    "5g",
    "conexión a internet",
    "acceso a internet",
    "preparado para fibra",
    "preinstalación de internet",
)

# R11 — Sin internet
_NO_INTERNET_KEYWORDS = (
    "sin cobertura",
    "sin internet",
    "sin wifi",
    "sin fibra",
)

# R6 — Preinstalación de AC
_AC_PREINSTALLED_KEYWORDS = (
    "preinstalación aire acondicionado",
    "preinstalacion aire acondicionado",
    "preinstalación a/c",
    "preinstalacion a/c",
    "preparado para aire acondicionado",
    "preparado para a/c",
    "preinst. aire",
    "preinstalado para a/c",
    "preinstalación de climatización",
)

# R6 — Aire acondicionado instalado
# Keywords de AC confirmado (frío+calor garantizado)
_AC_KEYWORDS = (
    "aire acondicionado",
    "a/c",
    "a.a.",
    "climatizado",
    "climatizacion",
    "climatización",
    "split",
    "calefaccion y refrigeracion",
    "calefacción y refrigeración",
    "frio y calor",
    "frío y calor",
    "frio/calor",
    "frío/calor",
    "sistema de climatizacion",
    "sistema de climatización",
)
# Keywords de solo calefacción (NO cuentan como AC para R6=10)
_HEATING_ONLY_KEYWORDS = (
    "bomba de calor",
    "bomba calor",
    "calefaccion",
    "calefacción",
    "radiadores",
    "suelo radiante",
    "aerotermia",
)

# R2 — Extracción de m² de terreno
_TERRAIN_PATTERNS = [
    # "450 m² de terreno", "450m² parcela", "terreno de 450 m²"
    r"(\d[\d\.]+)\s*m[²2]\s*(?:de\s+)?(?:terreno|parcela|finca|solar|huerto)",
    r"(?:terreno|parcela|finca|solar)\s+(?:de\s+)?(\d[\d\.]+)\s*m[²2]",
    r"(\d[\d\.]+)\s*m[²2]\s+(?:de\s+)?(?:jardin|jardín)",
    r"(?:jardin|jardín|terreno|parcela)\s+(?:de\s+)?(\d[\d\.]+)\s*m[²2]",
]

# R5 — Piscina
_POOL_OWN_KEYWORDS = ("piscina propia", "piscina privada", "piscina individual")
_POOL_SPACE_KEYWORDS = (
    "posibilidad de piscina",
    "espacio para piscina",
    "parcela para piscina",
)
_POOL_COMMUNITY_KEYWORDS = (
    "piscina comunitaria",
    "piscina común",
    "zona comunitaria con piscina",
    "comunidad con piscina",
    "urbanización con piscina",
    "urbanizacion con piscina",
    "residencial con piscina",
    "complejo con piscina",
)
_POOL_GENERIC_KEYWORDS = ("piscina",)

# Use centralized headers from config (kept as alias for backward compatibility)
_DEFAULT_HEADERS = DEFAULT_HEADERS


# ---------------------------------------------------------------------------
# Dataclass de listado crudo
# ---------------------------------------------------------------------------


@dataclass
class RawListing:
    """
    Raw listing data extracted from a portal before normalization.

    This intermediate representation holds the text as scraped, before
    parsing into typed fields. Used by portal-specific scrapers to pass
    data to the common parsing functions.

    Attributes:
        portal_id: Unique identifier within the source portal.
        url: Full URL to the listing detail page.
        title: Listing title/headline.
        price_raw: Price as displayed (e.g., "125.000 €").
        rooms_raw: Room count text if available (e.g., "3 habitaciones").
        size_raw: Size text if available (e.g., "120 m²").
        description: Full listing description text.
        extras: Additional feature tags/labels from the listing.
    """

    portal_id: str
    url: str
    title: str
    price_raw: str
    rooms_raw: str | None
    size_raw: str | None
    description: str
    extras: list[str]


# ---------------------------------------------------------------------------
# Parseo de campos básicos
# ---------------------------------------------------------------------------


def parse_price(raw: str) -> int | None:
    """
    Parse a price string into an integer value in euros.

    Extracts digits from formatted price strings, handling Spanish
    thousand separators (dots) and euro symbols. Validates that the
    result falls within a reasonable range for Spanish real estate.

    Args:
        raw: Price string from listing (e.g., "125.000 €", "89000EUR").

    Returns:
        Price in euros as integer, or None if parsing fails or value
        is outside valid range (5,000 - 10,000,000 €).

    Example:
        >>> parse_price("125.000 €")
        125000
        >>> parse_price("invalid")
        None
    """
    digits = re.sub(r"[^\d]", "", raw)
    if not digits:
        return None
    price = int(digits)
    if price < 5_000 or price > 10_000_000:
        return None
    return price


def parse_rooms(raw: str | None) -> int | None:
    """
    Extract room count from a text string.

    Args:
        raw: Text containing room count (e.g., "3 habitaciones", "2 habs.").

    Returns:
        Number of rooms as integer, or None if not found.

    Example:
        >>> parse_rooms("3 habitaciones")
        3
    """
    if not raw:
        return None
    m = re.search(r"(\d+)", raw)
    return int(m.group(1)) if m else None


def parse_size(raw: str | None) -> float | None:
    """
    Extract property size in square meters from text.

    Handles both dot and comma as decimal separators (Spanish format).

    Args:
        raw: Text containing size (e.g., "120 m²", "85,5m2").

    Returns:
        Size in square meters as float, or None if not found.

    Example:
        >>> parse_size("120 m²")
        120.0
    """
    if not raw:
        return None
    m = re.search(r"([\d.,]+)", raw.replace(",", "."))
    return float(m.group(1)) if m else None


# ---------------------------------------------------------------------------
# Inferencia de campos nuevos
# ---------------------------------------------------------------------------


def infer_habitability(description: str, title: str) -> Habitability:
    """
    Infer property habitability level from description text (R4 rubric).

    Analyzes listing text for Spanish keywords indicating renovation state.
    Maps to Habitability enum values used by the scorer.

    Args:
        description: Full listing description text.
        title: Listing title/headline.

    Returns:
        Habitability enum value:
        - REFORMA: Uninhabitable, needs major renovation (-10 pts)
        - PENDIENTE: Minor renovation needed (4 pts)
        - REFORMADO: Recently renovated (10 pts)
        - BUENO: Good condition, default if description present (7 pts)
        - DESCONOCIDO: Unknown, no description available (0 pts)

    Example:
        >>> infer_habitability("Casa recién reformada", "Chalet")
        Habitability.REFORMADO
    """
    from models import Habitability

    text = (description + " " + title).lower()
    if any(kw in text for kw in _RUINA_KEYWORDS):
        return Habitability.REFORMA  # agrupa ruina y reforma integral
    if any(kw in text for kw in _REFORMADO_KEYWORDS):
        return Habitability.REFORMADO
    if any(kw in text for kw in _PENDIENTE_REFORMA_KEYWORDS):
        return Habitability.PENDIENTE
    # Sin keywords → buen estado por defecto si tiene descripción; desconocido si no
    if description.strip():
        return Habitability.BUENO
    return Habitability.DESCONOCIDO


def infer_internet(description: str, extras: list[str]) -> Internet:
    """
    Infer internet connectivity level from listing text (R11 rubric).

    Detects fiber optic, basic installation, or no internet mentions.

    Args:
        description: Full listing description text.
        extras: Additional feature tags from the listing.

    Returns:
        Internet enum value:
        - FIBRA: Fiber optic available (10 pts)
        - INSTALACION: Basic internet (ADSL, 4G) (7 pts)
        - NINGUNO: No internet mentioned or explicitly none (4 pts)

    Example:
        >>> infer_internet("Vivienda con fibra óptica instalada", [])
        Internet.FIBRA
    """
    from models import Internet

    text = (description + " " + " ".join(extras)).lower()
    if any(kw in text for kw in _NO_INTERNET_KEYWORDS):
        return Internet.NINGUNO
    if any(kw in text for kw in _FIBRA_KEYWORDS):
        return Internet.FIBRA
    if any(kw in text for kw in _INTERNET_INSTALACION_KEYWORDS):
        return Internet.INSTALACION
    return Internet.NINGUNO  # sin info → valor neutro (puntúa 4)


def infer_garage_type(description: str, extras: list[str]) -> GarageType:
    """
    Infer garage type from listing text (R3 rubric).

    Distinguishes between covered garage in building vs exterior parking.

    Args:
        description: Full listing description text.
        extras: Additional feature tags from the listing.

    Returns:
        GarageType enum value:
        - EDIFICIO: Covered garage in building (10 pts)
        - EXTERIOR: Outdoor parking/carport (7 pts)
        - NINGUNO: No garage mentioned (0 pts)

    Example:
        >>> infer_garage_type("Plaza de garaje incluida", [])
        GarageType.EDIFICIO
    """
    from models import GarageType

    text = (description + " " + " ".join(extras)).lower()
    if any(kw in text for kw in _GARAGE_EDIFICIO_KEYWORDS):
        return GarageType.EDIFICIO
    if any(kw in text for kw in _GARAGE_EXTERIOR_KEYWORDS):
        return GarageType.EXTERIOR
    return GarageType.NINGUNO


def infer_terrain_m2(description: str, extras: list[str]) -> float | None:
    """
    Extract terrain/plot size in m² from description text (R2 rubric).

    Uses regex patterns to find Spanish expressions for plot size.

    Args:
        description: Full listing description text.
        extras: Additional feature tags from the listing.

    Returns:
        Terrain size in square meters, or None if not found or invalid.
        Only returns values between 1 and 100,000 m².

    Example:
        >>> infer_terrain_m2("Parcela de 450 m²", [])
        450.0
    """
    text = (description + " " + " ".join(extras)).lower()
    for pattern in _TERRAIN_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            raw = m.group(1).replace(".", "").replace(",", ".")
            try:
                val = float(raw)
                if 1 < val < 100_000:
                    return val
            except ValueError:
                continue
    return None


def infer_ac_type(description: str, extras: list[str]) -> tuple[bool, bool]:
    """
    Infer air conditioning status from listing text (R6 rubric).

    Distinguishes between full AC (cooling+heating) and pre-installation.
    Heating-only systems (radiators, heat pumps) don't count as AC.

    Args:
        description: Full listing description text.
        extras: Additional feature tags from the listing.

    Returns:
        Tuple of (has_ac, has_ac_preinstalled):
        - (True, False): Full AC system installed (10 pts)
        - (False, True): AC pre-installation only (7 pts)
        - (False, False): No AC mentioned (5 pts default)

    Example:
        >>> infer_ac_type("Aire acondicionado frío/calor", [])
        (True, False)
    """
    text = (description + " " + " ".join(extras)).lower()
    if any(kw in text for kw in _AC_PREINSTALLED_KEYWORDS):
        return False, True
    if any(kw in text for kw in _AC_KEYWORDS):
        return True, False
    # Calefacción sola no cuenta como AC — devuelve (False, False) → 5 pts por defecto
    return False, False


# ---------------------------------------------------------------------------
# Funciones legadas (mantener compatibilidad)
# ---------------------------------------------------------------------------


def infer_habitable(description: str, title: str) -> bool:
    """
    Legacy function: check if property is habitable.

    Deprecated in favor of infer_habitability() which returns detailed
    Habitability enum. Kept for backward compatibility.

    Args:
        description: Full listing description text.
        title: Listing title/headline.

    Returns:
        False if property needs major renovation (RUINA/REFORMA),
        True otherwise.
    """
    hab = infer_habitability(description, title)
    from models import Habitability

    return hab not in (Habitability.RUINA, Habitability.REFORMA)


def infer_has_garden(description: str, extras: list[str]) -> bool:
    """
    Detect garden or plot presence from listing text.

    Args:
        description: Full listing description text.
        extras: Additional feature tags from the listing.

    Returns:
        True if garden/plot keywords found, False otherwise.
    """
    text = (description + " " + " ".join(extras)).lower()
    return any(kw in text for kw in _GARDEN_KEYWORDS)


def infer_has_garage(description: str, extras: list[str]) -> bool:
    """
    Detect garage presence from listing text.

    Args:
        description: Full listing description text.
        extras: Additional feature tags from the listing.

    Returns:
        True if any garage-related keywords found, False otherwise.
    """
    text = (description + " " + " ".join(extras)).lower()
    return any(kw in text for kw in _GARAGE_EXTERIOR_KEYWORDS)


def infer_no_internet(description: str) -> bool:
    """
    Detect explicit lack of internet connectivity.

    Args:
        description: Full listing description text.

    Returns:
        True if "sin internet/wifi/cobertura" explicitly mentioned.
    """
    text = description.lower()
    return any(kw in text for kw in _NO_INTERNET_KEYWORDS)


def infer_ac(description: str, extras: list[str]) -> bool:
    """
    Detect air conditioning presence from listing text.

    Wrapper around infer_ac_type() for backward compatibility.

    Args:
        description: Full listing description text.
        extras: Additional feature tags from the listing.

    Returns:
        True if full AC system detected, False otherwise.
    """
    has_ac, _ = infer_ac_type(description, extras)
    return has_ac


def infer_piscina(description: str, extras: list[str]) -> str:
    """
    Infer swimming pool type from listing text (R5 rubric).

    Distinguishes between private pool, space for pool, community pool,
    or no pool.

    Args:
        description: Full listing description text.
        extras: Additional feature tags from the listing.

    Returns:
        Piscina enum value:
        - PROPIA: Private pool (10 pts)
        - ESPACIO: Space/possibility for pool (7 pts)
        - COMUNITARIA: Community pool (5 pts)
        - NINGUNA: No pool (0 pts)

    Example:
        >>> infer_piscina("Urbanización con piscina comunitaria", [])
        Piscina.COMUNITARIA
    """
    from models import Piscina

    text = (description + " " + " ".join(extras)).lower()
    if any(kw in text for kw in _POOL_OWN_KEYWORDS):
        return Piscina.PROPIA
    if any(kw in text for kw in _POOL_SPACE_KEYWORDS):
        return Piscina.ESPACIO
    if any(kw in text for kw in _POOL_COMMUNITY_KEYWORDS):
        return Piscina.COMUNITARIA
    if any(kw in text for kw in _POOL_GENERIC_KEYWORDS):
        # No se puede asegurar si es privada → asumir comunitaria
        return Piscina.COMUNITARIA
    return Piscina.NINGUNA


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def get_html(
    url: str, client: httpx.Client, delay: float | None = None
) -> BeautifulSoup | None:
    """
    Fetch and parse HTML from a URL with rate limiting.

    Handles HTTP errors gracefully and returns parsed BeautifulSoup object.
    Includes configurable delay between requests to avoid IP blocking.

    Args:
        url: Full URL to fetch.
        client: httpx.Client instance with configured headers.
        delay: Seconds to wait before request. Defaults to config value.

    Returns:
        BeautifulSoup object of parsed HTML, or None on error.

    Example:
        >>> client = make_client()
        >>> soup = get_html("https://portal.com/search", client)
        >>> listings = soup.select("div.listing") if soup else []
    """
    if delay is None:
        delay = SCRAPER_CONFIG["request_delay"]
    try:
        time.sleep(delay)
        response = client.get(
            url, follow_redirects=True, timeout=SCRAPER_CONFIG["http_timeout"]
        )
        response.raise_for_status()
        return BeautifulSoup(response.text, "html.parser")
    except httpx.HTTPStatusError as e:
        logger.warning("[scraper] HTTP %s para %s", e.response.status_code, url)
        return None
    except (httpx.HTTPError, httpx.TimeoutException, OSError) as e:
        logger.error("[scraper] Error descargando %s: %s", url, e)
        return None


def make_client() -> httpx.Client:
    """
    Create an HTTP client with browser-like headers.

    Returns a configured httpx.Client with headers that mimic a real
    browser to reduce blocking by anti-bot systems.

    Returns:
        Configured httpx.Client instance. Caller should close when done
        or use as context manager.

    Example:
        >>> with make_client() as client:
        ...     soup = get_html("https://portal.com", client)
    """
    return httpx.Client(headers=_DEFAULT_HEADERS, follow_redirects=True)


# ---------------------------------------------------------------------------
# Resultado de scraping
# ---------------------------------------------------------------------------


@dataclass
class ScraperResult:
    """
    Result container for a scraping operation.

    Encapsulates the outcome of scraping a zone from a portal, including
    success/failure status and any error information.

    Attributes:
        portal: Name of the source portal (e.g., "habitaclia", "pisos").
        zone_id: Identifier of the scraped zone.
        properties: List of Property objects found.
        success: True if scraping completed without fatal errors.
        error_message: Description of error if success is False.

    Example:
        >>> result = ScraperResult.ok("habitaclia", "zona-norte", properties)
        >>> if not result.success:
        ...     logger.error(result.error_message)
    """

    portal: str
    zone_id: str
    properties: list
    success: bool
    error_message: str = ""

    @classmethod
    def ok(cls, portal: str, zone_id: str, properties: list) -> ScraperResult:
        """Create a successful result with properties."""
        return cls(portal=portal, zone_id=zone_id, properties=properties, success=True)

    @classmethod
    def fail(cls, portal: str, zone_id: str, error: str) -> ScraperResult:
        """Create a failed result with error message."""
        return cls(
            portal=portal,
            zone_id=zone_id,
            properties=[],
            success=False,
            error_message=error,
        )
