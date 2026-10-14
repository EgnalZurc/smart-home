"""
Portfolio Monitor — Dividends endpoint.

Exposes a dividend calendar for the configured ETFs: per-ETF trailing yield and
last/next distribution, plus a flat list of distributions estimated to fall
within the next 90 days. Current prices are read from the orchestrator's cached
ETF analysis (no extra network calls); dividend history itself comes from
``calculate_dividend_info`` which caches ``yf.Ticker.dividends`` for an hour and
is offloaded to a worker thread so the event loop stays responsive.

``get_orchestrator`` is resolved through the ``api.routes`` package namespace at
call time so tests patching ``api.routes.get_orchestrator`` take effect here.
"""

import asyncio
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter

from .helpers import _safe_json

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])

# How far ahead the calendar looks for estimated upcoming distributions.
UPCOMING_WINDOW_DAYS = 90


def _current_prices_by_ticker() -> dict[str, float]:
    """Map ticker → latest known price from the orchestrator's cached analysis.

    Falls back to an empty map if the summary has no ETF analysis yet (e.g. the
    first run before any monitor has executed).
    """
    import api.routes as routes

    orch = routes.get_orchestrator()
    summary = orch.get_summary()

    prices: dict[str, float] = {}
    for analysis in summary.etf_analysis or []:
        ticker = getattr(analysis, "ticker", None)
        price = getattr(analysis, "price", None)
        if ticker and price:
            prices[ticker] = float(price)
    return prices


@router.get("/dividends")
async def get_dividends():
    """Return the dividend calendar for every configured ETF.

    Shape::

        {
          "etfs": [
            {
              "fund_id", "symbol", "name",
              "last_dividend_date", "last_dividend_amount",
              "dividend_yield_pct", "estimated_annual_income",
              "next_dividend_date", "frequency_days"
            },
            ...
          ],
          "upcoming": [
            {"symbol", "name", "expected_date", "days_until",
             "estimated_amount_per_share", "estimated_income"},
            ...
          ],
          "upcoming_window_days": 90
        }
    """
    import config
    from monitors.etf_monitor import calculate_dividend_info

    prices = _current_prices_by_ticker()
    portfolio = config.get_etf_portfolio()

    async def _build(fund_id: str, cfg: dict):
        ticker = cfg.get("ticker", "")
        units = cfg.get("units", 0.0) or 0.0
        current_price = prices.get(ticker)
        info = await asyncio.to_thread(
            calculate_dividend_info, ticker, current_price, units
        )
        return fund_id, cfg, info

    results = await asyncio.gather(
        *(_build(fund_id, cfg) for fund_id, cfg in portfolio.items())
    )

    etfs = []
    upcoming = []
    today = datetime.now(timezone.utc).date()
    horizon = today + timedelta(days=UPCOMING_WINDOW_DAYS)

    for fund_id, cfg, info in results:
        name = cfg.get("name", fund_id)
        ticker = cfg.get("ticker", "")
        units = cfg.get("units", 0.0) or 0.0

        etfs.append(
            {
                "fund_id": fund_id,
                "symbol": ticker,
                "name": name,
                "last_dividend_date": info["last_dividend_date"],
                "last_dividend_amount": info["last_dividend_amount"],
                "dividend_yield_pct": info["dividend_yield_pct"],
                "estimated_annual_income": info["estimated_annual_income"],
                "next_dividend_date": info["next_dividend_date"],
                "frequency_days": info["frequency_days"],
            }
        )

        # Add to the upcoming calendar if the estimated next payment falls
        # within the look-ahead window.
        next_date_str = info["next_dividend_date"]
        if not next_date_str:
            continue
        try:
            next_date = datetime.fromisoformat(next_date_str).date()
        except ValueError:
            continue

        if today <= next_date <= horizon:
            per_share = info["last_dividend_amount"]
            upcoming.append(
                {
                    "symbol": ticker,
                    "name": name,
                    "expected_date": next_date_str,
                    "days_until": (next_date - today).days,
                    "estimated_amount_per_share": per_share,
                    "estimated_income": (per_share * units)
                    if (per_share and units)
                    else 0.0,
                }
            )

    upcoming.sort(key=lambda item: item["expected_date"])

    return _safe_json(
        {
            "etfs": etfs,
            "upcoming": upcoming,
            "upcoming_window_days": UPCOMING_WINDOW_DAYS,
        }
    )
