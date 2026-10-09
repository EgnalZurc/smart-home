"""
Portfolio Monitor — Monitor Orchestrator.
Manages scheduled execution of monitors and maintains state.
Sends email alerts when WARN or DANGER signals are detected.

Supports dependency injection for testing.
"""

import asyncio
import json
import logging
from datetime import datetime, time, timedelta, timezone
from typing import Any, Protocol

import config
from config import DATA_DIR, reload_config
from models import AlertLevel, MonitorState, PortfolioSummary
from smart_home_common.persistence import atomic_write_json

logger = logging.getLogger(__name__)

# State file path
STATE_FILE = DATA_DIR / "state.json"


# ─────────────────────────────────────────────────────────────────────────────
# Protocols for dependency injection
# ─────────────────────────────────────────────────────────────────────────────
class NotifierProtocol(Protocol):
    """Protocol for email notifier - allows dependency injection."""

    @property
    def enabled(self) -> bool: ...

    def send_summary_alert(
        self,
        etf_results: list,
        crypto_results: list,
        overall_level: AlertLevel,
        fear_greed: int | None = None,
        savings_results: list | None = None,
    ) -> Any: ...

    def send_scheduled_alert(self, alert: Any) -> Any: ...


class MonitorProtocol(Protocol):
    """Protocol for monitors - allows dependency injection."""

    name: str

    async def run(self) -> dict[str, Any]: ...


# ─────────────────────────────────────────────────────────────────────────────
# Orchestrator
# ─────────────────────────────────────────────────────────────────────────────
class Orchestrator:
    """Orchestrates the execution of portfolio monitors."""

    def __init__(
        self,
        notifier: NotifierProtocol | None = None,
        monitors: dict[str, MonitorProtocol] | None = None,
    ):
        """
        Initialize the orchestrator.

        Args:
            notifier: Email notifier instance. If None, creates EmailNotifier.
            monitors: Dict of monitor instances. If None, creates them on start().
        """
        self._state = MonitorState()
        self._summary = PortfolioSummary()
        self._monitors: dict[str, Any] = monitors or {}
        self._notifier = notifier
        self._running = False
        self._scheduler_task: asyncio.Task | None = None
        self._load_state()

    def _get_notifier(self) -> NotifierProtocol:
        """Get notifier, creating lazily if needed."""
        if self._notifier is None:
            from email_notifier import EmailNotifier

            self._notifier = EmailNotifier()
        return self._notifier

    def _load_state(self):
        """Load persisted state from disk."""
        try:
            if STATE_FILE.exists():
                with open(STATE_FILE) as f:
                    data = json.load(f)
                    self._state = MonitorState.from_dict(data)
                logger.info("Loaded state from disk")
        except Exception as e:
            logger.warning(f"Could not load state: {e}")

    def _save_state(self):
        """Persist state to disk (synchronous).

        Uses atomic_write_json so a crash mid-write cannot leave a truncated
        state.json: it writes to a temp file in the same directory and renames
        it over the target. Any error is logged and swallowed so a failed save
        never crashes the orchestrator.
        """
        try:
            atomic_write_json(STATE_FILE, self._state.to_dict())
        except Exception as e:
            logger.error(f"Could not save state: {e}")

    async def _save_state_async(self):
        """Persist state without blocking the event loop.

        _save_state does synchronous file I/O; when called from an async code
        path we offload it to a worker thread so the event loop stays free.
        """
        await asyncio.to_thread(self._save_state)

    async def _init_monitors(self):
        """Initialize monitor instances if not injected."""
        if self._monitors:
            logger.info(f"Using {len(self._monitors)} injected monitors")
            return

        from monitors.crypto_monitor import CryptoMonitor
        from monitors.etf_monitor import ETFMonitor
        from monitors.savings_monitor import SavingsMonitor

        self._monitors = {
            "etf": ETFMonitor(),
            "crypto": CryptoMonitor(),
            "savings": SavingsMonitor(),
        }
        logger.info(
            f"Initialized {len(self._monitors)} monitors: {list(self._monitors.keys())}"
        )

    async def run_monitor(self, name: str) -> dict[str, Any]:
        """Run a specific monitor."""
        if name not in self._monitors:
            raise ValueError(f"Unknown monitor: {name}")

        logger.info(f"Running monitor: {name}")
        monitor = self._monitors[name]

        try:
            result = await monitor.run()

            # Update state
            if name == "etf":
                self._state.last_etf_run = datetime.now(timezone.utc)
                self._summary.etf_total_value = result.get("total_value", 0)
                self._summary.etf_total_invested = result.get("total_invested", 0)
                self._summary.etf_total_gain_loss = result.get("total_gain_loss", 0)
                self._summary.etf_total_gain_loss_pct = result.get(
                    "total_gain_loss_pct", 0
                )
                self._summary.etf_analysis = result.get("analysis", [])
                self._summary.etf_level = result.get("level", AlertLevel.OK)
                self._summary.phase = result.get("phase", "")
                self._summary.phase_months_remaining = result.get(
                    "phase_months_remaining"
                )
                self._summary.etf_last_update = result.get("last_update")
            elif name == "crypto":
                self._state.last_crypto_run = datetime.now(timezone.utc)
                self._summary.crypto_total_value = result.get("total_value", 0)
                self._summary.crypto_total_daily_gain = result.get(
                    "total_daily_gain", 0
                )
                self._summary.crypto_analysis = result.get("analysis", [])
                self._summary.crypto_level = result.get("level", AlertLevel.OK)
                self._summary.crypto_fear_greed = result.get("fear_greed")
                self._summary.crypto_fear_greed_label = result.get("fear_greed_label")
                self._summary.crypto_last_update = result.get("last_update")
            elif name == "savings":
                self._summary.savings_total_balance = result.get("total_balance", 0)
                self._summary.savings_yearly_interest = result.get("yearly_interest", 0)
                self._summary.savings_analysis = result.get("analysis", [])
                self._summary.savings_last_update = result.get("last_update")

            await self._save_state_async()
            logger.info(f"Monitor {name} completed successfully")

            return result

        except Exception as e:
            logger.error(f"Monitor {name} failed: {e}")
            raise

    async def run_all_monitors(self) -> dict[str, Any]:
        """Run all registered monitors and send alerts if needed."""
        results = {}

        for name in self._monitors:
            try:
                results[name] = await self.run_monitor(name)
            except Exception as e:
                logger.error(f"Failed to run {name}: {e}")
                results[name] = {"error": str(e)}

        # Load upcoming alerts
        self._load_upcoming_alerts()

        # Check and send scheduled alerts due today
        self._check_scheduled_alerts()

        # Send email alert if there are WARN or DANGER signals
        await self._send_alerts_if_needed()

        return results

    def _load_upcoming_alerts(self):
        """Load alerts scheduled in the next 5 days (includes overdue)."""
        from alerts import get_upcoming_alerts

        self._summary.upcoming_alerts = get_upcoming_alerts(days=5)
        overdue = [a for a in self._summary.upcoming_alerts if not a.completed]
        logger.info(
            f"Loaded {len(self._summary.upcoming_alerts)} alerts "
            f"({len([a for a in overdue if a.date <= datetime.now(timezone.utc).date().isoformat()])} overdue/due)"
        )

    def _check_scheduled_alerts(self):
        """Check for alerts due today (or overdue) and send notifications."""
        from alerts import check_and_trigger_alerts

        triggered = check_and_trigger_alerts(self._get_notifier())
        if triggered:
            logger.info(f"Sent notifications for {len(triggered)} scheduled alerts")

    async def _send_alerts_if_needed(self):
        """
        Send email alerts for market conditions (ETF/Crypto).

        Only sends if there are actual WARN or DANGER signals.
        """
        # Calculate overall level from actual market signals
        overall_level = AlertLevel.OK
        if self._summary.etf_level:
            overall_level = overall_level.escalate(self._summary.etf_level)
        if self._summary.crypto_level:
            overall_level = overall_level.escalate(self._summary.crypto_level)

        # Only send if there are actual market warnings
        if overall_level not in (AlertLevel.WARN, AlertLevel.DANGER):
            logger.info(
                f"No market alerts to send — ETF: {self._summary.etf_level}, "
                f"Crypto: {self._summary.crypto_level}, Overall: OK"
            )
            return

        # Count actual WARN/DANGER positions
        etf_alerts = [
            e
            for e in (self._summary.etf_analysis or [])
            if e.level in (AlertLevel.WARN, AlertLevel.DANGER)
        ]
        crypto_alerts = [
            c
            for c in (self._summary.crypto_analysis or [])
            if c.level in (AlertLevel.WARN, AlertLevel.DANGER)
        ]

        if not etf_alerts and not crypto_alerts:
            logger.info(
                "Overall level is elevated but no individual positions have warnings"
            )
            return

        logger.info(
            f"Sending market alert — {len(etf_alerts)} ETF alerts, "
            f"{len(crypto_alerts)} crypto alerts"
        )

        # Send summary alert
        notifier = self._get_notifier()
        result = notifier.send_summary_alert(
            etf_results=self._summary.etf_analysis or [],
            crypto_results=self._summary.crypto_analysis or [],
            overall_level=overall_level,
            fear_greed=self._summary.crypto_fear_greed,
            savings_results=self._summary.savings_analysis or [],
        )

        if result.success:
            logger.info(f"Market alert email sent: {result.message}")
        else:
            logger.error(f"Failed to send market alert email: {result.message}")

    def get_summary(self) -> PortfolioSummary:
        """Get the current portfolio summary."""
        return self._summary

    def get_state(self) -> MonitorState:
        """Get the current state."""
        return self._state

    def get_schedule(self) -> dict[str, str]:
        """Get the monitoring schedule."""
        return config.get_schedule().copy()

    def get_next_run_times(self) -> dict[str, datetime | None]:
        """Calculate next scheduled run times for each monitor."""
        now = datetime.now(timezone.utc)
        today = now.date()

        result = {}

        schedule = config.get_schedule()
        for monitor_name in ["etf", "crypto"]:
            time_str = schedule.get(f"{monitor_name}_time", "00:00")
            hour, minute = map(int, time_str.split(":"))
            scheduled_time = time(hour, minute)

            # Calculate next run
            next_run = datetime.combine(today, scheduled_time, tzinfo=timezone.utc)
            if next_run <= now:
                tomorrow = today + timedelta(days=1)
                next_run = datetime.combine(
                    tomorrow,
                    scheduled_time,
                    tzinfo=timezone.utc,
                )

            result[monitor_name] = next_run

        return result

    async def _schedule_loop(self):
        """Background task that runs monitors on schedule."""
        logger.info("Starting scheduler loop")

        while self._running:
            try:
                now = datetime.now(timezone.utc)
                next_runs = self.get_next_run_times()

                # Check if any monitor should run now (within 1 minute tolerance)
                for monitor_name, next_run in next_runs.items():
                    if next_run and abs((next_run - now).total_seconds()) < 60:
                        logger.info(f"Scheduled run for {monitor_name}")
                        try:
                            await self.run_monitor(monitor_name)
                        except Exception as e:
                            logger.error(
                                f"Scheduled run failed for {monitor_name}: {e}"
                            )

                # Sleep for 1 minute
                await asyncio.sleep(60)

            except asyncio.CancelledError:
                logger.info("Scheduler loop cancelled")
                break
            except Exception as e:
                logger.error(f"Scheduler error: {e}")
                await asyncio.sleep(60)

    async def start(self):
        """Start the orchestrator and scheduler."""
        if self._running:
            return

        self._running = True
        await self._init_monitors()

        # Run all monitors immediately on startup if no previous data
        if not self._summary.etf_analysis and not self._summary.crypto_analysis:
            logger.info("No previous data — running initial monitor refresh...")
            try:
                await self.run_all_monitors()
            except Exception as e:
                logger.error(f"Initial monitor run failed: {e}")

        # Start scheduler in background
        self._scheduler_task = asyncio.create_task(self._schedule_loop())

        logger.info("Orchestrator started")

    async def stop(self):
        """Stop the orchestrator."""
        self._running = False

        if self._scheduler_task:
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass

        await self._save_state_async()
        logger.info("Orchestrator stopped")

    def reload_config(self):
        """Reload configuration from disk."""
        reload_config()
        logger.info("Configuration reloaded")


# ─────────────────────────────────────────────────────────────────────────────
# Singleton instance (with factory for dependency injection in tests)
# ─────────────────────────────────────────────────────────────────────────────
_orchestrator: Orchestrator | None = None


def get_orchestrator() -> Orchestrator:
    """Get the orchestrator singleton."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = Orchestrator()
    return _orchestrator


def set_orchestrator(orch: Orchestrator) -> None:
    """Set the orchestrator instance (for testing)."""
    global _orchestrator
    _orchestrator = orch


def reset_orchestrator() -> None:
    """Reset the orchestrator singleton (for testing)."""
    global _orchestrator
    _orchestrator = None
