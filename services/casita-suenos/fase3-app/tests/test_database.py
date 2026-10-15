"""
Tests unitarios de database.py.
Usa una DB temporal para no tocar el disco.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest
from database import Database
from models import (
    FireRisk,
    FloodRisk,
    GarageType,
    Habitability,
    Internet,
    Piscina,
    Portal,
    Property,
    ScoreBreakdown,
    ScoredProperty,
    Zone,
)


@pytest.fixture
def db(tmp_path) -> Database:
    return Database(str(tmp_path / "test_casita.db"))


def _make_property(
    portal_id: str = "test_001",
    price: int = 180_000,
    rooms: int = 4,
    **kwargs,
) -> Property:
    """Helper para crear Property con valores por defecto válidos."""
    defaults = {
        "portal": Portal.PISOS,
        "portal_id": portal_id,
        "url": f"https://pisos.com/{portal_id}",
        "zone_id": "zamora_meseta",
        "title": "Casa de prueba",
        "price": price,
        "size_m2": 200.0,
        "rooms": rooms,
        "has_garden_or_plot": True,
        "terrain_m2": 500.0,
        "garage_type": GarageType.EDIFICIO,
        "piscina": Piscina.ESPACIO,
        "habitability": Habitability.BUENO,
        "internet": Internet.FIBRA,
        "has_garage": True,
        "description": "Casa amplia con jardín",
        "first_seen": datetime.now(),
        "last_seen": datetime.now(),
        "source": "test",
    }
    defaults.update(kwargs)
    return Property(**defaults)


@pytest.fixture
def sample_property() -> Property:
    return _make_property()


@pytest.fixture
def sample_zone() -> Zone:
    return Zone(
        id="zamora_meseta",
        name="Zamora meseta",
        distance_madrid_min=150,
        distance_beach_min=None,
        distance_natural_pools_min=30,
        distance_supermarket_min=10,
        distance_health_center_min=10,
        distance_hospital_min=20,
        fire_risk=FireRisk.NULO,
        flood_risk=FloodRisk.NULO,
        price_min=50_000,
        price_max=260_000,
        has_coast=False,
    )


def _make_scored(prop: Property, zone: Zone, score: float = 120.0) -> ScoredProperty:
    """Helper: crea un ScoredProperty con puntuación fija para tests."""
    breakdown = ScoreBreakdown(
        r1_rooms=8.0,
        r2_terrain=8.0,
        r3_garage=10.0,
        r4_habitability=8.0,
        r5_piscina=5.0,
        r6_ac=5.0,
        r7_price=6.0,
        r8_supermarket=8.0,
        r9_health=8.0,
        r10_hospital=8.0,
        r11_internet=8.0,
        r12_madrid=10.0,
        r13_beach=5.0,
        r14_pools=5.0,
        r15_fire=8.0,
        r16_flood=4.0,
        r17_coast=0.0,
        r18_beach_plot=0.0,
    )
    return ScoredProperty(prop=prop, zone=zone, score=breakdown)


# ── Tests existentes (propiedades básicas) ────────────────────────────────────


class TestDatabase:
    def test_insert_new_property(self, db, sample_property):
        assert db.is_new(sample_property) is True
        db.upsert_property(sample_property)
        assert db.is_new(sample_property) is False

    def test_count_increases_after_insert(self, db, sample_property):
        assert db.count_properties() == 0
        db.upsert_property(sample_property)
        assert db.count_properties() == 1

    def test_upsert_same_price_no_price_event(self, db, sample_property):
        db.upsert_property(sample_property)
        event = db.upsert_property(sample_property)
        assert event is None

    def test_upsert_price_drop_creates_event(self, db, sample_property):
        db.upsert_property(sample_property)
        sample_property.price = 160_000
        event = db.upsert_property(sample_property)
        assert event is not None
        assert event.old_price == 180_000
        assert event.new_price == 160_000
        assert event.delta == -20_000
        assert event.delta_pct == pytest.approx(-11.11, rel=0.01)

    def test_upsert_price_rise_creates_event(self, db, sample_property):
        db.upsert_property(sample_property)
        sample_property.price = 200_000
        event = db.upsert_property(sample_property)
        assert event is not None
        assert event.delta > 0

    def test_mark_alerted_and_check(self, db, sample_property):
        db.upsert_property(sample_property)
        uid = sample_property.unique_id
        assert db.is_alerted(uid) is False
        db.mark_alerted(uid)
        assert db.is_alerted(uid) is True

    def test_count_by_zone(self, db, sample_property):
        db.upsert_property(sample_property)
        counts = db.count_by_zone()
        assert "zamora_meseta" in counts
        assert counts["zamora_meseta"] == 1

    def test_count_radar_empty_by_default(self, db):
        assert db.count_radar_properties(min_score=0.0) == 0

    def test_count_radar_only_counts_scored_above_threshold(self, db, sample_zone):
        """count_radar_properties cuenta solo las que pasan el threshold.

        Una propiedad sin score, o con score por debajo del umbral, no debe
        contarse aunque esté en la tabla de propiedades (que es lo que hace
        count_properties).
        """
        # Propiedad con score alto -> en radar
        prop_hi = _make_property(portal_id="hi", price=150_000)
        db.upsert_property(prop_hi)
        db.upsert_score(_make_scored(prop_hi, sample_zone))

        # Propiedad sin score -> monitorizada pero NO en radar
        prop_unscored = _make_property(portal_id="unscored", price=200_000)
        db.upsert_property(prop_unscored)

        # count_properties cuenta ambas, count_radar solo la del radar
        assert db.count_properties() == 2
        assert db.count_radar_properties(min_score=0.0) == 1

    def test_count_radar_respects_min_score(self, db, sample_property, sample_zone):
        db.upsert_property(sample_property)
        db.upsert_score(_make_scored(sample_property, sample_zone))

        # Con umbral mayor que el score no se cuenta
        assert db.count_radar_properties(min_score=1_000.0) == 0
        # Con umbral menor sí
        assert db.count_radar_properties(min_score=0.0) == 1

    def test_count_radar_excludes_dismissed(self, db, sample_property, sample_zone):
        db.upsert_property(sample_property)
        db.upsert_score(_make_scored(sample_property, sample_zone))
        assert db.count_radar_properties(min_score=0.0) == 1

        db.dismiss(sample_property.unique_id)
        assert db.count_radar_properties(min_score=0.0) == 0

    def test_is_on_radar_true_when_scored_and_not_dismissed(
        self, db, sample_property, sample_zone
    ):
        """is_on_radar returns True for scored property above threshold."""
        db.upsert_property(sample_property)
        db.upsert_score(_make_scored(sample_property, sample_zone))
        # Sample score is ~114, use min_score=100 to verify logic works
        assert db.is_on_radar(sample_property.unique_id, min_score=100.0) is True

    def test_is_on_radar_false_when_dismissed(self, db, sample_property, sample_zone):
        """is_on_radar returns False after dismissing."""
        db.upsert_property(sample_property)
        db.upsert_score(_make_scored(sample_property, sample_zone))
        db.dismiss(sample_property.unique_id)
        assert db.is_on_radar(sample_property.unique_id, min_score=100.0) is False

    def test_is_on_radar_false_when_below_threshold(
        self, db, sample_property, sample_zone
    ):
        """is_on_radar returns False when score is below threshold."""
        db.upsert_property(sample_property)
        db.upsert_score(_make_scored(sample_property, sample_zone))
        # Sample score is ~114, so min_score=200 should return False
        assert db.is_on_radar(sample_property.unique_id, min_score=200.0) is False

    def test_is_on_radar_false_when_not_scored(self, db, sample_property):
        """is_on_radar returns False for unscored property."""
        db.upsert_property(sample_property)
        assert db.is_on_radar(sample_property.unique_id, min_score=0.0) is False

    def test_count_by_zone_radar_groups_only_radar(self, db, sample_zone):
        """count_by_zone_radar agrupa solo propiedades en el radar."""
        # Dos propiedades en la misma zona, una descartada
        prop1 = _make_property(portal_id="z1", price=150_000)
        prop2 = _make_property(portal_id="z2", price=200_000)
        for p in (prop1, prop2):
            db.upsert_property(p)
            db.upsert_score(_make_scored(p, sample_zone))

        counts = db.count_by_zone_radar(min_score=0.0)
        assert counts == {"zamora_meseta": 2}

        db.dismiss(prop1.unique_id)
        counts = db.count_by_zone_radar(min_score=0.0)
        assert counts == {"zamora_meseta": 1}

    def test_count_by_zone_radar_ignores_unscored(self, db, sample_zone):
        """Una propiedad sin score no aparece en el conteo por zona del radar."""
        scored = _make_property(portal_id="scored", price=150_000)
        db.upsert_property(scored)
        db.upsert_score(_make_scored(scored, sample_zone))

        unscored = _make_property(portal_id="noscore", price=200_000)
        db.upsert_property(unscored)

        counts = db.count_by_zone_radar(min_score=0.0)
        assert counts == {"zamora_meseta": 1}

    def test_get_top_scored_empty(self, db):
        result = db.get_top_scored()
        assert result == []

    def test_get_recent_price_drops_empty(self, db):
        result = db.get_recent_price_drops()
        assert result == []

    def test_get_price_trend_no_history(self, db, sample_property):
        """Sin historial de precios, todos los campos son None."""
        db.upsert_property(sample_property)
        trend = db.get_price_trend(sample_property.unique_id)
        assert trend == {
            "previous_price": None,
            "price_change": None,
            "price_change_pct": None,
            "trend": None,
        }

    def test_get_price_trend_unknown_uid(self, db):
        """Un uid que no existe devuelve None en todos los campos."""
        trend = db.get_price_trend("portal:no_existe")
        assert trend["previous_price"] is None
        assert trend["trend"] is None

    def test_get_price_trend_down(self, db, sample_property):
        """Una bajada de precio produce trend='down' y price_change negativo."""
        db.upsert_property(sample_property)  # 180_000
        sample_property.price = 160_000
        db.upsert_property(sample_property)
        trend = db.get_price_trend(sample_property.unique_id)
        assert trend["previous_price"] == 180_000
        assert trend["price_change"] == -20_000
        assert trend["price_change_pct"] == pytest.approx(-11.11, rel=0.01)
        assert trend["trend"] == "down"

    def test_get_price_trend_up(self, db, sample_property):
        """Una subida de precio produce trend='up' y price_change positivo."""
        db.upsert_property(sample_property)  # 180_000
        sample_property.price = 200_000
        db.upsert_property(sample_property)
        trend = db.get_price_trend(sample_property.unique_id)
        assert trend["previous_price"] == 180_000
        assert trend["price_change"] == 20_000
        assert trend["price_change_pct"] > 0
        assert trend["trend"] == "up"

    def test_get_price_trend_uses_latest_change(self, db, sample_property):
        """Con varios cambios, se usa el más reciente."""
        db.upsert_property(sample_property)  # 180_000
        sample_property.price = 170_000
        db.upsert_property(sample_property)
        sample_property.price = 175_000
        db.upsert_property(sample_property)
        trend = db.get_price_trend(sample_property.unique_id)
        # Último cambio: 170_000 -> 175_000
        assert trend["previous_price"] == 170_000
        assert trend["price_change"] == 5_000
        assert trend["trend"] == "up"

    def test_close_does_not_raise(self, db):
        db.close()


# ── Tests de descarte ─────────────────────────────────────────────────────────


class TestDismiss:
    def _insert_scored(self, db, prop, zone):
        db.upsert_property(prop)
        scored = _make_scored(prop, zone)
        db.upsert_score(scored)

    def test_dismiss_nonexistent_returns_false(self, db):
        assert db.dismiss("portal:no_existe") is False

    def test_dismiss_existing_returns_true(self, db, sample_property, sample_zone):
        self._insert_scored(db, sample_property, sample_zone)
        uid = sample_property.unique_id
        assert db.dismiss(uid) is True

    def test_dismissed_property_not_in_radar(self, db, sample_property, sample_zone):
        self._insert_scored(db, sample_property, sample_zone)
        uid = sample_property.unique_id

        # Antes de descartar aparece en el radar
        radar = db.get_radar_properties(min_score=0.0)
        assert any(p["uid"] == uid for p in radar["items"])

        # Después de descartar no aparece
        db.dismiss(uid)
        radar = db.get_radar_properties(min_score=0.0)
        assert not any(p["uid"] == uid for p in radar["items"])

    def test_dismissed_property_in_get_dismissed(
        self, db, sample_property, sample_zone
    ):
        self._insert_scored(db, sample_property, sample_zone)
        uid = sample_property.unique_id
        db.dismiss(uid)

        dismissed = db.get_dismissed()
        assert len(dismissed) == 1
        assert dismissed[0]["uid"] == uid

    def test_undismiss_nonexistent_returns_false(self, db):
        assert db.undismiss("portal:no_existe") is False

    def test_undismiss_restores_to_radar(self, db, sample_property, sample_zone):
        self._insert_scored(db, sample_property, sample_zone)
        uid = sample_property.unique_id

        db.dismiss(uid)
        assert len(db.get_dismissed()) == 1
        assert len(db.get_radar_properties(min_score=0.0)["items"]) == 0

        db.undismiss(uid)
        assert len(db.get_dismissed()) == 0
        assert len(db.get_radar_properties(min_score=0.0)["items"]) == 1

    def test_dismissed_at_is_set_on_dismiss(self, db, sample_property, sample_zone):
        self._insert_scored(db, sample_property, sample_zone)
        db.dismiss(sample_property.unique_id)

        dismissed = db.get_dismissed()
        assert dismissed[0]["dismissed_at"] is not None

    def test_dismissed_at_cleared_on_undismiss(self, db, sample_property, sample_zone):
        self._insert_scored(db, sample_property, sample_zone)
        uid = sample_property.unique_id
        db.dismiss(uid)
        db.undismiss(uid)

        # Comprobamos directamente en la DB que dismissed_at se limpió
        row = db._conn.execute(
            "SELECT dismissed, dismissed_at FROM scored_properties WHERE property_uid=?",
            (uid,),
        ).fetchone()
        assert row["dismissed"] == 0
        assert row["dismissed_at"] is None

    def test_double_dismiss_is_idempotent(self, db, sample_property, sample_zone):
        self._insert_scored(db, sample_property, sample_zone)
        uid = sample_property.unique_id
        db.dismiss(uid)
        db.dismiss(uid)  # segunda vez no debe fallar
        assert len(db.get_dismissed()) == 1

    def test_dismiss_does_not_affect_other_properties(self, db, sample_zone):
        # Insertar dos propiedades
        prop1 = _make_property(portal_id="p1", price=150_000)
        prop2 = _make_property(portal_id="p2", price=200_000)
        for p in (prop1, prop2):
            db.upsert_property(p)
            db.upsert_score(_make_scored(p, sample_zone))

        db.dismiss(prop1.unique_id)

        radar = db.get_radar_properties(min_score=0.0)
        uids = [p["uid"] for p in radar["items"]]
        assert prop1.unique_id not in uids
        assert prop2.unique_id in uids


# ── Tests del radar ───────────────────────────────────────────────────────────


class TestRadar:
    def _insert(self, db, prop, zone, score_total=120.0):
        db.upsert_property(prop)
        db.upsert_score(_make_scored(prop, zone, score_total))

    def test_radar_empty_by_default(self, db):
        assert db.get_radar_properties()["items"] == []

    def test_radar_respects_min_score(self, db, sample_property, sample_zone):
        self._insert(db, sample_property, sample_zone, score_total=120.0)

        # Con umbral mayor no aparece
        assert db.get_radar_properties(min_score=150.0)["items"] == []

        # Con umbral menor aparece
        assert len(db.get_radar_properties(min_score=100.0)["items"]) == 1

    def test_radar_ordered_by_date_desc(self, db, sample_zone):
        """Con sort_by='date', la propiedad más reciente aparece primera."""
        older = _make_property(
            portal_id="old",
            first_seen=datetime.now() - timedelta(days=10),
        )
        newer = _make_property(
            portal_id="new",
            first_seen=datetime.now(),
        )
        for p in (older, newer):
            self._insert(db, p, sample_zone)

        radar = db.get_radar_properties(min_score=0.0, sort_by="date")["items"]
        assert radar[0]["uid"] == newer.unique_id
        assert radar[1]["uid"] == older.unique_id

    def test_radar_returns_expected_fields(self, db, sample_property, sample_zone):
        self._insert(db, sample_property, sample_zone)
        result = db.get_radar_properties(min_score=0.0)
        assert len(result["items"]) == 1
        p = result["items"][0]
        # Campos de propiedad
        for field in (
            "uid",
            "title",
            "price",
            "url",
            "zone_id",
            "rooms",
            "size_m2",
            "piscina",
            "first_seen",
            "last_seen",
        ):
            assert field in p, f"Campo '{field}' no encontrado"
        # Campos de scoring
        assert "score_total" in p

    def test_radar_excludes_dismissed(self, db, sample_property, sample_zone):
        self._insert(db, sample_property, sample_zone)
        db.dismiss(sample_property.unique_id)
        assert db.get_radar_properties(min_score=0.0)["items"] == []

    def test_radar_limit_is_respected(self, db, sample_zone):
        for i in range(5):
            p = _make_property(portal_id=str(i), price=150_000 + i * 1000)
            self._insert(db, p, sample_zone)

        assert len(db.get_radar_properties(min_score=0.0, limit=3)["items"]) == 3

    def test_radar_sort_params_are_injection_safe(
        self, db, sample_property, sample_zone
    ):
        """Malicious sort_by/sort_dir must not break out of the query.

        sort_by is whitelisted via _SORT_MAP (unknown -> score fallback) and
        sort_dir collapses to DESC/ASC, so injection payloads are inert: the
        call still returns the normal result set instead of erroring or
        dropping the table.
        """
        self._insert(db, sample_property, sample_zone, score_total=100.0)

        malicious = db.get_radar_properties(
            min_score=0.0,
            sort_by="s.score_total; DROP TABLE properties;--",
            sort_dir="DESC; DROP TABLE scored_properties;--",
        )
        assert len(malicious["items"]) == 1

        # Tables survived: a follow-up query still works.
        assert len(db.get_radar_properties(min_score=0.0)["items"]) == 1


# ── Tests del análisis precio/m² vs media de zona ─────────────────────────────


class TestPricePerM2Analysis:
    """Tests de get_zone_avg_price_per_m2, get_price_per_m2_analysis y del
    enriquecido del radar con los campos precio/m²."""

    def _insert(self, db, prop, zone, score_total=120.0):
        db.upsert_property(prop)
        db.upsert_score(_make_scored(prop, zone, score_total))

    # ── get_zone_avg_price_per_m2 ──────────────────────────────────────────

    def test_zone_avg_none_when_no_properties(self, db):
        assert db.get_zone_avg_price_per_m2("zamora_meseta") is None

    def test_zone_avg_single_property(self, db, sample_zone):
        # 200_000€ / 100 m² = 2000 €/m²
        p = _make_property(portal_id="a", price=200_000, size_m2=100.0)
        self._insert(db, p, sample_zone)
        assert db.get_zone_avg_price_per_m2(sample_zone.id) == 2000.0

    def test_zone_avg_averages_multiple_properties(self, db, sample_zone):
        # 2000 €/m² y 3000 €/m² -> media 2500 €/m²
        p1 = _make_property(portal_id="a", price=200_000, size_m2=100.0)
        p2 = _make_property(portal_id="b", price=300_000, size_m2=100.0)
        self._insert(db, p1, sample_zone)
        self._insert(db, p2, sample_zone)
        assert db.get_zone_avg_price_per_m2(sample_zone.id) == 2500.0

    def test_zone_avg_ignores_properties_without_m2(self, db, sample_zone):
        p1 = _make_property(portal_id="a", price=200_000, size_m2=100.0)
        p2 = _make_property(portal_id="b", price=300_000, size_m2=None)
        self._insert(db, p1, sample_zone)
        self._insert(db, p2, sample_zone)
        # Solo p1 cuenta -> 2000 €/m²
        assert db.get_zone_avg_price_per_m2(sample_zone.id) == 2000.0

    def test_zone_avg_excludes_dismissed(self, db, sample_zone):
        p1 = _make_property(portal_id="a", price=200_000, size_m2=100.0)
        p2 = _make_property(portal_id="b", price=400_000, size_m2=100.0)
        self._insert(db, p1, sample_zone)
        self._insert(db, p2, sample_zone)
        db.dismiss(p2.unique_id)
        # Solo p1 activa -> 2000 €/m² (p2 descartada no infla la media)
        assert db.get_zone_avg_price_per_m2(sample_zone.id) == 2000.0

    def test_zone_avg_scoped_by_zone(self, db, sample_zone):
        p1 = _make_property(portal_id="a", price=200_000, size_m2=100.0)
        p2 = _make_property(
            portal_id="b", price=500_000, size_m2=100.0, zone_id="otra_zona"
        )
        self._insert(db, p1, sample_zone)
        db.upsert_property(p2)  # p2 en otra zona
        assert db.get_zone_avg_price_per_m2(sample_zone.id) == 2000.0

    # ── get_price_per_m2_analysis ──────────────────────────────────────────

    def test_analysis_unknown_uid_all_none(self, db):
        # Use a valid format that doesn't exist in the DB
        result = db.get_price_per_m2_analysis("pisos:no_existe")
        assert result == {
            "price_per_m2": None,
            "zone_avg_price_per_m2": None,
            "below_zone_avg": None,
            "pct_vs_zone_avg": None,
        }

    def test_analysis_property_without_m2(self, db, sample_zone):
        p = _make_property(portal_id="a", price=200_000, size_m2=None)
        self._insert(db, p, sample_zone)
        result = db.get_price_per_m2_analysis(p.unique_id)
        assert result["price_per_m2"] is None
        assert result["below_zone_avg"] is None
        assert result["pct_vs_zone_avg"] is None

    def test_analysis_below_zone_average(self, db, sample_zone):
        # cheap: 1500 €/m², otras dos a 2000 y 2500 -> media 2000 €/m²
        cheap = _make_property(portal_id="cheap", price=150_000, size_m2=100.0)
        mid = _make_property(portal_id="mid", price=200_000, size_m2=100.0)
        exp = _make_property(portal_id="exp", price=250_000, size_m2=100.0)
        for p in (cheap, mid, exp):
            self._insert(db, p, sample_zone)
        result = db.get_price_per_m2_analysis(cheap.unique_id)
        assert result["price_per_m2"] == 1500.0
        assert result["zone_avg_price_per_m2"] == 2000.0
        assert result["below_zone_avg"] is True
        # (1500 - 2000) / 2000 * 100 = -25.0 -> 25% más barato
        assert result["pct_vs_zone_avg"] == -25.0

    def test_analysis_above_zone_average(self, db, sample_zone):
        cheap = _make_property(portal_id="cheap", price=150_000, size_m2=100.0)
        mid = _make_property(portal_id="mid", price=200_000, size_m2=100.0)
        exp = _make_property(portal_id="exp", price=250_000, size_m2=100.0)
        for p in (cheap, mid, exp):
            self._insert(db, p, sample_zone)
        result = db.get_price_per_m2_analysis(exp.unique_id)
        assert result["price_per_m2"] == 2500.0
        assert result["zone_avg_price_per_m2"] == 2000.0
        assert result["below_zone_avg"] is False
        # (2500 - 2000) / 2000 * 100 = 25.0 -> 25% más caro
        assert result["pct_vs_zone_avg"] == 25.0

    # ── Enriquecido del radar ──────────────────────────────────────────────

    def test_radar_includes_price_per_m2_fields(self, db, sample_zone):
        cheap = _make_property(portal_id="cheap", price=150_000, size_m2=100.0)
        exp = _make_property(portal_id="exp", price=250_000, size_m2=100.0)
        for p in (cheap, exp):
            self._insert(db, p, sample_zone)
        items = db.get_radar_properties(min_score=0.0)["items"]
        assert len(items) == 2
        for item in items:
            for field in (
                "price_per_m2",
                "zone_avg_price_per_m2",
                "below_zone_avg",
                "pct_vs_zone_avg",
            ):
                assert field in item, f"Campo '{field}' no encontrado en el radar"

    def test_radar_price_per_m2_values_match_analysis(self, db, sample_zone):
        cheap = _make_property(portal_id="cheap", price=150_000, size_m2=100.0)
        exp = _make_property(portal_id="exp", price=250_000, size_m2=100.0)
        for p in (cheap, exp):
            self._insert(db, p, sample_zone)
        items = {i["uid"]: i for i in db.get_radar_properties(min_score=0.0)["items"]}
        cheap_item = items[cheap.unique_id]
        # media (1500 + 2500) / 2 = 2000 €/m²
        assert cheap_item["price_per_m2"] == 1500.0
        assert cheap_item["zone_avg_price_per_m2"] == 2000.0
        assert cheap_item["below_zone_avg"] is True
        assert cheap_item["pct_vs_zone_avg"] == -25.0


# ── Tests del resumen semanal ─────────────────────────────────────────────────


class TestWeeklySummary:
    def test_no_summary_returns_none(self, db):
        assert db.get_last_weekly_summary() is None

    def test_save_and_retrieve_summary(self, db):
        db.save_weekly_summary("Resumen de prueba con 3 casas")
        result = db.get_last_weekly_summary()
        assert result is not None
        assert result["content"] == "Resumen de prueba con 3 casas"
        assert "sent_at" in result
        assert result["sent_at"] is not None

    def test_multiple_summaries_returns_last(self, db):
        db.save_weekly_summary("Primer resumen")
        db.save_weekly_summary("Segundo resumen")
        db.save_weekly_summary("Tercer resumen")
        result = db.get_last_weekly_summary()
        assert result["content"] == "Tercer resumen"

    def test_summary_content_preserved_exactly(self, db):
        content = (
            "🏠 Casa 1\n  La Rioja — 250.000€ — 62.5 pts\n  https://idealista.com/123"
        )
        db.save_weekly_summary(content)
        assert db.get_last_weekly_summary()["content"] == content


# ── Tests de configuración de schedule ───────────────────────────────────────


class TestScheduleConfig:
    def test_defaults_returned_if_empty(self, db):
        config = db.get_schedule_config()
        assert config["scraping_enabled"] is True
        assert config["scraping_days"] == [0, 3]
        assert config["scraping_hour"] == 7
        assert config["gmail_check_enabled"] is True
        assert config["gmail_interval_min"] == 30
        assert config["summary_enabled"] is True
        assert config["summary_day"] == 6
        assert config["summary_hour"] == 9

    def test_save_and_retrieve_config(self, db):
        db.save_schedule_config({"scraping_enabled": False})
        config = db.get_schedule_config()
        assert config["scraping_enabled"] is False

    def test_save_preserves_unmodified_defaults(self, db):
        """Guardar solo un campo no debe borrar los demás defaults."""
        db.save_schedule_config({"summary_hour": 10})
        config = db.get_schedule_config()
        assert config["summary_hour"] == 10
        # Los demás siguen siendo defaults
        assert config["scraping_enabled"] is True
        assert config["scraping_days"] == [0, 3]

    def test_save_complex_value(self, db):
        """Listas y enteros se persisten y recuperan correctamente."""
        db.save_schedule_config({"scraping_days": [1, 4]})
        config = db.get_schedule_config()
        assert config["scraping_days"] == [1, 4]

    def test_overwrite_config(self, db):
        db.save_schedule_config({"gmail_interval_min": 60})
        db.save_schedule_config({"gmail_interval_min": 15})
        config = db.get_schedule_config()
        assert config["gmail_interval_min"] == 15

    def test_full_config_roundtrip(self, db):
        new_config = {
            "scraping_enabled": False,
            "scraping_days": [2, 5],
            "scraping_hour": 8,
            "gmail_check_enabled": False,
            "gmail_interval_min": 45,
            "summary_enabled": False,
            "summary_day": 0,
            "summary_hour": 7,
        }
        db.save_schedule_config(new_config)
        config = db.get_schedule_config()
        for key, value in new_config.items():
            assert config[key] == value, f"Fallo en clave '{key}'"


# ── Tests de upsert_score ─────────────────────────────────────────────────────


class TestUpsertScore:
    def test_score_persisted_in_scored_properties(
        self, db, sample_property, sample_zone
    ):
        """El score debe guardarse en la tabla scored_properties."""
        db.upsert_property(sample_property)
        scored = _make_scored(sample_property, sample_zone)
        db.upsert_score(scored)

        row = db._conn.execute(
            "SELECT score_total FROM scored_properties WHERE property_uid=?",
            (sample_property.unique_id,),
        ).fetchone()
        assert row is not None
        assert row["score_total"] > 0

    def test_dismiss_preserved_after_upsert_score(
        self, db, sample_property, sample_zone
    ):
        """Actualizar el score de una propiedad descartada no debe restaurarla."""
        db.upsert_property(sample_property)
        scored = _make_scored(sample_property, sample_zone)
        db.upsert_score(scored)
        db.dismiss(sample_property.unique_id)

        # Volvemos a hacer upsert_score (simula nuevo scraping)
        db.upsert_score(scored)

        # Debe seguir descartada
        row = db._conn.execute(
            "SELECT dismissed FROM scored_properties WHERE property_uid=?",
            (sample_property.unique_id,),
        ).fetchone()
        assert row["dismissed"] == 1

    def test_alerted_preserved_after_upsert_score(
        self, db, sample_property, sample_zone
    ):
        """Actualizar el score de una propiedad alertada no debe perder el flag alerted."""
        db.upsert_property(sample_property)
        scored = _make_scored(sample_property, sample_zone)
        db.upsert_score(scored)
        db.mark_alerted(sample_property.unique_id)

        # Segundo upsert_score
        db.upsert_score(scored)

        assert db.is_alerted(sample_property.unique_id) is True


# ── Tests de get_recent_high_scorers ──────────────────────────────────────────


class TestGetRecentHighScorers:
    def _insert_scored(self, db, prop, zone, scored_at, total=130.0):
        """Inserta una propiedad con un score concreto y un scored_at dado.

        Construye un ScoreBreakdown cuya suma sea ``total`` para controlar si
        la propiedad supera o no el umbral de alerta.
        """
        db.upsert_property(prop)
        breakdown = ScoreBreakdown(
            r1_rooms=total,
            r2_terrain=0.0,
            r3_garage=0.0,
            r4_habitability=0.0,
            r5_piscina=0.0,
            r6_ac=0.0,
            r7_price=0.0,
            r8_supermarket=0.0,
            r9_health=0.0,
            r10_hospital=0.0,
            r11_internet=0.0,
            r12_madrid=0.0,
            r13_beach=0.0,
            r14_pools=0.0,
            r15_fire=0.0,
            r16_flood=0.0,
            r17_coast=0.0,
            r18_beach_plot=0.0,
        )
        db.upsert_score(
            ScoredProperty(prop=prop, zone=zone, score=breakdown, scored_at=scored_at)
        )

    def test_returns_recent_high_scorer(self, db, sample_zone):
        prop = _make_property(portal_id="recent_001")
        now = datetime.now()
        self._insert_scored(db, prop, sample_zone, now)

        cutoff = (now - timedelta(hours=24)).isoformat()
        results = db.get_recent_high_scorers(cutoff, 119.0)

        assert len(results) == 1
        assert results[0]["uid"] == prop.unique_id
        assert results[0]["title"] == prop.title
        assert results[0]["score_total"] >= 119.0
        assert results[0]["url"] == prop.url
        assert "scored_at" in results[0]

    def test_excludes_old_scorer(self, db, sample_zone):
        """Una propiedad puntuada hace más de 24h no debe aparecer."""
        prop = _make_property(portal_id="old_001")
        old_time = datetime.now() - timedelta(hours=48)
        self._insert_scored(db, prop, sample_zone, old_time)

        cutoff = (datetime.now() - timedelta(hours=24)).isoformat()
        results = db.get_recent_high_scorers(cutoff, 119.0)

        assert results == []

    def test_excludes_below_threshold(self, db, sample_zone):
        """Una propiedad con score por debajo del umbral no debe aparecer."""
        prop = _make_property(portal_id="low_001")
        now = datetime.now()
        self._insert_scored(db, prop, sample_zone, now, total=100.0)

        cutoff = (now - timedelta(hours=24)).isoformat()
        results = db.get_recent_high_scorers(cutoff, 119.0)

        assert results == []

    def test_excludes_dismissed(self, db, sample_zone):
        """Las propiedades descartadas no deben aparecer en las alertas."""
        prop = _make_property(portal_id="dismissed_001")
        now = datetime.now()
        self._insert_scored(db, prop, sample_zone, now)
        db.dismiss(prop.unique_id)

        cutoff = (now - timedelta(hours=24)).isoformat()
        results = db.get_recent_high_scorers(cutoff, 119.0)

        assert results == []

    def test_ordered_by_scored_at_desc(self, db, sample_zone):
        """Los resultados deben ordenarse por scored_at descendente."""
        now = datetime.now()
        older = _make_property(portal_id="order_old")
        newer = _make_property(portal_id="order_new")
        self._insert_scored(db, older, sample_zone, now - timedelta(hours=5))
        self._insert_scored(db, newer, sample_zone, now - timedelta(hours=1))

        cutoff = (now - timedelta(hours=24)).isoformat()
        results = db.get_recent_high_scorers(cutoff, 119.0)

        assert [r["uid"] for r in results] == [
            newer.unique_id,
            older.unique_id,
        ]

    def test_respects_limit(self, db, sample_zone):
        now = datetime.now()
        for i in range(5):
            prop = _make_property(portal_id=f"limit_{i}")
            self._insert_scored(db, prop, sample_zone, now - timedelta(minutes=i))

        cutoff = (now - timedelta(hours=24)).isoformat()
        results = db.get_recent_high_scorers(cutoff, 119.0, limit=3)

        assert len(results) == 3

    def test_empty_when_no_scores(self, db):
        cutoff = (datetime.now() - timedelta(hours=24)).isoformat()
        assert db.get_recent_high_scorers(cutoff, 119.0) == []


# ── Tests de get_zone_trends ──────────────────────────────────────────────────


class TestGetZoneTrends:
    def _insert(self, db, prop, zone, total=130.0):
        """Inserta una propiedad y su score (suma = ``total``)."""
        db.upsert_property(prop)
        breakdown = ScoreBreakdown(
            r1_rooms=total,
            r2_terrain=0.0,
            r3_garage=0.0,
            r4_habitability=0.0,
            r5_piscina=0.0,
            r6_ac=0.0,
            r7_price=0.0,
            r8_supermarket=0.0,
            r9_health=0.0,
            r10_hospital=0.0,
            r11_internet=0.0,
            r12_madrid=0.0,
            r13_beach=0.0,
            r14_pools=0.0,
            r15_fire=0.0,
            r16_flood=0.0,
            r17_coast=0.0,
            r18_beach_plot=0.0,
        )
        db.upsert_score(ScoredProperty(prop=prop, zone=zone, score=breakdown))

    def test_empty_when_no_properties(self, db):
        assert db.get_zone_trends() == []

    def test_single_zone_single_day(self, db, sample_zone):
        now = datetime.now()
        prop = _make_property(portal_id="zt_001", price=100_000, first_seen=now)
        self._insert(db, prop, sample_zone)

        trends = db.get_zone_trends(days=30)
        assert len(trends) == 1
        zone = trends[0]
        assert zone["zone_id"] == "zamora_meseta"
        # zone_name se resuelve desde el catálogo zones.ZONES
        assert zone["zone_name"].startswith("Zamora")
        assert zone["total_properties"] == 1
        assert len(zone["data_points"]) == 1

        dp = zone["data_points"][0]
        assert dp["date"] == now.isoformat()[:10]
        assert dp["count"] == 1
        assert dp["avg_price"] == 100_000
        assert dp["avg_score"] == pytest.approx(130.0)

    def test_zone_name_fallback_to_id(self, db, sample_zone):
        """Si la zona no está en el catálogo, zone_name cae al zone_id."""
        now = datetime.now()
        prop = _make_property(portal_id="zt_unknown", zone_id="zona_inexistente_xyz")
        self._insert(db, prop, sample_zone)

        trends = db.get_zone_trends(days=30)
        zone = next(z for z in trends if z["zone_id"] == "zona_inexistente_xyz")
        assert zone["zone_name"] == "zona_inexistente_xyz"

    def test_avg_price_and_score_aggregated_per_day(self, db, sample_zone):
        now = datetime.now()
        p1 = _make_property(portal_id="zt_a", price=100_000, first_seen=now)
        p2 = _make_property(portal_id="zt_b", price=200_000, first_seen=now)
        self._insert(db, p1, sample_zone, total=100.0)
        self._insert(db, p2, sample_zone, total=140.0)

        trends = db.get_zone_trends(days=30)
        assert len(trends) == 1
        dps = trends[0]["data_points"]
        assert len(dps) == 1
        assert dps[0]["count"] == 2
        assert dps[0]["avg_price"] == pytest.approx(150_000)
        assert dps[0]["avg_score"] == pytest.approx(120.0)

    def test_data_points_split_across_days(self, db, sample_zone):
        now = datetime.now()
        old = _make_property(portal_id="zt_old", first_seen=now - timedelta(days=5))
        new = _make_property(portal_id="zt_new", first_seen=now)
        self._insert(db, old, sample_zone)
        self._insert(db, new, sample_zone)

        trends = db.get_zone_trends(days=30)
        dps = trends[0]["data_points"]
        assert len(dps) == 2
        # Ordenados cronológicamente ascendente
        assert dps[0]["date"] < dps[1]["date"]

    def test_window_excludes_old_properties(self, db, sample_zone):
        now = datetime.now()
        inside = _make_property(portal_id="zt_in", first_seen=now - timedelta(days=3))
        outside = _make_property(
            portal_id="zt_out", first_seen=now - timedelta(days=40)
        )
        self._insert(db, inside, sample_zone)
        self._insert(db, outside, sample_zone)

        trends = db.get_zone_trends(days=7)
        assert len(trends) == 1
        # Solo la propiedad dentro de la ventana aparece en los puntos diarios
        total_count = sum(dp["count"] for dp in trends[0]["data_points"])
        assert total_count == 1
        # total_properties cuenta todas las puntuadas no descartadas de la zona
        assert trends[0]["total_properties"] == 2

    def test_trend_growing(self, db, sample_zone):
        now = datetime.now()
        # Ventana de 30 días → midpoint ~día -15.
        # 1 propiedad en la primera mitad (día -20), 2 en la segunda (días -5, 0)
        # → growing.
        self._insert(
            db,
            _make_property(portal_id="g0", first_seen=now - timedelta(days=20)),
            sample_zone,
        )
        self._insert(
            db,
            _make_property(portal_id="g1", first_seen=now - timedelta(days=5)),
            sample_zone,
        )
        self._insert(
            db,
            _make_property(portal_id="g2", first_seen=now),
            sample_zone,
        )
        trends = db.get_zone_trends(days=30)
        assert trends[0]["trend"] == "growing"

    def test_trend_declining(self, db, sample_zone):
        now = datetime.now()
        # Ventana de 30 días → midpoint ~día -15.
        # 2 propiedades en la primera mitad (días -25, -20), 1 en la segunda
        # (día 0) → declining.
        self._insert(
            db,
            _make_property(portal_id="d0", first_seen=now - timedelta(days=25)),
            sample_zone,
        )
        self._insert(
            db,
            _make_property(portal_id="d1", first_seen=now - timedelta(days=20)),
            sample_zone,
        )
        self._insert(
            db,
            _make_property(portal_id="d2", first_seen=now),
            sample_zone,
        )
        trends = db.get_zone_trends(days=30)
        assert trends[0]["trend"] == "declining"

    def test_trend_stable_single_point(self, db, sample_zone):
        now = datetime.now()
        self._insert(db, _make_property(portal_id="s0", first_seen=now), sample_zone)
        trends = db.get_zone_trends(days=30)
        assert trends[0]["trend"] == "stable"

    def test_dismissed_excluded_from_total_properties(self, db, sample_zone):
        now = datetime.now()
        keep = _make_property(portal_id="zt_keep", first_seen=now)
        drop = _make_property(portal_id="zt_drop", first_seen=now)
        self._insert(db, keep, sample_zone)
        self._insert(db, drop, sample_zone)
        db.dismiss(drop.unique_id)

        trends = db.get_zone_trends(days=30)
        assert trends[0]["total_properties"] == 1

    def test_multiple_zones_sorted_by_id(self, db, sample_zone):
        now = datetime.now()
        pa = _make_property(portal_id="mz_a", zone_id="aaa_zone", first_seen=now)
        pb = _make_property(portal_id="mz_b", zone_id="bbb_zone", first_seen=now)
        self._insert(db, pa, sample_zone)
        self._insert(db, pb, sample_zone)

        trends = db.get_zone_trends(days=30)
        zone_ids = [z["zone_id"] for z in trends]
        assert zone_ids == sorted(zone_ids)

    def test_days_clamped_to_minimum(self, db, sample_zone):
        """days <= 0 se trata como 1 (no explota)."""
        now = datetime.now()
        self._insert(
            db, _make_property(portal_id="zt_clamp", first_seen=now), sample_zone
        )
        # No debe lanzar excepción y devuelve la zona del día de hoy
        trends = db.get_zone_trends(days=0)
        assert len(trends) == 1


# ── Tests de validación de property_uid (SQL injection prevention) ────────────


class TestPropertyUidValidation:
    """Tests for _validate_property_uid() SQL injection prevention.

    property_uid values should match the pattern 'portal:id' where both parts
    contain only alphanumeric characters, underscores, and hyphens.
    """

    def test_valid_uid_passes(self, db, sample_property, sample_zone):
        """Standard portal:id format should work."""
        db.upsert_property(sample_property)
        scored = _make_scored(sample_property, sample_zone)
        db.upsert_score(scored)
        # These should not raise
        uid = sample_property.unique_id
        assert db.is_alerted(uid) is False
        db.mark_alerted(uid)
        assert db.is_alerted(uid) is True

    def test_valid_uid_with_underscores(self, db, sample_zone):
        """UIDs with underscores should pass validation."""
        prop = _make_property(portal_id="prop_123_abc")
        db.upsert_property(prop)
        db.upsert_score(_make_scored(prop, sample_zone))
        # Should not raise
        assert db.dismiss(prop.unique_id) is True

    def test_valid_uid_with_hyphens(self, db, sample_zone):
        """UIDs with hyphens should pass validation."""
        prop = _make_property(portal_id="prop-123-abc")
        db.upsert_property(prop)
        db.upsert_score(_make_scored(prop, sample_zone))
        # Should not raise
        assert db.mark_viewed(prop.unique_id) is True

    def test_sql_injection_in_dismiss_rejected(self, db):
        """SQL injection attempt via dismiss() should raise ValueError."""
        malicious_uid = "pisos:123'; DROP TABLE properties;--"
        with pytest.raises(ValueError, match="Invalid property_uid format"):
            db.dismiss(malicious_uid)

    def test_sql_injection_in_undismiss_rejected(self, db):
        """SQL injection attempt via undismiss() should raise ValueError."""
        malicious_uid = "pisos:123 OR 1=1"
        with pytest.raises(ValueError, match="Invalid property_uid format"):
            db.undismiss(malicious_uid)

    def test_sql_injection_in_mark_alerted_rejected(self, db):
        """SQL injection attempt via mark_alerted() should raise ValueError."""
        malicious_uid = "pisos:'; DELETE FROM scored_properties;--"
        with pytest.raises(ValueError, match="Invalid property_uid format"):
            db.mark_alerted(malicious_uid)

    def test_sql_injection_in_is_alerted_rejected(self, db):
        """SQL injection attempt via is_alerted() should raise ValueError."""
        malicious_uid = "pisos:1 UNION SELECT * FROM properties"
        with pytest.raises(ValueError, match="Invalid property_uid format"):
            db.is_alerted(malicious_uid)

    def test_sql_injection_in_mark_viewed_rejected(self, db):
        """SQL injection attempt via mark_viewed() should raise ValueError."""
        malicious_uid = "pisos:x'; UPDATE properties SET price=0;--"
        with pytest.raises(ValueError, match="Invalid property_uid format"):
            db.mark_viewed(malicious_uid)

    def test_sql_injection_in_save_comment_rejected(self, db):
        """SQL injection attempt via save_comment() should raise ValueError."""
        malicious_uid = "pisos:1; INSERT INTO telegram_chats VALUES('hacker','','')"
        with pytest.raises(ValueError, match="Invalid property_uid format"):
            db.save_comment(malicious_uid, "test comment")

    def test_sql_injection_in_get_price_trend_rejected(self, db):
        """SQL injection attempt via get_price_trend() should raise ValueError."""
        malicious_uid = "pisos:123'; DROP TABLE--"
        with pytest.raises(ValueError, match="Invalid property_uid format"):
            db.get_price_trend(malicious_uid)

    def test_sql_injection_in_get_price_per_m2_analysis_rejected(self, db):
        """SQL injection attempt via get_price_per_m2_analysis() should raise ValueError."""
        malicious_uid = "pisos:1' OR '1'='1"
        with pytest.raises(ValueError, match="Invalid property_uid format"):
            db.get_price_per_m2_analysis(malicious_uid)

    def test_empty_uid_rejected(self, db):
        """Empty UID should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid property_uid format"):
            db.dismiss("")

    def test_uid_without_colon_rejected(self, db):
        """UID without colon separator should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid property_uid format"):
            db.dismiss("pisos12345")

    def test_uid_with_spaces_rejected(self, db):
        """UID with spaces should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid property_uid format"):
            db.dismiss("pisos:123 456")

    def test_uid_with_quotes_rejected(self, db):
        """UID with quotes should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid property_uid format"):
            db.dismiss("pisos:'test'")

    def test_uid_with_semicolon_rejected(self, db):
        """UID with semicolon should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid property_uid format"):
            db.dismiss("pisos:test;drop")


# ── Tests de thread-safety (concurrent writes) ────────────────────────────────


class TestConcurrentWrites:
    """Tests for thread-safe database writes using threading.Lock."""

    def test_concurrent_upsert_property_no_race(self, db, sample_zone):
        """Multiple threads upserting properties should not corrupt data."""
        import threading

        errors: list[Exception] = []
        num_threads = 10
        props_per_thread = 20

        def worker(thread_id: int) -> None:
            try:
                for i in range(props_per_thread):
                    prop = _make_property(
                        portal_id=f"thread{thread_id}_prop{i}",
                        price=100_000 + thread_id * 1000 + i,
                    )
                    db.upsert_property(prop)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=worker, args=(t,)) for t in range(num_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Errors during concurrent writes: {errors}"
        assert db.count_properties() == num_threads * props_per_thread

    def test_concurrent_dismiss_undismiss_no_race(self, db, sample_zone):
        """Concurrent dismiss/undismiss should not corrupt dismissed state."""
        import threading

        # Setup: create properties with scores
        props = [_make_property(portal_id=f"dismiss_test_{i}") for i in range(20)]
        for prop in props:
            db.upsert_property(prop)
            db.upsert_score(_make_scored(prop, sample_zone))

        errors: list[Exception] = []

        def dismiss_worker() -> None:
            try:
                for prop in props:
                    db.dismiss(prop.unique_id)
            except Exception as e:
                errors.append(e)

        def undismiss_worker() -> None:
            try:
                for prop in props:
                    db.undismiss(prop.unique_id)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=dismiss_worker),
            threading.Thread(target=undismiss_worker),
            threading.Thread(target=dismiss_worker),
            threading.Thread(target=undismiss_worker),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Errors during concurrent dismiss/undismiss: {errors}"

    def test_concurrent_mark_viewed_save_comment_no_race(self, db, sample_zone):
        """Concurrent mark_viewed and save_comment should not corrupt data."""
        import threading

        # Setup: create property with score
        prop = _make_property(portal_id="view_comment_test")
        db.upsert_property(prop)
        db.upsert_score(_make_scored(prop, sample_zone))

        errors: list[Exception] = []
        uid = prop.unique_id

        def view_worker() -> None:
            try:
                for _ in range(50):
                    db.mark_viewed(uid)
            except Exception as e:
                errors.append(e)

        def comment_worker(comment_id: int) -> None:
            try:
                for i in range(50):
                    db.save_comment(uid, f"Comment {comment_id}-{i}")
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=view_worker),
            threading.Thread(target=comment_worker, args=(1,)),
            threading.Thread(target=comment_worker, args=(2,)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Errors during concurrent view/comment: {errors}"
