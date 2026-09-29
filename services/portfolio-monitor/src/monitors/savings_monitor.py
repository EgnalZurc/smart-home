"""
Portfolio Monitor — Savings Account Monitor.
Tracks interest from remunerada/deposit accounts.
"""

import logging
from datetime import datetime, timezone
from typing import Any

from config import SAVINGS_ACCOUNTS
from models import AlertLevel, SavingsAnalysis

from . import BaseMonitor, register_monitor

logger = logging.getLogger(__name__)


def calculate_interest(balance: float, apy: float) -> tuple[float, float]:
    """Calculate monthly and yearly interest."""
    yearly = balance * (apy / 100)
    monthly = yearly / 12
    return monthly, yearly


def days_since_start(start_date: str) -> int:
    """Return days since account was opened."""
    try:
        start = datetime.fromisoformat(start_date).date()
        today = datetime.now(timezone.utc).date()
        return (today - start).days
    except (ValueError, TypeError):
        return 0


@register_monitor
class SavingsMonitor(BaseMonitor):
    """Savings account monitor."""

    name = "savings"

    def __init__(self):
        self._last_update: datetime | None = None
        self._level = AlertLevel.OK
        self._results: list[SavingsAnalysis] = []

    async def run(self) -> dict[str, Any]:
        """Execute the savings monitor."""
        logger.info("Starting savings monitor...")

        if not SAVINGS_ACCOUNTS:
            logger.info("No savings accounts configured.")
            return {
                "analysis": [],
                "total_balance": 0,
                "yearly_interest": 0,
                "level": AlertLevel.OK,
                "last_update": None,
            }

        results: list[SavingsAnalysis] = []
        total_balance = 0.0
        total_yearly = 0.0

        for account in SAVINGS_ACCOUNTS:
            account_id = account.get("id", "")
            logger.info(f"  → Processing {account_id}...")

            try:
                balance = account.get("balance", 0)
                apy = account.get("apy", 0)
                monthly, yearly = calculate_interest(balance, apy)
                days = days_since_start(account.get("start_date", ""))

                # Estimate accumulated interest (simplified)
                accumulated = (yearly / 365) * days

                analysis = SavingsAnalysis(
                    account_id=account_id,
                    name=account.get("name", account_id),
                    bank=account.get("bank", ""),
                    balance=balance,
                    apy=apy,
                    account_type=account.get("type", "remunerada"),
                    start_date=account.get("start_date", ""),
                    monthly_interest=monthly,
                    yearly_interest=yearly,
                    days_active=days,
                    accumulated_interest=accumulated,
                    level=AlertLevel.OK,
                )

                results.append(analysis)
                total_balance += balance
                total_yearly += yearly

            except Exception as e:
                logger.error(f"Error processing {account_id}: {e}")
                continue

        self._results = results
        self._last_update = datetime.now(timezone.utc)

        logger.info(f"Savings monitor complete. {len(results)} accounts processed.")

        return {
            "analysis": results,
            "total_balance": total_balance,
            "yearly_interest": total_yearly,
            "level": AlertLevel.OK,
            "last_update": self._last_update,
        }

    def get_level(self) -> AlertLevel:
        return self._level

    def get_last_update(self) -> datetime | None:
        return self._last_update

    def get_results(self) -> list[SavingsAnalysis]:
        return self._results
