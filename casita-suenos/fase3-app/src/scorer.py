"""
Motor de scoring para Casita Sueños.

Aplica:
  - Limitantes L1–L11: si alguno falla, la propiedad se descarta.
  - Criterios de puntuación P1–P11 con ponderaciones definidas en el estudio.

Puntuación máxima: 84 puntos (75 base + 9 de P11 gusto provincia).
Umbral de alerta: 50 puntos (sube 5 respecto a los 45 originales al añadir P11).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from models import (
    FilterResult,
    FireRisk,
    Piscina,
    Property,
    ScoreBreakdown,
    ScoredProperty,
    Zone,
)

logger = logging.getLogger(__name__)

ALERT_THRESHOLD = 50.0   # sube de 45 a 50 con la adición de P11
MAX_PRICE = 320_000


# ---------------------------------------------------------------------------
# Limitantes
# ---------------------------------------------------------------------------

def apply_limiters(prop: Property, zone: Zone) -> FilterResult:
    """
    Aplica los 11 limitantes. Devuelve FilterResult con todos los fallos.
    Un solo fallo ya descarta la propiedad.
    """
    failures: list[str] = []

    # L1 — Mínimo 3 habitaciones
    if prop.rooms is not None and prop.rooms < 3:
        failures.append(f"L1: habitaciones={prop.rooms} < 3")

    # L2 — Aparcamiento / garaje / espacio en finca
    if not prop.has_garage:
        failures.append("L2: sin aparcamiento ni garaje")

    # L3 — Parcela con espacio para huerto y barbacoa
    if not prop.has_garden_or_plot:
        failures.append("L3: sin parcela o jardín")

    # L4 — Estructura sana (habitable)
    if not prop.habitable:
        failures.append("L4: vivienda no habitable (ruina / obra mayor)")

    # L5 — Conectividad para teletrabajar (mención a internet en descripción)
    # Solo descartamos si la descripción menciona explícitamente ausencia de cobertura.
    # La mayoría de anuncios no mencionan internet → no descartamos por omisión.
    desc_lower = prop.description.lower()
    no_internet_signals = ("sin cobertura", "sin internet", "sin wifi", "sin fibra")
    if any(s in desc_lower for s in no_internet_signals):
        failures.append("L5: descripción indica sin cobertura de internet")

    # L6 — Máximo 4h30 desde Vicálvaro (270 min)
    if zone.distance_madrid_min > 270:
        failures.append(f"L6: distancia Madrid={zone.distance_madrid_min}min > 270min")

    # L7 — Supermercado máximo 30 min
    supermarket_min = prop.distance_supermarket_min or zone.distance_supermarket_min
    if supermarket_min > 30:
        failures.append(f"L7: supermercado={supermarket_min}min > 30min")

    # L8 — Centro de salud máximo 60 min
    health_min = prop.distance_health_center_min or zone.distance_health_center_min
    if health_min > 60:
        failures.append(f"L8: centro salud={health_min}min > 60min")

    # L9 — Hospital máximo 90 min
    hospital_min = prop.distance_hospital_min or zone.distance_hospital_min
    if hospital_min > 90:
        failures.append(f"L9: hospital={hospital_min}min > 90min")

    # L10 — Riesgo de incendio MUY ALTO → descarte
    if zone.fire_risk == FireRisk.MUY_ALTO:
        failures.append(f"L10: riesgo incendio MUY_ALTO en zona {zone.id}")

    # L11 — Precio máximo 320.000 €
    if prop.price > MAX_PRICE:
        failures.append(f"L11: precio={prop.price}€ > {MAX_PRICE}€")

    if failures:
        return FilterResult.fail(*failures)
    return FilterResult.ok()


# ---------------------------------------------------------------------------
# Puntuación
# ---------------------------------------------------------------------------

def _score_rooms(rooms: int | None) -> float:
    """P1 — Habitaciones (máx 5)."""
    if rooms is None:
        return 2.0
    if rooms >= 5:
        return 5.0
    if rooms == 4:
        return 3.5
    return 2.0  # 3 hab


def _score_piscina(piscina: Piscina) -> float:
    """P2 — Piscina (máx 8)."""
    return {
        Piscina.PROPIA:      8.0,
        Piscina.ESPACIO:     5.0,
        Piscina.COMUNITARIA: 3.0,
        Piscina.NINGUNA:     0.0,
    }[piscina]


def _score_distance_madrid(minutes: int) -> float:
    """P3 — Distancia Madrid (máx 6). Sin peaje."""
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
    return 0.5  # 240–270 min


def _score_beach(minutes: int | None) -> float:
    """P4 — Playa (máx 7). None = muy lejos."""
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
    """P5 — Piscinas naturales (máx 6)."""
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
    """P6 — Supermercado (máx 8). Dentro del límite de 30 min."""
    if minutes <= 5:
        return 8.0
    if minutes <= 10:
        return 6.0
    if minutes <= 20:
        return 4.0
    return 2.0  # 20–30 min


def _score_health_center(minutes: int) -> float:
    """P7 — Centro de salud (máx 9). Dentro del límite de 60 min."""
    if minutes <= 10:
        return 9.0
    if minutes <= 20:
        return 7.0
    if minutes <= 30:
        return 5.0
    if minutes <= 45:
        return 3.0
    return 1.0  # 45–60 min


def _score_hospital(minutes: int) -> float:
    """P8 — Hospital (máx 9). Dentro del límite de 90 min."""
    if minutes <= 20:
        return 9.0
    if minutes <= 30:
        return 7.0
    if minutes <= 45:
        return 5.0
    if minutes <= 60:
        return 3.0
    return 1.0  # 60–90 min


def _score_price(price: int) -> float:
    """P9 — Precio (máx 8). Cuanto más barato mejor."""
    if price <= 150_000:
        return 8.0
    if price <= 200_000:
        return 6.5
    if price <= 250_000:
        return 5.0
    if price <= 270_000:
        return 3.5
    return 2.0  # 270k–320k


def _score_fire_risk(risk: FireRisk) -> float:
    """P10 — Riesgo incendio (máx 9). MUY_ALTO ya fue descartado en L10."""
    return {
        FireRisk.NULO:       9.0,
        FireRisk.MUY_BAJO:   7.0,
        FireRisk.BAJO:       5.0,
        FireRisk.MEDIO:      3.0,
        FireRisk.MEDIO_ALTO: 2.0,
        FireRisk.ALTO:       1.0,
        FireRisk.MUY_ALTO:   0.0,  # nunca debería llegar aquí
    }[risk]


def _score_preference(preference: float) -> float:
    """P11 — Gusto personal por la provincia (máx 9). Valor directo de Zone.zone_preference."""
    return max(0.0, min(9.0, float(preference)))


def calculate_score(prop: Property, zone: Zone) -> ScoreBreakdown:
    """Calcula la puntuación completa de una propiedad que ya pasó los limitantes."""
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
    )


# ---------------------------------------------------------------------------
# Función principal
# ---------------------------------------------------------------------------

def evaluate(prop: Property, zone: Zone) -> ScoredProperty | None:
    """
    Evalúa una propiedad aplicando limitantes y puntuación.

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
        "[scorer] %s → %.1f/75 %s",
        prop.unique_id,
        scored.total_score,
        "⭐ ALERTA" if scored.passes_alert_threshold else "",
    )

    return scored
