"""
Modelos de datos para Casita Sueños.
Todos los objetos son dataclasses inmutables o mutables según necesidad.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Portal(str, Enum):
    IDEALISTA  = "idealista"
    FOTOCASA   = "fotocasa"
    PISOS      = "pisos"
    HABITACLIA = "habitaclia"


class Piscina(str, Enum):
    PROPIA       = "propia"
    ESPACIO      = "espacio"       # cabe instalarla
    COMUNITARIA  = "comunitaria"
    NINGUNA      = "ninguna"


class FireRisk(str, Enum):
    """Nivel de riesgo de incendio de la zona."""
    NULO        = "nulo"
    MUY_BAJO    = "muy_bajo"
    BAJO        = "bajo"
    MEDIO       = "medio"
    MEDIO_ALTO  = "medio_alto"
    ALTO        = "alto"
    MUY_ALTO    = "muy_alto"   # → descarte automático (L10)

class FloodRisk(str, Enum):
    """Nivel de riesgo de inundación de la zona (SNCZI/CHE/CHC/PATRICOVA)."""
    NULO        = "nulo"        # P12=9 — sin riesgo
    BAJO        = "bajo"        # P12=7
    BAJO_MEDIO  = "bajo_medio"  # P12=5
    MEDIO       = "medio"       # P12=3
    MEDIO_ALTO  = "medio_alto"  # P12=1
    ALTO        = "alto"        # → descarte automático (L12)


# ---------------------------------------------------------------------------
# Zona geográfica candidata
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Zone:
    """
    Una zona candidata del estudio de Fase 1.
    Contiene los valores de referencia para calcular P3-P10.
    """
    id: str                          # ej: "zamora_meseta"
    name: str                        # ej: "Zamora meseta central"

    # Distancias de referencia de la zona (minutos en coche, sin peaje)
    distance_madrid_min: int         # P3
    distance_beach_min: int | None   # P4 — None si no aplica / muy lejos
    distance_natural_pools_min: int | None  # P5

    # Servicios de referencia (minutos al más cercano típico de la zona)
    distance_supermarket_min: int    # P6
    distance_health_center_min: int  # P7
    distance_hospital_min: int       # P8

    # Riesgo de incendio de la zona
    fire_risk: FireRisk              # P10 / L10

    # Rango de precio orientativo de la zona (€)
    price_min: int
    price_max: int

    # Gusto personal por la provincia (P11) — valor entre 0 y 9
    zone_preference: float = 5.0
    flood_risk: "FloodRisk" = None  # P12 / L12 — None se trata como BAJO

    # Búsquedas configuradas para scrapers (URLs o términos)
    fotocasa_search_urls: tuple[str, ...] = field(default_factory=tuple)
    pisos_search_urls: tuple[str, ...] = field(default_factory=tuple)
    habitaclia_search_urls: tuple[str, ...] = field(default_factory=tuple)
    idealista_alert_keywords: tuple[str, ...] = field(default_factory=tuple)
    # Municipios de Fotocasa que corresponden a esta zona
    fotocasa_municipios: tuple[str, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Propiedad (anuncio inmobiliario)
# ---------------------------------------------------------------------------

@dataclass
class Property:
    """
    Representa un anuncio inmobiliario normalizado, independientemente
    del portal del que provenga.
    """
    # Identificación
    portal: Portal
    portal_id: str                   # ID único en ese portal
    url: str
    zone_id: str                     # ID de la Zone a la que pertenece

    # Datos del anuncio
    title: str
    price: int                       # € — entero para comparaciones exactas
    size_m2: float | None            # metros cuadrados construidos
    rooms: int | None                # número de habitaciones
    has_garage: bool                 # L2
    has_garden_or_plot: bool         # L3 — parcela/jardín
    piscina: Piscina                 # P2
    has_internet_mention: bool       # L5 — mención a fibra/internet en descripción

    # Servicios específicos del anuncio (override de zona si se conocen)
    distance_supermarket_min: int | None = None
    distance_health_center_min: int | None = None
    distance_hospital_min: int | None = None

    # Estado de la vivienda
    habitable: bool = True           # L4 — False si descripción indica ruina/derruida
    description: str = ""

    # Metadatos
    first_seen: datetime = field(default_factory=datetime.now)
    last_seen: datetime = field(default_factory=datetime.now)
    source: str = ""                 # info adicional de origen (ej: "gmail_alert")
    published_at: str | None = None  # fecha de publicacion en el portal (ISO str o None)
    has_ac: bool = False             # P13 ? aire acondicionado

    @property
    def unique_id(self) -> str:
        """ID global único: portal + id en portal."""
        return f"{self.portal.value}:{self.portal_id}"


# ---------------------------------------------------------------------------
# Propiedad puntuada
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ScoreBreakdown:
    """Desglose de puntuación por criterio."""
    p1_rooms: float        # máx 5
    p2_piscina: float      # máx 8
    p3_distance: float     # máx 6
    p4_beach: float        # máx 7
    p5_pools: float        # máx 6
    p6_supermarket: float  # máx 8
    p7_health: float       # máx 9
    p8_hospital: float     # máx 9
    p9_price: float        # máx 8
    p10_fire: float        # máx 9
    p11_preference: float  # máx 9 — gusto personal por la provincia
    p12_flood: float       # máx 9 — riesgo inundación
    p13_ac: float          # máx 4 — aire acondicionado

    @property
    def total(self) -> float:
        return (
            self.p1_rooms + self.p2_piscina + self.p3_distance +
            self.p4_beach + self.p5_pools + self.p6_supermarket +
            self.p7_health + self.p8_hospital + self.p9_price +
            self.p10_fire + self.p11_preference + self.p12_flood + self.p13_ac
        )

    MAX_SCORE: float = 97.0   # 75 + 9 P11 + 9 P12 + 4 P13

    def as_dict(self) -> dict[str, float]:
        return {
            "P1_habitaciones": self.p1_rooms,
            "P2_piscina": self.p2_piscina,
            "P3_distancia_madrid": self.p3_distance,
            "P4_playa": self.p4_beach,
            "P5_piscinas_naturales": self.p5_pools,
            "P6_supermercado": self.p6_supermarket,
            "P7_centro_salud": self.p7_health,
            "P8_hospital": self.p8_hospital,
            "P9_precio": self.p9_price,
            "P10_incendio": self.p10_fire,
            "P11_preferencia_provincia": self.p11_preference,
            "P12_riesgo_inundacion": self.p12_flood,
            "P13_aire_acondicionado": self.p13_ac,
            "TOTAL": self.total,
        }


@dataclass(frozen=True)
class ScoredProperty:
    """Propiedad que ha pasado los limitantes y tiene puntuación calculada."""
    prop: Property
    zone: Zone
    score: ScoreBreakdown
    scored_at: datetime = field(default_factory=datetime.now)

    @property
    def total_score(self) -> float:
        return self.score.total

    @property
    def passes_alert_threshold(self) -> bool:
        return self.total_score >= 57.0  # sincronizado con ALERT_THRESHOLD en scorer.py


# ---------------------------------------------------------------------------
# Resultado de filtrado de limitantes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FilterResult:
    """Resultado de aplicar los limitantes L1-L11 a una propiedad."""
    passes: bool
    failed_limiters: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def ok(cls) -> FilterResult:
        return cls(passes=True, failed_limiters=())

    @classmethod
    def fail(cls, *reasons: str) -> FilterResult:
        return cls(passes=False, failed_limiters=reasons)


# ---------------------------------------------------------------------------
# Evento de precio (para historial)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PriceEvent:
    """Cambio de precio detectado en un anuncio."""
    property_uid: str        # Property.unique_id
    old_price: int           # € anterior
    new_price: int           # € actual
    detected_at: datetime = field(default_factory=datetime.now)

    @property
    def delta(self) -> int:
        return self.new_price - self.old_price

    @property
    def delta_pct(self) -> float:
        if self.old_price == 0:
            return 0.0
        return (self.delta / self.old_price) * 100
