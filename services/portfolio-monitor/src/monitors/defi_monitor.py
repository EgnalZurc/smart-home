"""
Portfolio Monitor — DeFi Yield Monitor.

Tracks DeFi (decentralised finance) positions whose yield is entered MANUALLY.
Unlike the ETF/crypto monitors, this one makes NO external API calls: the user
records the deposited ``amount`` and the advertised ``apy_pct`` for each
position, and the monitor projects the expected daily/monthly/yearly yield from
those static inputs.

The ``amount`` is treated as the position's estimated value in the portfolio's
base currency (EUR): DeFi deposits are commonly stablecoins or LP positions the
user already values in fiat, so there is no price lookup to perform.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import config
from models import AlertLevel, DeFiAnalysis

from . import BaseMonitor, register_monitor, sanitize_id

logger: logging.Logger = logging.getLogger(__name__)

# Divisor to convert percentage (e.g., 5.0 for 5%) to decimal (0.05)
PERCENT_DIVISOR: float = 100.0

# Max length for position_id
_POSITION_ID_MAX_LENGTH: int = 100


def _sanitize_position_id(protocol: str, asset: str) -> str:
    """Generate and sanitize a position_id from protocol and asset.

    Args:
        protocol: DeFi protocol name (e.g., "Aave", "Compound").
        asset: Asset symbol (e.g., "USDC", "ETH").

    Returns:
        Sanitized position_id in format "protocol:asset", with invalid
        characters removed and length bounded to 100 chars.
    """
    safe_protocol = sanitize_id(protocol, max_length=50)
    safe_asset = sanitize_id(asset, max_length=49)

    position_id = f"{safe_protocol}:{safe_asset}"

    # Truncate to max length if needed (already bounded per component)
    if len(position_id) > _POSITION_ID_MAX_LENGTH:
        position_id = position_id[:_POSITION_ID_MAX_LENGTH]

    return position_id


def calculate_yield(amount: float, apy_pct: float) -> tuple[float, float, float]:
    """Project yield from a deposited amount and an annual percentage yield.

    Args:
        amount: Deposited value in the portfolio base currency (EUR).
        apy_pct: Advertised annual percentage yield (e.g., 5.0 for 5%).

    Returns:
        A (daily, monthly, yearly) tuple of projected yield amounts in EUR.
        Uses simple (non-compounding) projection: the APY expresses the
        annual return, so monthly = yearly / 12 and daily = yearly / 365.
    """
    yearly = amount * (apy_pct / PERCENT_DIVISOR)
    monthly = yearly / 12
    daily = yearly / 365
    return daily, monthly, yearly


@register_monitor
class DeFiMonitor(BaseMonitor):
    """DeFi yield monitor (manual APY, no external APIs)."""

    name: str = "defi"

    def __init__(self) -> None:
        self._last_update: datetime | None = None
        self._level: AlertLevel = AlertLevel.OK
        self._results: list[DeFiAnalysis] = []

    async def run(self) -> dict[str, Any]:
        """Execute the DeFi monitor."""
        logger.info("Starting DeFi monitor...")

        positions = config.get_defi_positions()
        if not positions:
            logger.info("No DeFi positions configured.")
            return {
                "analysis": [],
                "total_value": 0,
                "yearly_yield": 0,
                "level": AlertLevel.OK,
                "last_update": None,
            }

        results: list[DeFiAnalysis] = []
        total_value = 0.0
        total_yearly = 0.0

        for position in positions:
            protocol: str = position.get("protocol", "")
            asset: str = position.get("asset", "")
            position_id = _sanitize_position_id(protocol, asset)
            logger.info("  → Processing %s...", position_id)

            try:
                amount = float(position.get("amount", 0) or 0)
                apy_pct = float(position.get("apy_pct", 0) or 0)
                daily, monthly, yearly = calculate_yield(amount, apy_pct)

                analysis = DeFiAnalysis(
                    position_id=position_id,
                    protocol=protocol,
                    asset=asset,
                    amount=amount,
                    apy_pct=apy_pct,
                    platform_url=position.get("platform_url", ""),
                    estimated_value=amount,
                    daily_yield=daily,
                    monthly_yield=monthly,
                    yearly_yield=yearly,
                    level=AlertLevel.OK,
                )

                results.append(analysis)
                total_value += amount
                total_yearly += yearly

            except (ValueError, TypeError, KeyError, AttributeError) as e:
                logger.error("Error processing %s: %s", position_id, e)
                continue

        self._results = results
        self._last_update = datetime.now(timezone.utc)

        logger.info("DeFi monitor complete. %d positions processed.", len(results))

        return {
            "analysis": results,
            "total_value": total_value,
            "yearly_yield": total_yearly,
            "level": AlertLevel.OK,
            "last_update": self._last_update,
        }

    def get_level(self) -> AlertLevel:
        return self._level

    def get_last_update(self) -> datetime | None:
        return self._last_update

    def get_results(self) -> list[DeFiAnalysis]:
        return self._results
