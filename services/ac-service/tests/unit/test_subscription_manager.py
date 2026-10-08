"""Unit tests for SubscriptionManager.

Tests the subscription system that manages external API updates
and caching for services like MELCloud and outdoor temperature.
"""

import time
from unittest.mock import MagicMock

from smart_home_common.mqtt.subscription import (
    CachedData,
    SubscriptionConfig,
    SubscriptionManager,
)


class TestSubscriptionConfig:
    """Tests for SubscriptionConfig defaults."""

    def test_default_intervals(self):
        """Config should have sensible default intervals."""
        config = SubscriptionConfig()

        assert config.melcloud_interval == 30
        assert config.outdoor_interval == 600
        assert config.max_cache_age == 3600


class TestCachedData:
    """Tests for CachedData class."""

    def test_age_calculation(self):
        """age should return seconds since cache creation."""
        cached = CachedData(
            service="test",
            data={"temp": 25},
            timestamp=time.time() - 60,  # 60 seconds ago
            size_bytes=100,
        )

        assert 59 < cached.age < 61

    def test_is_stale_false_for_fresh_data(self):
        """is_stale should return False for recent data."""
        cached = CachedData(
            service="test",
            data={"temp": 25},
            timestamp=time.time(),
            size_bytes=100,
        )

        assert cached.is_stale(max_age=3600) is False

    def test_is_stale_true_for_old_data(self):
        """is_stale should return True for old data."""
        cached = CachedData(
            service="test",
            data={"temp": 25},
            timestamp=time.time() - 7200,  # 2 hours ago
            size_bytes=100,
        )

        assert cached.is_stale(max_age=3600) is True


class TestSubscriptionManager:
    """Tests for SubscriptionManager class."""

    def test_subscribe_adds_service(self):
        """subscribe should add a service to subscriptions."""
        config = SubscriptionConfig()
        manager = SubscriptionManager(config)

        fetcher = MagicMock(return_value={"data": "test"})
        manager.subscribe("test_service", fetcher, interval=60)

        assert "test_service" in manager.subscriptions
        assert manager.subscriptions["test_service"].interval == 60

    def test_subscribe_uses_default_interval(self):
        """subscribe should use config default if no interval given."""
        config = SubscriptionConfig(melcloud_interval=45)
        manager = SubscriptionManager(config)

        fetcher = MagicMock()
        manager.subscribe("test_service", fetcher)

        assert manager.subscriptions["test_service"].interval == 45

    def test_get_cached_returns_none_for_missing(self):
        """get_cached should return default for missing service."""
        config = SubscriptionConfig()
        manager = SubscriptionManager(config)

        result = manager.get_cached("nonexistent", default="default_value")

        assert result == "default_value"

    def test_get_cached_returns_data(self):
        """get_cached should return cached data."""
        config = SubscriptionConfig()
        manager = SubscriptionManager(config)

        # Manually add to cache
        manager.cache["test"] = CachedData(
            service="test",
            data={"temperature": 25.5},
            timestamp=time.time(),
            size_bytes=50,
        )

        result = manager.get_cached("test")

        assert result == {"temperature": 25.5}

    def test_get_cached_never_fetches(self):
        """get_cached should NEVER trigger a fetch."""
        config = SubscriptionConfig()
        manager = SubscriptionManager(config)

        fetcher = MagicMock(return_value={"data": "new"})
        manager.subscribe("test", fetcher)

        # Call get_cached without any prior update
        result = manager.get_cached("test", default={})

        # Fetcher should NOT have been called
        fetcher.assert_not_called()
        assert result == {}

    def test_force_update_triggers_fetch(self):
        """force_update should trigger immediate fetch."""
        config = SubscriptionConfig()
        manager = SubscriptionManager(config)

        fetcher = MagicMock(return_value={"data": "forced"})
        manager.subscribe("test", fetcher)

        # Force update
        manager.force_update("test")

        # Give the background thread time to complete
        time.sleep(0.2)

        # Fetcher should have been called
        assert fetcher.call_count >= 1

    def test_force_update_ignores_unknown_service(self):
        """force_update should silently ignore unknown services."""
        config = SubscriptionConfig()
        manager = SubscriptionManager(config)

        # Should not raise
        manager.force_update("nonexistent")

    def test_update_service_handles_exception(self):
        """_update_service should handle fetcher exceptions gracefully."""
        config = SubscriptionConfig()
        manager = SubscriptionManager(config)

        def failing_fetcher():
            raise ConnectionError("Network error")

        manager.subscribe("failing", failing_fetcher)
        sub = manager.subscriptions["failing"]

        # Should not raise
        manager._update_service("failing", sub)

        # Error count should increment
        assert sub.error_count == 1

    def test_update_service_resets_error_count_on_success(self):
        """_update_service should reset error count on success."""
        config = SubscriptionConfig()
        manager = SubscriptionManager(config)

        fetcher = MagicMock(return_value={"data": "success"})
        manager.subscribe("test", fetcher)
        sub = manager.subscriptions["test"]
        sub.error_count = 5  # Simulate previous errors

        manager._update_service("test", sub)

        assert sub.error_count == 0

    def test_get_stats_returns_info(self):
        """get_stats should return subscription statistics."""
        config = SubscriptionConfig()
        manager = SubscriptionManager(config)

        manager.subscribe("service1", MagicMock(), interval=30)
        manager.subscribe("service2", MagicMock(), interval=60)

        stats = manager.get_stats()

        assert stats["subscriptions"] == 2
        assert len(stats["services"]) == 2

    def test_cleanup_stale_cache(self):
        """cleanup_stale_cache should remove old entries."""
        config = SubscriptionConfig(max_cache_age=60)
        manager = SubscriptionManager(config)

        # Add stale entry
        manager.cache["stale"] = CachedData(
            service="stale",
            data={},
            timestamp=time.time() - 120,  # 2 minutes old
            size_bytes=10,
        )

        # Add fresh entry
        manager.cache["fresh"] = CachedData(
            service="fresh",
            data={},
            timestamp=time.time(),
            size_bytes=10,
        )

        manager.cleanup_stale_cache()

        assert "stale" not in manager.cache
        assert "fresh" in manager.cache


class TestSubscriptionManagerLifecycle:
    """Tests for start/stop lifecycle."""

    def test_start_begins_updates(self):
        """start should begin periodic updates."""
        config = SubscriptionConfig()
        manager = SubscriptionManager(config)

        fetcher = MagicMock(return_value={"data": "test"})
        manager.subscribe("test", fetcher, interval=1)

        manager.start()

        # Wait for initial update
        time.sleep(0.3)

        assert manager._running is True
        assert fetcher.call_count >= 1

        manager.stop()

    def test_stop_halts_updates(self):
        """stop should halt the update loop."""
        config = SubscriptionConfig()
        manager = SubscriptionManager(config)

        fetcher = MagicMock(return_value={"data": "test"})
        manager.subscribe("test", fetcher, interval=1)

        manager.start()
        time.sleep(0.1)
        manager.stop()

        assert manager._running is False

    def test_double_start_is_safe(self):
        """Calling start twice should not create multiple threads."""
        config = SubscriptionConfig()
        manager = SubscriptionManager(config)

        manager.start()
        thread1 = manager._thread
        manager.start()
        thread2 = manager._thread

        # Should be the same thread
        assert thread1 is thread2

        manager.stop()
