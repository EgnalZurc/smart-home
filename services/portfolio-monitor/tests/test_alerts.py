"""
Tests for the alerts module.
"""

import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

# Mock config before importing alerts
with patch.dict("os.environ", {"DATA_DIR": tempfile.mkdtemp()}):
    import sys

    # Force reimport of config with mocked DATA_DIR
    if "config" in sys.modules:
        del sys.modules["config"]
    if "alerts" in sys.modules:
        del sys.modules["alerts"]


@pytest.fixture
def temp_data_dir(tmp_path):
    """Create a temporary data directory for tests."""
    with patch("alerts.DATA_DIR", tmp_path):
        with patch("alerts.ALERTS_STATE_FILE", tmp_path / "alerts_state.json"):
            yield tmp_path


@pytest.fixture
def sample_alerts_config():
    """Sample alerts configuration."""
    today = datetime.now(timezone.utc).date()
    return [
        {
            "id": "alert-1",
            "date": today.isoformat(),
            "action": "sell_crypto",
            "symbol": "ETH",
            "title": "Review ETH position",
            "description": "Check staking rewards",
            "priority": "high",
        },
        {
            "id": "alert-2",
            "date": (today + timedelta(days=3)).isoformat(),
            "action": "review",
            "symbol": "BTC",
            "title": "BTC review",
            "description": "Monthly review",
            "priority": "medium",
        },
        {
            "id": "alert-3",
            "date": (today - timedelta(days=2)).isoformat(),
            "action": "modify_etf",
            "symbol": "VWCE",
            "title": "Overdue alert",
            "description": "This is overdue",
            "priority": "low",
        },
        {
            "id": "alert-4",
            "date": (today + timedelta(days=10)).isoformat(),
            "action": "review",
            "symbol": "SPY",
            "title": "Future alert",
            "description": "Too far in the future",
            "priority": "low",
        },
    ]


class TestAlertsStateManagement:
    """Tests for alerts state persistence."""

    def test_load_empty_state(self, temp_data_dir):
        """Loading state when file doesn't exist returns empty dict."""
        from alerts import _load_alerts_state

        state = _load_alerts_state()
        assert state == {}

    def test_save_and_load_state(self, temp_data_dir):
        """State can be saved and loaded."""
        from alerts import _load_alerts_state, _save_alerts_state

        state = {
            "alert-1": {"triggered": True, "completed": False},
            "alert-2": {"triggered": False, "completed": True},
        }
        _save_alerts_state(state)

        loaded = _load_alerts_state()
        assert loaded == state

    def test_load_corrupted_state(self, temp_data_dir):
        """Loading corrupted state returns empty dict."""
        from alerts import _load_alerts_state

        # Write invalid JSON
        state_file = temp_data_dir / "alerts_state.json"
        state_file.write_text("not valid json {{{")

        with patch("alerts.ALERTS_STATE_FILE", state_file):
            state = _load_alerts_state()
        assert state == {}


class TestGetAlerts:
    """Tests for alert retrieval functions."""

    def test_get_all_alerts(self, temp_data_dir, sample_alerts_config):
        """Get all configured alerts."""
        from alerts import get_all_alerts

        with patch("config.SCHEDULED_ALERTS", sample_alerts_config):
            alerts = get_all_alerts()

        assert len(alerts) == 4
        assert alerts[0].alert_id == "alert-1"
        assert alerts[0].action == "sell_crypto"
        assert alerts[0].symbol == "ETH"

    def test_get_all_alerts_with_state(self, temp_data_dir, sample_alerts_config):
        """Alerts include persisted state."""
        from alerts import _save_alerts_state, get_all_alerts

        # Save some state
        _save_alerts_state(
            {
                "alert-1": {"triggered": True, "completed": False},
            }
        )

        with patch("config.SCHEDULED_ALERTS", sample_alerts_config):
            alerts = get_all_alerts()

        alert_1 = next(a for a in alerts if a.alert_id == "alert-1")
        assert alert_1.triggered is True
        assert alert_1.completed is False

    def test_get_upcoming_alerts(self, temp_data_dir, sample_alerts_config):
        """Get alerts within next N days."""
        from alerts import get_upcoming_alerts

        with patch("config.SCHEDULED_ALERTS", sample_alerts_config):
            # Default 5 days should include alert-1, alert-2, alert-3 (overdue)
            # but not alert-4 (10 days away)
            upcoming = get_upcoming_alerts(days=5)

        ids = [a.alert_id for a in upcoming]
        assert "alert-1" in ids  # today
        assert "alert-2" in ids  # 3 days
        assert "alert-3" in ids  # overdue
        assert "alert-4" not in ids  # 10 days

    def test_get_upcoming_alerts_excludes_completed(
        self, temp_data_dir, sample_alerts_config
    ):
        """Completed alerts are excluded from upcoming."""
        from alerts import _save_alerts_state, get_upcoming_alerts

        _save_alerts_state({"alert-1": {"completed": True}})

        with patch("config.SCHEDULED_ALERTS", sample_alerts_config):
            upcoming = get_upcoming_alerts(days=5)

        ids = [a.alert_id for a in upcoming]
        assert "alert-1" not in ids

    def test_get_alerts_due(self, temp_data_dir, sample_alerts_config):
        """Get alerts due today or overdue."""
        from alerts import get_alerts_due

        with patch("config.SCHEDULED_ALERTS", sample_alerts_config):
            due = get_alerts_due(include_overdue=True)

        ids = [a.alert_id for a in due]
        assert "alert-1" in ids  # today
        assert "alert-3" in ids  # overdue
        assert "alert-2" not in ids  # future
        assert "alert-4" not in ids  # future

    def test_get_alerts_due_excludes_triggered(
        self, temp_data_dir, sample_alerts_config
    ):
        """Already triggered alerts are excluded."""
        from alerts import _save_alerts_state, get_alerts_due

        _save_alerts_state({"alert-1": {"triggered": True}})

        with patch("config.SCHEDULED_ALERTS", sample_alerts_config):
            due = get_alerts_due()

        ids = [a.alert_id for a in due]
        assert "alert-1" not in ids


class TestMarkAlerts:
    """Tests for marking alerts as triggered/completed."""

    def test_mark_alert_triggered(self, temp_data_dir, sample_alerts_config):
        """Mark an alert as triggered."""
        from alerts import _load_alerts_state, mark_alert_triggered

        result = mark_alert_triggered("alert-1")
        assert result is True

        state = _load_alerts_state()
        assert state["alert-1"]["triggered"] is True
        assert "triggered_at" in state["alert-1"]

    def test_mark_alert_completed_today(self, temp_data_dir, sample_alerts_config):
        """Can complete an alert due today."""
        from alerts import _load_alerts_state, mark_alert_completed

        with patch("config.SCHEDULED_ALERTS", sample_alerts_config):
            result = mark_alert_completed("alert-1")

        assert result is True
        state = _load_alerts_state()
        assert state["alert-1"]["completed"] is True

    def test_mark_alert_completed_overdue(self, temp_data_dir, sample_alerts_config):
        """Can complete an overdue alert."""
        from alerts import mark_alert_completed

        with patch("config.SCHEDULED_ALERTS", sample_alerts_config):
            result = mark_alert_completed("alert-3")

        assert result is True

    def test_cannot_complete_future_alert(self, temp_data_dir, sample_alerts_config):
        """Cannot complete an alert that hasn't arrived."""
        from alerts import mark_alert_completed

        with patch("config.SCHEDULED_ALERTS", sample_alerts_config):
            result = mark_alert_completed("alert-4")

        assert result is False

    def test_cannot_complete_nonexistent_alert(self, temp_data_dir):
        """Cannot complete an alert that doesn't exist."""
        from alerts import mark_alert_completed

        with patch("config.SCHEDULED_ALERTS", []):
            result = mark_alert_completed("nonexistent")

        assert result is False


class TestCheckAndTriggerAlerts:
    """Tests for the alert notification trigger."""

    def test_trigger_due_alerts(self, temp_data_dir, sample_alerts_config):
        """Due alerts are sent to notifier."""
        from alerts import check_and_trigger_alerts

        mock_notifier = MagicMock()
        mock_notifier.send_scheduled_alert.return_value = MagicMock(success=True)

        with patch("config.SCHEDULED_ALERTS", sample_alerts_config):
            triggered = check_and_trigger_alerts(mock_notifier)

        # Should trigger alert-1 (today) and alert-3 (overdue)
        assert len(triggered) == 2
        assert mock_notifier.send_scheduled_alert.call_count == 2

    def test_no_alerts_due(self, temp_data_dir):
        """No notifications when no alerts are due."""
        from datetime import timedelta

        from alerts import check_and_trigger_alerts

        future_date = (
            datetime.now(timezone.utc).date() + timedelta(days=5)
        ).isoformat()
        config = [
            {
                "id": "future-alert",
                "date": future_date,
                "action": "review",
                "symbol": "TEST",
                "title": "Future",
                "description": "Not due",
                "priority": "low",
            }
        ]

        mock_notifier = MagicMock()

        with patch("config.SCHEDULED_ALERTS", config):
            triggered = check_and_trigger_alerts(mock_notifier)

        assert len(triggered) == 0
        mock_notifier.send_scheduled_alert.assert_not_called()

    def test_notification_failure_doesnt_mark_triggered(
        self, temp_data_dir, sample_alerts_config
    ):
        """Failed notification doesn't mark alert as triggered."""
        from alerts import _load_alerts_state, check_and_trigger_alerts

        mock_notifier = MagicMock()
        mock_notifier.send_scheduled_alert.return_value = MagicMock(success=False)

        with patch("config.SCHEDULED_ALERTS", sample_alerts_config):
            triggered = check_and_trigger_alerts(mock_notifier)

        assert len(triggered) == 0
        state = _load_alerts_state()
        assert "alert-1" not in state or not state.get("alert-1", {}).get("triggered")


class TestSerializeAlert:
    """Tests for alert serialization."""

    def test_serialize_alert_today(self, temp_data_dir, sample_alerts_config):
        """Serialize an alert due today."""
        from alerts import get_all_alerts, serialize_alert

        with patch("config.SCHEDULED_ALERTS", sample_alerts_config):
            alerts = get_all_alerts()

        alert = next(a for a in alerts if a.alert_id == "alert-1")
        serialized = serialize_alert(alert)

        assert serialized["id"] == "alert-1"
        assert serialized["days_until"] == 0
        assert serialized["is_actionable"] is True

    def test_serialize_alert_future(self, temp_data_dir, sample_alerts_config):
        """Serialize a future alert."""
        from alerts import get_all_alerts, serialize_alert

        with patch("config.SCHEDULED_ALERTS", sample_alerts_config):
            alerts = get_all_alerts()

        alert = next(a for a in alerts if a.alert_id == "alert-2")
        serialized = serialize_alert(alert)

        assert serialized["id"] == "alert-2"
        assert serialized["days_until"] == 3
        assert serialized["is_actionable"] is False

    def test_serialize_alert_overdue(self, temp_data_dir, sample_alerts_config):
        """Serialize an overdue alert."""
        from alerts import get_all_alerts, serialize_alert

        with patch("config.SCHEDULED_ALERTS", sample_alerts_config):
            alerts = get_all_alerts()

        alert = next(a for a in alerts if a.alert_id == "alert-3")
        serialized = serialize_alert(alert)

        assert serialized["id"] == "alert-3"
        assert serialized["days_until"] == -2
        assert serialized["is_actionable"] is True
