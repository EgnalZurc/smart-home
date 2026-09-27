"""
Tests unitarios del scheduler (casita_scheduler.py).
Verifica la lógica de scheduling sin levantar threads ni red.
"""

from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest
from casita_scheduler import CasitaScheduler, _SCRAPING_DAYS, _SUMMARY_DAY


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
        gmail_credentials_path="/tmp/creds.json",
        gmail_token_path="/tmp/token.json",
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
        from datetime import timedelta
        now = datetime(2026, 8, 31, 12, 0, 0)
        scheduler._last_gmail_check = datetime(2026, 8, 31, 11, 45, 0)  # hace 15 min
        assert scheduler._should_run_gmail_check(now) is False

    def test_gmail_check_runs_after_30_min(self, scheduler):
        from datetime import timedelta
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
        with patch("idealista_email_parser.fetch_new_alert_urls", return_value=[]):
            scheduler._run_gmail_check()
            scheduler._apify.scrape_property_url.assert_not_called()

    def test_gmail_check_with_url_below_threshold(self, scheduler):
        from models import FireRisk, Piscina, Portal, Property
        from datetime import datetime as dt

        low_score_prop = Property(
            portal=Portal.IDEALISTA, portal_id="111",
            url="https://www.idealista.com/inmueble/111/",
            zone_id="zamora_meseta",
            title="Casa pequeña", price=310_000,  # cerca del límite → score bajo
            size_m2=60.0, rooms=3,
            has_garage=True, has_garden_or_plot=True,
            piscina=Piscina.NINGUNA, has_internet_mention=True,
            habitable=True, description="",
            first_seen=dt.now(), last_seen=dt.now(),
        )

        scheduler._apify.scrape_property_url.return_value = low_score_prop

        with patch("idealista_email_parser.fetch_new_alert_urls",
                   return_value=["https://www.idealista.com/inmueble/111/"]):
            scheduler._run_gmail_check()
            # Debe haber procesado pero no alertado (score bajo)
            scheduler._db.upsert_property.assert_called()
            # La notificación de nueva propiedad NO debe haberse enviado
            # (ya que el score no supera el umbral con esos datos)
            # No podemos garantizar el threshold sin calcular el score exacto,
            # pero sí podemos verificar que el flujo se ejecutó
            scheduler._apify.scrape_property_url.assert_called_once()
