"""
Motor de scoring para Casita Sueños — sistema R1-R18.

No hay distinción entre limitantes y puntuación.
Todos los criterios puntúan, con posibilidad de puntuación negativa.

Puntuación máxima: 180 pts
Umbral de alerta: 66% → 119 pts
"""
from __future__ import annotations
import logging
import math
from models import (
    FireRisk, FloodRisk, GarageType, Habitability, Internet,
    Piscina, Property, ScoreBreakdown, ScoredProperty, Zone,
)

logger = logging.getLogger(__name__)

ALERT_THRESHOLD = 119.0   # 66% de 180 (redondeado a entero)
MAX_SCORE       = 180.0


# ---------------------------------------------------------------------------
# R1 — Habitaciones (máx 10)
# ---------------------------------------------------------------------------

def _r1_rooms(rooms: int | None) -> float:
    if rooms is None or rooms <= 2:
        return 0.0
    if rooms == 3:
        return 5.0
    # 4=6, 5=7, 6=8, 7=9, 8+=10
    return min(10.0, float(4 + rooms))


# ---------------------------------------------------------------------------
# R2 — Terreno (máx 10, mín -5)
# ---------------------------------------------------------------------------

def _r2_terrain(has_garden: bool, terrain_m2: float | None) -> float:
    if not has_garden:
        return -5.0
    # Tiene terreno: sin dato → 5, linear 100-400m² → 5-10, ≥400 → 10
    if terrain_m2 is None or terrain_m2 <= 0:
        return 5.0
    if terrain_m2 < 100:
        return 5.0
    if terrain_m2 >= 400:
        return 10.0
    # Linear entre 100m²=5 y 400m²=10
    return round(5.0 + (terrain_m2 - 100) / (400 - 100) * 5.0, 1)


# ---------------------------------------------------------------------------
# R3 — Garaje (máx 10)
# ---------------------------------------------------------------------------

def _r3_garage(garage_type: GarageType, has_garden: bool) -> float:
    if garage_type == GarageType.EDIFICIO:
        return 10.0
    if garage_type == GarageType.EXTERIOR:
        return 5.0
    # Sin info: si tiene terreno → 5, si no → 0
    if has_garden:
        return 5.0
    return 0.0


# ---------------------------------------------------------------------------
# R4 — Habitabilidad (máx 10, mín -10)
# ---------------------------------------------------------------------------

def _r4_habitability(hab: Habitability) -> float:
    return {
        Habitability.RUINA:       -10.0,
        Habitability.REFORMA:     -10.0,
        Habitability.DESCONOCIDO:   0.0,
        Habitability.PENDIENTE:     4.0,
        Habitability.BUENO:         7.0,
        Habitability.REFORMADO:    10.0,
    }[hab]


# ---------------------------------------------------------------------------
# R5 — Piscina (máx 10)
# ---------------------------------------------------------------------------

def _r5_piscina(piscina: Piscina) -> float:
    return {
        Piscina.PROPIA:      10.0,
        Piscina.COMUNITARIA:  8.0,
        Piscina.ESPACIO:      6.0,
        Piscina.NINGUNA:      0.0,
    }[piscina]


# ---------------------------------------------------------------------------
# R6 — Aire acondicionado (máx 10)
# ---------------------------------------------------------------------------

def _r6_ac(has_ac: bool, has_ac_preinstalled: bool) -> float:
    if has_ac:
        return 10.0
    if has_ac_preinstalled:
        return 8.0
    return 5.0  # Sin info: 5 pts (puede instalarse)


# ---------------------------------------------------------------------------
# R7 — Precio (máx 10, mín 0)
#   0€ → 0 | 0-50k lineal 0→3 | 50-100k lineal 3→10
#   100k → 10 (pico) | 100-300k lineal 10→5 | 300k → 5
#   300-350k lineal 5→0 | ≥350k → 0
# ---------------------------------------------------------------------------

def _r7_price(price: int) -> float:
    if price <= 0:
        return 0.0
    if price <= 50_000:
        return round(price / 50_000 * 3.0, 1)
    if price <= 100_000:
        return round(3.0 + (price - 50_000) / 50_000 * 7.0, 1)
    if price <= 300_000:
        return round(10.0 - (price - 100_000) / 200_000 * 5.0, 1)
    if price <= 350_000:
        return round(5.0 - (price - 300_000) / 50_000 * 5.0, 1)
    return 0.0


# ---------------------------------------------------------------------------
# R8 — Supermercado (máx 10)
#   ≤5min → 10 | 5-20min lineal 10→5 | >20min → 0
# ---------------------------------------------------------------------------

def _r8_supermarket(minutes: int) -> float:
    if minutes <= 5:
        return 10.0
    if minutes > 20:
        return 0.0
    # 5-20min → 10 a 5 (lineal, redondeo arriba sin decimales)
    raw = 10.0 - (minutes - 5) / (20 - 5) * 5.0
    return math.ceil(raw)


# ---------------------------------------------------------------------------
# R9 — Centro de salud (máx 10)
#   ≤5min → 10 | 5-60min lineal 10→0 | >60min → 0
# ---------------------------------------------------------------------------

def _r9_health(minutes: int) -> float:
    if minutes <= 5:
        return 10.0
    if minutes >= 60:
        return 0.0
    raw = 10.0 - (minutes - 5) / (60 - 5) * 10.0
    return math.ceil(raw)


# ---------------------------------------------------------------------------
# R10 — Hospital (máx 10)
#   ≤5min → 10 | 5-90min lineal 10→0 | >90min → 0
# ---------------------------------------------------------------------------

def _r10_hospital(minutes: int) -> float:
    if minutes <= 5:
        return 10.0
    if minutes >= 90:
        return 0.0
    raw = 10.0 - (minutes - 5) / (90 - 5) * 10.0
    return math.ceil(raw)


# ---------------------------------------------------------------------------
# R11 — Internet (máx 10)
# ---------------------------------------------------------------------------

def _r11_internet(internet: Internet) -> float:
    return {
        Internet.NINGUNO:     4.0,
        Internet.INSTALACION: 8.0,
        Internet.FIBRA:       10.0,
    }[internet]


# ---------------------------------------------------------------------------
# R12 — Distancia Madrid (0 o 10)
#   ≤270min → 10 | >270min → 0
# ---------------------------------------------------------------------------

def _r12_madrid(minutes: int) -> float:
    return 10.0 if minutes <= 270 else 0.0


# ---------------------------------------------------------------------------
# R13 — Playa (máx 10)
#   ≤5min → 10 | 5-30min lineal 10→0 | ≥30min → 0
# ---------------------------------------------------------------------------

def _r13_beach(minutes: int | None) -> float:
    if minutes is None:
        return 0.0
    if minutes <= 5:
        return 10.0
    if minutes >= 30:
        return 0.0
    raw = 10.0 - (minutes - 5) / (30 - 5) * 10.0
    return max(0.0, math.ceil(raw))


# ---------------------------------------------------------------------------
# R14 — Piscinas naturales (máx 10)
#   ≤5min → 10 | 5-20min lineal 10→0 | ≥20min → 0
# ---------------------------------------------------------------------------

def _r14_pools(minutes: int | None) -> float:
    if minutes is None:
        return 0.0
    if minutes <= 5:
        return 10.0
    if minutes >= 20:
        return 0.0
    raw = 10.0 - (minutes - 5) / (20 - 5) * 10.0
    return max(0.0, math.ceil(raw))


# ---------------------------------------------------------------------------
# R15 — Riesgo de incendio (máx 10, mín -10)
# ---------------------------------------------------------------------------

def _r15_fire(risk: FireRisk) -> float:
    return {
        FireRisk.MUY_ALTO:   -10.0,
        FireRisk.ALTO:         0.0,
        FireRisk.MEDIO_ALTO:   3.0,
        FireRisk.MEDIO:        5.0,
        FireRisk.MUY_BAJO:     7.0,  # MUY_BAJO usa misma escala que MEDIO_BAJO
        FireRisk.BAJO:         9.0,
        FireRisk.NULO:        10.0,
    }[risk]


# ---------------------------------------------------------------------------
# R16 — Riesgo de inundación (máx 10, mín -10)
# ---------------------------------------------------------------------------

def _r16_flood(risk) -> float:
    if risk is None:
        return 4.0  # Sin datos → neutro
    mapping = {
        FloodRisk.ALTO:        0.0,   # No hay MUY_ALTO en FloodRisk → ALTO = 0
        FloodRisk.MEDIO_ALTO:  3.0,
        FloodRisk.MEDIO:       5.0,
        FloodRisk.BAJO_MEDIO:  7.0,
        FloodRisk.BAJO:        9.0,
        FloodRisk.NULO:       10.0,
    }
    val = mapping.get(risk, 4.0)
    return val


# ---------------------------------------------------------------------------
# R17 — Provincia con costa (0 o 10)
# ---------------------------------------------------------------------------

def _r17_coast(has_coast: bool) -> float:
    return 10.0 if has_coast else 0.0


# ---------------------------------------------------------------------------
# R18 — Bonus playa+terreno (0 o 10)
#   Condición: terreno confirmado (has_garden=True) Y playa a ≤1.5km
#   Proxy: distance_beach_min <= 2 min en coche ≈ ≤1.5km
# ---------------------------------------------------------------------------

def _r18_beach_plot(has_garden: bool, beach_min: int | None) -> float:
    if not has_garden:
        return 0.0
    if beach_min is None:
        return 0.0
    # ≤1.5km ≈ ≤2 min en coche o ≤30min andando (proxy)
    if beach_min <= 2:
        return 10.0
    return 0.0


# ---------------------------------------------------------------------------
# Función principal
# ---------------------------------------------------------------------------

def evaluate(prop: Property, zone: Zone) -> ScoredProperty:
    """
    Evalúa una propiedad y devuelve ScoredProperty con puntuación R1-R18.
    Siempre devuelve un resultado (no hay descarte por limitantes — todo puntúa).
    Una propiedad con muchas penalizaciones puede quedar en puntuación negativa
    y no pasará el umbral de alerta.
    """
    supermarket_min = prop.distance_supermarket_min or zone.distance_supermarket_min
    health_min      = prop.distance_health_center_min or zone.distance_health_center_min
    hospital_min    = prop.distance_hospital_min or zone.distance_hospital_min
    beach_min       = zone.distance_beach_min

    # Habitability desde el nuevo campo; fallback desde bool habitable legado
    hab = getattr(prop, 'habitability', None)
    if hab is None:
        hab = Habitability.BUENO if prop.habitable else Habitability.REFORMA

    # Internet desde el nuevo campo; fallback desde has_internet_mention legado
    internet = getattr(prop, 'internet', None)
    if internet is None:
        internet = Internet.INSTALACION if prop.has_internet_mention else Internet.NINGUNO

    # GarageType desde el nuevo campo; fallback desde has_garage legado
    garage_type = getattr(prop, 'garage_type', None)
    if garage_type is None:
        garage_type = GarageType.EXTERIOR if prop.has_garage else GarageType.NINGUNO

    # terrain_m2 — puede ser None
    terrain_m2 = getattr(prop, 'terrain_m2', None)

    # has_ac y has_ac_preinstalled
    has_ac = getattr(prop, 'has_ac', False)
    has_ac_pre = getattr(prop, 'has_ac_preinstalled', False)

    # has_coast desde la zona
    has_coast = getattr(zone, 'has_coast', False)

    score = ScoreBreakdown(
        r1_rooms      = _r1_rooms(prop.rooms),
        r2_terrain    = _r2_terrain(prop.has_garden_or_plot, terrain_m2),
        r3_garage     = _r3_garage(garage_type, prop.has_garden_or_plot),
        r4_habitability = _r4_habitability(hab),
        r5_piscina    = _r5_piscina(prop.piscina),
        r6_ac         = _r6_ac(has_ac, has_ac_pre),
        r7_price      = _r7_price(prop.price),
        r8_supermarket = _r8_supermarket(supermarket_min),
        r9_health     = _r9_health(health_min),
        r10_hospital  = _r10_hospital(hospital_min),
        r11_internet  = _r11_internet(internet),
        r12_madrid    = _r12_madrid(zone.distance_madrid_min),
        r13_beach     = _r13_beach(beach_min),
        r14_pools     = _r14_pools(zone.distance_natural_pools_min),
        r15_fire      = _r15_fire(zone.fire_risk),
        r16_flood     = _r16_flood(getattr(zone, 'flood_risk', None)),
        r17_coast     = _r17_coast(has_coast),
        r18_beach_plot = _r18_beach_plot(prop.has_garden_or_plot, beach_min),
    )

    scored = ScoredProperty(prop=prop, zone=zone, score=score)
    logger.info(
        "[scorer] %s → %.1f/180 %s",
        prop.unique_id,
        scored.total_score,
        "ALERTA" if scored.passes_alert_threshold else "",
    )
    return scored
