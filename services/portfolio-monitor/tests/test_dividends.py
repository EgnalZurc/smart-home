"""
Tests for ETF dividend tracking in the etf_monitor module.
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest


@pytest.fixture(autouse=True)
def clear_dividends_cache():
    """Ensure the dividend cache never leaks between tests."""
    from monitors.etf_monitor import _dividends_cache

    _dividends_cache.clear()
    yield
    _dividends_cache.clear()


def _make_dividend_series(entries: list[tuple[str, float]]) -> pd.Series:
    """Build a dividends Series indexed by ex-date (ascending)."""
    index = pd.to_datetime([d for d, _ in entries])
    values = [a for _, a in entries]
    return pd.Series(values, index=index, dtype="float64")


class TestFetchDividends:
    """Tests for fetch_dividends."""

    def test_returns_series_from_yfinance(self):
        from monitors.etf_monitor import fetch_dividends

        series = _make_dividend_series([("2024-03-01", 0.5), ("2024-06-01", 0.6)])
        mock_ticker = MagicMock()
        mock_ticker.dividends = series

        with patch("monitors.etf_monitor.yf.Ticker", return_value=mock_ticker):
            result = fetch_dividends("TEST.L")

        assert not result.empty
        assert len(result) == 2

    def test_empty_on_exception(self):
        from monitors.etf_monitor import fetch_dividends

        with patch("monitors.etf_monitor.yf.Ticker", side_effect=RuntimeError("boom")):
            result = fetch_dividends("BAD.L")

        assert result.empty

    def test_none_dividends_returns_empty_series(self):
        from monitors.etf_monitor import fetch_dividends

        mock_ticker = MagicMock()
        mock_ticker.dividends = None

        with patch("monitors.etf_monitor.yf.Ticker", return_value=mock_ticker):
            result = fetch_dividends("NODIV.L")

        assert result.empty

    def test_result_is_cached(self):
        from monitors.etf_monitor import fetch_dividends

        series = _make_dividend_series([("2024-03-01", 0.5)])
        mock_ticker = MagicMock()
        mock_ticker.dividends = series

        with patch(
            "monitors.etf_monitor.yf.Ticker", return_value=mock_ticker
        ) as mock_cls:
            fetch_dividends("CACHE.L")
            fetch_dividends("CACHE.L")

        # Second call should hit the cache, not yfinance.
        assert mock_cls.call_count == 1


class TestCalculateDividendInfo:
    """Tests for calculate_dividend_info."""

    def test_no_dividends_returns_empty_shape(self):
        from monitors.etf_monitor import calculate_dividend_info

        with patch(
            "monitors.etf_monitor.fetch_dividends",
            return_value=pd.Series(dtype="float64"),
        ):
            info = calculate_dividend_info("NODIV.L", 100.0, 10.0)

        assert info["last_dividend_date"] is None
        assert info["last_dividend_amount"] is None
        assert info["ttm_dividend"] == 0.0
        assert info["dividend_yield_pct"] is None
        assert info["estimated_annual_income"] == 0.0
        assert info["next_dividend_date"] is None

    def test_last_dividend_values(self):
        from monitors.etf_monitor import calculate_dividend_info

        series = _make_dividend_series(
            [("2024-03-01", 0.5), ("2024-06-01", 0.6), ("2024-09-01", 0.7)]
        )
        with patch("monitors.etf_monitor.fetch_dividends", return_value=series):
            info = calculate_dividend_info("TEST.L", 100.0, 0.0)

        assert info["last_dividend_date"] == "2024-09-01"
        assert info["last_dividend_amount"] == pytest.approx(0.7)

    def test_ttm_dividend_sums_last_year_only(self):
        from monitors.etf_monitor import calculate_dividend_info

        # Four quarterly payments spanning ~1 year; an old one outside the window.
        series = _make_dividend_series(
            [
                ("2022-01-01", 9.9),  # far outside TTM window
                ("2023-10-01", 0.25),
                ("2024-01-01", 0.25),
                ("2024-04-01", 0.25),
                ("2024-07-01", 0.25),
            ]
        )
        with patch("monitors.etf_monitor.fetch_dividends", return_value=series):
            info = calculate_dividend_info("TEST.L", 100.0, 0.0)

        # Window is last 365 days before 2024-07-01 → the 4 recent quarterly ones.
        assert info["ttm_dividend"] == pytest.approx(1.0)

    def test_yield_and_income(self):
        from monitors.etf_monitor import calculate_dividend_info

        series = _make_dividend_series([("2024-01-01", 1.0), ("2024-07-01", 1.0)])
        with patch("monitors.etf_monitor.fetch_dividends", return_value=series):
            info = calculate_dividend_info("TEST.L", 100.0, 50.0)

        # TTM = 2.0, price = 100 → yield 2.0%, income = 2.0 * 50 units = 100.
        assert info["dividend_yield_pct"] == pytest.approx(2.0)
        assert info["estimated_annual_income"] == pytest.approx(100.0)

    def test_yield_none_without_price(self):
        from monitors.etf_monitor import calculate_dividend_info

        series = _make_dividend_series([("2024-01-01", 1.0)])
        with patch("monitors.etf_monitor.fetch_dividends", return_value=series):
            info = calculate_dividend_info("TEST.L", None, 10.0)

        assert info["dividend_yield_pct"] is None

    def test_next_date_estimated_from_cadence(self):
        from monitors.etf_monitor import calculate_dividend_info

        # Quarterly cadence (~91 days apart).
        series = _make_dividend_series(
            [
                ("2024-01-01", 0.5),
                ("2024-04-01", 0.5),
                ("2024-07-01", 0.5),
            ]
        )
        with patch("monitors.etf_monitor.fetch_dividends", return_value=series):
            info = calculate_dividend_info("TEST.L", 100.0, 0.0)

        assert info["frequency_days"] is not None
        assert info["next_dividend_date"] is not None
        # Next date should land roughly one quarter after the last payment.
        last = datetime.fromisoformat("2024-07-01")
        nxt = datetime.fromisoformat(info["next_dividend_date"])
        assert 80 <= (nxt - last).days <= 100

    def test_single_dividend_no_next_estimate(self):
        from monitors.etf_monitor import calculate_dividend_info

        series = _make_dividend_series([("2024-01-01", 0.5)])
        with patch("monitors.etf_monitor.fetch_dividends", return_value=series):
            info = calculate_dividend_info("TEST.L", 100.0, 0.0)

        assert info["frequency_days"] is None
        assert info["next_dividend_date"] is None


class TestEstimateDividendFrequency:
    """Tests for the cadence estimator."""

    def test_too_few_payments(self):
        from monitors.etf_monitor import _estimate_dividend_frequency

        assert _estimate_dividend_frequency([datetime(2024, 1, 1)]) is None

    def test_monthly_cadence(self):
        from monitors.etf_monitor import _estimate_dividend_frequency

        base = datetime(2024, 1, 1)
        dates = [base + timedelta(days=30 * i) for i in range(4)]
        freq = _estimate_dividend_frequency(dates)
        assert freq == pytest.approx(30, abs=2)

    def test_quarterly_cadence(self):
        from monitors.etf_monitor import _estimate_dividend_frequency

        base = datetime(2024, 1, 1)
        dates = [base + timedelta(days=91 * i) for i in range(4)]
        freq = _estimate_dividend_frequency(dates)
        assert freq == pytest.approx(91, abs=2)
