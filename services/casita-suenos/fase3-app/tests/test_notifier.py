"""Unit tests for Telegram notifier module."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

# Skip all tests in this module if telegram is not installed
telegram = pytest.importorskip("telegram")


class TestScoreEmoji:
    """Tests for score emoji mapping."""

    def test_trophy_for_high_score(self):
        """Scores 70-84 should get trophy emoji."""
        from notifier import _score_emoji
        
        assert _score_emoji(75) == "🏆"
        assert _score_emoji(84) == "🏆"

    def test_three_stars_for_good_score(self):
        """Scores 60-69 should get three stars."""
        from notifier import _score_emoji
        
        assert _score_emoji(65) == "⭐⭐⭐"

    def test_two_stars_for_ok_score(self):
        """Scores 55-59 should get two stars."""
        from notifier import _score_emoji
        
        assert _score_emoji(57) == "⭐⭐"

    def test_one_star_for_low_score(self):
        """Scores 50-54 should get one star."""
        from notifier import _score_emoji
        
        assert _score_emoji(52) == "⭐"

    def test_empty_for_very_low_score(self):
        """Scores below 50 should get no emoji."""
        from notifier import _score_emoji
        
        assert _score_emoji(45) == ""


class TestPriceFormatting:
    """Tests for price formatting."""

    def test_format_price_with_thousands(self):
        """Should format price with dots as thousands separator."""
        from notifier import _format_price
        
        assert _format_price(250000) == "250.000€"
        assert _format_price(1500000) == "1.500.000€"

    def test_format_price_small_number(self):
        """Should handle small prices."""
        from notifier import _format_price
        
        assert _format_price(500) == "500€"


class TestMarkdownEscaping:
    """Tests for Markdown escaping."""

    def test_escape_asterisks(self):
        """Should escape asterisks."""
        from notifier import _escape_md
        
        assert _escape_md("*bold*") == "\\*bold\\*"

    def test_escape_underscores(self):
        """Should escape underscores."""
        from notifier import _escape_md
        
        assert _escape_md("_italic_") == "\\_italic\\_"

    def test_escape_backticks(self):
        """Should escape backticks."""
        from notifier import _escape_md
        
        assert _escape_md("`code`") == "\\`code\\`"

    def test_escape_brackets(self):
        """Should escape opening square brackets (for MarkdownV2 safety)."""
        from notifier import _escape_md
        
        # Only opening brackets are escaped per the implementation
        assert _escape_md("[link]") == "\\[link]"


class TestNewPropertyAlert:
    """Tests for new property alert formatting."""

    def test_format_new_property_alert_structure(self):
        """Should format alert with all sections."""
        from notifier import _format_new_property_alert
        from models import (
            Property, Zone, ScoredProperty, ScoreBreakdown, Portal, Piscina,
            GarageType, Habitability, Internet, FireRisk
        )
        
        prop = Property(
            portal=Portal.IDEALISTA,
            portal_id="test_123",
            url="https://example.com/property",
            zone_id="test_zone",
            title="Test Property",
            price=250000,
            rooms=3,
            size_m2=120,
            has_garden_or_plot=True,
            terrain_m2=500,
            garage_type=GarageType.EDIFICIO,
            piscina=Piscina.COMUNITARIA,
            habitability=Habitability.BUENO,
            internet=Internet.FIBRA,
            has_garage=True,
        )
        zone = Zone(
            id="test_zone",
            name="Test Zone",
            distance_madrid_min=180,
            distance_beach_min=30,
            distance_natural_pools_min=60,
            distance_supermarket_min=5,
            distance_health_center_min=10,
            distance_hospital_min=20,
            fire_risk=FireRisk.BAJO,
            price_min=100000,
            price_max=300000,
        )
        score = ScoreBreakdown(
            r1_rooms=10,
            r2_terrain=8,
            r3_garage=10,
            r4_habitability=7,
            r5_piscina=6,
            r6_ac=0,
            r7_price=8,
            r8_supermarket=9,
            r9_health=7,
            r10_hospital=5,
            r11_internet=10,
            r12_madrid=0,
            r13_beach=8,
            r14_pools=6,
            r15_fire=10,
            r16_flood=10,
            r17_coast=10,
            r18_beach_plot=10,
        )
        scored = ScoredProperty(
            prop=prop,
            zone=zone,
            score=score,
        )
        
        result = _format_new_property_alert(scored)
        
        assert "Nueva vivienda" in result
        assert "Test Zone" in result
        assert "250.000€" in result
        assert "3 hab." in result
        assert "120 m²" in result
        assert "garaje" in result
        assert "piscina comunitaria" in result
        assert "example.com" in result


class TestPriceDropAlert:
    """Tests for price drop alert formatting."""

    def test_format_price_drop(self):
        """Should format price drop alert correctly."""
        from notifier import _format_price_drop_alert
        from models import PriceEvent
        
        # PriceEvent calculates delta and delta_pct as properties
        event = PriceEvent(
            property_uid="test_123",
            old_price=300000,
            new_price=280000,
        )
        
        result = _format_price_drop_alert(
            event,
            title="Test Property",
            url="https://example.com",
            zone_name="Test Zone"
        )
        
        assert "Bajada de precio" in result
        assert "300.000€" in result
        assert "280.000€" in result
        assert "-20.000€" in result

    def test_format_price_increase(self):
        """Should format price increase alert."""
        from notifier import _format_price_drop_alert
        from models import PriceEvent
        
        event = PriceEvent(
            property_uid="test_123",
            old_price=280000,
            new_price=300000,
        )
        
        result = _format_price_drop_alert(
            event,
            title="Test Property",
            url="https://example.com",
            zone_name="Test Zone"
        )
        
        assert "Subida de precio" in result
        
        assert "Subida de precio" in result


class TestWeeklySummary:
    """Tests for weekly summary formatting."""

    def test_format_empty_summary(self):
        """Should handle empty properties list."""
        from notifier import _format_weekly_summary
        
        result = _format_weekly_summary([])
        
        assert "Resumen semanal" in result
        assert "Sin propiedades destacadas" in result

    def test_format_summary_with_properties(self):
        """Should format summary with top properties."""
        from notifier import _format_weekly_summary
        
        properties = [
            {
                "price": 250000,
                "score_total": 72.5,
                "rooms": 3,
                "size_m2": 120,
                "zone_id": "test_zone",
                "url": "https://example.com/1"
            },
            {
                "price": 200000,
                "score_total": 68.0,
                "rooms": 2,
                "size_m2": 90,
                "zone_id": "another_zone",
                "url": "https://example.com/2"
            }
        ]
        
        result = _format_weekly_summary(properties)
        
        assert "Resumen semanal" in result
        assert "72.5pts" in result
        assert "250.000€" in result
        assert "test zone" in result


class TestTelegramNotifier:
    """Tests for TelegramNotifier class."""

    def test_get_chat_ids_from_db(self):
        """Should get chat IDs from database."""
        from notifier import TelegramNotifier
        
        mock_db = Mock()
        mock_db.get_telegram_chat_ids.return_value = ["123", "456"]
        
        with patch('notifier.telegram.Bot'):
            notifier = TelegramNotifier("token", "fallback", db=mock_db)
            chat_ids = notifier._get_chat_ids()
        
        assert chat_ids == ["123", "456"]

    def test_get_chat_ids_fallback(self):
        """Should fallback to env chat ID when DB empty."""
        from notifier import TelegramNotifier
        
        mock_db = Mock()
        mock_db.get_telegram_chat_ids.return_value = []
        
        with patch('notifier.telegram.Bot'):
            notifier = TelegramNotifier("token", "fallback_123", db=mock_db)
            chat_ids = notifier._get_chat_ids()
        
        assert chat_ids == ["fallback_123"]

    def test_get_chat_ids_no_db(self):
        """Should use fallback when no DB configured."""
        from notifier import TelegramNotifier
        
        with patch('notifier.telegram.Bot'):
            notifier = TelegramNotifier("token", "fallback_456", db=None)
            chat_ids = notifier._get_chat_ids()
        
        assert chat_ids == ["fallback_456"]



# ═══════════════════════════════════════════════════════════════════════════════
# Additional notifier tests for coverage
# ═══════════════════════════════════════════════════════════════════════════════


class TestSendMethods:
    """Tests for TelegramNotifier send methods."""

    def test_send_without_chat_ids(self):
        """Test that send fails gracefully without chat IDs."""
        from notifier import TelegramNotifier
        from unittest.mock import MagicMock

        # Create notifier with mock bot
        notifier = TelegramNotifier.__new__(TelegramNotifier)
        notifier._bot = MagicMock()
        notifier._bot.token = "fake_token"
        notifier._fallback_chat_id = ""
        notifier._db = None

        # Should return False when no chat IDs
        result = notifier.send_status("test message")
        assert result is False

    def test_send_status_format(self, monkeypatch):
        """Test that send_status adds info emoji."""
        from notifier import TelegramNotifier
        from unittest.mock import MagicMock, patch

        sent_texts = []

        def mock_post(*args, **kwargs):
            sent_texts.append(kwargs.get("json", {}).get("text", ""))
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"ok": True}
            return mock_resp

        # Create notifier with mock
        notifier = TelegramNotifier.__new__(TelegramNotifier)
        notifier._bot = MagicMock()
        notifier._bot.token = "fake_token"
        notifier._fallback_chat_id = "123456"
        notifier._db = None

        with patch("httpx.post", mock_post):
            notifier.send_status("Test message")

        assert len(sent_texts) == 1
        assert "ℹ️" in sent_texts[0]
        assert "Test message" in sent_texts[0]


class TestFormattingHelpers:
    """Tests for formatting helper functions."""

    def test_escape_md_brackets(self):
        """Test markdown escaping for brackets."""
        from notifier import _escape_md

        result = _escape_md("text [with] brackets")
        assert "\\[" in result
        assert "\\]" not in result  # only [ is escaped in current impl

    def test_escape_md_combined(self):
        """Test markdown escaping with multiple special chars."""
        from notifier import _escape_md

        result = _escape_md("*bold* _italic_ `code`")
        assert "\\*" in result
        assert "\\_" in result
        assert "\\`" in result


class TestWeeklySummaryFormatting:
    """Tests for weekly summary formatting."""

    def test_format_weekly_summary_with_rooms_and_size(self):
        """Test summary includes rooms and size when available."""
        from notifier import _format_weekly_summary

        props = [
            {
                "price": 150000,
                "score_total": 130.5,
                "rooms": 4,
                "size_m2": 120.0,
                "zone_id": "zamora_meseta",
                "url": "https://example.com/1",
            }
        ]
        result = _format_weekly_summary(props)

        assert "150.000€" in result
        assert "130.5pts" in result
        assert "4 hab." in result
        assert "120m²" in result

    def test_format_weekly_summary_missing_details(self):
        """Test summary handles missing rooms/size."""
        from notifier import _format_weekly_summary

        props = [
            {
                "price": 100000,
                "score_total": 120.0,
                "rooms": None,
                "size_m2": None,
                "zone_id": "test_zone",
                "url": "https://example.com/2",
            }
        ]
        result = _format_weekly_summary(props)

        assert "100.000€" in result
        assert "120.0pts" in result


class TestPriceDropFormatting:
    """Tests for price drop alert formatting."""

    def test_format_price_drop_shows_difference(self):
        """Test price drop shows the delta."""
        from notifier import _format_price_drop_alert
        from models import PriceEvent
        from datetime import datetime

        event = PriceEvent(
            property_uid="test:123",
            old_price=200000,
            new_price=180000,
            detected_at=datetime.now(),
        )

        result = _format_price_drop_alert(event, "Test Casa", "https://example.com", "Zamora")

        assert "📉" in result
        assert "200.000€" in result
        assert "180.000€" in result
        assert "-20.000€" in result or "-20000€" in result

    def test_format_price_increase(self):
        """Test price increase shows upward arrow."""
        from notifier import _format_price_drop_alert
        from models import PriceEvent
        from datetime import datetime

        event = PriceEvent(
            property_uid="test:123",
            old_price=180000,
            new_price=200000,
            detected_at=datetime.now(),
        )

        result = _format_price_drop_alert(event, "Test Casa", "https://example.com", "Zamora")

        assert "📈" in result
