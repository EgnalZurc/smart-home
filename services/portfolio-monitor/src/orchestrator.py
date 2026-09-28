"""
Portfolio Monitor — Monitor Orchestrator.
Manages scheduled execution of monitors and maintains state.
Sends Telegram alerts when WARN or DANGER signals are detected.
"""

import asyncio
import json
import logging
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any

from config import DATA_DIR, SCHEDULE, reload_config
from models import AlertLevel, MonitorState, PortfolioSummary
from notifier import TelegramNotifier

logger = logging.getLogger(__name__)

# State file path
STATE_FILE = DATA_DIR / "state.json"


class Orchestrator:
    """Orchestrates the execution of portfolio monitors."""
    
    def __init__(self):
        self._state = MonitorState()
        self._summary = PortfolioSummary()
        self._monitors: dict[str, Any] = {}
        self._notifier = TelegramNotifier()
        self._running = False
        self._scheduler_task: asyncio.Task | None = None
        self._load_state()
    
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
        """Persist state to disk."""
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(STATE_FILE, "w") as f:
                json.dump(self._state.to_dict(), f, indent=2)
        except Exception as e:
            logger.error(f"Could not save state: {e}")
    
    async def _init_monitors(self):
        """Initialize monitor instances."""
        # Import monitors (they auto-register via decorator)
        from monitors.crypto_monitor import CryptoMonitor
        from monitors.etf_monitor import ETFMonitor
        
        self._monitors = {
            "etf": ETFMonitor(),
            "crypto": CryptoMonitor(),
        }
        logger.info(f"Initialized {len(self._monitors)} monitors: {list(self._monitors.keys())}")
    
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
                self._summary.etf_total_gain_loss_pct = result.get("total_gain_loss_pct", 0)
                self._summary.etf_analysis = result.get("analysis", [])
                self._summary.etf_level = result.get("level", AlertLevel.OK)
                self._summary.phase = result.get("phase", "")
                self._summary.phase_months_remaining = result.get("phase_months_remaining")
                self._summary.etf_last_update = result.get("last_update")
            elif name == "crypto":
                self._state.last_crypto_run = datetime.now(timezone.utc)
                self._summary.crypto_total_value = result.get("total_value", 0)
                self._summary.crypto_total_daily_gain = result.get("total_daily_gain", 0)
                self._summary.crypto_analysis = result.get("analysis", [])
                self._summary.crypto_level = result.get("level", AlertLevel.OK)
                self._summary.crypto_fear_greed = result.get("fear_greed")
                self._summary.crypto_fear_greed_label = result.get("fear_greed_label")
                self._summary.crypto_last_update = result.get("last_update")
            
            self._save_state()
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
        
        # Send Telegram alert if there are WARN or DANGER signals
        await self._send_alerts_if_needed()
        
        return results
    
    async def _send_alerts_if_needed(self):
        """Send Telegram alerts if there are warnings or dangers."""
        # Calculate overall level
        overall_level = AlertLevel.OK
        if self._summary.etf_level:
            overall_level = overall_level.escalate(self._summary.etf_level)
        if self._summary.crypto_level:
            overall_level = overall_level.escalate(self._summary.crypto_level)
        
        if overall_level not in (AlertLevel.WARN, AlertLevel.DANGER):
            logger.info("No alerts to send — portfolio status is OK")
            return
        
        # Send summary alert
        result = self._notifier.send_summary_alert(
            etf_results=self._summary.etf_analysis or [],
            crypto_results=self._summary.crypto_analysis or [],
            overall_level=overall_level,
            fear_greed=self._summary.crypto_fear_greed,
        )
        
        if result.success:
            logger.info(f"Alert sent to Telegram: {result.message}")
        else:
            logger.error(f"Failed to send Telegram alert: {result.message}")
    
    def get_summary(self) -> PortfolioSummary:
        """Get the current portfolio summary."""
        return self._summary
    
    def get_state(self) -> MonitorState:
        """Get the current state."""
        return self._state
    
    def get_schedule(self) -> dict[str, str]:
        """Get the monitoring schedule."""
        return SCHEDULE.copy()
    
    def get_next_run_times(self) -> dict[str, datetime | None]:
        """Calculate next scheduled run times for each monitor."""
        now = datetime.now(timezone.utc)
        today = now.date()
        
        result = {}
        
        for monitor_name in ["etf", "crypto"]:
            time_str = SCHEDULE.get(f"{monitor_name}_time", "00:00")
            hour, minute = map(int, time_str.split(":"))
            scheduled_time = time(hour, minute)
            
            # Calculate next run
            next_run = datetime.combine(today, scheduled_time, tzinfo=timezone.utc)
            if next_run <= now:
                # Already passed today, schedule for tomorrow
                next_run = datetime.combine(
                    today.replace(day=today.day + 1), 
                    scheduled_time, 
                    tzinfo=timezone.utc
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
                            logger.error(f"Scheduled run failed for {monitor_name}: {e}")
                
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
        
        self._save_state()
        logger.info("Orchestrator stopped")
    
    def reload_config(self):
        """Reload configuration from disk."""
        reload_config()
        logger.info("Configuration reloaded")


# Singleton instance
_orchestrator: Orchestrator | None = None


def get_orchestrator() -> Orchestrator:
    """Get the orchestrator singleton."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = Orchestrator()
    return _orchestrator
