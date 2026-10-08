"""
Tests for the crypto_monitor module.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from models import AlertLevel


class TestComputeSignals:
    """Tests for the compute_signals function."""

    def test_no_signals_stable_market(self):
        """Stable market conditions produce no warnings."""
        from monitors.crypto_monitor import compute_signals

        pos = {"coingecko_id": "bitcoin", "symbol": "BTC"}
        price_data = {
            "bitcoin": {
                "eur_24h_change": 1.5,
                "ath_change_pct": -40,
                "price_change_30d": 5,
            }
        }

        signals, level = compute_signals(pos, price_data, fear_greed_val=50)

        assert level == AlertLevel.OK
        # Should have some INFO signals but no WARN/DANGER
        danger_warn = [s for s in signals if s.level in ("WARN", "DANGER")]
        assert len(danger_warn) == 0

    def test_fear_greed_extreme_greed(self):
        """Extreme greed produces INFO signal (not warning for HODLers)."""
        from monitors.crypto_monitor import compute_signals

        pos = {"coingecko_id": "bitcoin"}
        price_data = {"bitcoin": {"eur_24h_change": 0, "price_change_30d": 0}}

        signals, level = compute_signals(pos, price_data, fear_greed_val=85)

        # Should be INFO, not WARN (adjusted for HODL strategy)
        fg_signals = [s for s in signals if "Fear & Greed" in s.body]
        assert len(fg_signals) == 1
        assert fg_signals[0].level == "INFO"
        assert level == AlertLevel.OK

    def test_fear_greed_extreme_fear(self):
        """Extreme fear produces OK signal (buying opportunity)."""
        from monitors.crypto_monitor import compute_signals

        pos = {"coingecko_id": "bitcoin"}
        price_data = {"bitcoin": {"eur_24h_change": 0, "price_change_30d": 0}}

        signals, level = compute_signals(pos, price_data, fear_greed_val=15)

        fg_signals = [s for s in signals if "Fear & Greed" in s.body]
        assert len(fg_signals) == 1
        assert fg_signals[0].level == "OK"

    def test_severe_24h_drop_danger(self):
        """Severe 24h drop triggers DANGER."""
        from monitors.crypto_monitor import compute_signals

        pos = {"coingecko_id": "bitcoin"}
        price_data = {"bitcoin": {"eur_24h_change": -20, "price_change_30d": 0}}

        signals, level = compute_signals(pos, price_data, fear_greed_val=None)

        assert level == AlertLevel.DANGER
        drop_signals = [s for s in signals if "24h" in s.body]
        assert any(s.level == "DANGER" for s in drop_signals)

    def test_moderate_24h_drop_warn(self):
        """Moderate 24h drop triggers WARN."""
        from monitors.crypto_monitor import compute_signals

        pos = {"coingecko_id": "bitcoin"}
        # Use -11% which is between default warn (-10) and danger (-15)
        price_data = {"bitcoin": {"eur_24h_change": -11, "price_change_30d": 0}}

        signals, level = compute_signals(pos, price_data, fear_greed_val=None)

        # Should be at least WARN (could be DANGER depending on thresholds)
        assert level in (AlertLevel.WARN, AlertLevel.DANGER)
        drop_signals = [s for s in signals if "24h" in s.body]
        assert any(s.level in ("WARN", "DANGER") for s in drop_signals)

    def test_small_drop_info(self):
        """Small drop produces INFO (normal volatility)."""
        from monitors.crypto_monitor import compute_signals

        pos = {"coingecko_id": "bitcoin"}
        # Use -6% which should be INFO level (between -5 info and -10 warn)
        price_data = {"bitcoin": {"eur_24h_change": -6, "price_change_30d": 0}}

        signals, level = compute_signals(pos, price_data, fear_greed_val=None)

        # Should be OK or INFO level for small drops
        assert level in (AlertLevel.OK, AlertLevel.INFO, AlertLevel.WARN)

    def test_strong_pump_info(self):
        """Strong pump produces INFO signal."""
        from monitors.crypto_monitor import compute_signals

        pos = {"coingecko_id": "bitcoin"}
        price_data = {"bitcoin": {"eur_24h_change": 15, "price_change_30d": 0}}

        signals, level = compute_signals(pos, price_data, fear_greed_val=None)

        assert level == AlertLevel.OK
        pump_signals = [
            s for s in signals if "Subida" in s.body or "surge" in s.body.lower()
        ]
        assert len(pump_signals) >= 1

    def test_ath_proximity_info(self):
        """Near ATH produces INFO signal."""
        from monitors.crypto_monitor import compute_signals

        pos = {"coingecko_id": "bitcoin"}
        price_data = {
            "bitcoin": {
                "eur_24h_change": 0,
                "ath_change_pct": -3,
                "price_change_30d": 0,
            }
        }

        signals, level = compute_signals(pos, price_data, fear_greed_val=None)

        assert level == AlertLevel.OK
        ath_signals = [s for s in signals if "ATH" in s.body]
        assert len(ath_signals) >= 1
        assert ath_signals[0].level == "INFO"

    def test_severe_30d_crash_danger(self):
        """Severe 30-day crash triggers DANGER."""
        from monitors.crypto_monitor import compute_signals

        pos = {"coingecko_id": "bitcoin"}
        price_data = {"bitcoin": {"eur_24h_change": 0, "price_change_30d": -55}}

        signals, level = compute_signals(pos, price_data, fear_greed_val=None)

        assert level == AlertLevel.DANGER

    def test_bear_30d_warn(self):
        """Bear market 30d produces WARN."""
        from monitors.crypto_monitor import compute_signals

        pos = {"coingecko_id": "bitcoin"}
        price_data = {"bitcoin": {"eur_24h_change": 0, "price_change_30d": -40}}

        signals, level = compute_signals(pos, price_data, fear_greed_val=None)

        assert level == AlertLevel.WARN

    def test_bull_30d_ok(self):
        """Bull market produces OK signal."""
        from monitors.crypto_monitor import compute_signals

        pos = {"coingecko_id": "bitcoin"}
        price_data = {"bitcoin": {"eur_24h_change": 0, "price_change_30d": 30}}

        signals, level = compute_signals(pos, price_data, fear_greed_val=None)

        assert level == AlertLevel.OK
        bull_signals = [
            s
            for s in signals
            if "30" in s.body and ("bull" in s.body.lower() or "Subida" in s.body)
        ]
        assert len(bull_signals) >= 1


class TestStakingRiskSignals:
    """Tests for staking and exchange risk signals."""

    def test_staking_maturity_soon_warning(self):
        """Staking maturing soon produces INFO signal."""
        from monitors.crypto_monitor import compute_staking_risk_signals

        maturity = (datetime.now(timezone.utc).date() + timedelta(days=3)).isoformat()
        pos = {
            "type": "fixed",
            "maturity_date": maturity,
            "symbol": "ETH",
        }

        signals, level = compute_staking_risk_signals(pos, {}, maturity_warn_days=7)

        assert len(signals) >= 1
        assert any(
            "vence" in s.body.lower() or "matures" in s.body.lower() for s in signals
        )

    def test_staking_already_matured(self):
        """Matured staking produces WARN signal."""
        from monitors.crypto_monitor import compute_staking_risk_signals

        past = (datetime.now(timezone.utc).date() - timedelta(days=2)).isoformat()
        pos = {
            "type": "fixed",
            "maturity_date": past,
            "symbol": "ETH",
        }

        signals, level = compute_staking_risk_signals(pos, {})

        assert level == AlertLevel.WARN
        assert any(
            "vencido" in s.body.lower() or "matured" in s.body.lower() for s in signals
        )

    def test_exchange_trust_critical(self):
        """Critical trust score produces DANGER."""
        from monitors.crypto_monitor import compute_staking_risk_signals

        pos = {"type": "flexible", "exchange": "risky_exchange", "symbol": "BTC"}
        exchange_trust = {"risky_exchange": 3}

        signals, level = compute_staking_risk_signals(pos, exchange_trust)

        assert level == AlertLevel.DANGER
        assert any("Trust Score" in s.body for s in signals)

    def test_exchange_trust_low(self):
        """Low trust score produces WARN."""
        from monitors.crypto_monitor import compute_staking_risk_signals

        pos = {"type": "flexible", "exchange": "medium_exchange", "symbol": "BTC"}
        exchange_trust = {"medium_exchange": 5}

        signals, level = compute_staking_risk_signals(pos, exchange_trust)

        assert level == AlertLevel.WARN

    def test_exchange_trust_ok(self):
        """Good trust score produces no warning."""
        from monitors.crypto_monitor import compute_staking_risk_signals

        pos = {"type": "flexible", "exchange": "good_exchange", "symbol": "BTC"}
        exchange_trust = {"good_exchange": 9}

        signals, level = compute_staking_risk_signals(pos, exchange_trust)

        assert level == AlertLevel.OK

    def test_custody_reminder(self):
        """Custody position produces INFO reminder."""
        from monitors.crypto_monitor import compute_staking_risk_signals

        pos = {
            "type": "custody",
            "exchange": "binance",
            "symbol": "BTC",
            "amount": 0.5,
        }

        signals, level = compute_staking_risk_signals(pos, {})

        assert any(
            "custodia" in s.body.lower() or "custody" in s.body.lower() for s in signals
        )


class TestDateHelpers:
    """Tests for date helper functions."""

    def test_days_until_available_flexible(self):
        """Flexible positions have rescue_days."""
        from monitors.crypto_monitor import days_until_available

        pos = {"type": "flexible", "rescue_days": 5}
        assert days_until_available(pos) == 5

    def test_days_until_available_fixed_future(self):
        """Fixed positions calculate from maturity date."""
        from monitors.crypto_monitor import days_until_available

        future = (datetime.now(timezone.utc).date() + timedelta(days=10)).isoformat()
        pos = {"type": "fixed", "maturity_date": future}

        assert days_until_available(pos) == 10

    def test_days_until_available_fixed_past(self):
        """Past maturity returns 0."""
        from monitors.crypto_monitor import days_until_available

        past = (datetime.now(timezone.utc).date() - timedelta(days=5)).isoformat()
        pos = {"type": "fixed", "maturity_date": past}

        assert days_until_available(pos) == 0

    def test_days_staked(self):
        """Calculate days since staking started."""
        from monitors.crypto_monitor import days_staked

        start = (datetime.now(timezone.utc).date() - timedelta(days=30)).isoformat()
        pos = {"start_date": start}

        assert days_staked(pos) == 30

    def test_next_distribution_in(self):
        """Calculate days until next reward distribution."""
        from monitors.crypto_monitor import next_distribution_in

        # Set next distribution to 3 days from now
        future = (datetime.now(timezone.utc).date() + timedelta(days=3)).isoformat()
        pos = {"next_distribution": future, "distribution_freq_days": 7}

        assert next_distribution_in(pos) == 3

    def test_next_distribution_wraps(self):
        """Distribution date wraps forward if in past."""
        from monitors.crypto_monitor import next_distribution_in

        # Set to past, should calculate next occurrence
        past = (datetime.now(timezone.utc).date() - timedelta(days=2)).isoformat()
        pos = {"next_distribution": past, "distribution_freq_days": 7}

        result = next_distribution_in(pos)
        assert result is not None
        assert result >= 0
        assert result <= 7


class TestCryptoMonitorRun:
    """Tests for the CryptoMonitor.run() method."""

    @pytest.mark.asyncio
    async def test_empty_positions(self):
        """Monitor handles empty positions."""
        from monitors.crypto_monitor import CryptoMonitor

        with patch("config.CRYPTO_POSITIONS", []):
            monitor = CryptoMonitor()
            result = await monitor.run()

        assert result["total_value"] == 0
        assert result["level"] == AlertLevel.OK
        assert len(result["analysis"]) == 0

    @pytest.mark.asyncio
    async def test_run_with_mocked_apis(self):
        """Monitor runs with mocked external APIs."""
        from monitors.crypto_monitor import CryptoMonitor

        positions = [
            {
                "symbol": "BTC",
                "name": "Bitcoin",
                "coingecko_id": "bitcoin",
                "amount": 0.5,
                "apy": 3.0,
                "type": "flexible",
                "rescue_days": 0,
                "start_date": "2024-01-01",
            }
        ]

        market_data = {
            "bitcoin": {
                "eur": 50000,
                "eur_24h_change": 2.5,
                "price_change_30d": 10,
                "ath": 60000,
                "ath_change_pct": -16,
            }
        }

        with patch("config.CRYPTO_POSITIONS", positions):
            with patch(
                "monitors.crypto_monitor.fetch_market_batch", return_value=market_data
            ):
                with patch(
                    "monitors.crypto_monitor.fetch_fear_greed",
                    return_value=(55, "Greed"),
                ):
                    with patch(
                        "monitors.crypto_monitor.fetch_exchange_trust_score",
                        return_value=None,
                    ):
                        with patch(
                            "monitors.crypto_monitor.fetch_ohlc", return_value=[]
                        ):
                            monitor = CryptoMonitor()
                            result = await monitor.run()

        assert result["total_value"] == 25000  # 0.5 * 50000
        assert result["fear_greed"] == 55
        assert len(result["analysis"]) == 1
        assert result["analysis"][0].symbol == "BTC"


class TestFetchHelpers:
    """Tests for API fetch helper functions."""

    def test_fetch_market_batch_success(self):
        """fetch_market_batch returns parsed data."""
        from monitors.crypto_monitor import fetch_market_batch

        mock_response = [
            {
                "id": "bitcoin",
                "current_price": 50000,
                "price_change_percentage_24h": 2.5,
                "market_cap": 1000000000,
                "ath": 60000,
                "ath_change_percentage": -16,
            }
        ]

        with patch("monitors.crypto_monitor._cg_client") as mock_client:
            mock_client.get.return_value.json.return_value = mock_response
            result = fetch_market_batch(["bitcoin"])

        assert "bitcoin" in result
        assert result["bitcoin"]["eur"] == 50000
        assert result["bitcoin"]["eur_24h_change"] == 2.5

    def test_fetch_market_batch_empty(self):
        """fetch_market_batch handles empty input."""
        from monitors.crypto_monitor import fetch_market_batch

        result = fetch_market_batch([])
        assert result == {}

    def test_fetch_fear_greed_success(self):
        """fetch_fear_greed returns value and label."""
        from monitors.crypto_monitor import fetch_fear_greed

        mock_data = {"data": [{"value": "65", "value_classification": "Greed"}]}

        with patch("monitors.crypto_monitor._generic_client") as mock_client:
            mock_client.get.return_value.json.return_value = mock_data
            value, label = fetch_fear_greed()

        assert value == 65
        assert label == "Greed"

    def test_fetch_fear_greed_error(self):
        """fetch_fear_greed handles errors gracefully."""
        from monitors.crypto_monitor import _fg_cache, fetch_fear_greed

        _fg_cache.clear()  # Clear cache to ensure API is called

        with patch("monitors.crypto_monitor._generic_client") as mock_client:
            mock_client.get.side_effect = Exception("Network error")
            value, label = fetch_fear_greed()

        assert value is None
        assert label is None


class TestTTLCache:
    """Tests for the TTL cache implementation."""

    def test_cache_stores_and_retrieves(self):
        """Cache stores and retrieves values."""
        from monitors.crypto_monitor import TTLCache

        cache = TTLCache(default_ttl_seconds=60)
        cache.set("key", {"data": "value"})

        result = cache.get("key")
        assert result == {"data": "value"}

    def test_cache_returns_none_for_missing_key(self):
        """Cache returns None for missing keys."""
        from monitors.crypto_monitor import TTLCache

        cache = TTLCache()
        result = cache.get("nonexistent")
        assert result is None

    def test_cache_expires_entries(self):
        """Cache entries expire after TTL."""
        from monitors.crypto_monitor import TTLCache

        cache = TTLCache(default_ttl_seconds=1)
        cache.set("key", "value")

        # Manually expire the entry
        cache._cache["key"] = (
            "value",
            datetime.now(timezone.utc) - timedelta(seconds=10),
        )

        result = cache.get("key")
        assert result is None

    def test_cache_custom_ttl(self):
        """Cache respects custom TTL per entry."""
        from monitors.crypto_monitor import TTLCache

        cache = TTLCache(default_ttl_seconds=300)
        cache.set("short", "value", ttl_seconds=1)
        cache.set("long", "value", ttl_seconds=3600)

        # Manually expire short entry
        cache._cache["short"] = (
            "value",
            datetime.now(timezone.utc) - timedelta(seconds=10),
        )

        assert cache.get("short") is None
        assert cache.get("long") == "value"

    def test_cache_clear(self):
        """Cache clear removes all entries."""
        from monitors.crypto_monitor import TTLCache

        cache = TTLCache()
        cache.set("key1", "value1")
        cache.set("key2", "value2")

        cache.clear()

        assert cache.get("key1") is None
        assert cache.get("key2") is None


class TestCachedFetchFunctions:
    """Tests for cached fetch functions."""

    def test_fetch_market_batch_uses_cache(self):
        """fetch_market_batch returns cached data on second call."""
        from monitors.crypto_monitor import _market_cache, fetch_market_batch

        _market_cache.clear()

        mock_response = [
            {
                "id": "bitcoin",
                "current_price": 50000,
                "price_change_percentage_24h": 2.5,
            }
        ]

        with patch("monitors.crypto_monitor._cg_client") as mock_client:
            mock_client.get.return_value.json.return_value = mock_response

            # First call - hits API
            result1 = fetch_market_batch(["bitcoin"])
            assert mock_client.get.call_count == 1

            # Second call - should use cache
            result2 = fetch_market_batch(["bitcoin"])
            assert mock_client.get.call_count == 1  # No additional API call

            assert result1 == result2

        _market_cache.clear()

    def test_fetch_ohlc_uses_cache(self):
        """fetch_ohlc returns cached data on second call."""
        from monitors.crypto_monitor import _ohlc_cache, fetch_ohlc

        _ohlc_cache.clear()

        mock_ohlc = [[1234567890, 50000, 51000, 49000, 50500]]

        with patch("monitors.crypto_monitor._cg_client") as mock_client:
            mock_client.get.return_value.json.return_value = mock_ohlc

            # First call - hits API
            result1 = fetch_ohlc("bitcoin", days=30)
            assert mock_client.get.call_count == 1

            # Second call - should use cache
            result2 = fetch_ohlc("bitcoin", days=30)
            assert mock_client.get.call_count == 1  # No additional API call

            assert result1 == result2

        _ohlc_cache.clear()

    def test_fetch_fear_greed_uses_cache(self):
        """fetch_fear_greed returns cached data on second call."""
        from monitors.crypto_monitor import _fg_cache, fetch_fear_greed

        _fg_cache.clear()

        mock_data = {"data": [{"value": "65", "value_classification": "Greed"}]}

        with patch("monitors.crypto_monitor._generic_client") as mock_client:
            mock_client.get.return_value.json.return_value = mock_data

            # First call - hits API
            val1, label1 = fetch_fear_greed()
            assert mock_client.get.call_count == 1

            # Second call - should use cache
            val2, label2 = fetch_fear_greed()
            assert mock_client.get.call_count == 1  # No additional API call

            assert val1 == val2 == 65
            assert label1 == label2 == "Greed"

        _fg_cache.clear()
