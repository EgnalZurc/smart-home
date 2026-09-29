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
