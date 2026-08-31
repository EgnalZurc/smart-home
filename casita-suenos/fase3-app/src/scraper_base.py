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

# ---------------------------------------------------------------------------
# Keywords
# ---------------------------------------------------------------------------

# R4 — Habitabilidad: ruina/reforma total → -10 pts
_RUINA_KEYWORDS = (
    "en ruinas", "derruid", "en estado ruinoso",
    "para rehabilitar", "rehabilitación integral", "rehabilitacion integral",
    "obra negra", "sin terminar", "sin cédula", "precisa reforma integral",
    "completamente a reformar", "totalmente a reformar",
    "casa a rehabilitar", "chalet a rehabilitar",
    "para reformar", "a reformar", "proyecto de reforma",
    "necesita reforma", "requiere reforma", "ideal para reformar",
    "oportunidad para reformar", "gran oportunidad para reformar",
    "vivienda a reformar", "vivienda para reformar",
    "para restaurar", "a restaurar", "estado de reforma",
    "necesitada de reforma", "precisa de reforma",
    "obra a reformar", "casa a restaurar",
)

# R4 — Pendiente de alguna reforma menor → 4 pts
_PENDIENTE_REFORMA_KEYWORDS = (
    "pendiente de reforma", "necesita alguna reforma", "pequeña reforma",
    "requiere pequeña reforma", "alguna mejora", "necesita actualización",
    "necesita actualizar", "reformar cocina", "reformar baño",
    "pintura", "actualizar cocina",
)

# R4 — Recién reformado → 10 pts
_REFORMADO_KEYWORDS = (
    "recién reformado", "recien reformado", "totalmente reformado",
    "completamente reformado", "reforma integral reciente", "reforma total",
    "recién renovado", "recien renovado", "totalmente renovado",
    "a estrenar", "obra nueva", "nuevo a estrenar", "sin estrenar",
    "llave en mano", "reformado en", "reformado recientemente",
    "reciente reforma", "reforma reciente", "perfectas condiciones",
    "impecable estado", "inmaculado", "completamente rehabilitado",
)

# R4 — Buen estado → 7 pts (se asume si no hay keywords de ruina/reforma/reformado)
# No hace falta lista separada: es el fallback

# R2 — Indicadores de terreno/parcela
_GARDEN_KEYWORDS = (
    "jardín", "jardin", "parcela", "finca", "huerto", "patio exterior",
    "terreno", "solar", "corral", "patio amplio",
)

# R3 — Garaje en edificio (cubierto, plaza)
_GARAGE_EDIFICIO_KEYWORDS = (
    "garaje en edificio", "plaza de garaje", "garaje cerrado",
    "garaje cubierto", "plaza cubierta", "garaje propio",
    "garaje individual", "parking cerrado", "cochera cerrada",
    "garaje incluido", "garaje en planta",
)

# R3 — Garaje exterior / cochera abierta
_GARAGE_EXTERIOR_KEYWORDS = (
    "garaje", "garage", "cochera", "aparcamiento", "parking",
    "espacio para coche", "plaza de parking", "zona de aparcamiento",
)

# R11 — Fibra óptica
_FIBRA_KEYWORDS = (
    "fibra óptica", "fibra optica", "internet por fibra", "fibra hasta el hogar",
    "ftth", "ftto", "fibra instalada", "conexión de fibra",
)

# R11 — Instalación básica (ADSL, 4G, etc.)
_INTERNET_INSTALACION_KEYWORDS = (
    "internet", "adsl", "wifi", "banda ancha", "4g", "5g",
    "conexión a internet", "acceso a internet", "preparado para fibra",
    "preinstalación de internet",
)

# R11 — Sin internet
_NO_INTERNET_KEYWORDS = (
    "sin cobertura", "sin internet", "sin wifi", "sin fibra",
)

# R6 — Preinstalación de AC
_AC_PREINSTALLED_KEYWORDS = (
    "preinstalación aire acondicionado", "preinstalacion aire acondicionado",
    "preinstalación a/c", "preinstalacion a/c",
    "preparado para aire acondicionado", "preparado para a/c",
    "preinst. aire", "preinstalado para a/c",
    "preinstalación de climatización",
)

# R6 — Aire acondicionado instalado
# Keywords de AC confirmado (frío+calor garantizado)
_AC_KEYWORDS = (
    "aire acondicionado", "a/c", "a.a.", "climatizado", "climatizacion",
    "climatización", "split",
    "calefaccion y refrigeracion", "calefacción y refrigeración",
    "frio y calor", "frío y calor",
    "frio/calor", "frío/calor",
    "sistema de climatizacion", "sistema de climatización",
)
# Keywords de solo calefacción (NO cuentan como AC para R6=10)
_HEATING_ONLY_KEYWORDS = (
    "bomba de calor", "bomba calor", "calefaccion", "calefacción",
    "radiadores", "suelo radiante", "aerotermia",
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
_POOL_SPACE_KEYWORDS = ("posibilidad de piscina", "espacio para piscina", "parcela para piscina")
_POOL_COMMUNITY_KEYWORDS = (
    "piscina comunitaria", "piscina común", "zona comunitaria con piscina",
    "comunidad con piscina", "urbanización con piscina", "urbanizacion con piscina",
    "residencial con piscina", "complejo con piscina",
)
_POOL_GENERIC_KEYWORDS = ("piscina",)

_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-ES,es;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


# ---------------------------------------------------------------------------
# Dataclass de listado crudo
# ---------------------------------------------------------------------------

@dataclass
class RawListing:
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
    digits = re.sub(r"[^\d]", "", raw)
    if not digits:
        return None
    price = int(digits)
    if price < 5_000 or price > 10_000_000:
        return None
    return price


def parse_rooms(raw: str | None) -> int | None:
    if not raw:
        return None
    m = re.search(r"(\d+)", raw)
    return int(m.group(1)) if m else None


def parse_size(raw: str | None) -> float | None:
    if not raw:
        return None
    m = re.search(r"([\d.,]+)", raw.replace(",", "."))
    return float(m.group(1)) if m else None


# ---------------------------------------------------------------------------
# Inferencia de campos nuevos
# ---------------------------------------------------------------------------

def infer_habitability(description: str, title: str):
    """R4 — Infiere el nivel de habitabilidad desde la descripción y el título."""
    from models import Habitability
    text = (description + " " + title).lower()
    if any(kw in text for kw in _RUINA_KEYWORDS):
        return Habitability.REFORMA   # agrupa ruina y reforma integral
    if any(kw in text for kw in _REFORMADO_KEYWORDS):
        return Habitability.REFORMADO
    if any(kw in text for kw in _PENDIENTE_REFORMA_KEYWORDS):
        return Habitability.PENDIENTE
    # Sin keywords → buen estado por defecto si tiene descripción; desconocido si no
    if description.strip():
        return Habitability.BUENO
    return Habitability.DESCONOCIDO


def infer_internet(description: str, extras: list[str]):
    """R11 — Infiere nivel de internet desde descripción y extras."""
    from models import Internet
    text = (description + " " + " ".join(extras)).lower()
    if any(kw in text for kw in _NO_INTERNET_KEYWORDS):
        return Internet.NINGUNO
    if any(kw in text for kw in _FIBRA_KEYWORDS):
        return Internet.FIBRA
    if any(kw in text for kw in _INTERNET_INSTALACION_KEYWORDS):
        return Internet.INSTALACION
    return Internet.NINGUNO  # sin info → valor neutro (puntúa 4)


def infer_garage_type(description: str, extras: list[str]):
    """R3 — Infiere tipo de garaje."""
    from models import GarageType
    text = (description + " " + " ".join(extras)).lower()
    if any(kw in text for kw in _GARAGE_EDIFICIO_KEYWORDS):
        return GarageType.EDIFICIO
    if any(kw in text for kw in _GARAGE_EXTERIOR_KEYWORDS):
        return GarageType.EXTERIOR
    return GarageType.NINGUNO


def infer_terrain_m2(description: str, extras: list[str]) -> float | None:
    """R2 — Intenta extraer m² de terreno/parcela de la descripción."""
    text = (description + " " + " ".join(extras)).lower()
    for pattern in _TERRAIN_PATTERNS:
        m = re.search(pattern, text, re.I)
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
    R6 — Infiere si hay AC instalado o solo preinstalación.
    Returns: (has_ac, has_ac_preinstalled)
    Solo devuelve has_ac=True si hay certeza de frío+calor (no solo calefacción).
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
    """Legado — devuelve False si la habitabilidad es RUINA o REFORMA."""
    hab = infer_habitability(description, title)
    from models import Habitability
    return hab not in (Habitability.RUINA, Habitability.REFORMA)


def infer_has_garden(description: str, extras: list[str]) -> bool:
    text = (description + " " + " ".join(extras)).lower()
    return any(kw in text for kw in _GARDEN_KEYWORDS)


def infer_has_garage(description: str, extras: list[str]) -> bool:
    text = (description + " " + " ".join(extras)).lower()
    return any(kw in text for kw in _GARAGE_EXTERIOR_KEYWORDS)


def infer_no_internet(description: str) -> bool:
    text = description.lower()
    return any(kw in text for kw in _NO_INTERNET_KEYWORDS)


def infer_ac(description: str, extras: list[str]) -> bool:
    has_ac, _ = infer_ac_type(description, extras)
    return has_ac


def infer_piscina(description: str, extras: list[str]) -> str:
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

def get_html(url: str, client: httpx.Client, delay: float = 2.0) -> BeautifulSoup | None:
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
    return httpx.Client(headers=_DEFAULT_HEADERS, follow_redirects=True)


# ---------------------------------------------------------------------------
# Resultado de scraping
# ---------------------------------------------------------------------------

@dataclass
class ScraperResult:
    portal: str
    zone_id: str
    properties: list
    success: bool
    error_message: str = ""

    @classmethod
    def ok(cls, portal: str, zone_id: str, properties: list) -> "ScraperResult":
        return cls(portal=portal, zone_id=zone_id, properties=properties, success=True)

    @classmethod
    def fail(cls, portal: str, zone_id: str, error: str) -> "ScraperResult":
        return cls(portal=portal, zone_id=zone_id, properties=[], success=False, error_message=error)
