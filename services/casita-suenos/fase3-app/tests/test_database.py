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

    def test_get_top_scored_empty(self, db):
        result = db.get_top_scored()
        assert result == []

    def test_get_recent_price_drops_empty(self, db):
        result = db.get_recent_price_drops()
        assert result == []

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
