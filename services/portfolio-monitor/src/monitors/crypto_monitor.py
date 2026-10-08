"""
Portfolio Monitor — Crypto Staking Monitor.
Fetches data from CoinGecko and tracks staking positions.
"""

import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

import config
from i18n import t
from models import AlertLevel, CryptoAnalysis, Signal
from smart_home_common.cache import TTLCache

from . import BaseMonitor, register_monitor

# Add libs to path for shared library import
_LIBS_PATH = os.environ.get("LIBS_PATH", "/app/libs")
if _LIBS_PATH not in sys.path:
    sys.path.insert(0, _LIBS_PATH)

from http_client import RetryClient, RetryConfig  # noqa: E402

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
# HTTP Client with retry (uses shared library)
# ─────────────────────────────────────────────────────────────────────────────
_cg_headers = {"x-cg-demo-api-key": _CG_API_KEY} if _CG_API_KEY else {}
_retry_config = RetryConfig(
    timeout=_TIMEOUT, max_retries=_RETRIES, initial_backoff=_BACKOFF
)

_cg_client = RetryClient(default_headers=_cg_headers, config=_retry_config)
_generic_client = RetryClient(config=_retry_config)


# ─────────────────────────────────────────────────────────────────────────────
# TTL Cache for API responses (shared implementation)
# CoinGecko Demo plan: 30 calls/min, 10k/month — cache reduces rate limit risk
# ─────────────────────────────────────────────────────────────────────────────
# Cache instances with different TTLs per data type
# Market data: 5 min (prices update ~every minute, but we don't need real-time)
# OHLC: 15 min (historical data, rarely changes)
# Fear & Greed: 30 min (updates ~daily)
_market_cache = TTLCache(default_ttl_seconds=300)  # 5 min
_ohlc_cache = TTLCache(default_ttl_seconds=900)  # 15 min
_fg_cache = TTLCache(default_ttl_seconds=1800)  # 30 min


def fetch_market_batch(coingecko_ids: list[str]) -> dict[str, Any]:
    """Fetch price, 24h change, ATH, 14d and 30d changes for all coins."""
    if not coingecko_ids:
        return {}

    # Create a stable cache key from sorted IDs
    ids_sorted = sorted(set(coingecko_ids))
    cache_key = ",".join(ids_sorted)

    # Check cache first
    cached = _market_cache.get(cache_key)
    if cached is not None:
        logger.debug(f"Cache hit for market data: {cache_key[:30]}...")
        return cached

    ids = ",".join(dict.fromkeys(coingecko_ids))
    try:
        rows = _cg_client.get(_MARKETS_URL.format(ids=ids)).json()
        result = {
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
        # Cache successful response
        _market_cache.set(cache_key, result)
        return result
    except Exception as e:
        logger.error(f"Error fetching prices: {e}")
        return {}


def fetch_ohlc(coingecko_id: str, days: int = 30) -> list[list[float]]:
    """Fetch OHLC data for sparkline charts."""
    cache_key = f"{coingecko_id}:{days}"

    # Check cache first
    cached = _ohlc_cache.get(cache_key)
    if cached is not None:
        logger.debug(f"Cache hit for OHLC: {cache_key}")
        return cached

    try:
        result = _cg_client.get(_OHLC_URL.format(id=coingecko_id, days=days)).json()
        # Cache successful response
        _ohlc_cache.set(cache_key, result)
        return result
    except Exception as e:
        logger.error(f"Error fetching OHLC for {coingecko_id}: {e}")
        return []


def fetch_fear_greed() -> tuple[int | None, str | None]:
    """Fetch the current Fear & Greed index value and label."""
    cache_key = "fear_greed"

    # Check cache first
    cached = _fg_cache.get(cache_key)
    if cached is not None:
        logger.debug("Cache hit for Fear & Greed")
        return cached

    try:
        data = _generic_client.get(_FG_URL).json()
        result = int(data["data"][0]["value"]), data["data"][0]["value_classification"]
        # Cache successful response
        _fg_cache.set(cache_key, result)
        return result
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
# Exchange Trust Score (CoinGecko)
# ─────────────────────────────────────────────────────────────────────────────
_EXCHANGE_IDS = {
    "bitvavo": "bitvavo",
    "kucoin": "kucoin",
    "binance": "binance",
    "coinbase": "gdax",
    "kraken": "kraken",
}


def fetch_exchange_trust_score(exchange: str) -> int | None:
    """Fetch CoinGecko trust score for an exchange (1-10 scale)."""
    exchange_id = _EXCHANGE_IDS.get(exchange.lower())
    if not exchange_id:
        return None

    url = f"https://api.coingecko.com/api/v3/exchanges/{exchange_id}"
    try:
        data = _cg_client.get(url).json()
        return data.get("trust_score")
    except Exception as e:
        logger.warning(f"Could not fetch trust score for {exchange}: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Staking & Exchange Risk Analysis
# ─────────────────────────────────────────────────────────────────────────────
def compute_staking_risk_signals(
    pos: dict[str, Any],
    exchange_trust: dict[str, int | None],
    maturity_warn_days: int = 7,
) -> tuple[list[Signal], AlertLevel]:
    """
    Compute risk signals specific to staking positions and exchange custody.

    Returns signals for:
    - Fixed staking approaching maturity
    - Exchange trust score degradation
    - Custody reminders for non-staked assets
    """
    signals: list[Signal] = []
    level = AlertLevel.OK

    pos_type = pos.get("type", "flexible")
    exchange = pos.get("exchange", "")
    symbol = pos.get("symbol", "")

    # ─────────────────────────────────────────────────────────────────────────
    # Fixed Staking Maturity Check
    # ─────────────────────────────────────────────────────────────────────────
    if pos_type == "fixed" and pos.get("maturity_date"):
        maturity_str = pos.get("maturity_date", "")
        try:
            maturity = datetime.fromisoformat(maturity_str).date()
            today = datetime.now(timezone.utc).date()
            days_left = (maturity - today).days

            if days_left <= 0:
                # Staking already matured
                signals.append(Signal("", t("crypto.staking_matured"), "WARN"))
                level = level.escalate(AlertLevel.WARN)
            elif days_left <= maturity_warn_days:
                # Staking maturing soon
                signals.append(
                    Signal(
                        "",
                        t(
                            "crypto.staking_maturity_soon",
                            days=days_left,
                            date=maturity_str,
                        ),
                        "INFO",
                    )
                )
        except (ValueError, TypeError):
            pass

    # ─────────────────────────────────────────────────────────────────────────
    # Exchange Trust Score Check
    # ─────────────────────────────────────────────────────────────────────────
    if exchange:
        trust = exchange_trust.get(exchange.lower())
        if trust is not None:
            if trust <= 4:
                # Critical - exchange has serious issues
                signals.append(
                    Signal(
                        "",
                        t(
                            "crypto.exchange_trust_critical",
                            exchange=exchange.title(),
                            score=trust,
                        ),
                        "DANGER",
                    )
                )
                level = level.escalate(AlertLevel.DANGER)
            elif trust <= 6:
                # Warning - trust score degraded
                signals.append(
                    Signal(
                        "",
                        t(
                            "crypto.exchange_trust_low",
                            exchange=exchange.title(),
                            score=trust,
                        ),
                        "WARN",
                    )
                )
                level = level.escalate(AlertLevel.WARN)

    # ─────────────────────────────────────────────────────────────────────────
    # Custody reminder (non-staked assets)
    # ─────────────────────────────────────────────────────────────────────────
    if pos_type == "custody":
        signals.append(
            Signal(
                "",
                t(
                    "crypto.custody_reminder",
                    amount=pos.get("amount", 0),
                    symbol=symbol,
                    exchange=exchange.title() if exchange else "exchange",
                ),
                "INFO",
            )
        )

    return signals, level


# ─────────────────────────────────────────────────────────────────────────────
# Signal analysis
# ─────────────────────────────────────────────────────────────────────────────
def compute_signals(
    pos: dict[str, Any],
    price_data: dict[str, Any],
    fear_greed_val: int | None,
) -> tuple[list[Signal], AlertLevel]:
    """
    Compute signals for a position.

    Logic optimized for HODL strategy:
    - Fear & Greed: informational only (sentiment indicator)
    - ATH proximity: informational (momentum indicator)
    - Price pumps: informational (could be rally start)
    - 24h drops: only escalate on significant moves (crypto is volatile)
    - 30d drops: only escalate on severe bear markets
    """
    signals: list[Signal] = []
    level = AlertLevel.OK

    cg_id = pos.get("coingecko_id", "")
    price_info = price_data.get(cg_id, {})

    change_24h = price_info.get("eur_24h_change", 0)
    ath_pct = price_info.get("ath_change_pct")
    change_30d = price_info.get("price_change_30d")

    thr = config.get_crypto_thresholds()

    # ─────────────────────────────────────────────────────────────────────────
    # Fear & Greed - INFORMATIONAL ONLY
    # This is market sentiment, not actionable for HODLers
    # ─────────────────────────────────────────────────────────────────────────
    if fear_greed_val is not None:
        if fear_greed_val >= thr.get("fg_extreme_greed", 75):
            signals.append(
                Signal("", t("crypto.fg_extreme_greed", val=fear_greed_val), "INFO")
            )
        elif fear_greed_val >= thr.get("fg_high_greed", 60):
            signals.append(
                Signal("", t("crypto.fg_high_greed", val=fear_greed_val), "INFO")
            )
        elif fear_greed_val <= thr.get("fg_extreme_fear", 25):
            # Extreme fear = potential buying opportunity for HODLers
            signals.append(
                Signal("", t("crypto.fg_extreme_fear", val=fear_greed_val), "OK")
            )

    # ─────────────────────────────────────────────────────────────────────────
    # 24h price change - adjusted for crypto volatility
    # Normal crypto volatility is ±5%, only alert on significant moves
    # ─────────────────────────────────────────────────────────────────────────
    if change_24h is not None:
        danger_threshold = thr.get("change_24h_danger", -15)
        warn_threshold = thr.get("change_24h_warn", -10)
        info_threshold = thr.get("change_24h_info", -5)
        pump_threshold = thr.get("change_24h_pump", 10)

        if change_24h <= danger_threshold:
            # Flash crash - rare, serious event
            signals.append(
                Signal("", t("crypto.drop_danger", pct=change_24h), "DANGER")
            )
            level = level.escalate(AlertLevel.DANGER)
        elif change_24h <= warn_threshold:
            # Significant drop - worth attention
            signals.append(Signal("", t("crypto.drop_warn", pct=change_24h), "WARN"))
            level = level.escalate(AlertLevel.WARN)
        elif change_24h <= info_threshold:
            # Normal volatility - informational only
            signals.append(Signal("", t("crypto.drop_info", pct=change_24h), "INFO"))
        elif change_24h >= pump_threshold:
            # Strong surge - informational (could be rally start)
            signals.append(Signal("", t("crypto.pump_info", pct=change_24h), "INFO"))

    # ─────────────────────────────────────────────────────────────────────────
    # ATH proximity - INFORMATIONAL ONLY
    # Being near ATH is not bad - crypto makes new ATHs in bull markets
    # ─────────────────────────────────────────────────────────────────────────
    if ath_pct is not None:
        ath_near = thr.get("ath_danger_pct", -5)
        ath_approaching = thr.get("ath_warn_pct", -15)

        if ath_pct >= ath_near:
            signals.append(Signal("", t("crypto.ath_near", pct=abs(ath_pct)), "INFO"))
        elif ath_pct >= ath_approaching:
            signals.append(
                Signal("", t("crypto.ath_approaching", pct=abs(ath_pct)), "INFO")
            )

    # ─────────────────────────────────────────────────────────────────────────
    # 30-day momentum - adjusted for crypto cycles
    # -20% in 30 days is a normal correction, not a crisis
    # ─────────────────────────────────────────────────────────────────────────
    if change_30d is not None:
        bear_danger = thr.get("change_30d_danger", -50)
        bear_warn = thr.get("change_30d_warn", -35)
        bear_info = thr.get("change_30d_bear", -20)
        bull_threshold = thr.get("change_30d_bull", 20)

        if change_30d <= bear_danger:
            # Severe crash - very rare (2022 Luna, FTX level)
            signals.append(Signal("", t("crypto.crash_30d", pct=change_30d), "DANGER"))
            level = level.escalate(AlertLevel.DANGER)
        elif change_30d <= bear_warn:
            # Bear market confirmed
            signals.append(Signal("", t("crypto.bear_30d", pct=change_30d), "WARN"))
            level = level.escalate(AlertLevel.WARN)
        elif change_30d <= bear_info:
            # Normal correction - informational for HODLers
            signals.append(
                Signal("", t("crypto.correction_30d", pct=change_30d), "INFO")
            )
        elif change_30d >= bull_threshold:
            # Bull momentum - positive signal
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

        positions = config.get_crypto_positions()
        if not positions:
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
        coingecko_ids = [p["coingecko_id"] for p in positions if "coingecko_id" in p]
        logger.info(f"  → Fetching market data for {len(coingecko_ids)} coins...")
        market_data = fetch_market_batch(coingecko_ids)

        # Fetch exchange trust scores for all exchanges in use
        exchanges_in_use = {
            p.get("exchange", "").lower() for p in positions if p.get("exchange")
        }
        exchange_trust: dict[str, int | None] = {}
        for exchange in exchanges_in_use:
            logger.info(f"  → Fetching trust score for {exchange}...")
            exchange_trust[exchange] = fetch_exchange_trust_score(exchange)

        # Get maturity warning threshold from config
        maturity_warn_days = config.get_crypto_thresholds().get(
            "staking_maturity_warn_days", 7
        )

        results: list[CryptoAnalysis] = []
        overall_level = AlertLevel.OK
        total_value = 0.0
        total_daily_gain = 0.0

        for pos in positions:
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

                # Price/market signals
                signals, level = compute_signals(pos, market_data, self._fear_greed)

                # Staking & exchange risk signals
                risk_signals, risk_level = compute_staking_risk_signals(
                    pos, exchange_trust, maturity_warn_days
                )
                signals.extend(risk_signals)
                level = level.escalate(risk_level)

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
            "exchange_trust": exchange_trust,
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
