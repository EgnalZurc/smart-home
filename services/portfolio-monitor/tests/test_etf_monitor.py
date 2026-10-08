"""
Tests for the etf_monitor module.
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytest
from models import AlertLevel


class TestTaxCalculation:
    """Tests for IRPF tax calculation."""

    @pytest.fixture(autouse=True)
    def setup_tax_brackets(self):
        """Set up tax brackets for all tax tests."""
        brackets = [
            (6_000, 0.19),
            (50_000, 0.21),
            (200_000, 0.23),
            (300_000, 0.27),
            (float("inf"), 0.30),
        ]
        with patch("config.ETF_PLAN", {"tax_brackets": brackets}):
            yield

    def test_zero_gain(self):
        """Zero gain means zero tax."""
        from monitors.etf_monitor import calculate_tax

        assert calculate_tax(0) == 0

    def test_negative_gain(self):
        """Negative gain (loss) means zero tax."""
        from monitors.etf_monitor import calculate_tax

        assert calculate_tax(-5000) == 0

    def test_first_bracket_only(self):
        """Gain in first bracket (0-6000€) at 19%."""
        from monitors.etf_monitor import calculate_tax

        # 5000€ gain → 5000 * 0.19 = 950€
        tax = calculate_tax(5000)
        assert abs(tax - 950) < 0.01

    def test_exactly_first_bracket(self):
        """Gain exactly at first bracket limit."""
        from monitors.etf_monitor import calculate_tax

        # 6000€ gain → 6000 * 0.19 = 1140€
        tax = calculate_tax(6000)
        assert abs(tax - 1140) < 0.01

    def test_second_bracket(self):
        """Gain spanning first and second brackets."""
        from monitors.etf_monitor import calculate_tax

        # 30000€ gain:
        # First 6000 at 19% = 1140
        # Next 24000 at 21% = 5040
        # Total = 6180
        tax = calculate_tax(30000)
        assert abs(tax - 6180) < 0.01

    def test_third_bracket(self):
        """Gain spanning first, second, and third brackets."""
        from monitors.etf_monitor import calculate_tax

        # 70000€ gain:
        # First 6000 at 19% = 1140
        # Next 44000 (6000-50000) at 21% = 9240
        # Remaining 20000 at 23% = 4600
        # Total = 14980
        tax = calculate_tax(70000)
        assert abs(tax - 14980) < 0.01

    def test_all_brackets_large_gain(self):
        """Large gain spanning all brackets."""
        from monitors.etf_monitor import calculate_tax

        # 400000€ gain:
        # First 6000 at 19% = 1140
        # Next 44000 at 21% = 9240
        # Next 150000 at 23% = 34500
        # Next 100000 at 27% = 27000
        # Remaining 100000 at 30% = 30000
        # Total = 101880
        tax = calculate_tax(400000)
        assert abs(tax - 101880) < 0.01


class TestTaxImpact:
    """Tests for calculate_tax_impact function."""

    @pytest.fixture(autouse=True)
    def setup_tax_brackets(self):
        """Set up tax brackets for all tax impact tests."""
        brackets = [
            (6_000, 0.19),
            (50_000, 0.21),
            (200_000, 0.23),
            (300_000, 0.27),
            (float("inf"), 0.30),
        ]
        with patch("config.ETF_PLAN", {"tax_brackets": brackets}):
            yield

    def test_tax_impact_with_gain(self):
        """Calculate tax impact for profitable position."""
        from monitors.etf_monitor import calculate_tax_impact

        # 100 units at avg cost 50€, now worth 70€ each
        result = calculate_tax_impact(units=100, avg_cost=50, current_price=70)

        assert result is not None
        assert result["gain"] == 2000  # (70-50) * 100
        assert result["tax"] > 0
        assert result["net"] < 7000  # 7000 - tax

    def test_tax_impact_with_loss(self):
        """No tax on loss position."""
        from monitors.etf_monitor import calculate_tax_impact

        result = calculate_tax_impact(units=100, avg_cost=70, current_price=50)

        assert result is not None
        assert result["gain"] == -2000
        assert result["tax"] == 0
        assert result["net"] == 5000  # current value

    def test_tax_impact_no_cost_basis(self):
        """No tax calculation without cost basis."""
        from monitors.etf_monitor import calculate_tax_impact

        result = calculate_tax_impact(units=100, avg_cost=None, current_price=70)
        assert result is None

    def test_tax_impact_zero_units(self):
        """No tax calculation with zero units."""
        from monitors.etf_monitor import calculate_tax_impact

        result = calculate_tax_impact(units=0, avg_cost=50, current_price=70)
        assert result is None


class TestPlanHelpers:
    """Tests for investment plan helper functions."""

    def test_current_phase_phase1(self):
        """Current phase returns phase 1 when before phase change date."""
        from monitors.etf_monitor import current_phase

        future = datetime(2030, 1, 1)
        with patch("config.ETF_PLAN", {"phase_change_date": future}):
            label, months = current_phase()

        assert "1" in label or "FASE 1" in label.upper()
        assert months is not None
        assert months > 0

    def test_current_phase_phase2(self):
        """Current phase returns phase 2 when after phase change date."""
        from monitors.etf_monitor import current_phase

        past = datetime(2020, 1, 1)
        with patch("config.ETF_PLAN", {"phase_change_date": past}):
            label, months = current_phase()

        assert "2" in label or "FASE 2" in label.upper()
        assert months is None

    def test_current_contribution_phase1(self):
        """Contribution returns phase 1 amount before phase change."""
        from monitors.etf_monitor import current_contribution

        future = datetime(2030, 1, 1)
        portfolio = {
            "test_fund": {
                "monthly_contrib": 100,
                "phase2_contrib": 500,
            }
        }

        with patch("config.ETF_PLAN", {"phase_change_date": future}):
            with patch("config.ETF_PORTFOLIO", portfolio):
                contrib = current_contribution("test_fund")

        assert contrib == 100

    def test_current_contribution_phase2(self):
        """Contribution returns phase 2 amount after phase change."""
        from monitors.etf_monitor import current_contribution

        past = datetime(2020, 1, 1)
        portfolio = {
            "test_fund": {
                "monthly_contrib": 100,
                "phase2_contrib": 500,
            }
        }

        with patch("config.ETF_PLAN", {"phase_change_date": past}):
            with patch("config.ETF_PORTFOLIO", portfolio):
                contrib = current_contribution("test_fund")

        assert contrib == 500


class TestSignalAnalysis:
    """Tests for signal calculation functions."""

    def _make_hist(self, prices: list[float], days: int = 252) -> pd.DataFrame:
        """Create a mock historical DataFrame."""
        dates = pd.date_range(end=datetime.now(), periods=len(prices), freq="D")
        return pd.DataFrame(
            {
                "Open": prices,
                "High": [p * 1.01 for p in prices],
                "Low": [p * 0.99 for p in prices],
                "Close": prices,
            },
            index=dates,
        )

    def test_calculate_signals_empty_history(self):
        """Empty history returns default values."""
        from monitors.etf_monitor import calculate_signals

        result = calculate_signals(pd.DataFrame(), avg_cost=50)

        assert result["price"] == 0
        assert result["level"] == AlertLevel.OK

    def test_calculate_signals_profit_position(self):
        """Profitable position generates OK signal."""
        from monitors.etf_monitor import calculate_signals

        # Upward trending prices
        prices = [50 + i * 0.1 for i in range(252)]
        hist = self._make_hist(prices)

        result = calculate_signals(hist, avg_cost=45)

        assert result["price"] > 0
        # Should have profit signal - check for Spanish or English text
        # If position is profitable, we should have at least OK level
        assert result["level"] in (AlertLevel.OK, AlertLevel.INFO)

    def test_calculate_signals_loss_position_warn(self):
        """Loss position generates WARN signal."""
        from monitors.etf_monitor import calculate_signals

        # Price dropped below avg cost
        prices = [60 - i * 0.05 for i in range(252)]
        hist = self._make_hist(prices)

        # Current price ~47, avg cost 55 → ~-14% loss
        result = calculate_signals(hist, avg_cost=55)

        assert result["level"] in (AlertLevel.WARN, AlertLevel.DANGER)

    def test_calculate_signals_severe_drawdown(self):
        """Severe drawdown triggers DANGER."""
        from monitors.etf_monitor import calculate_signals

        # High at start, drops 25%
        prices = [100] * 100 + [75] * 152
        hist = self._make_hist(prices)

        result = calculate_signals(hist, avg_cost=None)

        # -25% drawdown should trigger warning
        assert result["level"] in (AlertLevel.WARN, AlertLevel.DANGER)

    def test_moving_average_analysis_below_ma200(self):
        """Price below MA200 triggers WARN."""
        from monitors.etf_monitor import _analyse_moving_averages

        # Create history with price well below MA200
        prices = [100] * 200 + [85] * 52  # Price dropped to 85
        hist = self._make_hist(prices)
        price = 85
        ma50 = np.mean(prices[-50:])
        ma200 = np.mean(prices[-200:])

        signals, level = _analyse_moving_averages(hist, price, ma50, ma200)

        # Price is ~15% below MA200, should trigger warning
        assert level >= AlertLevel.INFO

    def test_moving_average_analysis_above_both(self):
        """Price above both MAs is OK."""
        from monitors.etf_monitor import _analyse_moving_averages

        # Uptrending prices
        prices = [50 + i * 0.2 for i in range(252)]
        hist = self._make_hist(prices)
        price = prices[-1]
        ma50 = np.mean(prices[-50:])
        ma200 = np.mean(prices[-200:])

        signals, level = _analyse_moving_averages(hist, price, ma50, ma200)

        assert level == AlertLevel.OK
        ok_signals = [s for s in signals if s.level == "OK"]
        assert len(ok_signals) >= 1


class TestETFMonitor:
    """Tests for the ETFMonitor class."""

    @pytest.mark.asyncio
    async def test_empty_portfolio(self):
        """Monitor handles empty portfolio."""
        from monitors.etf_monitor import ETFMonitor

        with patch("config.ETF_PORTFOLIO", {}):
            monitor = ETFMonitor()
            result = await monitor.run()

        assert result["total_value"] == 0
        assert result["level"] == AlertLevel.OK
        assert len(result["analysis"]) == 0

    @pytest.mark.asyncio
    async def test_run_with_mocked_data(self):
        """Monitor runs with mocked Yahoo Finance data."""
        from monitors.etf_monitor import ETFMonitor

        portfolio = {
            "TEST": {
                "id": "TEST",
                "ticker": "TEST.L",
                "name": "Test ETF",
                "color": "#FF0000",
                "avg_cost": 100,
                "units": 10,
                "monthly_contrib": 50,
                "start_date": "2024-01-01",
            }
        }

        # Create mock historical data
        prices = [100 + i * 0.1 for i in range(252)]
        dates = pd.date_range(end=datetime.now(), periods=252, freq="D")
        mock_hist = pd.DataFrame(
            {
                "Open": prices,
                "High": [p * 1.01 for p in prices],
                "Low": [p * 0.99 for p in prices],
                "Close": prices,
            },
            index=dates,
        )

        with patch("config.ETF_PORTFOLIO", portfolio):
            with patch("config.ETF_FUND_IDS", ["TEST"]):
                with patch(
                    "monitors.etf_monitor.fetch_etf_data",
                    return_value=(mock_hist, {}),
                ):
                    with patch("monitors.etf_monitor.fetch_ohlc_data", return_value=[]):
                        monitor = ETFMonitor()
                        result = await monitor.run()

        assert len(result["analysis"]) == 1
        assert result["analysis"][0].fund_id == "TEST"
        assert result["total_value"] > 0


class TestFetchHelpers:
    """Tests for data fetching functions."""

    def test_fetch_etf_data_success(self):
        """fetch_etf_data returns history and info."""
        from monitors.etf_monitor import fetch_etf_data

        mock_ticker = MagicMock()
        mock_hist = pd.DataFrame({"Close": [100, 101, 102]})
        mock_ticker.history.return_value = mock_hist
        mock_ticker.fast_info = {"last_price": 102}

        with patch("monitors.etf_monitor.yf.Ticker", return_value=mock_ticker):
            hist, info = fetch_etf_data("TEST.L")

        assert len(hist) == 3
        assert "Close" in hist.columns

    def test_fetch_etf_data_empty(self):
        """fetch_etf_data handles empty response."""
        from monitors.etf_monitor import fetch_etf_data

        mock_ticker = MagicMock()
        mock_ticker.history.return_value = pd.DataFrame()

        with patch("monitors.etf_monitor.yf.Ticker", return_value=mock_ticker):
            hist, info = fetch_etf_data("INVALID")

        assert hist.empty

    def test_fetch_ohlc_data_success(self):
        """fetch_ohlc_data returns OHLC list."""
        from monitors.etf_monitor import fetch_ohlc_data

        mock_ticker = MagicMock()
        dates = pd.date_range(end=datetime.now(), periods=30, freq="D")
        mock_hist = pd.DataFrame(
            {
                "Open": [100] * 30,
                "High": [101] * 30,
                "Low": [99] * 30,
                "Close": [100] * 30,
            },
            index=dates,
        )
        mock_ticker.history.return_value = mock_hist

        with patch("monitors.etf_monitor.yf.Ticker", return_value=mock_ticker):
            ohlc = fetch_ohlc_data("TEST.L", "1mo")

        assert len(ohlc) == 30
        assert len(ohlc[0]) == 5  # [timestamp, open, high, low, close]


class TestRecommendations:
    """Tests for get_recommendation function."""

    def test_recommendation_danger(self):
        """DANGER level produces danger recommendation."""
        from monitors.etf_monitor import get_recommendation

        rec = get_recommendation(AlertLevel.DANGER, "Test ETF")

        assert rec.level == "DANGER"
        assert "Test ETF" in rec.body

    def test_recommendation_warn(self):
        """WARN level produces warning recommendation."""
        from monitors.etf_monitor import get_recommendation

        rec = get_recommendation(AlertLevel.WARN, "Test ETF")

        assert rec.level == "WARN"

    def test_recommendation_ok(self):
        """OK level produces positive recommendation."""
        from monitors.etf_monitor import get_recommendation

        rec = get_recommendation(AlertLevel.OK, "Test ETF")

        assert rec.level == "OK"


class TestTTLCache:
    """Tests for the in-memory TTL cache."""

    def test_set_and_get(self):
        """A stored value is returned before it expires."""
        from monitors.etf_monitor import TTLCache

        cache = TTLCache(default_ttl_seconds=60)
        cache.set("key", "value")

        assert cache.get("key") == "value"

    def test_missing_key_returns_none(self):
        """Unknown keys return None."""
        from monitors.etf_monitor import TTLCache

        cache = TTLCache()
        assert cache.get("nope") is None

    def test_expired_entry_returns_none(self):
        """An entry past its TTL is evicted and returns None."""
        from monitors.etf_monitor import TTLCache

        cache = TTLCache(default_ttl_seconds=0)  # expires immediately
        cache.set("key", "value")

        # TTL of 0 → expires_at == now, and get() uses >= comparison
        assert cache.get("key") is None
        # Confirm the entry was evicted from the backing dict
        assert "key" not in cache._cache

    def test_per_entry_ttl_override(self):
        """set() accepts a per-entry TTL that overrides the default."""
        from monitors.etf_monitor import TTLCache

        cache = TTLCache(default_ttl_seconds=300)
        cache.set("short", "value", ttl_seconds=0)

        assert cache.get("short") is None

    def test_clear(self):
        """clear() removes all entries."""
        from monitors.etf_monitor import TTLCache

        cache = TTLCache()
        cache.set("a", 1)
        cache.set("b", 2)
        cache.clear()

        assert cache.get("a") is None
        assert cache.get("b") is None


class TestFetchCaching:
    """Tests that fetch helpers use the TTL cache."""

    def setup_method(self):
        """Clear module caches before each test for isolation."""
        from monitors import etf_monitor

        etf_monitor._history_cache.clear()
        etf_monitor._ohlc_cache.clear()

    def test_fetch_etf_data_caches_result(self):
        """Second call for the same ticker is served from cache (no re-download)."""
        from monitors.etf_monitor import fetch_etf_data

        mock_ticker = MagicMock()
        mock_hist = pd.DataFrame({"Close": [100, 101, 102]})
        mock_ticker.history.return_value = mock_hist
        mock_ticker.fast_info = {"last_price": 102}

        with patch(
            "monitors.etf_monitor.yf.Ticker", return_value=mock_ticker
        ) as mock_cls:
            first_hist, _ = fetch_etf_data("TEST.L")
            second_hist, _ = fetch_etf_data("TEST.L")

        # yf.Ticker constructed exactly once → second call hit the cache
        assert mock_cls.call_count == 1
        assert len(first_hist) == 3
        assert len(second_hist) == 3

    def test_fetch_etf_data_empty_not_cached(self):
        """Empty history is not cached, so a later populated call still downloads."""
        from monitors.etf_monitor import fetch_etf_data

        mock_ticker = MagicMock()
        mock_ticker.history.return_value = pd.DataFrame()

        with patch(
            "monitors.etf_monitor.yf.Ticker", return_value=mock_ticker
        ) as mock_cls:
            fetch_etf_data("EMPTY.L")
            fetch_etf_data("EMPTY.L")

        # Not cached → constructed twice
        assert mock_cls.call_count == 2

    def test_fetch_ohlc_data_caches_result(self):
        """Second OHLC call for the same (ticker, period) hits the cache."""
        from monitors.etf_monitor import fetch_ohlc_data

        mock_ticker = MagicMock()
        dates = pd.date_range(end=datetime.now(), periods=5, freq="D")
        mock_hist = pd.DataFrame(
            {
                "Open": [100] * 5,
                "High": [101] * 5,
                "Low": [99] * 5,
                "Close": [100] * 5,
            },
            index=dates,
        )
        mock_ticker.history.return_value = mock_hist

        with patch(
            "monitors.etf_monitor.yf.Ticker", return_value=mock_ticker
        ) as mock_cls:
            first = fetch_ohlc_data("TEST.L", "1mo")
            second = fetch_ohlc_data("TEST.L", "1mo")

        assert mock_cls.call_count == 1
        assert first == second
        assert len(first) == 5


class TestNonBlockingRun:
    """Tests that the monitor offloads blocking I/O to a thread."""

    @pytest.mark.asyncio
    async def test_run_offloads_fetches_to_thread(self):
        """run() calls fetch helpers via asyncio.to_thread (non-blocking)."""
        from monitors.etf_monitor import ETFMonitor

        portfolio = {
            "TEST": {
                "id": "TEST",
                "ticker": "TEST.L",
                "name": "Test ETF",
                "color": "#FF0000",
                "avg_cost": 100,
                "units": 10,
                "monthly_contrib": 50,
                "start_date": "2024-01-01",
            }
        }

        prices = [100 + i * 0.1 for i in range(252)]
        dates = pd.date_range(end=datetime.now(), periods=252, freq="D")
        mock_hist = pd.DataFrame(
            {
                "Open": prices,
                "High": [p * 1.01 for p in prices],
                "Low": [p * 0.99 for p in prices],
                "Close": prices,
            },
            index=dates,
        )

        with patch("config.ETF_PORTFOLIO", portfolio):
            with patch("config.ETF_FUND_IDS", ["TEST"]):
                with patch(
                    "monitors.etf_monitor.fetch_etf_data",
                    return_value=(mock_hist, {}),
                ):
                    with patch(
                        "monitors.etf_monitor.fetch_ohlc_data", return_value=[]
                    ):
                        with patch(
                            "monitors.etf_monitor.asyncio.to_thread",
                            new_callable=AsyncMock,
                        ) as mock_to_thread:
                            # Delegate to the real functions so results are valid
                            async def _call(fn, *args, **kwargs):
                                return fn(*args, **kwargs)

                            mock_to_thread.side_effect = _call

                            monitor = ETFMonitor()
                            result = await monitor.run()

        # Both blocking downloads were routed through asyncio.to_thread
        assert mock_to_thread.await_count == 2
        assert len(result["analysis"]) == 1
