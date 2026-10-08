"""
Portfolio Monitor — Savings Account Monitor.
Tracks interest from remunerada/deposit accounts.
"""

import logging
from datetime import datetime, timezone
from typing import Any

import config
from models import AlertLevel, SavingsAnalysis

from . import BaseMonitor, register_monitor

logger = logging.getLogger(__name__)


def calculate_interest(balance: float, apy: float) -> tuple[float, float]:
    """Calculate monthly and yearly interest."""
    yearly = balance * (apy / 100)
    monthly = yearly / 12
    return monthly, yearly


def days_until_next_payment(payment_day: int = 25) -> int:
    """Return days until next interest payment (default: day 25 of month)."""
    today = datetime.now(timezone.utc).date()

    # This month's payment day
    try:
        this_month_payment = today.replace(day=payment_day)
    except ValueError:
        # If payment_day > days in month, use last day
        import calendar

        last_day = calendar.monthrange(today.year, today.month)[1]
        this_month_payment = today.replace(day=min(payment_day, last_day))

    if today <= this_month_payment:
        return (this_month_payment - today).days

    # Next month's payment day
    if today.month == 12:
        next_month = today.replace(year=today.year + 1, month=1, day=1)
    else:
        next_month = today.replace(month=today.month + 1, day=1)

    try:
        next_payment = next_month.replace(day=payment_day)
    except ValueError:
        import calendar

        last_day = calendar.monthrange(next_month.year, next_month.month)[1]
        next_payment = next_month.replace(day=min(payment_day, last_day))

    return (next_payment - today).days


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

        accounts = config.get_savings_accounts()
        if not accounts:
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

        for account in accounts:
            account_id = account.get("id", "")
            logger.info(f"  → Processing {account_id}...")

            try:
                balance = account.get("balance", 0)
                apy = account.get("apy", 0)
                monthly, yearly = calculate_interest(balance, apy)
                payment_day = account.get("payment_day", 25)
                days_to_payment = days_until_next_payment(payment_day)

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
                    days_until_payment=days_to_payment,
                    payment_day=payment_day,
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
