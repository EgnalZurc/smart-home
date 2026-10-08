"""
Tests unitarios del scheduler (casita_scheduler.py).
Verifica la lógica de scheduling sin levantar threads ni red.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest
from casita_scheduler import CasitaScheduler

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def scheduler() -> CasitaScheduler:
    db = MagicMock()
    db.count_properties.return_value = 0
    db.count_by_zone.return_value = {}
    db.is_new.return_value = True
    db.upsert_property.return_value = None
    db.is_alerted.return_value = False

    notifier = MagicMock()
    notifier.send_new_property_alert.return_value = True
    notifier.send_price_drop_alert.return_value = True
    notifier.send_weekly_summary.return_value = True
    notifier.send_status.return_value = True

    apify = MagicMock()
    apify.scrape_zone.return_value = []
    apify.scrape_property_url.return_value = None

    return CasitaScheduler(
        db=db,
        notifier=notifier,
        apify=apify,
        gmail_address="test@gmail.com",
        gmail_app_password="test_app_password",
    )


# ── Tests de condiciones de scheduling ───────────────────────────────────────


class TestSchedulingConditions:
    def test_scraping_runs_on_monday_at_7(self, scheduler):
        # Lunes (weekday=0) a las 07:00
        monday_7am = datetime(2026, 8, 31, 7, 0, 0)  # lunes
        assert monday_7am.weekday() == 0  # confirmar que es lunes
        assert scheduler._should_run_scraping(monday_7am) is True

    def test_scraping_runs_on_thursday_at_7(self, scheduler):
        # Jueves (weekday=3) a las 07:00
        thursday_7am = datetime(2026, 9, 3, 7, 0, 0)  # jueves
        assert thursday_7am.weekday() == 3
        assert scheduler._should_run_scraping(thursday_7am) is True

    def test_scraping_does_not_run_on_tuesday(self, scheduler):
        tuesday_7am = datetime(2026, 9, 1, 7, 0, 0)
        assert tuesday_7am.weekday() == 1
        assert scheduler._should_run_scraping(tuesday_7am) is False

    def test_scraping_does_not_run_on_monday_wrong_hour(self, scheduler):
        monday_8am = datetime(2026, 8, 31, 8, 0, 0)
        assert scheduler._should_run_scraping(monday_8am) is False

    def test_scraping_does_not_run_twice_same_day(self, scheduler):
        monday_7am = datetime(2026, 8, 31, 7, 0, 0)
        scheduler._last_scraping_date = monday_7am
        assert scheduler._should_run_scraping(monday_7am) is False

    def test_gmail_check_runs_immediately_if_never_ran(self, scheduler):
        scheduler._last_gmail_check = None
        assert scheduler._should_run_gmail_check(datetime.now()) is True

    def test_gmail_check_waits_30_min(self, scheduler):
        now = datetime(2026, 8, 31, 12, 0, 0)
        scheduler._last_gmail_check = datetime(2026, 8, 31, 11, 45, 0)  # hace 15 min
        assert scheduler._should_run_gmail_check(now) is False

    def test_gmail_check_runs_after_30_min(self, scheduler):
        now = datetime(2026, 8, 31, 12, 31, 0)
        scheduler._last_gmail_check = datetime(2026, 8, 31, 12, 0, 0)  # hace 31 min
        assert scheduler._should_run_gmail_check(now) is True

    def test_summary_runs_on_sunday_at_9(self, scheduler):
        sunday_9am = datetime(2026, 8, 30, 9, 0, 0)
        assert sunday_9am.weekday() == 6  # domingo
        assert scheduler._should_run_summary(sunday_9am) is True

    def test_summary_does_not_run_twice_sunday(self, scheduler):
        sunday_9am = datetime(2026, 8, 30, 9, 0, 0)
        scheduler._last_summary_date = sunday_9am
        assert scheduler._should_run_summary(sunday_9am) is False

    def test_summary_does_not_run_on_monday(self, scheduler):
        monday_9am = datetime(2026, 8, 31, 9, 0, 0)
        assert scheduler._should_run_summary(monday_9am) is False


# ── Tests de run_weekly_summary ───────────────────────────────────────────────


class TestWeeklySummary:
    def test_summary_calls_notifier(self, scheduler):
        scheduler._db.get_top_scored.return_value = []
        scheduler._run_weekly_summary()
        scheduler._notifier.send_weekly_summary.assert_called_once()

    def test_summary_calls_status_with_stats(self, scheduler):
        scheduler._db.get_top_scored.return_value = []
        scheduler._db.count_properties.return_value = 42
        scheduler._db.count_by_zone.return_value = {"zamora": 10, "salamanca": 15}
        scheduler._run_weekly_summary()
        scheduler._notifier.send_status.assert_called_once()
        status_msg = scheduler._notifier.send_status.call_args[0][0]
        assert "42" in status_msg


# ── Tests de _infer_zone_from_url ─────────────────────────────────────────────


class TestZoneInference:
    def test_infer_zamora_from_url(self, scheduler):
        url = "https://www.idealista.com/inmueble/12345678/"
        # Sin keywords → fallback a zamora_meseta
        zone = scheduler._infer_zone_from_url(url)
        assert zone is not None
        assert zone.id == "zamora_meseta"

    def test_infer_potes_from_url(self, scheduler):
        url = "https://www.idealista.com/inmueble/99999/potes-cantabria/"
        zone = scheduler._infer_zone_from_url(url)
        assert zone is not None
        # Debería inferir cantabria_liebana por la keyword "potes"
        assert zone.id == "cantabria_liebana"

    def test_infer_vinaros_from_url(self, scheduler):
        url = "https://www.idealista.com/inmueble/88888/vinaros-castellon/"
        zone = scheduler._infer_zone_from_url(url)
        assert zone is not None
        assert zone.id == "castellon_costa_norte"


# ── Tests de run_gmail_check (mock) ───────────────────────────────────────────


class TestGmailCheck:
    def test_gmail_check_with_no_urls(self, scheduler):
        with patch(
            "idealista_email_parser.fetch_new_alerts", return_value=([], [], None)
        ):
            scheduler._run_gmail_check()
            scheduler._apify.scrape_property_url.assert_not_called()

    def test_gmail_check_with_url_below_threshold(self, scheduler):
        """Verifica que un alerta de Gmail se procesa incluso con score bajo."""
        from idealista_email_parser import IdealistaAlert

        mock_alert = IdealistaAlert(
            url="https://www.idealista.com/inmueble/111/",
            property_id="111",
            email_id="12345",
            folder="INBOX",
            location_hint="zamora",
            price=310_000,
            rooms=3,
            size_m2=60.0,
            title="Casa pequeña",
        )

        mock_imap = MagicMock()
        mock_imap.close.return_value = None
        mock_imap.logout.return_value = None

        with (
            patch(
                "idealista_email_parser.fetch_new_alerts",
                return_value=([mock_alert], [], mock_imap),
            ),
            patch(
                "idealista_email_parser.delete_processed_emails",
                return_value=None,
            ),
            patch("httpx.Client") as mock_client,
        ):
            # Simular respuesta 403 de Idealista (bloquea scraping)
            mock_response = MagicMock()
            mock_response.status_code = 403
            mock_response.text = ""
            mock_client.return_value.__enter__.return_value.get.return_value = (
                mock_response
            )

            scheduler._run_gmail_check()

            # Debe haber insertado la propiedad usando fallback del email
            scheduler._db.upsert_property.assert_called()
            scheduler._db.upsert_score.assert_called()



# ═══════════════════════════════════════════════════════════════════════════════
# Additional scheduler tests for coverage - SchedulerStatus and helpers
# ═══════════════════════════════════════════════════════════════════════════════


class TestSchedulerStatus:
    """Tests for SchedulerStatus dataclass."""

    def test_scheduler_status_creation(self):
        """Test creating a SchedulerStatus object."""
        from casita_scheduler import SchedulerStatus, ScraperError
        from datetime import datetime

        status = SchedulerStatus(
            running=True,
            last_scraping=datetime(2026, 10, 1, 7, 0),
            last_gmail_check=datetime(2026, 10, 1, 8, 0),
            last_fotocasa_check=datetime(2026, 10, 1, 8, 30),
            last_summary=datetime(2026, 9, 29, 9, 0),
            last_scraping_result="ok",
            total_properties=100,
            radar_count=20,
            dismissed_count=5,
            scraper_errors=[],
            top_properties=[],
        )

        assert status.running is True
        assert status.total_properties == 100
        assert status.radar_count == 20

    def test_scraper_error_creation(self):
        """Test creating a ScraperError object."""
        from casita_scheduler import ScraperError
        from datetime import datetime

        error = ScraperError(
            portal="pisos",
            zone_id="zamora_meseta",
            error="Connection timeout",
        )

        assert error.portal == "pisos"
        assert error.zone_id == "zamora_meseta"
        assert error.error == "Connection timeout"
        assert isinstance(error.detected_at, datetime)


class TestSchedulerInferZone:
    """Tests for zone inference from URL."""

    def test_infer_zone_zamora_keywords(self):
        """Test inferring Zamora zone from URL."""
        from casita_scheduler import CasitaScheduler
        from zones import ZONES

        # Create minimal scheduler for testing
        scheduler = CasitaScheduler.__new__(CasitaScheduler)
        scheduler._db = None
        scheduler._notifier = None
        scheduler._apify = None

        zone = scheduler._infer_zone_from_url(
            "https://www.idealista.com/venta-viviendas/zamora/con-jardin/"
        )
        assert zone is not None
        assert zone.id == "zamora_meseta"

    def test_infer_zone_potes(self):
        """Test inferring Potes zone from URL."""
        from casita_scheduler import CasitaScheduler

        scheduler = CasitaScheduler.__new__(CasitaScheduler)
        zone = scheduler._infer_zone_from_url(
            "https://www.idealista.com/venta-viviendas/potes-liebana/"
        )
        assert zone is not None
        assert zone.id == "cantabria_liebana"

    def test_infer_zone_unknown_fallback(self):
        """Test fallback to default zone for unknown URL."""
        from casita_scheduler import CasitaScheduler

        scheduler = CasitaScheduler.__new__(CasitaScheduler)
        zone = scheduler._infer_zone_from_url(
            "https://www.idealista.com/venta-viviendas/unknown-place/"
        )
        # Should fallback to zamora_meseta
        assert zone is not None
        assert zone.id == "zamora_meseta"


class TestSchedulerConditions:
    """Tests for scheduler condition checking."""

    def test_should_run_gmail_check_first_time(self):
        """Test gmail check runs immediately if never ran."""
        from casita_scheduler import CasitaScheduler
        from datetime import datetime

        scheduler = CasitaScheduler.__new__(CasitaScheduler)
        scheduler._last_gmail_check = None

        result = scheduler._should_run_gmail_check_interval(1800)  # 30 min
        assert result is True

    def test_should_run_gmail_check_after_interval(self):
        """Test gmail check runs after interval passed."""
        from casita_scheduler import CasitaScheduler
        from datetime import datetime, timedelta

        scheduler = CasitaScheduler.__new__(CasitaScheduler)
        scheduler._last_gmail_check = datetime.now() - timedelta(minutes=35)

        result = scheduler._should_run_gmail_check_interval(1800)  # 30 min
        assert result is True

    def test_should_not_run_gmail_check_before_interval(self):
        """Test gmail check doesn't run before interval."""
        from casita_scheduler import CasitaScheduler
        from datetime import datetime, timedelta

        scheduler = CasitaScheduler.__new__(CasitaScheduler)
        scheduler._last_gmail_check = datetime.now() - timedelta(minutes=10)

        result = scheduler._should_run_gmail_check_interval(1800)  # 30 min
        assert result is False

    def test_should_run_fotocasa_check_first_time(self):
        """Test fotocasa check runs immediately if never ran."""
        from casita_scheduler import CasitaScheduler

        scheduler = CasitaScheduler.__new__(CasitaScheduler)
        scheduler._last_fotocasa_check = None

        result = scheduler._should_run_fotocasa_check_interval(1800)
        assert result is True


class TestSchedulerRadar:
    """Tests for scheduler get_radar method."""

    def test_get_radar_enriches_with_distance(self):
        """Test that get_radar adds distance_madrid_min to results."""
        from casita_scheduler import CasitaScheduler
        from unittest.mock import MagicMock

        scheduler = CasitaScheduler.__new__(CasitaScheduler)
        scheduler._db = MagicMock()
        scheduler._db.get_radar_properties.return_value = {
            "items": [
                {"zone_id": "zamora_meseta", "price": 100000}
            ],
            "total": 1,
        }

        result = scheduler.get_radar(limit=10)

        assert "items" in result
        assert len(result["items"]) == 1
        # Should have distance_madrid_min from zone
        assert "distance_madrid_min" in result["items"][0]
        assert result["items"][0]["distance_madrid_min"] == 150  # zamora_meseta value


class TestSchedulerDelegation:
    """Tests for scheduler delegation methods."""

    def test_dismiss_property_delegates(self):
        """Test dismiss_property calls db.dismiss."""
        from casita_scheduler import CasitaScheduler
        from unittest.mock import MagicMock

        scheduler = CasitaScheduler.__new__(CasitaScheduler)
        scheduler._db = MagicMock()
        scheduler._db.dismiss.return_value = True

        result = scheduler.dismiss_property("idealista:123")

        scheduler._db.dismiss.assert_called_once_with("idealista:123")
        assert result is True

    def test_undismiss_property_delegates(self):
        """Test undismiss_property calls db.undismiss."""
        from casita_scheduler import CasitaScheduler
        from unittest.mock import MagicMock

        scheduler = CasitaScheduler.__new__(CasitaScheduler)
        scheduler._db = MagicMock()
        scheduler._db.undismiss.return_value = True

        result = scheduler.undismiss_property("idealista:123")

        scheduler._db.undismiss.assert_called_once_with("idealista:123")
        assert result is True

    def test_mark_viewed_delegates(self):
        """Test mark_viewed calls db.mark_viewed."""
        from casita_scheduler import CasitaScheduler
        from unittest.mock import MagicMock

        scheduler = CasitaScheduler.__new__(CasitaScheduler)
        scheduler._db = MagicMock()
        scheduler._db.mark_viewed.return_value = True

        result = scheduler.mark_viewed("idealista:123")

        scheduler._db.mark_viewed.assert_called_once_with("idealista:123")
        assert result is True

    def test_save_comment_delegates(self):
        """Test save_comment calls db.save_comment."""
        from casita_scheduler import CasitaScheduler
        from unittest.mock import MagicMock

        scheduler = CasitaScheduler.__new__(CasitaScheduler)
        scheduler._db = MagicMock()
        scheduler._db.save_comment.return_value = True

        result = scheduler.save_comment("idealista:123", "Nice house!")

        scheduler._db.save_comment.assert_called_once_with("idealista:123", "Nice house!")
        assert result is True

    def test_get_schedule_config_delegates(self):
        """Test get_schedule_config calls db."""
        from casita_scheduler import CasitaScheduler
        from unittest.mock import MagicMock

        scheduler = CasitaScheduler.__new__(CasitaScheduler)
        scheduler._db = MagicMock()
        scheduler._db.get_schedule_config.return_value = {"key": "value"}

        result = scheduler.get_schedule_config()

        scheduler._db.get_schedule_config.assert_called_once()
        assert result == {"key": "value"}

    def test_save_schedule_config_delegates(self):
        """Test save_schedule_config calls db."""
        from casita_scheduler import CasitaScheduler
        from unittest.mock import MagicMock

        scheduler = CasitaScheduler.__new__(CasitaScheduler)
        scheduler._db = MagicMock()

        scheduler.save_schedule_config({"scraping_hour": 8})

        scheduler._db.save_schedule_config.assert_called_once_with({"scraping_hour": 8})

    def test_get_last_summary_delegates(self):
        """Test get_last_summary calls db."""
        from casita_scheduler import CasitaScheduler
        from unittest.mock import MagicMock

        scheduler = CasitaScheduler.__new__(CasitaScheduler)
        scheduler._db = MagicMock()
        scheduler._db.get_last_weekly_summary.return_value = {"content": "test"}

        result = scheduler.get_last_summary()

        scheduler._db.get_last_weekly_summary.assert_called_once()
        assert result == {"content": "test"}

    def test_get_dismissed_delegates(self):
        """Test get_dismissed calls db."""
        from casita_scheduler import CasitaScheduler
        from unittest.mock import MagicMock

        scheduler = CasitaScheduler.__new__(CasitaScheduler)
        scheduler._db = MagicMock()
        scheduler._db.get_dismissed.return_value = [{"uid": "test:1"}]

        result = scheduler.get_dismissed()

        scheduler._db.get_dismissed.assert_called_once()
        assert result == [{"uid": "test:1"}]



# ═══════════════════════════════════════════════════════════════════════════════
# Coverage expansion (T13): lifecycle, run_scraping, gmail/fotocasa checks,
# zone inference (hint + nominatim), idealista scraping, weekly summary, status.
# These tests exercise the previously-omitted code paths of casita_scheduler.py.
# ═══════════════════════════════════════════════════════════════════════════════

from models import (
    GarageType,
    Habitability,
    Internet,
    Piscina,
    Portal,
    Property,
    ScoreBreakdown,
    ScoredProperty,
)
from zones import ZONES


def _make_property(zone_id: str = "zamora_meseta", price: int = 150_000) -> Property:
    """Build a minimal valid Property for scheduler processing tests."""
    return Property(
        portal=Portal.PISOS,
        portal_id="p-1",
        url="https://www.pisos.com/casa-1/",
        zone_id=zone_id,
        title="Casa de prueba",
        price=price,
        size_m2=120.0,
        rooms=4,
        has_garden_or_plot=True,
        terrain_m2=300.0,
        garage_type=GarageType.EDIFICIO,
        piscina=Piscina.NINGUNA,
        habitability=Habitability.BUENO,
        internet=Internet.FIBRA,
        has_garage=True,
    )


def _high_score(prop: Property, zone) -> ScoredProperty:
    """A ScoredProperty guaranteed to pass the alert threshold (all 10s)."""
    breakdown = ScoreBreakdown(
        r1_rooms=10, r2_terrain=10, r3_garage=10, r4_habitability=10,
        r5_piscina=10, r6_ac=10, r7_price=10, r8_supermarket=10,
        r9_health=10, r10_hospital=10, r11_internet=10, r12_madrid=10,
        r13_beach=10, r14_pools=10, r15_fire=10, r16_flood=10,
        r17_coast=10, r18_beach_plot=10,
    )
    return ScoredProperty(prop=prop, zone=zone, score=breakdown)


# ── Lifecycle ─────────────────────────────────────────────────────────────────


class TestLifecycle:
    def test_start_launches_thread_and_sets_running(self, scheduler):
        with patch.object(scheduler, "_loop") as mock_loop:
            scheduler.start()
            assert scheduler._running is True
            assert scheduler._thread is not None
            # join so the daemon thread (which just calls the mocked _loop) finishes
            scheduler._thread.join(timeout=2)
            mock_loop.assert_called_once()

    def test_stop_clears_running(self, scheduler):
        scheduler._running = True
        scheduler.stop()
        assert scheduler._running is False


# ── Loop (single iteration) ─────────────────────────────────────────────────


class TestLoopIteration:
    def test_loop_triggers_all_jobs_when_due(self, scheduler):
        """One loop pass on summary day/hour that also triggers scraping + checks."""
        # Sunday 2026-08-30 is weekday 6; use a config where everything fires.
        fixed_now = datetime(2026, 8, 30, 9, 0, 0)
        scheduler._db.get_schedule_config.return_value = {
            "scraping_enabled": True,
            "scraping_days": [6],  # make scraping fire on Sunday too
            "scraping_hour": 9,
            "gmail_check_enabled": True,
            "gmail_interval_min": 30,
            "summary_enabled": True,
            "summary_day": 6,
            "summary_hour": 9,
        }

        call_count = {"n": 0}

        class _FakeDateTime:
            @staticmethod
            def now():
                return fixed_now

        scheduler._running = True

        def _fake_sleep(_secs):
            # No-op for the grace sleep; the loop is stopped by _run_weekly_summary
            # below (the last job in the iteration) so the body runs exactly once.
            call_count["n"] += 1

        def _stop_loop():
            scheduler._running = False

        with (
            patch("casita_scheduler.datetime", _FakeDateTime),
            patch("casita_scheduler.time.sleep", side_effect=_fake_sleep),
            patch.object(scheduler, "_run_scraping") as m_scrap,
            patch.object(scheduler, "_run_gmail_check") as m_gmail,
            patch.object(scheduler, "_run_fotocasa_check") as m_foto,
            patch.object(
                scheduler, "_run_weekly_summary", side_effect=_stop_loop
            ) as m_sum,
        ):
            scheduler._loop()

        m_scrap.assert_called_once()
        m_gmail.assert_called_once()
        m_foto.assert_called_once()
        m_sum.assert_called_once()

    def test_loop_skips_jobs_when_disabled(self, scheduler):
        fixed_now = datetime(2026, 9, 1, 12, 0, 0)  # Tuesday noon, nothing due
        scheduler._db.get_schedule_config.return_value = {
            "scraping_enabled": False,
            "gmail_check_enabled": False,
            "summary_enabled": False,
        }

        class _FakeDateTime:
            @staticmethod
            def now():
                return fixed_now

        scheduler._running = True

        def _fake_sleep(_secs):
            scheduler._running = False

        with (
            patch("casita_scheduler.datetime", _FakeDateTime),
            patch("casita_scheduler.time.sleep", side_effect=_fake_sleep),
            patch.object(scheduler, "_run_scraping") as m_scrap,
            patch.object(scheduler, "_run_gmail_check") as m_gmail,
            patch.object(scheduler, "_run_weekly_summary") as m_sum,
        ):
            scheduler._loop()

        m_scrap.assert_not_called()
        m_gmail.assert_not_called()
        m_sum.assert_not_called()


# ── run_scraping ──────────────────────────────────────────────────────────────


class TestRunScraping:
    def test_scraping_processes_props_and_sends_summary(self, scheduler):
        prop = _make_property()
        zone = ZONES["zamora_meseta"]

        scheduler._db.upsert_property.return_value = None
        scheduler._db.is_alerted.return_value = False
        scheduler._apify.scrape_zone.return_value = []

        with (
            patch(
                "casita_scheduler.pisos_scraper.scrape_zone", return_value=[prop]
            ),
            patch(
                "casita_scheduler.fotocasa_scraper.scrape_zone", return_value=[]
            ),
            patch(
                "casita_scheduler.habitaclia_scraper.scrape_zone", return_value=[]
            ),
            patch("casita_scheduler.evaluate", return_value=_high_score(prop, zone)),
        ):
            scheduler.run_scraping_now()

        # A property passed the threshold → marked alerted; a summary is sent.
        scheduler._db.mark_alerted.assert_called()
        scheduler._notifier.send_status.assert_called()
        assert scheduler._last_scraping_result in ("ok", "ok_with_errors")

    def test_scraping_marks_error_when_zero_scored(self, scheduler):
        with (
            patch("casita_scheduler.pisos_scraper.scrape_zone", return_value=[]),
            patch("casita_scheduler.fotocasa_scraper.scrape_zone", return_value=[]),
            patch("casita_scheduler.habitaclia_scraper.scrape_zone", return_value=[]),
        ):
            scheduler._apify.scrape_zone.return_value = []
            scheduler.run_scraping_now()

        assert scheduler._last_scraping_result == "error"

    def test_scraping_records_scraper_errors(self, scheduler):
        with (
            patch(
                "casita_scheduler.pisos_scraper.scrape_zone",
                side_effect=RuntimeError("boom"),
            ),
            patch("casita_scheduler.fotocasa_scraper.scrape_zone", return_value=[]),
            patch("casita_scheduler.habitaclia_scraper.scrape_zone", return_value=[]),
        ):
            scheduler._apify.scrape_zone.return_value = []
            scheduler.run_scraping_now()

        status = scheduler.get_status()
        assert any(e.portal == "pisos" for e in status.scraper_errors)
        assert scheduler._last_scraping_result == "error"

    def test_scraping_handles_apify_error(self, scheduler):
        with (
            patch("casita_scheduler.pisos_scraper.scrape_zone", return_value=[]),
            patch("casita_scheduler.fotocasa_scraper.scrape_zone", return_value=[]),
            patch("casita_scheduler.habitaclia_scraper.scrape_zone", return_value=[]),
        ):
            scheduler._apify.scrape_zone.side_effect = RuntimeError("apify down")
            scheduler.run_scraping_now()

        status = scheduler.get_status()
        assert any(e.portal == "idealista_apify" for e in status.scraper_errors)

    def test_scraping_sends_price_drop_alert(self, scheduler):
        prop = _make_property()
        zone = ZONES["zamora_meseta"]
        from models import PriceEvent

        price_event = PriceEvent(
            property_uid=prop.unique_id, old_price=200_000, new_price=180_000
        )
        scheduler._db.upsert_property.return_value = price_event

        with (
            patch("casita_scheduler.pisos_scraper.scrape_zone", return_value=[prop]),
            patch("casita_scheduler.fotocasa_scraper.scrape_zone", return_value=[]),
            patch("casita_scheduler.habitaclia_scraper.scrape_zone", return_value=[]),
            patch("casita_scheduler.evaluate", return_value=_high_score(prop, zone)),
        ):
            scheduler._apify.scrape_zone.return_value = []
            scheduler.run_scraping_now()

        scheduler._notifier.send_price_drop_alert.assert_called()


# ── Gmail check ───────────────────────────────────────────────────────────────


class TestRunGmailCheck:
    def test_gmail_check_guard_against_concurrent(self, scheduler):
        scheduler._gmail_check_running = True
        with patch.object(scheduler, "_do_gmail_check") as m_do:
            scheduler._run_gmail_check()
            m_do.assert_not_called()

    def test_gmail_check_resets_flag_after_run(self, scheduler):
        with patch.object(scheduler, "_do_gmail_check"):
            scheduler._run_gmail_check()
        assert scheduler._gmail_check_running is False

    def test_do_gmail_check_fetch_error_returns_early(self, scheduler):
        with patch(
            "idealista_email_parser.fetch_new_alerts",
            side_effect=RuntimeError("imap fail"),
        ):
            scheduler._do_gmail_check()
        scheduler._db.upsert_property.assert_not_called()

    def test_do_gmail_check_no_alerts_closes_connection(self, scheduler):
        imap = MagicMock()
        with patch(
            "idealista_email_parser.fetch_new_alerts",
            return_value=([], [], imap),
        ):
            scheduler._do_gmail_check()
        imap.close.assert_called_once()
        imap.logout.assert_called_once()

    def test_do_gmail_check_reports_parse_errors(self, scheduler):
        with patch(
            "idealista_email_parser.fetch_new_alerts",
            return_value=([], ["parse error 1"], None),
        ):
            scheduler._do_gmail_check()
        scheduler._notifier.send_status.assert_called()

    def test_do_gmail_check_processes_alert_and_notifies(self, scheduler):
        from idealista_email_parser import IdealistaAlert

        alert = IdealistaAlert(
            url="https://www.idealista.com/inmueble/1/zamora/",
            property_id="1",
            email_id="e1",
            folder="INBOX",
            location_hint="zamora",
            price=150_000,
            rooms=4,
            size_m2=120.0,
            title="Casa Zamora",
        )
        imap = MagicMock()
        prop = _make_property()
        zone = ZONES["zamora_meseta"]

        with (
            patch(
                "idealista_email_parser.fetch_new_alerts",
                return_value=([alert], [], imap),
            ),
            patch("idealista_email_parser.delete_processed_emails"),
            patch.object(scheduler, "_scrape_idealista_property", return_value=prop),
            patch(
                "casita_scheduler.evaluate_from_email",
                return_value=_high_score(prop, zone),
            ),
        ):
            scheduler._db.is_alerted.return_value = False
            scheduler._do_gmail_check()

        scheduler._db.upsert_score.assert_called()
        scheduler._db.mark_alerted.assert_called()
        scheduler._notifier.send_status.assert_called()

    def test_do_gmail_check_skips_when_no_zone(self, scheduler):
        from idealista_email_parser import IdealistaAlert

        alert = IdealistaAlert(
            url="https://x/",
            property_id="2",
            email_id="e2",
            folder="INBOX",
            location_hint="unknownville",
        )
        imap = MagicMock()
        with (
            patch(
                "idealista_email_parser.fetch_new_alerts",
                return_value=([alert], [], imap),
            ),
            patch("idealista_email_parser.delete_processed_emails"),
            patch.object(scheduler, "_infer_zone_from_hint", return_value=None),
        ):
            scheduler._do_gmail_check()
        scheduler._db.upsert_score.assert_not_called()


# ── Fotocasa check ───────────────────────────────────────────────────────────


class TestRunFotocasaCheck:
    def test_fotocasa_check_guard_against_concurrent(self, scheduler):
        scheduler._fotocasa_check_running = True
        with patch.object(scheduler, "_do_fotocasa_check") as m_do:
            scheduler._run_fotocasa_check()
            m_do.assert_not_called()

    def test_do_fotocasa_fetch_error_returns_early(self, scheduler):
        with patch(
            "fotocasa_email_parser.fetch_new_fotocasa_alerts",
            side_effect=RuntimeError("imap fail"),
        ):
            scheduler._do_fotocasa_check()
        scheduler._db.upsert_property.assert_not_called()

    def test_do_fotocasa_no_alerts_closes_connection(self, scheduler):
        imap = MagicMock()
        with patch(
            "fotocasa_email_parser.fetch_new_fotocasa_alerts",
            return_value=([], [], imap),
        ):
            scheduler._do_fotocasa_check()
        imap.close.assert_called_once()

    def test_do_fotocasa_processes_alert(self, scheduler):
        from fotocasa_email_parser import FotocasaAlert

        alert = FotocasaAlert(
            url="https://www.fotocasa.es/zamora/1/",
            property_id="1",
            email_id="f1",
            folder="INBOX",
            location_hint="zamora",
            price=140_000,
            rooms=4,
            size_m2=110.0,
            has_garden=True,
            has_garage=True,
            has_ac=True,
        )
        imap = MagicMock()

        with (
            patch(
                "fotocasa_email_parser.fetch_new_fotocasa_alerts",
                return_value=([alert], [], imap),
            ),
            patch("fotocasa_email_parser.delete_processed_fotocasa_emails"),
            patch(
                "casita_scheduler.evaluate_from_email",
                side_effect=lambda p, z: _high_score(p, z),
            ),
        ):
            scheduler._db.is_alerted.return_value = False
            scheduler._do_fotocasa_check()

        scheduler._db.upsert_score.assert_called()
        scheduler._db.mark_alerted.assert_called()

    def test_do_fotocasa_skips_alert_with_parse_error(self, scheduler):
        from fotocasa_email_parser import FotocasaAlert

        alert = FotocasaAlert(
            url="https://www.fotocasa.es/zamora/2/",
            property_id="2",
            email_id="f2",
            folder="INBOX",
            location_hint="zamora",
            parse_error="broken",
        )
        imap = MagicMock()
        with (
            patch(
                "fotocasa_email_parser.fetch_new_fotocasa_alerts",
                return_value=([alert], [], imap),
            ),
            patch("fotocasa_email_parser.delete_processed_fotocasa_emails"),
        ):
            scheduler._do_fotocasa_check()
        scheduler._db.upsert_score.assert_not_called()

    def test_do_fotocasa_skips_alert_without_price(self, scheduler):
        from fotocasa_email_parser import FotocasaAlert

        alert = FotocasaAlert(
            url="https://www.fotocasa.es/zamora/3/",
            property_id="3",
            email_id="f3",
            folder="INBOX",
            location_hint="zamora",
            price=None,
        )
        imap = MagicMock()
        with (
            patch(
                "fotocasa_email_parser.fetch_new_fotocasa_alerts",
                return_value=([alert], [], imap),
            ),
            patch("fotocasa_email_parser.delete_processed_fotocasa_emails"),
        ):
            scheduler._do_fotocasa_check()
        scheduler._db.upsert_score.assert_not_called()


# ── Zone inference from hint ─────────────────────────────────────────────────


class TestInferZoneFromHint:
    def test_hint_matches_municipio(self, scheduler):
        zone = scheduler._infer_zone_from_hint("zamora", "https://x/")
        assert zone is not None
        assert zone.id == "zamora_meseta"

    def test_hint_matches_keyword(self, scheduler):
        zone = scheduler._infer_zone_from_hint("potes", "https://x/")
        assert zone is not None
        assert zone.id == "cantabria_liebana"

    def test_url_fallback_when_no_hint_match(self, scheduler):
        zone = scheduler._infer_zone_from_hint(
            None, "https://www.idealista.com/zamora/casa/"
        )
        assert zone is not None
        assert zone.id == "zamora_meseta"

    def test_nominatim_fallback_invoked(self, scheduler):
        sentinel = ZONES["zamora_meseta"]
        with patch.object(
            scheduler, "_infer_zone_nominatim", return_value=sentinel
        ) as m_nom:
            zone = scheduler._infer_zone_from_hint("pueblo-raro-xyz", "https://x/")
            m_nom.assert_called_once()
        assert zone is sentinel

    def test_returns_none_when_everything_fails(self, scheduler):
        with patch.object(scheduler, "_infer_zone_nominatim", return_value=None):
            zone = scheduler._infer_zone_from_hint("pueblo-raro-xyz", "https://x/")
        assert zone is None


# ── Zone inference via Nominatim ─────────────────────────────────────────────


class TestInferZoneNominatim:
    def test_nominatim_returns_nearest_zone(self, scheduler):
        payload = [{"lat": "41.503", "lon": "-5.744", "type": "city"}]
        resp = MagicMock()
        resp.read.return_value = __import__("json").dumps(payload).encode()
        resp.__enter__ = lambda s: s
        resp.__exit__ = lambda *a: False
        with patch("urllib.request.urlopen", return_value=resp):
            zone = scheduler._infer_zone_nominatim("zamora")
        assert zone is not None
        assert zone.id == "zamora_meseta"

    def test_nominatim_no_results_returns_none(self, scheduler):
        resp = MagicMock()
        resp.read.return_value = b"[]"
        resp.__enter__ = lambda s: s
        resp.__exit__ = lambda *a: False
        with patch("urllib.request.urlopen", return_value=resp):
            zone = scheduler._infer_zone_nominatim("nowhere")
        assert zone is None

    def test_nominatim_too_far_returns_none(self, scheduler):
        # Canary Islands coords — >200 km from any peninsular zone.
        payload = [{"lat": "28.291", "lon": "-16.629", "type": "city"}]
        resp = MagicMock()
        resp.read.return_value = __import__("json").dumps(payload).encode()
        resp.__enter__ = lambda s: s
        resp.__exit__ = lambda *a: False
        with patch("urllib.request.urlopen", return_value=resp):
            zone = scheduler._infer_zone_nominatim("tenerife")
        assert zone is None

    def test_nominatim_exception_returns_none(self, scheduler):
        with patch(
            "urllib.request.urlopen", side_effect=RuntimeError("network down")
        ):
            zone = scheduler._infer_zone_nominatim("zamora")
        assert zone is None


# ── Idealista property scraping ──────────────────────────────────────────────


class TestScrapeIdealistaProperty:
    def _alert(self):
        from idealista_email_parser import IdealistaAlert

        return IdealistaAlert(
            url="https://www.idealista.com/inmueble/1/",
            property_id="1",
            email_id="e1",
            folder="INBOX",
            location_hint="zamora",
            price=150_000,
            rooms=4,
            size_m2=120.0,
            title="Casa",
        )

    def test_scrape_blocked_uses_email_fallback(self, scheduler):
        zone = ZONES["zamora_meseta"]
        resp = MagicMock()
        resp.status_code = 403
        resp.text = ""
        client_cm = MagicMock()
        client_cm.__enter__.return_value.get.return_value = resp
        with patch("httpx.Client", return_value=client_cm):
            prop = scheduler._scrape_idealista_property(self._alert(), zone)
        assert prop is not None
        assert prop.price == 150_000
        assert prop.portal == Portal.IDEALISTA

    def test_scrape_returns_none_without_price(self, scheduler):
        from idealista_email_parser import IdealistaAlert

        zone = ZONES["zamora_meseta"]
        alert = IdealistaAlert(
            url="https://www.idealista.com/inmueble/9/",
            property_id="9",
            email_id="e9",
            folder="INBOX",
            location_hint="zamora",
            price=None,
        )
        resp = MagicMock()
        resp.status_code = 403
        resp.text = ""
        client_cm = MagicMock()
        client_cm.__enter__.return_value.get.return_value = resp
        with patch("httpx.Client", return_value=client_cm):
            prop = scheduler._scrape_idealista_property(alert, zone)
        assert prop is None

    def test_scrape_handles_request_exception(self, scheduler):
        zone = ZONES["zamora_meseta"]
        with patch("httpx.Client", side_effect=RuntimeError("conn error")):
            prop = scheduler._scrape_idealista_property(self._alert(), zone)
        # Falls back to email data despite the exception.
        assert prop is not None
        assert prop.price == 150_000


# ── Weekly summary ───────────────────────────────────────────────────────────


class TestWeeklySummaryExtended:
    def test_summary_saves_to_db(self, scheduler):
        scheduler._db.get_top_scored.return_value = [
            {
                "score_total": 150.0,
                "price": 120_000,
                "zone_id": "zamora_meseta",
                "url": "https://x/1",
            }
        ]
        scheduler._db.count_by_zone.return_value = {"zamora_meseta": 5}
        scheduler._db.count_properties.return_value = 5
        scheduler.run_summary_now()
        scheduler._db.save_weekly_summary.assert_called_once()

    def test_summary_handles_db_exception(self, scheduler):
        scheduler._db.get_top_scored.side_effect = RuntimeError("db error")
        # Should swallow the exception, not raise.
        scheduler.run_summary_now()
        scheduler._notifier.send_weekly_summary.assert_not_called()


# ── get_status ───────────────────────────────────────────────────────────────


class TestGetStatus:
    def test_status_reports_counts(self, scheduler):
        scheduler._db.count_properties.return_value = 50
        scheduler._db.get_radar_properties.return_value = {"total": 12}
        scheduler._db.get_dismissed.return_value = [{"uid": "a"}, {"uid": "b"}]
        scheduler._db.get_top_scored.return_value = []

        status = scheduler.get_status()

        assert status.total_properties == 50
        assert status.radar_count == 12
        assert status.dismissed_count == 2
        assert status.running is False
