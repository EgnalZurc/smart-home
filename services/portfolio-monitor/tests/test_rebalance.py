"""
Tests for monitors.rebalance — target-allocation drift logic.

The module is pure (no I/O), so these tests build analyses and config entries
directly and assert on the returned dict.
"""

from monitors.rebalance import DEFAULT_THRESHOLD_PCT, compute_rebalance
from models import CryptoAnalysis, ETFAnalysis


def _etf(fund_id, value, target):
    return ETFAnalysis(
        fund_id=fund_id,
        ticker=f"{fund_id}.L",
        name=fund_id,
        color="#000000",
        current_value=value,
    ), {"id": fund_id, "target_allocation_pct": target}


def _crypto(symbol, value, target):
    return CryptoAnalysis(
        symbol=symbol,
        name=symbol,
        coingecko_id=symbol.lower(),
        current_value=value,
    ), {"symbol": symbol, "target_allocation_pct": target}


class TestComputeRebalance:
    def test_balanced_portfolio_no_flags(self):
        """Exact target weights produce zero deviation and no flags."""
        a1, f1 = _etf("VUAA", 40.0, 40.0)
        a2, f2 = _etf("VWCE", 30.0, 30.0)
        c1, p1 = _crypto("BTC", 30.0, 30.0)

        result = compute_rebalance([a1, a2], [c1], [f1, f2], [p1])

        assert result["total_value"] == 100.0
        assert result["needs_rebalance"] is False
        assert result["suggested_trades"] == []
        for pos in result["positions"]:
            assert pos["deviation"] == 0.0
            assert pos["needs_rebalance"] is False

    def test_allocation_is_percentage_of_total(self):
        """current_allocation = value / total * 100."""
        a1, f1 = _etf("VUAA", 60.0, 50.0)
        a2, f2 = _etf("VWCE", 40.0, 50.0)

        result = compute_rebalance([a1, a2], [], [f1, f2], [])

        by_sym = {p["symbol"]: p for p in result["positions"]}
        assert by_sym["VUAA"]["current_allocation"] == 60.0
        assert by_sym["VWCE"]["current_allocation"] == 40.0

    def test_deviation_above_threshold_flags(self):
        """A position drifting beyond the threshold is flagged + gets a trade."""
        # VUAA target 50%, actual 70% → +20 pts deviation (> default 5)
        a1, f1 = _etf("VUAA", 70.0, 50.0)
        a2, f2 = _etf("VWCE", 30.0, 50.0)

        result = compute_rebalance([a1, a2], [], [f1, f2], [])

        assert result["needs_rebalance"] is True
        by_sym = {p["symbol"]: p for p in result["positions"]}
        assert by_sym["VUAA"]["needs_rebalance"] is True
        assert by_sym["VUAA"]["deviation"] == 20.0
        assert by_sym["VWCE"]["needs_rebalance"] is True
        assert by_sym["VWCE"]["deviation"] == -20.0

        trades = {t["symbol"]: t for t in result["suggested_trades"]}
        # VUAA is 20€ over its 50€ target → SELL 20
        assert trades["VUAA"]["action"] == "SELL"
        assert trades["VUAA"]["amount_eur"] == 20.0
        # VWCE is 20€ under its 50€ target → BUY 20
        assert trades["VWCE"]["action"] == "BUY"
        assert trades["VWCE"]["amount_eur"] == 20.0

    def test_deviation_within_threshold_not_flagged(self):
        """A 3-pt drift with default 5-pt threshold does not flag."""
        a1, f1 = _etf("VUAA", 53.0, 50.0)
        a2, f2 = _etf("VWCE", 47.0, 50.0)

        result = compute_rebalance([a1, a2], [], [f1, f2], [])

        assert result["needs_rebalance"] is False
        assert result["suggested_trades"] == []

    def test_custom_threshold(self):
        """A tighter threshold flags a drift that the default would ignore."""
        a1, f1 = _etf("VUAA", 53.0, 50.0)
        a2, f2 = _etf("VWCE", 47.0, 50.0)

        result = compute_rebalance([a1, a2], [], [f1, f2], [], threshold_pct=2.0)

        assert result["threshold_pct"] == 2.0
        assert result["needs_rebalance"] is True

    def test_untargeted_positions_excluded(self):
        """Positions with target 0 (or missing) are not analysed."""
        a1, f1 = _etf("VUAA", 50.0, 50.0)
        a2, f2 = _etf("CASH", 50.0, 0.0)  # no target

        result = compute_rebalance([a1, a2], [], [f1, f2], [])

        symbols = {p["symbol"] for p in result["positions"]}
        assert symbols == {"VUAA"}
        # Only VUAA counts toward the total, so it is at 100% of tracked value.
        assert result["total_value"] == 50.0

    def test_empty_portfolio_no_flags(self):
        """Zero total value cannot flag (avoids spurious alerts)."""
        a1, f1 = _etf("VUAA", 0.0, 50.0)
        a2, f2 = _etf("VWCE", 0.0, 50.0)

        result = compute_rebalance([a1, a2], [], [f1, f2], [])

        assert result["total_value"] == 0.0
        assert result["needs_rebalance"] is False
        for pos in result["positions"]:
            assert pos["current_allocation"] == 0.0
            assert pos["needs_rebalance"] is False

    def test_mixed_etf_and_crypto(self):
        """ETF and crypto positions share one combined denominator."""
        a1, f1 = _etf("VUAA", 80.0, 50.0)
        c1, p1 = _crypto("BTC", 20.0, 50.0)

        result = compute_rebalance([a1], [c1], [f1], [p1])

        assert result["total_value"] == 100.0
        by_sym = {p["symbol"]: p for p in result["positions"]}
        assert by_sym["VUAA"]["current_allocation"] == 80.0
        assert by_sym["BTC"]["current_allocation"] == 20.0

    def test_default_threshold_constant(self):
        """The documented default is 5 percentage points."""
        assert DEFAULT_THRESHOLD_PCT == 5.0
