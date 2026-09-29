"""
Portfolio Monitor — Crypto Staking Monitor.
Fetches data from CoinGecko and tracks staking positions.
"""

import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import requests
from config import CRYPTO_POSITIONS, CRYPTO_THRESHOLDS
from i18n import t
from models import AlertLevel, CryptoAnalysis, Signal

from . import BaseMonitor, register_monitor

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# API Configuration
# ─────────────────────────────────────────────────────────────────────────────
_TIMEOUT = 10
_RETRIES = 4
_BACKOFF = 2.0

# CoinGecko API key (Demo plan: 30 calls/min, 10k/month)
_CG_API_KEY = os.environ.get("COINGECKO_API_KEY", "")

_MARKETS_URL = (
    "https://api.coingecko.com/api/v3/coins/markets"
    "?vs_currency=eur&ids={ids}&price_change_percentage=14d,30d"
)
_OHLC_URL = (
    "https://api.coingecko.com/api/v3/coins/{id}/ohlc?vs_currency=eur&days={days}"
)
_FG_URL = "https://api.alternative.me/fng/?limit=1"


# ─────────────────────────────────────────────────────────────────────────────
# API Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _get(url: str, use_cg_key: bool = True) -> requests.Response:
    """GET with exponential backoff retry on 429/403."""
    headers = {}
    if use_cg_key and _CG_API_KEY and "coingecko.com" in url:
        headers["x-cg-demo-api-key"] = _CG_API_KEY

    delay = _BACKOFF
    for attempt in range(1, _RETRIES + 1):
        r = requests.get(url, headers=headers, timeout=_TIMEOUT)
        if r.status_code in (429, 403):
            logger.debug(
                f"Rate limited ({r.status_code}), retrying in {delay:.0f}s "
                f"(attempt {attempt}/{_RETRIES})"
            )
            time.sleep(delay)
            delay *= 2
            continue
        r.raise_for_status()
        return r
    r.raise_for_status()
    return r


def fetch_market_batch(coingecko_ids: list[str]) -> dict[str, Any]:
    """Fetch price, 24h change, ATH, 14d and 30d changes for all coins."""
    if not coingecko_ids:
        return {}

    ids = ",".join(dict.fromkeys(coingecko_ids))
    try:
        rows = _get(_MARKETS_URL.format(ids=ids)).json()
        return {
            row["id"]: {
                "eur": row.get("current_price", 0),
                "eur_24h_change": row.get("price_change_percentage_24h", 0),
                "market_cap": row.get("market_cap"),
                "ath": row.get("ath"),
                "ath_change_pct": row.get("ath_change_percentage"),
                "price_change_14d": row.get("price_change_percentage_14d_in_currency"),
                "price_change_30d": row.get("price_change_percentage_30d_in_currency"),
            }
            for row in rows
        }
    except Exception as e:
        logger.error(f"Error fetching prices: {e}")
        return {}


def fetch_ohlc(coingecko_id: str, days: int = 30) -> list[list[float]]:
    """Fetch OHLC data for sparkline charts."""
    try:
        return _get(_OHLC_URL.format(id=coingecko_id, days=days)).json()
    except Exception as e:
        logger.error(f"Error fetching OHLC for {coingecko_id}: {e}")
        return []


def fetch_fear_greed() -> tuple[int | None, str | None]:
    """Fetch the current Fear & Greed index value and label."""
    try:
        r = requests.get(_FG_URL, timeout=_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        return int(data["data"][0]["value"]), data["data"][0]["value_classification"]
    except Exception as e:
        logger.error(f"Error fetching Fear & Greed: {e}")
        return None, None


# ─────────────────────────────────────────────────────────────────────────────
# Date helpers
# ─────────────────────────────────────────────────────────────────────────────
def days_until_available(pos: dict[str, Any]) -> int:
    """Return days until the position can be redeemed."""
    today = datetime.now(timezone.utc).date()
    if pos.get("type") == "fixed":
        maturity = datetime.fromisoformat(pos.get("maturity_date", "")).date()
        return max(0, (maturity - today).days)
    return pos.get("rescue_days", 0)


def next_distribution_in(pos: dict[str, Any]) -> int | None:
    """Return days until the next staking reward distribution."""
    if "next_distribution" not in pos:
        return None

    today = datetime.now(timezone.utc).date()
    nd = datetime.fromisoformat(pos["next_distribution"]).date()
    freq = pos.get("distribution_freq_days", 1)

    while nd < today:
        nd += timedelta(days=freq)

    return (nd - today).days


def days_staked(pos: dict[str, Any]) -> int:
    """Return days since staking started."""
    try:
        start = datetime.fromisoformat(pos.get("start_date", "")).date()
        today = datetime.now(timezone.utc).date()
        return (today - start).days
    except (ValueError, TypeError):
        return 0


# ─────────────────────────────────────────────────────────────────────────────
# Signal analysis
# ─────────────────────────────────────────────────────────────────────────────
def compute_signals(
    pos: dict[str, Any],
    price_data: dict[str, Any],
    fear_greed_val: int | None,
) -> tuple[list[Signal], AlertLevel]:
    """Compute signals for a position."""
    signals: list[Signal] = []
    level = AlertLevel.OK

    cg_id = pos.get("coingecko_id", "")
    price_info = price_data.get(cg_id, {})

    change_24h = price_info.get("eur_24h_change", 0)
    ath_pct = price_info.get("ath_change_pct")
    change_30d = price_info.get("price_change_30d")

    thr = CRYPTO_THRESHOLDS

    # Fear & Greed signals
    if fear_greed_val is not None:
        if fear_greed_val >= thr["fg_extreme_greed"]:
            signals.append(
                Signal("", t("crypto.fg_extreme_greed", val=fear_greed_val), "DANGER")
            )
            level = level.escalate(AlertLevel.DANGER)
        elif fear_greed_val >= thr["fg_high_greed"]:
            signals.append(
                Signal("", t("crypto.fg_high_greed", val=fear_greed_val), "WARN")
            )
            level = level.escalate(AlertLevel.WARN)
        elif fear_greed_val <= thr["fg_extreme_fear"]:
            signals.append(
                Signal("", t("crypto.fg_extreme_fear", val=fear_greed_val), "OK")
            )

    # 24h price change signals
    if change_24h is not None:
        if change_24h <= thr["change_24h_danger"]:
            signals.append(
                Signal("", t("crypto.drop_danger", pct=change_24h), "DANGER")
            )
            level = level.escalate(AlertLevel.DANGER)
        elif change_24h <= thr["change_24h_warn"]:
            signals.append(Signal("", t("crypto.drop_warn", pct=change_24h), "WARN"))
            level = level.escalate(AlertLevel.WARN)
        elif change_24h >= thr["change_24h_pump"]:
            # Strong surge is informational, not a warning - could be good news
            signals.append(Signal("", t("crypto.pump_warn", pct=change_24h), "INFO"))

    # ATH proximity signals - informational, not actionable
    # Being near ATH can indicate strong momentum, not necessarily a sell signal
    if ath_pct is not None:
        if ath_pct >= thr["ath_danger_pct"]:
            signals.append(Signal("", t("crypto.ath_danger", pct=abs(ath_pct)), "INFO"))
            # Don't escalate level - ATH proximity is informational
        elif ath_pct >= thr["ath_warn_pct"]:
            signals.append(Signal("", t("crypto.ath_warn", pct=abs(ath_pct)), "INFO"))

    # 30-day momentum signals
    if change_30d is not None:
        if change_30d <= thr["change_30d_bear"]:
            signals.append(Signal("", t("crypto.bear_30d", pct=change_30d), "WARN"))
            level = level.escalate(AlertLevel.WARN)
        elif change_30d >= thr["change_30d_bull"]:
            signals.append(Signal("", t("crypto.bull_30d", pct=change_30d), "OK"))

    return signals, level


# ─────────────────────────────────────────────────────────────────────────────
# Monitor class
# ─────────────────────────────────────────────────────────────────────────────
@register_monitor
class CryptoMonitor(BaseMonitor):
    """Crypto staking monitor."""

    name = "crypto"

    def __init__(self):
        self._last_update: datetime | None = None
        self._level = AlertLevel.OK
        self._results: list[CryptoAnalysis] = []
        self._fear_greed: int | None = None
        self._fear_greed_label: str | None = None

    async def run(self) -> dict[str, Any]:
        """Execute the crypto monitor."""
        logger.info("Starting crypto monitor...")

        if not CRYPTO_POSITIONS:
            logger.info("No crypto positions configured.")
            return {
                "analysis": [],
                "total_value": 0,
                "total_daily_gain": 0,
                "level": AlertLevel.OK,
                "fear_greed": None,
                "fear_greed_label": None,
                "last_update": None,
            }

        # Fetch Fear & Greed
        logger.info("  → Fetching Fear & Greed...")
        self._fear_greed, self._fear_greed_label = fetch_fear_greed()

        # Fetch market data for all positions
        coingecko_ids = [
            p["coingecko_id"] for p in CRYPTO_POSITIONS if "coingecko_id" in p
        ]
        logger.info(f"  → Fetching market data for {len(coingecko_ids)} coins...")
        market_data = fetch_market_batch(coingecko_ids)

        results: list[CryptoAnalysis] = []
        overall_level = AlertLevel.OK
        total_value = 0.0
        total_daily_gain = 0.0

        for pos in CRYPTO_POSITIONS:
            cg_id = pos.get("coingecko_id", "")
            symbol = pos.get("symbol", "")
            logger.info(f"  → Processing {symbol}...")

            try:
                price_info = market_data.get(cg_id, {})
                price_eur = price_info.get("eur", 0)

                amount = pos.get("amount", 0)
                apy = pos.get("apy", 0)

                # Calculate values
                current_value = price_eur * amount
                daily_gain = current_value * (apy / 100 / 365)
                days = days_staked(pos)
                accumulated_gain = daily_gain * days

                # Signals
                signals, level = compute_signals(pos, market_data, self._fear_greed)

                analysis = CryptoAnalysis(
                    symbol=symbol,
                    name=pos.get("name", symbol),
                    coingecko_id=cg_id,
                    amount=amount,
                    product=pos.get("product", ""),
                    position_type=pos.get("type", "flexible"),
                    apy=apy,
                    rescue_days=pos.get("rescue_days", 0),
                    start_date=pos.get("start_date", ""),
                    maturity_date=pos.get("maturity_date"),
                    next_distribution=pos.get("next_distribution"),
                    distribution_freq_days=pos.get("distribution_freq_days", 1),
                    price_eur=price_eur,
                    change_24h=price_info.get("eur_24h_change", 0),
                    change_30d=price_info.get("price_change_30d"),
                    ath=price_info.get("ath"),
                    ath_change_pct=price_info.get("ath_change_pct"),
                    current_value=current_value,
                    daily_gain=daily_gain,
                    accumulated_gain=accumulated_gain,
                    days_staked=days,
                    days_until_available=days_until_available(pos),
                    days_until_reward=next_distribution_in(pos),
                    signals=signals,
                    level=level,
                    ohlc=fetch_ohlc(cg_id, 30),
                )

                results.append(analysis)
                overall_level = overall_level.escalate(level)
                total_value += current_value
                total_daily_gain += daily_gain

            except Exception as e:
                logger.error(f"Error processing {symbol}: {e}")
                continue

        self._results = results
        self._level = overall_level
        self._last_update = datetime.now(timezone.utc)

        logger.info(f"Crypto monitor complete. {len(results)} positions processed.")

        return {
            "analysis": results,
            "total_value": total_value,
            "total_daily_gain": total_daily_gain,
            "level": overall_level,
            "fear_greed": self._fear_greed,
            "fear_greed_label": self._fear_greed_label,
            "last_update": self._last_update,
        }

    def get_level(self) -> AlertLevel:
        return self._level

    def get_last_update(self) -> datetime | None:
        return self._last_update

    def get_results(self) -> list[CryptoAnalysis]:
        return self._results

    def get_fear_greed(self) -> tuple[int | None, str | None]:
        return self._fear_greed, self._fear_greed_label
