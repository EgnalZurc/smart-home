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
        """Should escape square brackets."""
        from notifier import _escape_md
        
        assert _escape_md("[link]") == "\\[link\\]"


class TestNewPropertyAlert:
    """Tests for new property alert formatting."""

    def test_format_new_property_alert_structure(self):
        """Should format alert with all sections."""
        from notifier import _format_new_property_alert
        from models import Property, Zone, ScoredProperty, Score, Portal, Piscina
        
        prop = Property(
            unique_id="test_123",
            portal=Portal.IDEALISTA,
            url="https://example.com/property",
            title="Test Property",
            price=250000,
            rooms=3,
            bathrooms=2,
            size_m2=120,
            has_garage=True,
            piscina=Piscina.COMUNITARIA,
        )
        zone = Zone(id="test_zone", name="Test Zone")
        score = Score(
            p3_distance=10,
            p4_beach=8,
            p5_pools=6,
            p6_supermarket=9,
            p7_health=7,
            p8_hospital=5,
            p9_price=8,
            p10_fire=10,
            p11_preference=7,
        )
        scored = ScoredProperty(
            prop=prop,
            zone=zone,
            score=score,
            total_score=70.0,
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
        
        event = PriceEvent(
            property_uid="test_123",
            old_price=300000,
            new_price=280000,
            delta=-20000,
            delta_pct=-6.67,
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
            delta=20000,
            delta_pct=7.14,
        )
        
        result = _format_price_drop_alert(
            event,
            title="Test Property",
            url="https://example.com",
            zone_name="Test Zone"
        )
        
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
