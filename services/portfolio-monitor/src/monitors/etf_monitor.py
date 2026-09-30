"""
Portfolio Monitor — ETF Monitor.
Downloads market data from Yahoo Finance and calculates technical signals.
"""

import logging
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf
from config import ETF_FUND_IDS, ETF_PLAN, ETF_PORTFOLIO, ETF_THRESHOLDS
from i18n import t
from models import AlertLevel, ETFAnalysis, Signal

from . import BaseMonitor, register_monitor

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Plan helpers
# ─────────────────────────────────────────────────────────────────────────────
def current_phase() -> tuple[str, int | None]:
    """Return (phase label, months remaining) tuple."""
    today = datetime.today()
    phase_date = ETF_PLAN.get("phase_change_date", datetime(2027, 3, 1))

    if today >= phase_date:
        return t("etf.phase2"), None

    months = int((phase_date - today).days / 30.44)
    return t("etf.phase1", months=months), months


def current_contribution(fund_id: str) -> float:
    """Return the active monthly contribution for a fund."""
    cfg = ETF_PORTFOLIO.get(fund_id, {})
    phase_date = ETF_PLAN.get("phase_change_date", datetime(2027, 3, 1))

    if datetime.today() >= phase_date:
        return cfg.get("phase2_contrib", 0.0)
    return cfg.get("monthly_contrib", 0.0)


def years_since_start() -> int:
    """Return years elapsed since the first ETF purchase."""
    try:
        first_fund = list(ETF_PORTFOLIO.values())[0] if ETF_PORTFOLIO else {}
        start = datetime.fromisoformat(first_fund.get("start_date", ""))
        return max(1, round((datetime.today() - start).days / 365))
    except (ValueError, KeyError, IndexError):
        return 1


def projected_milestone(fund_id: str) -> float | None:
    """Return the projected EUR milestone for the current year."""
    try:
        milestones = ETF_PLAN.get("milestones", {})
        year = min(years_since_start(), max(milestones.keys()) if milestones else 1)
        milestone = milestones.get(year)
        if milestone is None:
            return None
        idx = ETF_FUND_IDS.index(fund_id) if fund_id in ETF_FUND_IDS else 0
        return milestone[idx] if idx < len(milestone) else None
    except (KeyError, IndexError, TypeError, ValueError):
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Tax calculation
# ─────────────────────────────────────────────────────────────────────────────
def calculate_tax(gain: float) -> float:
    """
    Calculate IRPF tax on a capital gain using progressive brackets.

    Spanish capital gains tax (base del ahorro) is progressive:
    - Each bracket has an upper limit and a rate
    - You pay the rate only on the portion within that bracket

    Example with 2025 brackets for a 70.000€ gain:
    - First 6.000€ at 19% = 1.140€
    - Next 44.000€ (6.000-50.000) at 21% = 9.240€
    - Remaining 20.000€ (50.000-70.000) at 23% = 4.600€
    - Total = 14.980€
    """
    if gain <= 0:
        return 0.0

    brackets = ETF_PLAN.get("tax_brackets", [])
    if not brackets:
        return 0.0

    total = 0.0
    prev_limit = 0.0

    for limit, rate in brackets:
        if gain <= prev_limit:
            break

        # Amount taxable in this bracket
        taxable_in_bracket = min(gain, limit) - prev_limit
        if taxable_in_bracket > 0:
            total += taxable_in_bracket * rate

        prev_limit = limit

    return total


def calculate_tax_impact(
    units: float, avg_cost: float | None, current_price: float
) -> dict[str, float] | None:
    """Calculate tax impact if the position were sold today."""
    if not avg_cost or units <= 0:
        return None

    current_value = units * current_price
    cost_basis = units * avg_cost
    gain = current_value - cost_basis

    if gain <= 0:
        return {"gain": gain, "tax": 0.0, "net": current_value, "set_aside": 0.0}

    tax = calculate_tax(gain)
    return {
        "gain": gain,
        "tax": tax,
        "net": current_value - tax,
        "set_aside": tax,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Data download
# ─────────────────────────────────────────────────────────────────────────────
def fetch_etf_data(ticker_sym: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Download one year of historical data for an ETF."""
    try:
        ticker = yf.Ticker(ticker_sym)
        hist = ticker.history(period="1y")
        if hist.empty:
            logger.warning(f"Empty history for {ticker_sym}")
            return pd.DataFrame(), {}

        info = {}
        try:
            # Try fast_info first (yfinance 0.2.x), fall back to info (yfinance 1.x)
            info = getattr(ticker, "fast_info", None) or ticker.info or {}
        except (AttributeError, KeyError, ValueError, TypeError):
            logger.debug(f"Info not available for {ticker_sym}")

        return hist, info
    except Exception as e:
        logger.error(f"Error downloading {ticker_sym}: {e}")
        raise


def fetch_ohlc_data(ticker_sym: str, period: str = "1mo") -> list[list[float]]:
    """Fetch OHLC data for sparkline charts."""
    try:
        ticker = yf.Ticker(ticker_sym)
        hist = ticker.history(period=period)
        if hist.empty:
            return []

        # Convert to list of [timestamp, open, high, low, close]
        ohlc = []
        for idx, row in hist.iterrows():
            ts = int(idx.timestamp() * 1000) if hasattr(idx, "timestamp") else 0
            ohlc.append([ts, row["Open"], row["High"], row["Low"], row["Close"]])

        return ohlc
    except Exception as e:
        logger.error(f"Error fetching OHLC for {ticker_sym}: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Signal analysis
# ─────────────────────────────────────────────────────────────────────────────
def _analyse_moving_averages(
    hist: pd.DataFrame,
    price: float,
    ma50: float | None,
    ma200: float | None,
) -> tuple[list[Signal], AlertLevel]:
    """Analyse moving average positions and recent crossovers."""
    signals: list[Signal] = []
    level = AlertLevel.OK

    if not (ma50 and ma200):
        return signals, level

    # Calculate percentage differences
    pct_diff_50 = ((price - ma50) / ma50) * 100
    pct_diff_200 = ((price - ma200) / ma200) * 100

    # Thresholds to filter noise (based on Moving Average Envelope best practices)
    # -3% for MA200: proven to reduce whipsaws from 27 to 4 signals (StockCharts study)
    # -2% for MA50: standard minimum envelope for ETFs
    MA200_THRESHOLD = -3.0
    MA50_THRESHOLD = -2.0

    # Price vs MAs (only signal if below threshold to filter noise)
    if pct_diff_200 <= MA200_THRESHOLD:
        signals.append(
            Signal(
                t("signal.mm200.title"),
                t("signal.mm200.body", price=price, mm=ma200, pct=pct_diff_200),
                "WARN",
            )
        )
        level = level.escalate(AlertLevel.WARN)
    elif pct_diff_50 <= MA50_THRESHOLD:
        signals.append(
            Signal(
                t("signal.mm50.title"),
                t("signal.mm50.body", price=price, mm=ma50, pct=pct_diff_50),
                "INFO",
            )
        )
        level = level.escalate(AlertLevel.INFO)
    else:
        signals.append(
            Signal(
                t("signal.mm_ok.title"),
                t(
                    "signal.mm_ok.body",
                    price=price,
                    mm50=ma50,
                    mm200=ma200,
                    pct50=pct_diff_50,
                    pct200=pct_diff_200,
                ),
                "OK",
            )
        )

    # Check for crossovers
    ma_short = ETF_THRESHOLDS["ma_short"]
    ma_long = ETF_THRESHOLDS["ma_long"]

    try:
        if len(hist) > ma_long:
            prev_ma50 = float(hist["Close"].rolling(ma_short).mean().iloc[-2])
            prev_ma200 = float(hist["Close"].rolling(ma_long).mean().iloc[-2])

            if prev_ma50 <= prev_ma200 and ma50 > ma200:
                signals.append(
                    Signal(t("signal.golden.title"), t("signal.golden.body"), "INFO")
                )
                level = level.escalate(AlertLevel.INFO)
            elif prev_ma50 >= prev_ma200 and ma50 < ma200:
                signals.append(
                    Signal(t("signal.death.title"), t("signal.death.body"), "DANGER")
                )
                level = AlertLevel.DANGER
    except (IndexError, ValueError, TypeError):
        pass

    return signals, level


def _analyse_drawdown_and_cost(
    price: float,
    high_52w: float,
    drawdown: float,
    avg_cost: float | None,
) -> tuple[list[Signal], AlertLevel]:
    """Analyse drawdown from 52-week high and position vs average cost."""
    signals: list[Signal] = []
    level = AlertLevel.OK

    critical = ETF_THRESHOLDS["critical_threshold"]
    drop_warn = ETF_THRESHOLDS["drop_from_high_warn"]
    loss_warn = ETF_THRESHOLDS["loss_vs_cost_warn"]

    # Drawdown from high
    if drawdown < critical:
        signals.append(
            Signal(
                t("signal.drop_severe.title"),
                t("signal.drop_severe.body", pct=drawdown, high=high_52w),
                "DANGER",
            )
        )
        level = AlertLevel.DANGER
    elif drawdown < drop_warn:
        signals.append(
            Signal(
                t("signal.drop_warn.title"),
                t("signal.drop_warn.body", pct=drawdown, high=high_52w),
                "WARN",
            )
        )
        level = level.escalate(AlertLevel.WARN)

    # Position vs average cost
    if avg_cost and avg_cost > 0:
        pct = (price / avg_cost) - 1

        if pct < critical:
            signals.append(
                Signal(
                    t("signal.loss_crit.title"),
                    t("signal.loss_crit.body", pct=pct, avg=avg_cost),
                    "DANGER",
                )
            )
            level = AlertLevel.DANGER
        elif pct < loss_warn:
            signals.append(
                Signal(
                    t("signal.loss_warn.title"),
                    t("signal.loss_warn.body", pct=pct, avg=avg_cost),
                    "WARN",
                )
            )
            level = level.escalate(AlertLevel.WARN)
        elif pct >= 0:
            signals.append(
                Signal(
                    t("signal.profit.title"),
                    t("signal.profit.body", pct=pct, avg=avg_cost),
                    "OK",
                )
            )

    return signals, level


def calculate_signals(hist: pd.DataFrame, avg_cost: float | None) -> dict[str, Any]:
    """Calculate all technical signals for an ETF."""
    empty: dict[str, Any] = {
        "price": 0,
        "high_52w": 0,
        "low_52w": 0,
        "chg_1d": 0,
        "chg_1m": 0,
        "chg_3m": 0,
        "chg_ytd": 0,
        "ma50": None,
        "ma200": None,
        "drawdown": 0,
        "pct_vs_cost": None,
        "annual_vol": 0,
        "signals": [],
        "level": AlertLevel.OK,
    }

    if hist.empty or len(hist) < 2:
        return empty

    ma_short = ETF_THRESHOLDS["ma_short"]
    ma_long = ETF_THRESHOLDS["ma_long"]

    # Basic price data
    price = float(hist["Close"].iloc[-1])
    high_52w = float(hist["High"].max())
    low_52w = float(hist["Low"].min())

    # Changes
    chg_1d = (
        (hist["Close"].iloc[-1] / hist["Close"].iloc[-2] - 1) if len(hist) > 1 else 0
    )
    chg_1m = (
        (hist["Close"].iloc[-1] / hist["Close"].iloc[-22] - 1) if len(hist) > 22 else 0
    )
    chg_3m = (
        (hist["Close"].iloc[-1] / hist["Close"].iloc[-66] - 1) if len(hist) > 66 else 0
    )

    # YTD
    try:
        ytd_mask = hist.index.year == datetime.now(timezone.utc).year
        ytd_idx = hist[ytd_mask].index[0] if any(ytd_mask) else hist.index[0]
        ytd_price = float(hist["Close"].loc[ytd_idx])
        chg_ytd = (hist["Close"].iloc[-1] / ytd_price - 1) if ytd_price else 0
    except (IndexError, KeyError, TypeError):
        chg_ytd = 0

    # Moving averages
    _v50 = (
        hist["Close"].rolling(ma_short).mean().iloc[-1]
        if len(hist) >= ma_short
        else None
    )
    _v200 = (
        hist["Close"].rolling(ma_long).mean().iloc[-1] if len(hist) >= ma_long else None
    )
    ma50 = float(_v50) if _v50 is not None and not pd.isna(_v50) else None
    ma200 = float(_v200) if _v200 is not None and not pd.isna(_v200) else None

    drawdown = (price / high_52w) - 1 if high_52w > 0 else 0

    # Signals
    signals: list[Signal] = []
    level = AlertLevel.OK

    ma_signals, ma_level = _analyse_moving_averages(hist, price, ma50, ma200)
    signals.extend(ma_signals)
    level = level.escalate(ma_level)

    dd_signals, dd_level = _analyse_drawdown_and_cost(
        price, high_52w, drawdown, avg_cost
    )
    signals.extend(dd_signals)
    level = level.escalate(dd_level)

    pct_vs_cost = (price / avg_cost - 1) if avg_cost and avg_cost > 0 else None

    # Volatility
    annual_vol = 0.0
    try:
        returns = hist["Close"].pct_change().dropna()
        annual_vol = float(returns.std() * np.sqrt(252))
        if annual_vol > 0.30:
            signals.append(
                Signal(
                    t("signal.volatility.title"),
                    t("signal.volatility.body", vol=annual_vol),
                    "INFO",
                )
            )
    except (ValueError, TypeError):
        pass

    return {
        "price": price,
        "high_52w": high_52w,
        "low_52w": low_52w,
        "chg_1d": chg_1d,
        "chg_1m": chg_1m,
        "chg_3m": chg_3m,
        "chg_ytd": chg_ytd,
        "ma50": ma50,
        "ma200": ma200,
        "drawdown": drawdown,
        "pct_vs_cost": pct_vs_cost,
        "annual_vol": annual_vol,
        "signals": signals,
        "level": level,
    }


def get_recommendation(level: AlertLevel, name: str) -> Signal:
    """Return recommendation based on alert level."""
    if level == AlertLevel.DANGER:
        return Signal(t("rec.danger.title"), t("rec.danger.body", name=name), "DANGER")
    if level == AlertLevel.WARN:
        return Signal(t("rec.warn.title"), t("rec.warn.body", name=name), "WARN")
    return Signal(t("rec.ok.title"), t("rec.ok.body", name=name), "OK")


# ─────────────────────────────────────────────────────────────────────────────
# Monitor class
# ─────────────────────────────────────────────────────────────────────────────
@register_monitor
class ETFMonitor(BaseMonitor):
    """ETF portfolio monitor."""

    name = "etf"

    def __init__(self):
        self._last_update: datetime | None = None
        self._level = AlertLevel.OK
        self._results: list[ETFAnalysis] = []

    async def run(self) -> dict[str, Any]:
        """Execute the ETF monitor."""
        logger.info("Starting ETF monitor...")

        results: list[ETFAnalysis] = []
        overall_level = AlertLevel.OK
        total_value = 0.0
        total_invested = 0.0

        for fund_id, cfg in ETF_PORTFOLIO.items():
            ticker = cfg["ticker"]
            logger.info(f"  → {fund_id} ({ticker})...")

            try:
                hist, info = fetch_etf_data(ticker)
                if hist.empty:
                    continue

                analysis_data = calculate_signals(hist, cfg.get("avg_cost"))

                # Build analysis object
                units = cfg.get("units", 0.0)
                avg_cost = cfg.get("avg_cost")
                price = analysis_data["price"]
                current_value = price * units if units else 0
                cost_basis = (avg_cost * units) if avg_cost and units else 0

                # Tax impact
                tax_data = calculate_tax_impact(units, avg_cost, price) or {}

                # Projection
                milestone = projected_milestone(fund_id)
                year = years_since_start()

                analysis = ETFAnalysis(
                    fund_id=fund_id,
                    ticker=ticker,
                    name=cfg["name"],
                    color=cfg["color"],
                    price=price,
                    high_52w=analysis_data["high_52w"],
                    low_52w=analysis_data["low_52w"],
                    chg_1d=analysis_data["chg_1d"],
                    chg_1m=analysis_data["chg_1m"],
                    chg_3m=analysis_data["chg_3m"],
                    chg_ytd=analysis_data["chg_ytd"],
                    ma50=analysis_data["ma50"],
                    ma200=analysis_data["ma200"],
                    drawdown=analysis_data["drawdown"],
                    annual_vol=analysis_data["annual_vol"],
                    units=units,
                    avg_cost=avg_cost,
                    current_value=current_value,
                    gain_loss_eur=current_value - cost_basis if cost_basis else 0,
                    gain_loss_pct=analysis_data["pct_vs_cost"] or 0,
                    monthly_contrib=current_contribution(fund_id),
                    start_date=cfg.get("start_date", ""),
                    tax_gain=tax_data.get("gain", 0),
                    tax_irpf=tax_data.get("tax", 0),
                    tax_net=tax_data.get("net", 0),
                    proj_expected=milestone,
                    proj_actual=current_value,
                    proj_deviation=(current_value / milestone - 1)
                    if milestone and milestone > 0
                    else 0,
                    proj_year=year,
                    signals=analysis_data["signals"],
                    level=analysis_data["level"],
                    recommendation=get_recommendation(
                        analysis_data["level"], cfg["name"]
                    ),
                    ohlc=fetch_ohlc_data(ticker, "1mo"),
                )

                results.append(analysis)
                overall_level = overall_level.escalate(analysis.level)
                total_value += current_value
                total_invested += cost_basis

            except Exception as e:
                logger.error(f"Error processing {fund_id}: {e}")
                continue

        self._results = results
        self._level = overall_level
        self._last_update = datetime.now(timezone.utc)

        phase_label, phase_months = current_phase()

        logger.info(f"ETF monitor complete. {len(results)} funds processed.")

        return {
            "analysis": results,
            "total_value": total_value,
            "total_invested": total_invested,
            "total_gain_loss": total_value - total_invested,
            "total_gain_loss_pct": (total_value / total_invested - 1)
            if total_invested > 0
            else 0,
            "level": overall_level,
            "phase": phase_label,
            "phase_months_remaining": phase_months,
            "last_update": self._last_update,
        }

    def get_level(self) -> AlertLevel:
        return self._level

    def get_last_update(self) -> datetime | None:
        return self._last_update

    def get_results(self) -> list[ETFAnalysis]:
        return self._results
