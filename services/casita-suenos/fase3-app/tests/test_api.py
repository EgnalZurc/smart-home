"""Tests for FastAPI endpoints in main.py."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch
from datetime import datetime


@pytest.fixture
def mock_scheduler():
    """Create a mock scheduler instance."""
    mock = MagicMock()
    mock.get_status.return_value = MagicMock(
        running=True,
        last_scraping=datetime(2026, 10, 1, 7, 0),
        last_gmail_check=datetime(2026, 10, 1, 8, 0),
        last_fotocasa_check=datetime(2026, 10, 1, 8, 30),
        last_summary=datetime(2026, 9, 29, 9, 0),
        last_scraping_result="ok",
        total_properties=150,
        radar_count=25,
        dismissed_count=10,
        scraper_errors=[],
        top_properties=[
            {
                "uid": "idealista:12345",
                "title": "Casa en Zamora",
                "price": 120000,
                "score_total": 130.5,
                "zone_id": "zamora_meseta",
                "url": "https://idealista.com/inmueble/12345",
                "rooms": 4,
                "size_m2": 150.0,
                "first_seen": "2026-09-15T10:00:00",
            }
        ],
    )
    mock.get_schedule_config.return_value = {
        "scraping_enabled": True,
        "scraping_days": [0, 3],
        "scraping_hour": 7,
        "gmail_check_enabled": True,
        "gmail_interval_min": 30,
        "summary_enabled": True,
        "summary_day": 6,
        "summary_hour": 9,
    }
    mock.get_radar.return_value = {
        "items": [
            {
                "uid": "idealista:12345",
                "title": "Casa en Zamora",
                "price": 120000,
                "score_total": 130.5,
            }
        ],
        "total": 1,
        "offset": 0,
        "limit": 20,
        "has_more": False,
    }
    mock.get_dismissed.return_value = []
    mock.get_last_summary.return_value = {"content": "Summary", "sent_at": "2026-09-29"}
    mock.dismiss_property.return_value = True
    mock.undismiss_property.return_value = True
    mock.mark_viewed.return_value = True
    mock.save_comment.return_value = True
    return mock


@pytest.fixture
def client(mock_scheduler):
    """Create test client with mocked scheduler."""
    import main

    main._scheduler_instance = mock_scheduler
    return TestClient(main.app)


class TestHealthEndpoint:
    """Tests for /health endpoint."""

    def test_health_returns_online(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"online": True}


class TestStatusEndpoint:
    """Tests for /status endpoint."""

    def test_status_returns_full_info(self, client, mock_scheduler):
        response = client.get("/status")
        assert response.status_code == 200
        data = response.json()

        assert data["online"] is True
        assert data["running"] is True
        assert data["total_properties"] == 150
        assert data["radar_count"] == 25
        assert data["dismissed_count"] == 10
        assert data["last_scraping_result"] == "ok"
        assert len(data["top_properties"]) == 1
        assert data["top_properties"][0]["uid"] == "idealista:12345"

    def test_status_503_when_scheduler_not_ready(self, mock_scheduler):
        import main

        main._scheduler_instance = None
        client = TestClient(main.app)

        response = client.get("/status")
        assert response.status_code == 503


class TestRadarEndpoint:
    """Tests for /radar endpoint."""

    def test_radar_returns_properties(self, client, mock_scheduler):
        response = client.get("/radar")
        assert response.status_code == 200
        data = response.json()

        assert "items" in data
        assert "total" in data
        assert data["total"] == 1

    def test_radar_with_pagination(self, client, mock_scheduler):
        response = client.get("/radar?limit=10&offset=5")
        assert response.status_code == 200
        mock_scheduler.get_radar.assert_called_with(
            limit=10,
            offset=5,
            sort_by="score",
            sort_dir="desc",
            filter_by=None,
            portal_filter=None,
        )

    def test_radar_with_filters(self, client, mock_scheduler):
        response = client.get("/radar?filter=viewed&portal=idealista")
        assert response.status_code == 200
        mock_scheduler.get_radar.assert_called_with(
            limit=20,
            offset=0,
            sort_by="score",
            sort_dir="desc",
            filter_by="viewed",
            portal_filter="idealista",
        )

    def test_radar_limit_capped_at_100(self, client, mock_scheduler):
        response = client.get("/radar?limit=500")
        assert response.status_code == 200
        mock_scheduler.get_radar.assert_called_with(
            limit=100,  # capped
            offset=0,
            sort_by="score",
            sort_dir="desc",
            filter_by=None,
            portal_filter=None,
        )


class TestDismissEndpoints:
    """Tests for dismiss/undismiss endpoints."""

    def test_dismiss_property_success(self, client, mock_scheduler):
        response = client.post("/dismiss", json={"uid": "idealista:12345"})
        assert response.status_code == 200
        assert response.json() == {"ok": True, "uid": "idealista:12345"}
        mock_scheduler.dismiss_property.assert_called_with("idealista:12345")

    def test_dismiss_property_not_found(self, client, mock_scheduler):
        mock_scheduler.dismiss_property.return_value = False
        response = client.post("/dismiss", json={"uid": "nonexistent"})
        assert response.status_code == 404

    def test_undismiss_property_success(self, client, mock_scheduler):
        response = client.post("/undismiss", json={"uid": "idealista:12345"})
        assert response.status_code == 200
        mock_scheduler.undismiss_property.assert_called_with("idealista:12345")

    def test_get_dismissed(self, client, mock_scheduler):
        mock_scheduler.get_dismissed.return_value = [
            {"uid": "pisos:999", "title": "Dismissed casa"}
        ]
        response = client.get("/dismissed")
        assert response.status_code == 200
        data = response.json()
        assert "properties" in data
        assert len(data["properties"]) == 1


class TestViewedAndComments:
    """Tests for mark-viewed and save-comment endpoints."""

    def test_mark_viewed_success(self, client, mock_scheduler):
        response = client.post("/mark-viewed", json={"uid": "idealista:12345"})
        assert response.status_code == 200
        mock_scheduler.mark_viewed.assert_called_with("idealista:12345")

    def test_mark_viewed_not_found(self, client, mock_scheduler):
        mock_scheduler.mark_viewed.return_value = False
        response = client.post("/mark-viewed", json={"uid": "nonexistent"})
        assert response.status_code == 404

    def test_save_comment_success(self, client, mock_scheduler):
        response = client.post(
            "/save-comment", json={"uid": "idealista:12345", "comment": "Nice house"}
        )
        assert response.status_code == 200
        mock_scheduler.save_comment.assert_called_with("idealista:12345", "Nice house")


class TestScheduleEndpoints:
    """Tests for schedule config endpoints."""

    def test_get_schedule(self, client, mock_scheduler):
        response = client.get("/schedule")
        assert response.status_code == 200
        data = response.json()
        assert data["scraping_enabled"] is True
        assert data["scraping_days"] == [0, 3]

    def test_save_schedule(self, client, mock_scheduler):
        response = client.post(
            "/schedule",
            json={"scraping_enabled": False, "scraping_hour": 8},
        )
        assert response.status_code == 200
        mock_scheduler.save_schedule_config.assert_called_with(
            {"scraping_enabled": False, "scraping_hour": 8}
        )

    def test_save_schedule_ignores_none_values(self, client, mock_scheduler):
        response = client.post("/schedule", json={"scraping_hour": 9})
        assert response.status_code == 200
        mock_scheduler.save_schedule_config.assert_called_with({"scraping_hour": 9})


class TestSummaryEndpoint:
    """Tests for summary endpoint."""

    def test_get_summary(self, client, mock_scheduler):
        response = client.get("/summary")
        assert response.status_code == 200
        data = response.json()
        assert data["content"] == "Summary"

    def test_get_summary_empty(self, client, mock_scheduler):
        mock_scheduler.get_last_summary.return_value = None
        response = client.get("/summary")
        assert response.status_code == 200
        assert response.json() == {"content": None, "sent_at": None}


class TestManualTriggerEndpoints:
    """Tests for manual trigger endpoints."""

    def test_run_scraping(self, client, mock_scheduler):
        response = client.post("/run-scraping")
        assert response.status_code == 200
        assert response.json()["ok"] is True
        assert "iniciado" in response.json()["message"].lower()

    def test_run_gmail_check(self, client, mock_scheduler):
        response = client.post("/run-gmail-check")
        assert response.status_code == 200
        assert response.json()["ok"] is True

    def test_run_fotocasa_check(self, client, mock_scheduler):
        response = client.post("/run-fotocasa-check")
        assert response.status_code == 200
        assert response.json()["ok"] is True

    def test_run_summary(self, client, mock_scheduler):
        response = client.post("/run-summary")
        assert response.status_code == 200
        assert response.json()["ok"] is True


class TestTelegramWebhook:
    """Tests for telegram webhook endpoint."""

    def test_telegram_webhook_start_command(self, client, mock_scheduler):
        mock_scheduler._notifier = MagicMock()
        response = client.post(
            "/telegram-webhook",
            json={
                "message": {
                    "chat": {"id": 123456, "username": "testuser"},
                    "text": "/start",
                }
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data.get("registered") == "123456"

    def test_telegram_webhook_other_message(self, client, mock_scheduler):
        response = client.post(
            "/telegram-webhook",
            json={
                "message": {
                    "chat": {"id": 123456},
                    "text": "hello",
                }
            },
        )
        assert response.status_code == 200
        assert response.json()["ok"] is True

    def test_telegram_webhook_no_scheduler(self):
        import main

        main._scheduler_instance = None
        client = TestClient(main.app)
        response = client.post("/telegram-webhook", json={})
        assert response.status_code == 200


class TestFrontendRoutes:
    """Tests for frontend serving routes."""

    def test_root_serves_html(self, client):
        response = client.get("/")
        # May 404 if static file doesn't exist in test env, but should not error
        assert response.status_code in (200, 404)

    def test_smart_home_casita_route(self, client):
        response = client.get("/smart-home/casita")
        assert response.status_code in (200, 404)



# ═══════════════════════════════════════════════════════════════════════════════
# Additional tests for main.py bootstrap and helpers
# ═══════════════════════════════════════════════════════════════════════════════


class TestConfigValidation:
    """Tests for configuration validation."""

    def test_validate_config_missing_token(self, monkeypatch):
        """Test that missing TELEGRAM_BOT_TOKEN is detected."""
        import main as main_module

        monkeypatch.setattr(main_module, "TELEGRAM_BOT_TOKEN", "")
        monkeypatch.setattr(main_module, "TELEGRAM_CHAT_ID", "123")
        monkeypatch.setattr(main_module, "APIFY_API_TOKEN", "apify_token")
        monkeypatch.setattr(main_module, "GMAIL_ADDRESS", "test@gmail.com")

        with pytest.raises(SystemExit):
            main_module._validate_config()

    def test_validate_config_missing_apify(self, monkeypatch):
        """Test that missing APIFY_API_TOKEN is detected."""
        import main as main_module

        monkeypatch.setattr(main_module, "TELEGRAM_BOT_TOKEN", "bot_token")
        monkeypatch.setattr(main_module, "TELEGRAM_CHAT_ID", "123")
        monkeypatch.setattr(main_module, "APIFY_API_TOKEN", "")
        monkeypatch.setattr(main_module, "GMAIL_ADDRESS", "test@gmail.com")

        with pytest.raises(SystemExit):
            main_module._validate_config()

    def test_validate_config_missing_gmail(self, monkeypatch):
        """Test that missing GMAIL_ADDRESS is detected."""
        import main as main_module

        monkeypatch.setattr(main_module, "TELEGRAM_BOT_TOKEN", "bot_token")
        monkeypatch.setattr(main_module, "TELEGRAM_CHAT_ID", "123")
        monkeypatch.setattr(main_module, "APIFY_API_TOKEN", "apify_token")
        monkeypatch.setattr(main_module, "GMAIL_ADDRESS", "")

        with pytest.raises(SystemExit):
            main_module._validate_config()

    def test_validate_config_warning_no_gmail_password(self, monkeypatch, caplog):
        """Test warning when GMAIL_APP_PASSWORD is missing."""
        import main as main_module
        import logging

        monkeypatch.setattr(main_module, "TELEGRAM_BOT_TOKEN", "bot_token")
        monkeypatch.setattr(main_module, "TELEGRAM_CHAT_ID", "123")
        monkeypatch.setattr(main_module, "APIFY_API_TOKEN", "apify_token")
        monkeypatch.setattr(main_module, "GMAIL_ADDRESS", "test@gmail.com")
        monkeypatch.setattr(main_module, "GMAIL_APP_PASSWORD", "")

        with caplog.at_level(logging.WARNING):
            main_module._validate_config()

        # Should log a warning about missing password
        assert any("GMAIL_APP_PASSWORD" in record.message for record in caplog.records)


class TestProcessNaming:
    """Tests for process naming."""

    def test_set_process_name_fallback(self, monkeypatch):
        """Test process name setting with fallback."""
        import main as main_module
        import sys

        # Mock setproctitle import to fail
        def mock_import_error(*args):
            raise ImportError("No module named setproctitle")

        monkeypatch.setattr("builtins.__import__", mock_import_error)

        # Should not raise, uses fallback
        old_argv = sys.argv[:]
        sys.argv = ["test_script.py"]

        try:
            main_module._set_process_name()
            # After fallback, argv[0] should be the process name
            assert sys.argv[0] == "casita-orquestador"
        finally:
            sys.argv = old_argv


class TestExceptionHandler:
    """Tests for global exception handler."""

    def test_global_exception_handler_registered(self, client, mock_scheduler):
        """Test that exception handler is registered."""
        import main

        # Verify handler is registered
        assert Exception in main.app.exception_handlers
