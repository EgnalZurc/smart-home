"""
Tests unitarios del motor de scoring (scorer.py).
Sistema R1-R18: puntuación máxima 180, umbral alerta 119 (66%).
"""

from __future__ import annotations

import sys
from pathlib import Path

# Añadir src al path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from datetime import datetime

import pytest
from models import (
    FireRisk,
    FloodRisk,
    GarageType,
    Habitability,
    Internet,
    Piscina,
    Portal,
    Property,
    Zone,
)
from scorer import ALERT_THRESHOLD, MAX_SCORE, evaluate


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def base_zone() -> Zone:
    """Zona que produce puntuación alta."""
    return Zone(
        id="test_zone",
        name="Zona de prueba",
        distance_madrid_min=150,
        distance_beach_min=30,
        distance_natural_pools_min=30,
        distance_supermarket_min=5,
        distance_health_center_min=10,
        distance_hospital_min=20,
        fire_risk=FireRisk.NULO,
        flood_risk=FloodRisk.NULO,
        has_coast=True,
        price_min=50_000,
        price_max=300_000,
    )


@pytest.fixture
def base_property(base_zone: Zone) -> Property:
    """Propiedad con buenas características."""
    return Property(
        portal=Portal.PISOS,
        portal_id="12345",
        url="https://www.pisos.com/venta/12345",
        zone_id=base_zone.id,
        title="Casa con jardín y garaje en zona test",
        price=200_000,
        size_m2=180.0,
        rooms=4,
        garage_type=GarageType.EDIFICIO,
        has_garden_or_plot=True,
        terrain_m2=500.0,
        piscina=Piscina.ESPACIO,
        internet=Internet.FIBRA,
        habitability=Habitability.BUENO,
        has_ac=True,
        description="Casa amplia con jardín y garaje. Parcela grande.",
        first_seen=datetime.now(),
        last_seen=datetime.now(),
    )


# ── Tests de evaluate ─────────────────────────────────────────────────────────


class TestEvaluate:
    def test_returns_scored_property(self, base_property, base_zone):
        """evaluate() debe devolver un ScoredProperty."""
        result = evaluate(base_property, base_zone)
        assert result is not None
        assert result.total_score > 0

    def test_total_does_not_exceed_max(self, base_property, base_zone):
        """La puntuación nunca debe superar MAX_SCORE."""
        result = evaluate(base_property, base_zone)
        assert result.total_score <= MAX_SCORE

    def test_good_property_passes_threshold(self, base_property, base_zone):
        """Una propiedad con buenas características debe superar el umbral."""
        base_property.rooms = 5
        base_property.piscina = Piscina.PROPIA
        base_property.price = 150_000
        result = evaluate(base_property, base_zone)
        assert result is not None
        assert result.passes_alert_threshold is True
        assert result.total_score >= ALERT_THRESHOLD

    def test_score_breakdown_exists(self, base_property, base_zone):
        """El resultado debe incluir desglose de puntuación."""
        result = evaluate(base_property, base_zone)
        assert result is not None
        assert result.score is not None
        # Verificar que tiene campos R1-R18
        assert hasattr(result.score, "r1_rooms")
        assert hasattr(result.score, "r7_price")


class TestConstants:
    def test_max_score_is_180(self):
        """La puntuación máxima debe ser 180."""
        assert MAX_SCORE == 180.0

    def test_alert_threshold_is_119(self):
        """El umbral de alerta debe ser 119 (66% de 180)."""
        assert ALERT_THRESHOLD == 119.0


# ── Tests del modelo Property ─────────────────────────────────────────────────


class TestPropertyModel:
    def test_unique_id_format(self, base_property):
        """unique_id debe ser portal:portal_id."""
        assert base_property.unique_id == "pisos:12345"

    def test_unique_id_is_composite(self):
        prop = Property(
            portal=Portal.FOTOCASA,
            portal_id="abc",
            url="",
            zone_id="z",
            title="",
            price=100_000,
            size_m2=None,
            rooms=None,
            garage_type=GarageType.NINGUNO,
            has_garden_or_plot=False,
            terrain_m2=None,
            piscina=Piscina.NINGUNA,
            internet=Internet.NINGUNO,
            habitability=Habitability.DESCONOCIDO,
        )
        assert prop.unique_id == "fotocasa:abc"



# ═══════════════════════════════════════════════════════════════════════════════
# Additional scorer tests for coverage
# ═══════════════════════════════════════════════════════════════════════════════


class TestR1Rooms:
    """Tests for R1 rooms scoring."""

    def test_rooms_none(self):
        from scorer import _r1_rooms
        assert _r1_rooms(None) == 0.0

    def test_rooms_2(self):
        from scorer import _r1_rooms
        assert _r1_rooms(2) == 0.0

    def test_rooms_3(self):
        from scorer import _r1_rooms
        assert _r1_rooms(3) == 5.0

    def test_rooms_4(self):
        from scorer import _r1_rooms
        assert _r1_rooms(4) == 8.0

    def test_rooms_5(self):
        from scorer import _r1_rooms
        assert _r1_rooms(5) == 9.0

    def test_rooms_8_max(self):
        from scorer import _r1_rooms
        assert _r1_rooms(8) == 10.0

    def test_rooms_10_capped(self):
        from scorer import _r1_rooms
        assert _r1_rooms(10) == 10.0


class TestR2Terrain:
    """Tests for R2 terrain scoring."""

    def test_no_garden(self):
        from scorer import _r2_terrain
        assert _r2_terrain(False, None) == -5.0

    def test_garden_no_size(self):
        from scorer import _r2_terrain
        assert _r2_terrain(True, None) == 5.0

    def test_garden_small(self):
        from scorer import _r2_terrain
        assert _r2_terrain(True, 50) == 5.0

    def test_garden_100m2(self):
        from scorer import _r2_terrain
        assert _r2_terrain(True, 100) == 5.0

    def test_garden_250m2(self):
        from scorer import _r2_terrain
        result = _r2_terrain(True, 250)
        assert 7.0 <= result <= 8.0  # linear between 5 and 10

    def test_garden_400m2(self):
        from scorer import _r2_terrain
        assert _r2_terrain(True, 400) == 10.0

    def test_garden_large(self):
        from scorer import _r2_terrain
        assert _r2_terrain(True, 1000) == 10.0


class TestR3Garage:
    """Tests for R3 garage scoring."""

    def test_garage_edificio(self):
        from scorer import _r3_garage
        from models import GarageType
        assert _r3_garage(GarageType.EDIFICIO, False) == 10.0

    def test_garage_exterior(self):
        from scorer import _r3_garage
        from models import GarageType
        assert _r3_garage(GarageType.EXTERIOR, False) == 5.0

    def test_no_garage_with_garden(self):
        from scorer import _r3_garage
        from models import GarageType
        assert _r3_garage(GarageType.NINGUNO, True) == 5.0

    def test_no_garage_no_garden(self):
        from scorer import _r3_garage
        from models import GarageType
        assert _r3_garage(GarageType.NINGUNO, False) == 0.0


class TestR4Habitability:
    """Tests for R4 habitability scoring."""

    def test_ruina(self):
        from scorer import _r4_habitability
        from models import Habitability
        assert _r4_habitability(Habitability.RUINA) == -10.0

    def test_reforma(self):
        from scorer import _r4_habitability
        from models import Habitability
        assert _r4_habitability(Habitability.REFORMA) == -10.0

    def test_desconocido(self):
        from scorer import _r4_habitability
        from models import Habitability
        assert _r4_habitability(Habitability.DESCONOCIDO) == 0.0

    def test_pendiente(self):
        from scorer import _r4_habitability
        from models import Habitability
        assert _r4_habitability(Habitability.PENDIENTE) == 4.0

    def test_bueno(self):
        from scorer import _r4_habitability
        from models import Habitability
        assert _r4_habitability(Habitability.BUENO) == 7.0

    def test_reformado(self):
        from scorer import _r4_habitability
        from models import Habitability
        assert _r4_habitability(Habitability.REFORMADO) == 10.0


class TestR5Piscina:
    """Tests for R5 piscina scoring."""

    def test_propia(self):
        from scorer import _r5_piscina
        from models import Piscina
        assert _r5_piscina(Piscina.PROPIA) == 10.0

    def test_comunitaria(self):
        from scorer import _r5_piscina
        from models import Piscina
        assert _r5_piscina(Piscina.COMUNITARIA) == 8.0

    def test_espacio(self):
        from scorer import _r5_piscina
        from models import Piscina
        assert _r5_piscina(Piscina.ESPACIO) == 6.0

    def test_ninguna(self):
        from scorer import _r5_piscina
        from models import Piscina
        assert _r5_piscina(Piscina.NINGUNA) == 0.0


class TestR6AC:
    """Tests for R6 AC scoring."""

    def test_ac_installed(self):
        from scorer import _r6_ac
        assert _r6_ac(True, False) == 10.0

    def test_ac_preinstalled(self):
        from scorer import _r6_ac
        assert _r6_ac(False, True) == 8.0

    def test_no_ac(self):
        from scorer import _r6_ac
        assert _r6_ac(False, False) == 5.0


class TestR7Price:
    """Tests for R7 price scoring."""

    def test_price_zero(self):
        from scorer import _r7_price
        assert _r7_price(0) == 0.0

    def test_price_25k(self):
        from scorer import _r7_price
        assert _r7_price(25000) == 1.5  # linear 0-3 for 0-50k

    def test_price_50k(self):
        from scorer import _r7_price
        assert _r7_price(50000) == 3.0

    def test_price_75k(self):
        from scorer import _r7_price
        result = _r7_price(75000)
        assert 6.0 <= result <= 7.0  # linear 3-10 for 50-100k

    def test_price_100k_peak(self):
        from scorer import _r7_price
        assert _r7_price(100000) == 10.0

    def test_price_200k(self):
        from scorer import _r7_price
        result = _r7_price(200000)
        assert 7.0 <= result <= 8.0  # linear 10-5 for 100-300k

    def test_price_300k(self):
        from scorer import _r7_price
        assert _r7_price(300000) == 5.0

    def test_price_325k(self):
        from scorer import _r7_price
        result = _r7_price(325000)
        assert 2.0 <= result <= 3.0  # linear 5-0 for 300-350k

    def test_price_350k(self):
        from scorer import _r7_price
        assert _r7_price(350000) == 0.0

    def test_price_500k(self):
        from scorer import _r7_price
        assert _r7_price(500000) == 0.0


class TestR8ToR14Services:
    """Tests for R8-R14 service distance scoring."""

    def test_r8_supermarket_close(self):
        from scorer import _r8_supermarket
        assert _r8_supermarket(3) == 10.0

    def test_r8_supermarket_medium(self):
        from scorer import _r8_supermarket
        result = _r8_supermarket(12)
        assert 5.0 < result < 10.0

    def test_r8_supermarket_far(self):
        from scorer import _r8_supermarket
        assert _r8_supermarket(25) == 0.0

    def test_r9_health_close(self):
        from scorer import _r9_health
        assert _r9_health(5) == 10.0

    def test_r9_health_far(self):
        from scorer import _r9_health
        assert _r9_health(60) == 0.0

    def test_r10_hospital_close(self):
        from scorer import _r10_hospital
        assert _r10_hospital(5) == 10.0

    def test_r10_hospital_far(self):
        from scorer import _r10_hospital
        assert _r10_hospital(90) == 0.0

    def test_r12_madrid_within(self):
        from scorer import _r12_madrid
        assert _r12_madrid(200) == 10.0

    def test_r12_madrid_limit(self):
        from scorer import _r12_madrid
        assert _r12_madrid(270) == 10.0

    def test_r12_madrid_beyond(self):
        from scorer import _r12_madrid
        assert _r12_madrid(300) == 0.0

    def test_r13_beach_none(self):
        from scorer import _r13_beach
        assert _r13_beach(None) == 0.0

    def test_r13_beach_close(self):
        from scorer import _r13_beach
        assert _r13_beach(5) == 10.0

    def test_r13_beach_far(self):
        from scorer import _r13_beach
        assert _r13_beach(30) == 0.0

    def test_r14_pools_none(self):
        from scorer import _r14_pools
        assert _r14_pools(None) == 0.0

    def test_r14_pools_close(self):
        from scorer import _r14_pools
        assert _r14_pools(5) == 10.0


class TestR15Fire:
    """Tests for R15 fire risk scoring."""

    def test_fire_muy_alto(self):
        from scorer import _r15_fire
        from models import FireRisk
        assert _r15_fire(FireRisk.MUY_ALTO) == -10.0

    def test_fire_alto(self):
        from scorer import _r15_fire
        from models import FireRisk
        assert _r15_fire(FireRisk.ALTO) == 0.0

    def test_fire_nulo(self):
        from scorer import _r15_fire
        from models import FireRisk
        assert _r15_fire(FireRisk.NULO) == 10.0


class TestR16Flood:
    """Tests for R16 flood risk scoring."""

    def test_flood_none(self):
        from scorer import _r16_flood
        assert _r16_flood(None) == 4.0

    def test_flood_alto(self):
        from scorer import _r16_flood
        from models import FloodRisk
        assert _r16_flood(FloodRisk.ALTO) == 0.0

    def test_flood_nulo(self):
        from scorer import _r16_flood
        from models import FloodRisk
        assert _r16_flood(FloodRisk.NULO) == 10.0


class TestR17Coast:
    """Tests for R17 coast scoring."""

    def test_has_coast(self):
        from scorer import _r17_coast
        assert _r17_coast(True) == 10.0

    def test_no_coast(self):
        from scorer import _r17_coast
        assert _r17_coast(False) == 0.0


class TestR18BeachPlot:
    """Tests for R18 beach+plot bonus."""

    def test_no_garden(self):
        from scorer import _r18_beach_plot
        assert _r18_beach_plot(False, 2) == 0.0

    def test_no_beach(self):
        from scorer import _r18_beach_plot
        assert _r18_beach_plot(True, None) == 0.0

    def test_beach_too_far(self):
        from scorer import _r18_beach_plot
        assert _r18_beach_plot(True, 10) == 0.0

    def test_beach_close_with_garden(self):
        from scorer import _r18_beach_plot
        assert _r18_beach_plot(True, 2) == 10.0


class TestEvaluateFromEmail:
    """Tests for evaluate_from_email function."""

    def test_email_bonus_applied(self):
        from scorer import evaluate_from_email, EMAIL_BONUS
        from models import Property, Portal, Piscina, GarageType, Habitability, Internet
        from zones import ZONES

        prop = Property(
            portal=Portal.IDEALISTA,
            portal_id="123",
            url="https://idealista.com/inmueble/123",
            zone_id="zamora_meseta",
            title="Casa test",
            price=100000,
            size_m2=120,
            rooms=4,
            has_garage=True,
            has_garden_or_plot=True,
            terrain_m2=200,
            garage_type=GarageType.EXTERIOR,
            habitability=Habitability.BUENO,
            internet=Internet.INSTALACION,
            piscina=Piscina.NINGUNA,
        )
        zone = ZONES["zamora_meseta"]
        scored = evaluate_from_email(prop, zone)

        # Should have email bonus added
        assert scored.total_score > 0
        assert scored.score.r18_beach_plot >= EMAIL_BONUS  # bonus absorbed here

    def test_defaults_applied_for_missing_data(self):
        from scorer import evaluate_from_email
        from models import Property, Portal, Piscina, GarageType, Habitability, Internet
        from zones import ZONES

        prop = Property(
            portal=Portal.IDEALISTA,
            portal_id="123",
            url="https://idealista.com/inmueble/123",
            zone_id="zamora_meseta",
            title="Casa test",
            price=100000,
            size_m2=None,
            rooms=None,  # Should default to 3
            has_garage=True,
            has_garden_or_plot=False,  # Should be set to True
            terrain_m2=None,
            garage_type=GarageType.NINGUNO,  # Should be set to EXTERIOR
            habitability=Habitability.DESCONOCIDO,  # Should be set to BUENO
            internet=Internet.NINGUNO,
            piscina=Piscina.NINGUNA,
        )
        zone = ZONES["zamora_meseta"]
        scored = evaluate_from_email(prop, zone)

        # Check that property was evaluated (not None)
        assert scored is not None
        assert scored.total_score > 0



# ── Consistencia modelo <-> scorer ──────────────────────────────────────────


class TestScorerConsistency:
    """Verifica que ScoreBreakdown y scorer.py no se desincronicen."""

    def test_max_score_is_classvar_not_field(self):
        """MAX_SCORE es un ClassVar, no un campo del dataclass.

        Si fuera un campo entraría en __init__/__eq__ y cada instancia llevaría
        su propio MAX_SCORE; debe ser una constante de clase compartida. Se
        comprueba contra dataclasses.fields() (los campos reales de init/eq);
        __dataclass_fields__ también lista los ClassVar como pseudo-campos.
        """
        import dataclasses

        from models import ScoreBreakdown

        field_names = {f.name for f in dataclasses.fields(ScoreBreakdown)}
        assert "MAX_SCORE" not in field_names
        assert ScoreBreakdown.MAX_SCORE == 180.0

    def test_model_max_score_matches_scorer(self):
        """ScoreBreakdown.MAX_SCORE y scorer.MAX_SCORE son la misma constante."""
        from models import ScoreBreakdown

        assert ScoreBreakdown.MAX_SCORE == MAX_SCORE == 180.0

    def test_alert_threshold_matches_passes_property(self):
        """passes_alert_threshold usa el mismo umbral que ALERT_THRESHOLD (119)."""
        from models import ScoreBreakdown, ScoredProperty

        assert ALERT_THRESHOLD == 119.0

        def _breakdown(total: float) -> ScoreBreakdown:
            fields = dict.fromkeys(
                (
                    "r1_rooms r2_terrain r3_garage r4_habitability r5_piscina "
                    "r6_ac r7_price r8_supermarket r9_health r10_hospital "
                    "r11_internet r12_madrid r13_beach r14_pools r15_fire "
                    "r16_flood r17_coast r18_beach_plot"
                ).split(),
                0.0,
            )
            fields["r12_madrid"] = total  # single field carries the whole total
            return ScoreBreakdown(**fields)

        # ScoredProperty only reads score.total, so prop/zone can be sentinels.
        at = ScoredProperty(prop=object(), zone=object(), score=_breakdown(ALERT_THRESHOLD))
        below = ScoredProperty(
            prop=object(), zone=object(), score=_breakdown(ALERT_THRESHOLD - 0.1)
        )

        assert at.total_score == ALERT_THRESHOLD
        assert at.passes_alert_threshold is True
        assert below.passes_alert_threshold is False
