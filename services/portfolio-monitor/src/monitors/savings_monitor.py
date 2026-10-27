"""
Portfolio Monitor — Savings Account Monitor.
Tracks interest from remunerada/deposit accounts.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

import config
from models import AlertLevel, SavingsAnalysis

from . import BaseMonitor, register_monitor

logger: logging.Logger = logging.getLogger(__name__)

# Divisor to convert percentage (e.g., 5.0 for 5%) to decimal (0.05)
PERCENT_DIVISOR: float = 100.0

# Max length for account_id to prevent memory issues
_ACCOUNT_ID_MAX_LENGTH: int = 50


def _sanitize_account_id(account_id: str | None) -> str:
    """Sanitize an account_id for safe use in logs and storage.

    Args:
        account_id: Raw account identifier from configuration.

    Returns:
        Sanitized account_id with invalid characters removed and
        length bounded to 50 chars. Returns "unknown" if empty.
    """
    if not account_id:
        return "unknown"

    # Remove any characters that aren't alphanumeric, dash, or underscore
    safe_id = re.sub(r"[^\w\-]", "", str(account_id))

    # Truncate to max length if needed
    if len(safe_id) > _ACCOUNT_ID_MAX_LENGTH:
        safe_id = safe_id[:_ACCOUNT_ID_MAX_LENGTH]

    # Return "unknown" if sanitization removed everything
    if not safe_id:
        return "unknown"

    return safe_id


def calculate_interest(balance: float, apy: float) -> tuple[float, float]:
    """Calculate monthly and yearly interest from account balance and APY.

    Args:
        balance: Account balance in EUR.
        apy: Annual Percentage Yield as a percentage (e.g., 5.0 for 5%).

    Returns:
        A tuple of (monthly_interest, yearly_interest) in EUR.
        Uses simple interest calculation (non-compounding).
    """
    yearly = balance * (apy / PERCENT_DIVISOR)
    monthly = yearly / 12
    return monthly, yearly


def days_until_next_payment(payment_day: int = 25) -> int:
    """Calculate the number of days until the next interest payment.

    Args:
        payment_day: Day of month when interest is paid (1-31). If the day
            exceeds the number of days in a given month, the last day of
            that month is used.

    Returns:
        Number of days until the next payment date. Returns 0 if today is
        the payment day.
    """
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

    name: str = "savings"

    def __init__(self) -> None:
        self._last_update: datetime | None = None
        self._level: AlertLevel = AlertLevel.OK
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
            raw_account_id: str = account.get("id", "")
            account_id = _sanitize_account_id(raw_account_id)
            logger.info("  → Processing %s...", account_id)

            try:
                balance: float = account.get("balance", 0)
                apy: float = account.get("apy", 0)
                monthly, yearly = calculate_interest(balance, apy)
                payment_day: int = account.get("payment_day", 25)
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

            except (ValueError, TypeError, KeyError, AttributeError) as e:
                logger.error("Error processing %s: %s", account_id, e)
                continue

        self._results = results
        self._last_update = datetime.now(timezone.utc)

        logger.info("Savings monitor complete. %d accounts processed.", len(results))

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
