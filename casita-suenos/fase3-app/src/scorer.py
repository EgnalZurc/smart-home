"""
Motor de scoring para Casita Suenos.
Aplica:
  - Limitantes L1, L4–L11: si alguno falla, la propiedad se descarta.
  - L2 (garaje) y L3 (jardin): SOFT — no descartan cuando el dato es desconocido
    porque los scrapers de listado no tienen esa informacion en el DOM.
    Solo descartan si el dato esta explicitamente a False Y la descripcion
    menciona ausencia activa. Si es True (garantizado por URL de busqueda), suma puntos.
  - Criterios de puntuacion P1–P11 con ponderaciones definidas en el estudio.
Puntuacion maxima: 84 puntos (75 base + 9 de P11 gusto provincia).
Umbral de alerta: 50 puntos.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass
from models import (
    FilterResult,
    FireRisk,
    FloodRisk,
    Piscina,
    Property,
    ScoreBreakdown,
    ScoredProperty,
    Zone,
)
logger = logging.getLogger(__name__)
ALERT_THRESHOLD = 57.0  # +5 P12 +2 P13
MAX_PRICE = 320_000
# ---------------------------------------------------------------------------
# Limitantes
# ---------------------------------------------------------------------------
def apply_limiters(prop: Property, zone: Zone) -> FilterResult:
    """
    Aplica los limitantes. L2 y L3 son soft: no descartan si el dato
    es desconocido (los scrapers de listado no tienen garaje/jardin en el DOM).
    Solo descartan si la descripcion menciona EXPLICITAMENTE la ausencia.
    """
    failures: list[str] = []

    # L1 — Minimo 3 habitaciones (solo descarta si conocemos el dato y es < 3)
    if prop.rooms is not None and prop.rooms < 3:
        failures.append(f"L1: habitaciones={prop.rooms} < 3")

    # L2 — Garaje/aparcamiento (SEMI-SOFT)
    # Si la casa tiene jardin/parcela pero garaje no se menciona: NO descartar.
    # Una casa con parcela en zona rural implica espacio para aparcar.
    # Descartamos solo si: descripcion dice explicitamente sin garaje
    # O si no tiene ni jardin ni garaje (piso urbano sin exterior).
    if not prop.has_garage:
        desc_lower_l2 = prop.description.lower()
        explicit_no_garage = any(s in desc_lower_l2 for s in (
            "sin garaje", "sin parking", "sin aparcamiento",
            "no dispone de garaje", "no incluye garaje", "no tiene garaje",
        ))
        if explicit_no_garage:
            failures.append("L2: descripcion indica sin garaje/aparcamiento")
        elif not prop.has_garden_or_plot:
            # Sin jardin Y sin garaje: propiedad urbana sin exterior
            failures.append("L2: sin garaje ni parcela (urbano sin exterior)")
        # Con jardin pero sin mencion garaje: pass (parcela implica espacio coche)

    # L3 — Jardin/parcela (HARD)
    # Requisito real: parcela con espacio para huerto y barbacoa.
    # Pisos.com garantiza por URL, Habitaclia infiere del texto.
    # Si no hay mención de jardín/parcela → descarte.
    if not prop.has_garden_or_plot:
        failures.append("L3: sin parcela o jardin (no mencionado o ausente)")

    # L4 — Estructura sana (habitable)
    if not prop.habitable:
        failures.append("L4: vivienda no habitable (ruina / obra mayor)")

    # L5 — Conectividad: solo descarta si descripcion menciona explicitamente sin cobertura
    desc_lower = prop.description.lower()
    no_internet_signals = ("sin cobertura", "sin internet", "sin wifi", "sin fibra")
    if any(s in desc_lower for s in no_internet_signals):
        failures.append("L5: descripcion indica sin cobertura de internet")

    # L6 — Maximo 4h30 desde Vicalvaro (270 min)
    if zone.distance_madrid_min > 270:
        failures.append(f"L6: distancia Madrid={zone.distance_madrid_min}min > 270min")

    # L7 — Supermercado maximo 30 min
    supermarket_min = prop.distance_supermarket_min or zone.distance_supermarket_min
    if supermarket_min > 30:
        failures.append(f"L7: supermercado={supermarket_min}min > 30min")

    # L8 — Centro de salud maximo 60 min
    health_min = prop.distance_health_center_min or zone.distance_health_center_min
    if health_min > 60:
        failures.append(f"L8: centro salud={health_min}min > 60min")

    # L9 — Hospital maximo 90 min
    hospital_min = prop.distance_hospital_min or zone.distance_hospital_min
    if hospital_min > 90:
        failures.append(f"L9: hospital={hospital_min}min > 90min")

    # L10 — Riesgo de incendio MUY ALTO → descarte
    if zone.fire_risk == FireRisk.MUY_ALTO:
        failures.append(f"L10: riesgo incendio MUY_ALTO en zona {zone.id}")

    # L11 — Precio maximo 320.000 EUR
    if prop.price > MAX_PRICE:
        failures.append(f"L11: precio={prop.price}EUR > {MAX_PRICE}EUR")

    # L12 — Riesgo de inundacion ALTO → descarte automatico
    flood = getattr(zone, "flood_risk", None)
    if flood is not None and flood == FloodRisk.ALTO:
        failures.append(f"L12: riesgo inundacion ALTO en zona {zone.id}")

    if failures:
        return FilterResult.fail(*failures)
    return FilterResult.ok()


# ---------------------------------------------------------------------------
# Puntuacion
# ---------------------------------------------------------------------------
def _score_rooms(rooms: int | None) -> float:
    """P1 — Habitaciones (max 5)."""
    if rooms is None:
        return 2.5   # desconocido: valor neutro (puede tener 3 o 4)
    if rooms >= 5:
        return 5.0
    if rooms == 4:
        return 3.5
    return 2.0  # 3 hab


def _score_piscina(piscina: Piscina) -> float:
    """P2 — Piscina (max 8)."""
    return {
        Piscina.PROPIA:      8.0,
        Piscina.ESPACIO:     5.0,
        Piscina.COMUNITARIA: 3.0,
        Piscina.NINGUNA:     0.0,
    }[piscina]


def _score_distance_madrid(minutes: int) -> float:
    """P3 — Distancia Madrid (max 6). Sin peaje."""
    if minutes <= 90:
        return 6.0
    if minutes <= 120:
        return 5.0
    if minutes <= 150:
        return 4.0
    if minutes <= 180:
        return 3.0
    if minutes <= 210:
        return 2.0
    if minutes <= 240:
        return 1.0
    return 0.5


def _score_beach(minutes: int | None) -> float:
    """P4 — Playa (max 7). None = muy lejos."""
    if minutes is None:
        return 0.5
    if minutes <= 30:
        return 7.0
    if minutes <= 60:
        return 5.0
    if minutes <= 90:
        return 3.0
    if minutes <= 120:
        return 1.5
    return 0.5


def _score_natural_pools(minutes: int | None) -> float:
    """P5 — Piscinas naturales (max 6)."""
    if minutes is None:
        return 0.5
    if minutes <= 15:
        return 6.0
    if minutes <= 30:
        return 4.5
    if minutes <= 60:
        return 3.0
    return 1.0


def _score_supermarket(minutes: int) -> float:
    """P6 — Supermercado (max 8)."""
    if minutes <= 5:
        return 8.0
    if minutes <= 10:
        return 6.0
    if minutes <= 20:
        return 4.0
    return 2.0


def _score_health_center(minutes: int) -> float:
    """P7 — Centro de salud (max 9)."""
    if minutes <= 10:
        return 9.0
    if minutes <= 20:
        return 7.0
    if minutes <= 30:
        return 5.0
    if minutes <= 45:
        return 3.0
    return 1.0


def _score_hospital(minutes: int) -> float:
    """P8 — Hospital (max 9)."""
    if minutes <= 20:
        return 9.0
    if minutes <= 30:
        return 7.0
    if minutes <= 45:
        return 5.0
    if minutes <= 60:
        return 3.0
    return 1.0


def _score_price(price: int) -> float:
    """P9 — Precio (max 8). Cuanto mas barato mejor."""
    if price <= 150_000:
        return 8.0
    if price <= 200_000:
        return 6.5
    if price <= 250_000:
        return 5.0
    if price <= 270_000:
        return 3.5
    return 2.0


def _score_fire_risk(risk: FireRisk) -> float:
    """P10 — Riesgo incendio (max 9)."""
    return {
        FireRisk.NULO:       9.0,
        FireRisk.MUY_BAJO:   7.0,
        FireRisk.BAJO:       5.0,
        FireRisk.MEDIO:      3.0,
        FireRisk.MEDIO_ALTO: 2.0,
        FireRisk.ALTO:       1.0,
        FireRisk.MUY_ALTO:   0.0,
    }[risk]


def _score_preference(preference: float) -> float:
    """P11 — Gusto personal por la provincia (max 9)."""
    return max(0.0, min(9.0, float(preference)))

def _score_flood_risk(risk) -> float:
    """P12 — Riesgo inundacion (max 9). ALTO ya fue descartado en L12."""
    if risk is None:
        return 7.0  # Sin dato → tratar como BAJO
    return {
        FloodRisk.NULO:        9.0,
        FloodRisk.BAJO:        7.0,
        FloodRisk.BAJO_MEDIO:  5.0,
        FloodRisk.MEDIO:       3.0,
        FloodRisk.MEDIO_ALTO:  1.0,
        FloodRisk.ALTO:        0.0,  # nunca debería llegar aquí
    }.get(risk, 7.0)

def _score_ac(has_ac: bool) -> float:
    """P13 — Aire acondicionado (max 4). Solo puntua si hay certeza de que existe."""
    return 4.0 if has_ac else 0.0


def calculate_score(prop: Property, zone: Zone) -> ScoreBreakdown:
    """Calcula la puntuacion completa de una propiedad que ya paso los limitantes."""
    supermarket_min = prop.distance_supermarket_min or zone.distance_supermarket_min
    health_min = prop.distance_health_center_min or zone.distance_health_center_min
    hospital_min = prop.distance_hospital_min or zone.distance_hospital_min
    return ScoreBreakdown(
        p1_rooms=_score_rooms(prop.rooms),
        p2_piscina=_score_piscina(prop.piscina),
        p3_distance=_score_distance_madrid(zone.distance_madrid_min),
        p4_beach=_score_beach(zone.distance_beach_min),
        p5_pools=_score_natural_pools(zone.distance_natural_pools_min),
        p6_supermarket=_score_supermarket(supermarket_min),
        p7_health=_score_health_center(health_min),
        p8_hospital=_score_hospital(hospital_min),
        p9_price=_score_price(prop.price),
        p10_fire=_score_fire_risk(zone.fire_risk),
        p11_preference=_score_preference(zone.zone_preference),
        p12_flood=_score_flood_risk(getattr(zone, "flood_risk", None)),
        p13_ac=_score_ac(getattr(prop, "has_ac", False)),
    )


# ---------------------------------------------------------------------------
# Funcion principal
# ---------------------------------------------------------------------------
def evaluate(prop: Property, zone: Zone) -> ScoredProperty | None:
    """
    Evalua una propiedad aplicando limitantes y puntuacion.
    L2/L3 son soft: no descartan si el dato es desconocido (scraper de listado).
    Returns:
        ScoredProperty si pasa los limitantes, None si es descartada.
    """
    filter_result = apply_limiters(prop, zone)
    if not filter_result.passes:
        logger.debug(
            "[scorer] Descartada %s: %s",
            prop.unique_id,
            ", ".join(filter_result.failed_limiters),
        )
        return None
    score = calculate_score(prop, zone)
    scored = ScoredProperty(prop=prop, zone=zone, score=score)
    logger.info(
        "[scorer] %s -> %.1f/97 %s",
        prop.unique_id,
        scored.total_score,
        "ALERTA" if scored.passes_alert_threshold else "",
    )
    return scored
