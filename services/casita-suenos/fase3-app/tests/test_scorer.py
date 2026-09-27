"""
Tests unitarios del motor de scoring (scorer.py).
Cubre: limitantes L1-L11, puntuaciones P1-P10 y la función evaluate().
"""

from __future__ import annotations

import sys
from pathlib import Path

# Añadir src al path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest
from datetime import datetime

from models import FireRisk, Piscina, Portal, Property, Zone
from scorer import (
    ALERT_THRESHOLD,
    MAX_PRICE,
    _score_beach,
    _score_distance_madrid,
    _score_fire_risk,
    _score_health_center,
    _score_hospital,
    _score_natural_pools,
    _score_price,
    _score_rooms,
    _score_supermarket,
    apply_limiters,
    calculate_score,
    evaluate,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def base_zone() -> Zone:
    """Zona que pasa todos los limitantes holgadamente."""
    return Zone(
        id="test_zone",
        name="Zona de prueba",
        distance_madrid_min=150,
        distance_beach_min=None,
        distance_natural_pools_min=30,
        distance_supermarket_min=10,
        distance_health_center_min=10,
        distance_hospital_min=20,
        fire_risk=FireRisk.NULO,
        zone_preference=5.0,
        price_min=100_000,
        price_max=300_000,
    )


@pytest.fixture
def base_property(base_zone: Zone) -> Property:
    """Propiedad que pasa todos los limitantes."""
    return Property(
        portal=Portal.PISOS,
        portal_id="12345",
        url="https://www.pisos.com/venta/12345",
        zone_id=base_zone.id,
        title="Casa con jardín y garaje en zona test",
        price=200_000,
        size_m2=180.0,
        rooms=4,
        has_garage=True,
        has_garden_or_plot=True,
        piscina=Piscina.ESPACIO,
        has_internet_mention=True,
        habitable=True,
        description="Casa amplia con jardín y garaje. Parcela grande.",
        first_seen=datetime.now(),
        last_seen=datetime.now(),
    )


# ── Tests de limitantes ───────────────────────────────────────────────────────

class TestLimiters:

    def test_all_pass(self, base_property, base_zone):
        result = apply_limiters(base_property, base_zone)
        assert result.passes is True
        assert len(result.failed_limiters) == 0

    def test_l1_rooms_fail(self, base_property, base_zone):
        base_property.rooms = 2
        result = apply_limiters(base_property, base_zone)
        assert result.passes is False
        assert any("L1" in f for f in result.failed_limiters)

    def test_l1_rooms_none_passes(self, base_property, base_zone):
        """Rooms=None no descarta (datos desconocidos)."""
        base_property.rooms = None
        result = apply_limiters(base_property, base_zone)
        assert result.passes is True

    def test_l2_no_garage_fail(self, base_property, base_zone):
        base_property.has_garage = False
        result = apply_limiters(base_property, base_zone)
        assert result.passes is False
        assert any("L2" in f for f in result.failed_limiters)

    def test_l3_no_garden_fail(self, base_property, base_zone):
        base_property.has_garden_or_plot = False
        result = apply_limiters(base_property, base_zone)
        assert result.passes is False
        assert any("L3" in f for f in result.failed_limiters)

    def test_l4_not_habitable_fail(self, base_property, base_zone):
        base_property.habitable = False
        result = apply_limiters(base_property, base_zone)
        assert result.passes is False
        assert any("L4" in f for f in result.failed_limiters)

    def test_l5_no_internet_explicit_fail(self, base_property, base_zone):
        base_property.description = "Casa rural. Sin cobertura de internet en la zona."
        result = apply_limiters(base_property, base_zone)
        assert result.passes is False
        assert any("L5" in f for f in result.failed_limiters)

    def test_l5_no_mention_passes(self, base_property, base_zone):
        """Sin mención a internet no descarta (mayoría de anuncios)."""
        base_property.description = "Casa con jardín."
        result = apply_limiters(base_property, base_zone)
        assert result.passes is True

    def test_l6_too_far_fail(self, base_property, base_zone):
        base_zone = Zone(
            id="far_zone", name="Zona lejana",
            distance_madrid_min=300,  # > 270 min (4h30)
            distance_beach_min=None, distance_natural_pools_min=None,
            distance_supermarket_min=10, distance_health_center_min=10,
            distance_hospital_min=20, fire_risk=FireRisk.NULO,
            price_min=0, price_max=999_999,
        )
        result = apply_limiters(base_property, base_zone)
        assert result.passes is False
        assert any("L6" in f for f in result.failed_limiters)

    def test_l7_supermarket_too_far_fail(self, base_property, base_zone):
        base_zone = Zone(
            id="z", name="z", distance_madrid_min=150,
            distance_beach_min=None, distance_natural_pools_min=None,
            distance_supermarket_min=35,  # > 30 min
            distance_health_center_min=10, distance_hospital_min=20,
            fire_risk=FireRisk.NULO, price_min=0, price_max=999_999,
        )
        result = apply_limiters(base_property, base_zone)
        assert result.passes is False
        assert any("L7" in f for f in result.failed_limiters)

    def test_l8_health_too_far_fail(self, base_property, base_zone):
        base_zone = Zone(
            id="z", name="z", distance_madrid_min=150,
            distance_beach_min=None, distance_natural_pools_min=None,
            distance_supermarket_min=10, distance_health_center_min=65,  # > 60
            distance_hospital_min=20, fire_risk=FireRisk.NULO,
            price_min=0, price_max=999_999,
        )
        result = apply_limiters(base_property, base_zone)
        assert result.passes is False
        assert any("L8" in f for f in result.failed_limiters)

    def test_l9_hospital_too_far_fail(self, base_property, base_zone):
        base_zone = Zone(
            id="z", name="z", distance_madrid_min=150,
            distance_beach_min=None, distance_natural_pools_min=None,
            distance_supermarket_min=10, distance_health_center_min=10,
            distance_hospital_min=100,  # > 90
            fire_risk=FireRisk.NULO, price_min=0, price_max=999_999,
        )
        result = apply_limiters(base_property, base_zone)
        assert result.passes is False
        assert any("L9" in f for f in result.failed_limiters)

    def test_l10_very_high_fire_risk_fail(self, base_property, base_zone):
        base_zone = Zone(
            id="z", name="z", distance_madrid_min=150,
            distance_beach_min=None, distance_natural_pools_min=None,
            distance_supermarket_min=10, distance_health_center_min=10,
            distance_hospital_min=20, fire_risk=FireRisk.MUY_ALTO,
            price_min=0, price_max=999_999,
        )
        result = apply_limiters(base_property, base_zone)
        assert result.passes is False
        assert any("L10" in f for f in result.failed_limiters)

    def test_l10_high_fire_risk_passes(self, base_property, base_zone):
        """Riesgo ALTO (no MUY_ALTO) no descarta — solo penaliza en puntuación."""
        base_zone = Zone(
            id="z", name="z", distance_madrid_min=150,
            distance_beach_min=None, distance_natural_pools_min=None,
            distance_supermarket_min=10, distance_health_center_min=10,
            distance_hospital_min=20, fire_risk=FireRisk.ALTO,
            price_min=0, price_max=999_999,
        )
        result = apply_limiters(base_property, base_zone)
        assert result.passes is True

    def test_l11_price_too_high_fail(self, base_property, base_zone):
        base_property.price = MAX_PRICE + 1
        result = apply_limiters(base_property, base_zone)
        assert result.passes is False
        assert any("L11" in f for f in result.failed_limiters)

    def test_l11_price_at_limit_passes(self, base_property, base_zone):
        base_property.price = MAX_PRICE
        result = apply_limiters(base_property, base_zone)
        assert result.passes is True

    def test_multiple_failures_reported(self, base_property, base_zone):
        """Todos los fallos deben reportarse, no solo el primero."""
        base_property.rooms = 1
        base_property.has_garage = False
        base_property.has_garden_or_plot = False
        result = apply_limiters(base_property, base_zone)
        assert result.passes is False
        assert len(result.failed_limiters) >= 3


# ── Tests de puntuación ───────────────────────────────────────────────────────

class TestScoringFunctions:

    def test_rooms_3(self):
        assert _score_rooms(3) == pytest.approx(2.0)

    def test_rooms_4(self):
        assert _score_rooms(4) == pytest.approx(3.5)

    def test_rooms_5_plus(self):
        assert _score_rooms(5) == pytest.approx(5.0)
        assert _score_rooms(7) == pytest.approx(5.0)

    def test_rooms_none(self):
        assert _score_rooms(None) == pytest.approx(2.0)

    def test_distance_madrid_brackets(self):
        assert _score_distance_madrid(60) == pytest.approx(6.0)
        assert _score_distance_madrid(90) == pytest.approx(6.0)
        assert _score_distance_madrid(91) == pytest.approx(5.0)
        assert _score_distance_madrid(150) == pytest.approx(4.0)
        assert _score_distance_madrid(270) == pytest.approx(0.5)

    def test_beach_none(self):
        assert _score_beach(None) == pytest.approx(0.5)

    def test_beach_near(self):
        assert _score_beach(5) == pytest.approx(7.0)
        assert _score_beach(30) == pytest.approx(7.0)

    def test_beach_moderate(self):
        assert _score_beach(45) == pytest.approx(5.0)
        assert _score_beach(90) == pytest.approx(3.0)

    def test_natural_pools_near(self):
        assert _score_natural_pools(10) == pytest.approx(6.0)

    def test_natural_pools_none(self):
        assert _score_natural_pools(None) == pytest.approx(0.5)

    def test_supermarket_brackets(self):
        assert _score_supermarket(3) == pytest.approx(8.0)
        assert _score_supermarket(8) == pytest.approx(6.0)
        assert _score_supermarket(15) == pytest.approx(4.0)
        assert _score_supermarket(28) == pytest.approx(2.0)

    def test_health_center_brackets(self):
        assert _score_health_center(5) == pytest.approx(9.0)
        assert _score_health_center(15) == pytest.approx(7.0)
        assert _score_health_center(55) == pytest.approx(1.0)

    def test_hospital_brackets(self):
        assert _score_hospital(10) == pytest.approx(9.0)
        assert _score_hospital(45) == pytest.approx(5.0)
        assert _score_hospital(80) == pytest.approx(1.0)

    def test_price_cheapest(self):
        assert _score_price(100_000) == pytest.approx(8.0)

    def test_price_mid(self):
        assert _score_price(220_000) == pytest.approx(5.0)

    def test_price_near_limit(self):
        assert _score_price(300_000) == pytest.approx(2.0)

    def test_fire_risk_nulo(self):
        assert _score_fire_risk(FireRisk.NULO) == pytest.approx(9.0)

    def test_fire_risk_alto(self):
        assert _score_fire_risk(FireRisk.ALTO) == pytest.approx(1.0)

    def test_fire_risk_medio(self):
        assert _score_fire_risk(FireRisk.MEDIO) == pytest.approx(3.0)


class TestP11Preference:

    def test_preference_max(self, base_zone):
        base_zone = Zone(**{**base_zone.__dict__, "zone_preference": 9.0})
        from scorer import _score_preference
        assert _score_preference(9.0) == pytest.approx(9.0)

    def test_preference_min(self):
        from scorer import _score_preference
        assert _score_preference(0.0) == pytest.approx(0.0)

    def test_preference_clamped_above(self):
        from scorer import _score_preference
        assert _score_preference(15.0) == pytest.approx(9.0)

    def test_preference_cantabria(self):
        """Cantabria tiene la máxima preferencia (9) según especificación."""
        from zones import ZONES
        assert ZONES["cantabria_liebana"].zone_preference == pytest.approx(9.0)

    def test_preference_in_total(self, base_property, base_zone):
        """El total debe incluir P11."""
        score = calculate_score(base_property, base_zone)
        assert score.p11_preference == pytest.approx(5.0)  # zona de prueba con pref=5
        assert score.total == pytest.approx(
            score.p1_rooms + score.p2_piscina + score.p3_distance +
            score.p4_beach + score.p5_pools + score.p6_supermarket +
            score.p7_health + score.p8_hospital + score.p9_price +
            score.p10_fire + score.p11_preference
        )

    def test_max_score_updated(self):
        """La puntuación máxima debe ser 84 (75 + 9 de P11)."""
        from models import ScoreBreakdown
        assert ScoreBreakdown.MAX_SCORE == pytest.approx(84.0)

    def test_alert_threshold_updated(self):
        """El umbral de alerta debe ser 50 (sube 5 con P11)."""
        from scorer import ALERT_THRESHOLD
        assert ALERT_THRESHOLD == pytest.approx(50.0)


# ── Tests de calculate_score ──────────────────────────────────────────────────

class TestCalculateScore:

    def test_total_does_not_exceed_max(self, base_property, base_zone):
        base_property.piscina = Piscina.PROPIA
        base_property.rooms = 5
        base_property.price = 100_000
        score = calculate_score(base_property, base_zone)
        assert score.total <= 75.0

    def test_total_is_sum_of_parts(self, base_property, base_zone):
        score = calculate_score(base_property, base_zone)
        expected = (
            score.p1_rooms + score.p2_piscina + score.p3_distance +
            score.p4_beach + score.p5_pools + score.p6_supermarket +
            score.p7_health + score.p8_hospital + score.p9_price +
            score.p10_fire + score.p11_preference
        )
        assert score.total == pytest.approx(expected)

    def test_property_distance_overrides_zone(self, base_property, base_zone):
        """Si la propiedad tiene distancias específicas, se usan sobre las de la zona."""
        base_property.distance_supermarket_min = 3   # muy cerca → 8 pts
        base_zone_copy = Zone(
            id=base_zone.id, name=base_zone.name,
            distance_madrid_min=base_zone.distance_madrid_min,
            distance_beach_min=base_zone.distance_beach_min,
            distance_natural_pools_min=base_zone.distance_natural_pools_min,
            distance_supermarket_min=25,  # lejos → 2 pts si se usa el de zona
            distance_health_center_min=base_zone.distance_health_center_min,
            distance_hospital_min=base_zone.distance_hospital_min,
            fire_risk=base_zone.fire_risk,
            price_min=base_zone.price_min, price_max=base_zone.price_max,
        )
        score = calculate_score(base_property, base_zone_copy)
        assert score.p6_supermarket == pytest.approx(8.0)  # usa el de la propiedad


# ── Tests de evaluate ─────────────────────────────────────────────────────────

class TestEvaluate:

    def test_valid_property_returns_scored(self, base_property, base_zone):
        result = evaluate(base_property, base_zone)
        assert result is not None
        assert result.total_score > 0

    def test_invalid_property_returns_none(self, base_property, base_zone):
        base_property.has_garage = False
        result = evaluate(base_property, base_zone)
        assert result is None

    def test_alert_threshold_property(self, base_property, base_zone):
        """Una propiedad buena debe superar el umbral de 50 puntos (incluye P11)."""
        base_property.rooms = 5
        base_property.piscina = Piscina.PROPIA
        base_property.price = 150_000
        result = evaluate(base_property, base_zone)
        assert result is not None
        assert result.passes_alert_threshold is True
        assert result.total_score >= ALERT_THRESHOLD

    def test_mediocre_property_below_threshold(self, base_property, base_zone):
        """Propiedad con muchos puntos negativos no debe superar el umbral."""
        # Zona con hospital lejos, supermercado lejos
        far_zone = Zone(
            id="far", name="Far zone",
            distance_madrid_min=260,   # casi en el límite → baja puntuación P3
            distance_beach_min=None,
            distance_natural_pools_min=None,
            distance_supermarket_min=28,
            distance_health_center_min=55,
            distance_hospital_min=85,
            fire_risk=FireRisk.MEDIO_ALTO,
            price_min=0, price_max=999_999,
        )
        base_property.price = 310_000  # caro → baja puntuación P9
        base_property.rooms = 3
        base_property.piscina = Piscina.NINGUNA
        result = evaluate(base_property, far_zone)
        assert result is not None
        assert result.passes_alert_threshold is False

    def test_score_breakdown_as_dict(self, base_property, base_zone):
        result = evaluate(base_property, base_zone)
        assert result is not None
        d = result.score.as_dict()
        assert "TOTAL" in d
        assert "P11_preferencia_provincia" in d
        assert d["TOTAL"] == pytest.approx(result.total_score)


# ── Tests del modelo ──────────────────────────────────────────────────────────

class TestPropertyModel:

    def test_unique_id_format(self, base_property):
        assert base_property.unique_id == "pisos:12345"

    def test_unique_id_is_composite(self):
        prop = Property(
            portal=Portal.FOTOCASA, portal_id="abc",
            url="", zone_id="z", title="", price=100_000,
            size_m2=None, rooms=None, has_garage=True,
            has_garden_or_plot=True, piscina=Piscina.NINGUNA,
            has_internet_mention=True, habitable=True,
        )
        assert prop.unique_id == "fotocasa:abc"
