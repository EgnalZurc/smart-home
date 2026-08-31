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
    ESPACIO      = "espacio"       # cabe instalarla en la parcela
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
    MUY_ALTO    = "muy_alto"

class FloodRisk(str, Enum):
    """Nivel de riesgo de inundación de la zona (SNCZI/CHE/CHC/PATRICOVA)."""
    NULO        = "nulo"
    BAJO        = "bajo"
    BAJO_MEDIO  = "bajo_medio"
    MEDIO       = "medio"
    MEDIO_ALTO  = "medio_alto"
    ALTO        = "alto"

class Habitability(str, Enum):
    """Estado de habitabilidad de la vivienda (R4)."""
    RUINA      = "ruina"        # Para rehabilitar / en ruinas          → -10 pts
    REFORMA    = "reforma"      # Para reformar / necesita reforma       → -10 pts
    DESCONOCIDO = "desconocido" # Sin especificar                        →   0 pts
    PENDIENTE  = "pendiente"    # Pendiente de alguna reforma menor      →   4 pts
    BUENO      = "bueno"        # Buen estado                            →   7 pts
    REFORMADO  = "reformado"    # Recién reformado / a estrenar          →  10 pts

class Internet(str, Enum):
    """Tipo de conexión a internet mencionada (R11)."""
    NINGUNO    = "ninguno"      # Sin cobertura o no mencionado          →   4 pts
    INSTALACION = "instalacion" # ADSL / 4G / instalación básica         →   8 pts
    FIBRA      = "fibra"        # Fibra óptica confirmada                →  10 pts

class GarageType(str, Enum):
    """Tipo de garaje/aparcamiento (R3)."""
    NINGUNO    = "ninguno"      # Sin info y sin terreno                 →   0 pts
    EXTERIOR   = "exterior"     # Plaza exterior / cochera / sin techn   →   5 pts
    EDIFICIO   = "edificio"     # Garaje en edificio / plaza cubierta    →  10 pts
    # Nota: "sin info pero con terreno" → EXTERIOR (5 pts) por defecto

# ---------------------------------------------------------------------------
# Zona geográfica candidata
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Zone:
    """Una zona candidata del estudio. Contiene valores de referencia para R12-R17."""
    id: str
    name: str
    distance_madrid_min: int         # R12
    distance_beach_min: int | None   # R13 — None si no aplica
    distance_natural_pools_min: int | None  # R14
    distance_supermarket_min: int    # R8
    distance_health_center_min: int  # R9
    distance_hospital_min: int       # R10
    fire_risk: FireRisk              # R15
    price_min: int
    price_max: int
    has_coast: bool = False          # R17 — True si la provincia tiene costa
    zone_preference: float = 5.0    # legado, ya no se usa en scoring (reemplazado por has_coast)
    flood_risk: "FloodRisk" = None  # R16
    fotocasa_search_urls: tuple[str, ...] = field(default_factory=tuple)
    pisos_search_urls: tuple[str, ...] = field(default_factory=tuple)
    habitaclia_search_urls: tuple[str, ...] = field(default_factory=tuple)
    idealista_alert_keywords: tuple[str, ...] = field(default_factory=tuple)
    fotocasa_municipios: tuple[str, ...] = field(default_factory=tuple)

# ---------------------------------------------------------------------------
# Propiedad (anuncio inmobiliario)
# ---------------------------------------------------------------------------

@dataclass
class Property:
    """Representa un anuncio inmobiliario normalizado."""
    # Identificación
    portal: Portal
    portal_id: str
    url: str
    zone_id: str

    # Datos del anuncio
    title: str
    price: int
    size_m2: float | None
    rooms: int | None

    # Campos R2/R3: terreno y garaje con más granularidad
    has_garden_or_plot: bool         # R2 — True si hay terreno/jardín/parcela
    terrain_m2: float | None         # R2 — m² de terreno (None = desconocido)
    garage_type: GarageType          # R3 — tipo de garaje

    # Campos de calidad y servicios
    piscina: Piscina                 # R5
    habitability: Habitability       # R4 — estado de habitabilidad
    internet: Internet               # R11 — tipo de conexión

    # Compatibilidad legada con scorer anterior
    has_garage: bool = False         # derivado de garage_type != NINGUNO
    has_internet_mention: bool = True # legado — se mantiene por compatibilidad

    # Servicios específicos del anuncio (override de zona si se conocen)
    distance_supermarket_min: int | None = None
    distance_health_center_min: int | None = None
    distance_hospital_min: int | None = None

    # Estado de la vivienda (legado — usar habitability)
    habitable: bool = True           # legado — False si habitability in (RUINA, REFORMA)

    description: str = ""
    first_seen: datetime = field(default_factory=datetime.now)
    last_seen: datetime = field(default_factory=datetime.now)
    source: str = ""
    published_at: str | None = None
    has_ac: bool = False             # R6 (preinstalación detectada en descripción)
    has_ac_preinstalled: bool = False # R6 — True si solo hay preinstalación

    @property
    def unique_id(self) -> str:
        return f"{self.portal.value}:{self.portal_id}"

# ---------------------------------------------------------------------------
# Puntuación (nuevo sistema R1-R18)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ScoreBreakdown:
    """Desglose de puntuación por criterio R1-R18."""
    r1_rooms: float          # máx 10 — habitaciones
    r2_terrain: float        # máx 10 (mín -5) — terreno
    r3_garage: float         # máx 10 — garaje
    r4_habitability: float   # máx 10 (mín -10) — habitabilidad
    r5_piscina: float        # máx 10 — piscina
    r6_ac: float             # máx 10 — aire acondicionado
    r7_price: float          # máx 10 — precio
    r8_supermarket: float    # máx 10 — supermercado
    r9_health: float         # máx 10 — centro de salud
    r10_hospital: float      # máx 10 — hospital
    r11_internet: float      # máx 10 — internet
    r12_madrid: float        # 0 o 10 — distancia Madrid
    r13_beach: float         # máx 10 — playa
    r14_pools: float         # máx 10 — piscinas naturales
    r15_fire: float          # máx 10 (mín -10) — riesgo incendio
    r16_flood: float         # máx 10 (mín -10) — riesgo inundación
    r17_coast: float         # 0 o 10 — provincia con costa
    r18_beach_plot: float    # 0 o 10 — bonus playa+terreno

    # Puntuación máxima posible: 18 criterios × 10 = 180 pts
    MAX_SCORE: float = 180.0

    @property
    def total(self) -> float:
        return (
            self.r1_rooms + self.r2_terrain + self.r3_garage + self.r4_habitability +
            self.r5_piscina + self.r6_ac + self.r7_price +
            self.r8_supermarket + self.r9_health + self.r10_hospital +
            self.r11_internet + self.r12_madrid + self.r13_beach + self.r14_pools +
            self.r15_fire + self.r16_flood + self.r17_coast + self.r18_beach_plot
        )

    def as_dict(self) -> dict[str, float]:
        return {
            "R1_habitaciones":      self.r1_rooms,
            "R2_terreno":           self.r2_terrain,
            "R3_garaje":            self.r3_garage,
            "R4_habitabilidad":     self.r4_habitability,
            "R5_piscina":           self.r5_piscina,
            "R6_aire_acondicionado":self.r6_ac,
            "R7_precio":            self.r7_price,
            "R8_supermercado":      self.r8_supermarket,
            "R9_centro_salud":      self.r9_health,
            "R10_hospital":         self.r10_hospital,
            "R11_internet":         self.r11_internet,
            "R12_distancia_madrid": self.r12_madrid,
            "R13_playa":            self.r13_beach,
            "R14_piscinas_naturales": self.r14_pools,
            "R15_riesgo_incendio":  self.r15_fire,
            "R16_riesgo_inundacion":self.r16_flood,
            "R17_provincia_costa":  self.r17_coast,
            "R18_bonus_playa_terreno": self.r18_beach_plot,
            "TOTAL":                self.total,
        }

@dataclass(frozen=True)
class ScoredProperty:
    """Propiedad con puntuación calculada."""
    prop: Property
    zone: Zone
    score: ScoreBreakdown
    scored_at: datetime = field(default_factory=datetime.now)

    @property
    def total_score(self) -> float:
        return self.score.total

    @property
    def passes_alert_threshold(self) -> bool:
        """60% de 180 = 108 pts."""
        return self.total_score >= 108.0

# ---------------------------------------------------------------------------
# Resultado de filtrado
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FilterResult:
    passes: bool
    failed_limiters: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def ok(cls) -> FilterResult:
        return cls(passes=True, failed_limiters=())

    @classmethod
    def fail(cls, *reasons: str) -> FilterResult:
        return cls(passes=False, failed_limiters=reasons)

# ---------------------------------------------------------------------------
# Evento de precio
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PriceEvent:
    property_uid: str
    old_price: int
    new_price: int
    detected_at: datetime = field(default_factory=datetime.now)

    @property
    def delta(self) -> int:
        return self.new_price - self.old_price

    @property
    def delta_pct(self) -> float:
        if self.old_price == 0:
            return 0.0
        return (self.delta / self.old_price) * 100
