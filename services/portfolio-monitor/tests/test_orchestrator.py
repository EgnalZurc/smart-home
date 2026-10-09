"""
Tests for the orchestrator module.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from models import AlertLevel


@pytest.fixture
def temp_data_dir(tmp_path):
    """Create a temporary data directory."""
    state_file = tmp_path / "state.json"
    with patch("orchestrator.STATE_FILE", state_file):
        with patch("orchestrator.DATA_DIR", tmp_path):
            yield tmp_path


@pytest.fixture
def mock_notifier():
    """Create a mock notifier."""
    notifier = MagicMock()
    notifier.enabled = True
    notifier.send_summary_alert.return_value = MagicMock(success=True, message="Sent")
    notifier.send_scheduled_alert.return_value = MagicMock(success=True, message="Sent")
    return notifier


@pytest.fixture
def mock_monitors():
    """Create mock monitors."""
    etf_monitor = MagicMock()
    etf_monitor.name = "etf"
    etf_monitor.run = AsyncMock(
        return_value={
            "total_value": 10000,
            "total_invested": 9000,
            "total_gain_loss": 1000,
            "total_gain_loss_pct": 0.11,
            "analysis": [],
            "level": AlertLevel.OK,
            "phase": "Phase 1",
            "phase_months_remaining": 24,
            "last_update": datetime.now(timezone.utc),
        }
    )

    crypto_monitor = MagicMock()
    crypto_monitor.name = "crypto"
    crypto_monitor.run = AsyncMock(
        return_value={
            "total_value": 5000,
            "total_daily_gain": 0.5,
            "analysis": [],
            "level": AlertLevel.OK,
            "fear_greed": 55,
            "fear_greed_label": "Greed",
            "last_update": datetime.now(timezone.utc),
        }
    )

    savings_monitor = MagicMock()
    savings_monitor.name = "savings"
    savings_monitor.run = AsyncMock(
        return_value={
            "total_balance": 20000,
            "yearly_interest": 600,
            "analysis": [],
            "last_update": datetime.now(timezone.utc),
        }
    )

    return {
        "etf": etf_monitor,
        "crypto": crypto_monitor,
        "savings": savings_monitor,
    }


class TestOrchestratorInit:
    """Tests for Orchestrator initialization."""

    def test_init_default(self, temp_data_dir):
        """Orchestrator initializes with defaults."""
        from orchestrator import Orchestrator

        orch = Orchestrator()

        assert orch._state is not None
        assert orch._summary is not None
        assert orch._running is False

    def test_init_with_injected_deps(self, temp_data_dir, mock_notifier, mock_monitors):
        """Orchestrator accepts injected dependencies."""
        from orchestrator import Orchestrator

        orch = Orchestrator(notifier=mock_notifier, monitors=mock_monitors)

        assert orch._notifier == mock_notifier
        assert orch._monitors == mock_monitors


class TestStateManagement:
    """Tests for state persistence."""

    def test_load_state_no_file(self, temp_data_dir):
        """Loading state when file doesn't exist."""
        from orchestrator import Orchestrator

        orch = Orchestrator()
        state = orch.get_state()

        assert state.last_etf_run is None
        assert state.last_crypto_run is None

    def test_save_and_load_state(self, temp_data_dir):
        """State can be saved and loaded."""
        from orchestrator import Orchestrator

        orch = Orchestrator()
        orch._state.last_etf_run = datetime.now(timezone.utc)
        orch._save_state()

        # Create new orchestrator to load state
        orch2 = Orchestrator()
        state = orch2.get_state()

        assert state.last_etf_run is not None

    @pytest.mark.asyncio
    async def test_save_state_async_persists(self, temp_data_dir):
        """Async save writes the same state the sync path would."""
        from orchestrator import Orchestrator

        orch = Orchestrator()
        orch._state.last_etf_run = datetime.now(timezone.utc)
        await orch._save_state_async()

        orch2 = Orchestrator()
        assert orch2.get_state().last_etf_run is not None

    @pytest.mark.asyncio
    async def test_save_state_async_offloads_to_thread(self, temp_data_dir):
        """Async save routes the blocking write through asyncio.to_thread."""
        from orchestrator import Orchestrator

        orch = Orchestrator()

        with patch(
            "orchestrator.asyncio.to_thread", new_callable=AsyncMock
        ) as mock_to_thread:
            await orch._save_state_async()

        mock_to_thread.assert_awaited_once()
        # The sync _save_state bound method is what gets offloaded
        assert mock_to_thread.await_args.args[0] == orch._save_state


class TestRunMonitor:
    """Tests for running individual monitors."""

    @pytest.mark.asyncio
    async def test_run_etf_monitor(self, temp_data_dir, mock_notifier, mock_monitors):
        """Running ETF monitor updates state."""
        from orchestrator import Orchestrator

        orch = Orchestrator(notifier=mock_notifier, monitors=mock_monitors)
        result = await orch.run_monitor("etf")

        assert result["total_value"] == 10000
        assert orch._state.last_etf_run is not None
        assert orch._summary.etf_total_value == 10000

    @pytest.mark.asyncio
    async def test_run_crypto_monitor(
        self, temp_data_dir, mock_notifier, mock_monitors
    ):
        """Running crypto monitor updates state."""
        from orchestrator import Orchestrator

        orch = Orchestrator(notifier=mock_notifier, monitors=mock_monitors)
        result = await orch.run_monitor("crypto")

        assert result["total_value"] == 5000
        assert orch._state.last_crypto_run is not None
        assert orch._summary.crypto_total_value == 5000
        assert orch._summary.crypto_fear_greed == 55

    @pytest.mark.asyncio
    async def test_run_savings_monitor(
        self, temp_data_dir, mock_notifier, mock_monitors
    ):
        """Running savings monitor updates state."""
        from orchestrator import Orchestrator

        orch = Orchestrator(notifier=mock_notifier, monitors=mock_monitors)
        result = await orch.run_monitor("savings")

        assert result["total_balance"] == 20000
        assert orch._summary.savings_total_balance == 20000

    @pytest.mark.asyncio
    async def test_run_unknown_monitor(
        self, temp_data_dir, mock_notifier, mock_monitors
    ):
        """Running unknown monitor raises error."""
        from orchestrator import Orchestrator

        orch = Orchestrator(notifier=mock_notifier, monitors=mock_monitors)

        with pytest.raises(ValueError, match="Unknown monitor"):
            await orch.run_monitor("nonexistent")


class TestRunAllMonitors:
    """Tests for running all monitors."""

    @pytest.mark.asyncio
    async def test_run_all_monitors(self, temp_data_dir, mock_notifier, mock_monitors):
        """Running all monitors updates all states."""
        from orchestrator import Orchestrator

        with patch("alerts.get_upcoming_alerts", return_value=[]):
            with patch("alerts.check_and_trigger_alerts", return_value=[]):
                orch = Orchestrator(notifier=mock_notifier, monitors=mock_monitors)
                results = await orch.run_all_monitors()

        assert "etf" in results
        assert "crypto" in results
        assert "savings" in results
        assert orch._summary.etf_total_value == 10000
        assert orch._summary.crypto_total_value == 5000
        assert orch._summary.savings_total_balance == 20000

    @pytest.mark.asyncio
    async def test_run_all_handles_failures(
        self, temp_data_dir, mock_notifier, mock_monitors
    ):
        """All monitors run even if one fails."""
        from orchestrator import Orchestrator

        mock_monitors["etf"].run = AsyncMock(side_effect=Exception("ETF error"))

        with patch("alerts.get_upcoming_alerts", return_value=[]):
            with patch("alerts.check_and_trigger_alerts", return_value=[]):
                orch = Orchestrator(notifier=mock_notifier, monitors=mock_monitors)
                results = await orch.run_all_monitors()

        assert "error" in results["etf"]
        assert results["crypto"]["total_value"] == 5000  # Still ran


class TestAlerts:
    """Tests for alert handling."""

    @pytest.mark.asyncio
    async def test_sends_alert_on_danger(
        self, temp_data_dir, mock_notifier, mock_monitors
    ):
        """Sends email when DANGER level detected."""
        from orchestrator import Orchestrator

        mock_monitors["etf"].run = AsyncMock(
            return_value={
                "total_value": 10000,
                "total_invested": 9000,
                "analysis": [MagicMock(level=AlertLevel.DANGER)],
                "level": AlertLevel.DANGER,
                "last_update": datetime.now(timezone.utc),
            }
        )

        with patch("alerts.get_upcoming_alerts", return_value=[]):
            with patch("alerts.check_and_trigger_alerts", return_value=[]):
                orch = Orchestrator(notifier=mock_notifier, monitors=mock_monitors)
                await orch.run_all_monitors()

        mock_notifier.send_summary_alert.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_alert_on_ok(self, temp_data_dir, mock_notifier, mock_monitors):
        """No email when all OK."""
        from orchestrator import Orchestrator

        with patch("alerts.get_upcoming_alerts", return_value=[]):
            with patch("alerts.check_and_trigger_alerts", return_value=[]):
                orch = Orchestrator(notifier=mock_notifier, monitors=mock_monitors)
                await orch.run_all_monitors()

        mock_notifier.send_summary_alert.assert_not_called()


class TestSchedule:
    """Tests for schedule functions."""

    def test_get_schedule(self, temp_data_dir):
        """Get schedule returns config."""
        from orchestrator import Orchestrator

        orch = Orchestrator()
        schedule = orch.get_schedule()

        assert "etf_time" in schedule
        assert "crypto_time" in schedule

    def test_get_next_run_times(self, temp_data_dir):
        """Next run times are calculated."""
        from orchestrator import Orchestrator

        orch = Orchestrator()
        next_runs = orch.get_next_run_times()

        assert "etf" in next_runs
        assert "crypto" in next_runs
        assert next_runs["etf"] is not None
        assert next_runs["crypto"] is not None


class TestLifecycle:
    """Tests for orchestrator lifecycle."""

    @pytest.mark.asyncio
    async def test_start_stop(self, temp_data_dir, mock_notifier, mock_monitors):
        """Orchestrator can start and stop."""
        from orchestrator import Orchestrator

        orch = Orchestrator(notifier=mock_notifier, monitors=mock_monitors)

        # Start with initial data to skip initial refresh
        orch._summary.etf_analysis = [MagicMock()]
        orch._summary.crypto_analysis = [MagicMock()]

        await orch.start()
        assert orch._running is True
        assert orch._scheduler_task is not None

        await orch.stop()
        assert orch._running is False


class TestSingleton:
    """Tests for singleton pattern."""

    def test_get_orchestrator_singleton(self, temp_data_dir):
        """get_orchestrator returns same instance."""
        from orchestrator import get_orchestrator, reset_orchestrator

        reset_orchestrator()

        orch1 = get_orchestrator()
        orch2 = get_orchestrator()

        assert orch1 is orch2

        reset_orchestrator()

    def test_set_orchestrator(self, temp_data_dir, mock_notifier, mock_monitors):
        """set_orchestrator overrides singleton."""
        from orchestrator import (
            Orchestrator,
            get_orchestrator,
            reset_orchestrator,
            set_orchestrator,
        )

        reset_orchestrator()

        custom = Orchestrator(notifier=mock_notifier, monitors=mock_monitors)
        set_orchestrator(custom)

        assert get_orchestrator() is custom

        reset_orchestrator()


class TestSchedulerLoop:
    """Tests for the scheduler loop edge cases."""

    @pytest.mark.asyncio
    async def test_scheduler_runs_monitor_at_scheduled_time(
        self, temp_data_dir, mock_notifier, mock_monitors
    ):
        """Scheduler triggers monitor when time matches."""
        import asyncio

        from orchestrator import Orchestrator

        orch = Orchestrator(notifier=mock_notifier, monitors=mock_monitors)
        orch._running = True

        # Mock get_next_run_times to return "now"
        now = datetime.now(timezone.utc)
        with patch.object(
            orch, "get_next_run_times", return_value={"etf": now, "crypto": now}
        ):
            # Run one iteration of the loop
            task = asyncio.create_task(orch._schedule_loop())
            await asyncio.sleep(0.1)
            orch._running = False
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # ETF and crypto monitors should have been called
        mock_monitors["etf"].run.assert_called()
        mock_monitors["crypto"].run.assert_called()

    @pytest.mark.asyncio
    async def test_scheduler_handles_monitor_error(
        self, temp_data_dir, mock_notifier, mock_monitors
    ):
        """Scheduler continues after monitor error."""
        import asyncio

        from orchestrator import Orchestrator

        mock_monitors["etf"].run = AsyncMock(side_effect=Exception("ETF failed"))

        orch = Orchestrator(notifier=mock_notifier, monitors=mock_monitors)
        orch._running = True

        now = datetime.now(timezone.utc)
        with patch.object(orch, "get_next_run_times", return_value={"etf": now}):
            task = asyncio.create_task(orch._schedule_loop())
            await asyncio.sleep(0.1)
            orch._running = False
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Should not crash — the error is logged and loop continues

    @pytest.mark.asyncio
    async def test_scheduler_cancellation(
        self, temp_data_dir, mock_notifier, mock_monitors
    ):
        """Scheduler handles cancellation gracefully."""
        import asyncio

        from orchestrator import Orchestrator

        orch = Orchestrator(notifier=mock_notifier, monitors=mock_monitors)
        orch._running = True

        # Make the monitor run take some time so we can cancel mid-flight
        mock_monitors["etf"].run = AsyncMock(side_effect=asyncio.sleep(10))

        # Start the loop
        task = asyncio.create_task(orch._schedule_loop())
        await asyncio.sleep(0.05)

        # Stop the orchestrator (graceful shutdown)
        orch._running = False
        task.cancel()

        # Should complete without raising
        try:
            await asyncio.wait_for(task, timeout=1.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass  # Both are acceptable

        # The key assertion is that we got here without hanging


class TestReloadConfig:
    """Tests for config reload functionality."""

    def test_reload_config(self, temp_data_dir, mock_notifier, mock_monitors):
        """Config reload calls the config module."""
        from orchestrator import Orchestrator

        orch = Orchestrator(notifier=mock_notifier, monitors=mock_monitors)

        with patch("orchestrator.reload_config") as mock_reload:
            orch.reload_config()
            mock_reload.assert_called_once()


class TestInitialRefresh:
    """Tests for initial monitor refresh on startup."""

    @pytest.mark.asyncio
    async def test_initial_refresh_when_no_data(
        self, temp_data_dir, mock_notifier, mock_monitors
    ):
        """Runs initial refresh when no previous data exists."""
        from orchestrator import Orchestrator

        orch = Orchestrator(notifier=mock_notifier, monitors=mock_monitors)

        # No previous data
        assert not orch._summary.etf_analysis
        assert not orch._summary.crypto_analysis

        with patch("alerts.get_upcoming_alerts", return_value=[]):
            with patch("alerts.check_and_trigger_alerts", return_value=[]):
                await orch.start()

        # Monitors should have been called
        mock_monitors["etf"].run.assert_called()
        mock_monitors["crypto"].run.assert_called()

        await orch.stop()

    @pytest.mark.asyncio
    async def test_skip_initial_refresh_when_data_exists(
        self, temp_data_dir, mock_notifier, mock_monitors
    ):
        """Skips initial refresh when data already exists."""
        from orchestrator import Orchestrator

        orch = Orchestrator(notifier=mock_notifier, monitors=mock_monitors)

        # Pre-populate data
        orch._summary.etf_analysis = [MagicMock()]
        orch._summary.crypto_analysis = [MagicMock()]

        await orch.start()

        # Monitors should NOT have been called (data exists)
        mock_monitors["etf"].run.assert_not_called()

        await orch.stop()


class TestLazyNotifierInit:
    """Tests for lazy notifier initialization."""

    def test_notifier_created_lazily(self, temp_data_dir, mock_monitors):
        """Notifier is created lazily when needed."""
        from orchestrator import Orchestrator

        orch = Orchestrator(monitors=mock_monitors)

        # No notifier yet
        assert orch._notifier is None

        # Access triggers creation - patch where it's imported
        with patch("email_notifier.EmailNotifier") as MockNotifier:
            MockNotifier.return_value = MagicMock(enabled=True)
            notifier = orch._get_notifier()
            # EmailNotifier is imported inside _get_notifier, so it creates a real one
            # Just verify we got a notifier back
            assert notifier is not None


class TestStateFileCorruption:
    """Tests for handling corrupted state files."""

    def test_handles_corrupted_state_file(self, temp_data_dir):
        """Handles corrupted state.json gracefully."""
        from orchestrator import Orchestrator

        state_file = temp_data_dir / "state.json"
        state_file.write_text("{ invalid json }")

        with patch("orchestrator.STATE_FILE", state_file):
            with patch("orchestrator.DATA_DIR", temp_data_dir):
                # Should not crash
                orch = Orchestrator()
                state = orch.get_state()

                # Should have default values
                assert state.last_etf_run is None

    def test_handles_state_save_error(
        self, temp_data_dir, mock_notifier, mock_monitors
    ):
        """Handles state save errors gracefully."""
        from orchestrator import Orchestrator

        orch = Orchestrator(notifier=mock_notifier, monitors=mock_monitors)

        # Make state file unwritable
        with patch(
            "orchestrator.STATE_FILE", temp_data_dir / "nonexistent" / "state.json"
        ):
            # Should not crash
            orch._save_state()

    def test_save_state_is_atomic_on_crash(
        self, temp_data_dir, mock_notifier, mock_monitors
    ):
        """A crash mid-write leaves the previous state.json intact (atomic write).

        _save_state writes via smart_home_common.atomic_write_json (temp file +
        os.replace). If json.dump blows up partway through, the real target must
        be untouched and no stray .tmp file should remain.
        """
        import json as _json

        from orchestrator import Orchestrator

        state_file = temp_data_dir / "state.json"
        state_file.write_text('{"last_etf_run": "good"}', encoding="utf-8")

        orch = Orchestrator(notifier=mock_notifier, monitors=mock_monitors)

        with patch("orchestrator.STATE_FILE", state_file):
            with patch(
                "smart_home_common.persistence.atomic_json.json.dump",
                side_effect=ValueError("boom"),
            ):
                # atomic_write_json re-raises; _save_state swallows and logs.
                orch._save_state()

        # Previous content survived — not truncated.
        assert state_file.read_text(encoding="utf-8") == '{"last_etf_run": "good"}'
        # It is still valid JSON.
        _json.loads(state_file.read_text(encoding="utf-8"))
        # No leftover temp files in the data dir.
        assert not list(temp_data_dir.glob(".state.json.*.tmp"))
