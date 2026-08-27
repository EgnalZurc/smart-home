"""
Tests unitarios de database.py.
Usa una DB en memoria (:memory:) para no tocar el disco.
"""

from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest
from models import FireRisk, Piscina, Portal, Property, Zone, ScoreBreakdown, ScoredProperty
from database import Database, _DEFAULT_SCHEDULE


@pytest.fixture
def db(tmp_path) -> Database:
    return Database(str(tmp_path / "test_casita.db"))


@pytest.fixture
def sample_property() -> Property:
    return Property(
        portal=Portal.PISOS,
        portal_id="test_001",
        url="https://pisos.com/test",
        zone_id="zamora_meseta",
        title="Casa de prueba",
        price=180_000,
        size_m2=200.0,
        rooms=4,
        has_garage=True,
        has_garden_or_plot=True,
        piscina=Piscina.ESPACIO,
        has_internet_mention=True,
        habitable=True,
        description="Casa amplia con jardín",
        first_seen=datetime.now(),
        last_seen=datetime.now(),
        source="test",
    )


@pytest.fixture
def sample_zone() -> Zone:
    return Zone(
        id="zamora_meseta", name="Zamora meseta",
        distance_madrid_min=150, distance_beach_min=None,
        distance_natural_pools_min=30, distance_supermarket_min=10,
        distance_health_center_min=10, distance_hospital_min=20,
        fire_risk=FireRisk.NULO, zone_preference=5.0,
        price_min=50_000, price_max=260_000,
    )


def _make_scored(prop: Property, zone: Zone, score: float = 55.0) -> ScoredProperty:
    """Helper: crea un ScoredProperty con puntuación fija para tests."""
    breakdown = ScoreBreakdown(
        p1_rooms=3.5, p2_piscina=5.0, p3_distance=4.0, p4_beach=0.5,
        p5_pools=3.0, p6_supermarket=6.0, p7_health=9.0, p8_hospital=9.0,
        p9_price=6.5, p10_fire=9.0, p11_preference=5.0,
    )
    # Ajustar p1 para aproximar el total al valor pedido (no crítico en tests)
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
        assert any(p["uid"] == uid for p in radar)

        # Después de descartar no aparece
        db.dismiss(uid)
        radar = db.get_radar_properties(min_score=0.0)
        assert not any(p["uid"] == uid for p in radar)

    def test_dismissed_property_in_get_dismissed(self, db, sample_property, sample_zone):
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
        assert len(db.get_radar_properties(min_score=0.0)) == 0

        db.undismiss(uid)
        assert len(db.get_dismissed()) == 0
        assert len(db.get_radar_properties(min_score=0.0)) == 1

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
            "SELECT dismissed, dismissed_at FROM scored_properties WHERE property_uid=?", (uid,)
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
        prop1 = Property(
            portal=Portal.PISOS, portal_id="p1", url="https://x.com/1",
            zone_id="zamora_meseta", title="Casa 1", price=150_000,
            size_m2=100.0, rooms=4, has_garage=True, has_garden_or_plot=True,
            piscina=Piscina.NINGUNA, has_internet_mention=True, habitable=True,
        )
        prop2 = Property(
            portal=Portal.PISOS, portal_id="p2", url="https://x.com/2",
            zone_id="zamora_meseta", title="Casa 2", price=200_000,
            size_m2=120.0, rooms=4, has_garage=True, has_garden_or_plot=True,
            piscina=Piscina.NINGUNA, has_internet_mention=True, habitable=True,
        )
        for p in (prop1, prop2):
            db.upsert_property(p)
            db.upsert_score(_make_scored(p, sample_zone))

        db.dismiss(prop1.unique_id)

        radar = db.get_radar_properties(min_score=0.0)
        uids = [p["uid"] for p in radar]
        assert prop1.unique_id not in uids
        assert prop2.unique_id in uids


# ── Tests del radar ───────────────────────────────────────────────────────────

class TestRadar:

    def _insert(self, db, prop, zone, score_total=55.0):
        db.upsert_property(prop)
        db.upsert_score(_make_scored(prop, zone, score_total))

    def test_radar_empty_by_default(self, db):
        assert db.get_radar_properties() == []

    def test_radar_respects_min_score(self, db, sample_property, sample_zone):
        self._insert(db, sample_property, sample_zone, score_total=55.0)

        # El breakdown del helper suma 60.5 — con umbral mayor no aparece
        assert db.get_radar_properties(min_score=65.0) == []

        # Con umbral menor o igual aparece
        assert len(db.get_radar_properties(min_score=60.0)) == 1

    def test_radar_ordered_by_first_seen_desc(self, db, sample_zone):
        """La propiedad más reciente debe aparecer primera."""
        from datetime import datetime, timedelta

        older = Property(
            portal=Portal.PISOS, portal_id="old", url="https://x.com/old",
            zone_id="zamora_meseta", title="Antigua", price=150_000,
            size_m2=100.0, rooms=4, has_garage=True, has_garden_or_plot=True,
            piscina=Piscina.NINGUNA, has_internet_mention=True, habitable=True,
            first_seen=datetime.now() - timedelta(days=10),
        )
        newer = Property(
            portal=Portal.PISOS, portal_id="new", url="https://x.com/new",
            zone_id="zamora_meseta", title="Nueva", price=180_000,
            size_m2=120.0, rooms=4, has_garage=True, has_garden_or_plot=True,
            piscina=Piscina.NINGUNA, has_internet_mention=True, habitable=True,
            first_seen=datetime.now(),
        )
        for p in (older, newer):
            self._insert(db, p, sample_zone)

        radar = db.get_radar_properties(min_score=0.0)
        assert radar[0]["uid"] == newer.unique_id
        assert radar[1]["uid"] == older.unique_id

    def test_radar_returns_expected_fields(self, db, sample_property, sample_zone):
        self._insert(db, sample_property, sample_zone)
        props = db.get_radar_properties(min_score=0.0)
        assert len(props) == 1
        p = props[0]
        # Campos de propiedad
        for field in ("uid", "title", "price", "url", "zone_id", "rooms",
                      "size_m2", "piscina", "first_seen", "last_seen"):
            assert field in p, f"Campo '{field}' no encontrado"
        # Campos de scoring
        assert "score_total" in p

    def test_radar_excludes_dismissed(self, db, sample_property, sample_zone):
        self._insert(db, sample_property, sample_zone)
        db.dismiss(sample_property.unique_id)
        assert db.get_radar_properties(min_score=0.0) == []

    def test_radar_limit_is_respected(self, db, sample_zone):
        for i in range(5):
            p = Property(
                portal=Portal.PISOS, portal_id=str(i), url=f"https://x.com/{i}",
                zone_id="zamora_meseta", title=f"Casa {i}", price=150_000 + i * 1000,
                size_m2=100.0, rooms=4, has_garage=True, has_garden_or_plot=True,
                piscina=Piscina.NINGUNA, has_internet_mention=True, habitable=True,
            )
            self._insert(db, p, sample_zone)

        assert len(db.get_radar_properties(min_score=0.0, limit=3)) == 3


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
        content = "🏠 Casa 1\n  La Rioja — 250.000€ — 62.5 pts\n  https://idealista.com/123"
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
            "scraping_enabled":    False,
            "scraping_days":       [2, 5],
            "scraping_hour":       8,
            "gmail_check_enabled": False,
            "gmail_interval_min":  45,
            "summary_enabled":     False,
            "summary_day":         0,
            "summary_hour":        7,
        }
        db.save_schedule_config(new_config)
        config = db.get_schedule_config()
        for key, value in new_config.items():
            assert config[key] == value, f"Fallo en clave '{key}'"


# ── Tests de upsert_score con P11 ─────────────────────────────────────────────

class TestUpsertScoreP11:

    def test_p11_persisted_in_scored_properties(self, db, sample_property, sample_zone):
        """p11_preference debe guardarse en score_p11 en la tabla."""
        db.upsert_property(sample_property)
        scored = _make_scored(sample_property, sample_zone)
        db.upsert_score(scored)

        row = db._conn.execute(
            "SELECT score_p11 FROM scored_properties WHERE property_uid=?",
            (sample_property.unique_id,),
        ).fetchone()
        assert row is not None
        assert row["score_p11"] == pytest.approx(5.0)  # zone_preference del fixture

    def test_dismiss_preserved_after_upsert_score(self, db, sample_property, sample_zone):
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

    def test_alerted_preserved_after_upsert_score(self, db, sample_property, sample_zone):
        """Actualizar el score de una propiedad alertada no debe perder el flag alerted."""
        db.upsert_property(sample_property)
        scored = _make_scored(sample_property, sample_zone)
        db.upsert_score(scored)
        db.mark_alerted(sample_property.unique_id)

        # Segundo upsert_score
        db.upsert_score(scored)

        assert db.is_alerted(sample_property.unique_id) is True
