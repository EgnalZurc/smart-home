"""Tests for smart_home_common.mqtt.subscription — subscription management."""

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from smart_home_common.mqtt.subscription import (
    CachedData,
    Subscription,
    SubscriptionConfig,
    SubscriptionManager,
)


class TestSubscriptionConfig:
    """Tests for SubscriptionConfig dataclass."""

    def test_default_values(self):
        """Default configuration values are sensible."""
        config = SubscriptionConfig()
        assert config.melcloud_interval == 30
        assert config.outdoor_interval == 600
        assert config.max_cache_age == 3600

    def test_custom_values(self):
        """Custom configuration values are respected."""
        config = SubscriptionConfig(
            melcloud_interval=60,
            outdoor_interval=1200,
            max_cache_age=7200,
        )
        assert config.melcloud_interval == 60
        assert config.outdoor_interval == 1200
        assert config.max_cache_age == 7200


class TestSubscription:
    """Tests for Subscription dataclass."""

    def test_default_values(self):
        """Subscription has correct defaults."""
        sub = Subscription(name="test", fetcher=lambda: None, interval=30)
        assert sub.name == "test"
        assert sub.interval == 30
        assert sub.last_update == 0.0
        assert sub.enabled is True
        assert sub.error_count == 0

    def test_custom_values(self):
        """Subscription accepts custom values."""
        fetcher = MagicMock()
        sub = Subscription(
            name="custom",
            fetcher=fetcher,
            interval=120,
            last_update=1000.0,
            enabled=False,
            error_count=5,
        )
        assert sub.name == "custom"
        assert sub.fetcher is fetcher
        assert sub.interval == 120
        assert sub.last_update == 1000.0
        assert sub.enabled is False
        assert sub.error_count == 5


class TestCachedData:
    """Tests for CachedData dataclass."""

    def test_creation(self):
        """CachedData stores all fields correctly."""
        now = time.time()
        cached = CachedData(
            service="test_service",
            data={"key": "value"},
            timestamp=now,
            size_bytes=100,
        )
        assert cached.service == "test_service"
        assert cached.data == {"key": "value"}
        assert cached.timestamp == now
        assert cached.size_bytes == 100

    def test_age_property(self):
        """Age property calculates correctly."""
        old_time = time.time() - 60  # 60 seconds ago
        cached = CachedData(
            service="test",
            data=None,
            timestamp=old_time,
            size_bytes=0,
        )
        # Allow 1 second tolerance for test execution time
        assert 59 <= cached.age <= 62

    def test_is_stale_false(self):
        """Fresh data is not stale."""
        cached = CachedData(
            service="test",
            data=None,
            timestamp=time.time(),
            size_bytes=0,
        )
        assert cached.is_stale(max_age=3600) is False

    def test_is_stale_true(self):
        """Old data is stale."""
        old_time = time.time() - 7200  # 2 hours ago
        cached = CachedData(
            service="test",
            data=None,
            timestamp=old_time,
            size_bytes=0,
        )
        assert cached.is_stale(max_age=3600) is True


class TestSubscriptionManager:
    """Tests for SubscriptionManager class."""

    @pytest.fixture
    def config(self):
        """Standard test configuration."""
        return SubscriptionConfig(melcloud_interval=30, max_cache_age=3600)

    @pytest.fixture
    def manager(self, config):
        """SubscriptionManager instance for testing."""
        mgr = SubscriptionManager(config)
        yield mgr
        mgr.stop()  # Cleanup

    def test_initialization(self, config):
        """Manager initializes with empty subscriptions and cache."""
        manager = SubscriptionManager(config)
        assert manager.config is config
        assert manager.subscriptions == {}
        assert manager.cache == {}
        assert manager._running is False
        manager.stop()

    def test_subscribe_default_interval(self, manager):
        """Subscribe uses config default interval when not specified."""
        fetcher = MagicMock()
        manager.subscribe("test_service", fetcher)

        assert "test_service" in manager.subscriptions
        sub = manager.subscriptions["test_service"]
        assert sub.name == "test_service"
        assert sub.fetcher is fetcher
        assert sub.interval == manager.config.melcloud_interval
        assert sub.last_update == 0.0

    def test_subscribe_custom_interval(self, manager):
        """Subscribe respects custom interval."""
        fetcher = MagicMock()
        manager.subscribe("custom_service", fetcher, interval=120)

        sub = manager.subscriptions["custom_service"]
        assert sub.interval == 120

    def test_subscribe_multiple_services(self, manager):
        """Multiple services can be subscribed."""
        manager.subscribe("service1", lambda: "data1", interval=30)
        manager.subscribe("service2", lambda: "data2", interval=60)

        assert len(manager.subscriptions) == 2
        assert "service1" in manager.subscriptions
        assert "service2" in manager.subscriptions

    def test_get_cached_returns_none_for_unknown(self, manager):
        """get_cached returns None for unknown services."""
        result = manager.get_cached("nonexistent")
        assert result is None

    def test_get_cached_returns_default(self, manager):
        """get_cached returns custom default for unknown services."""
        result = manager.get_cached("nonexistent", default="fallback")
        assert result == "fallback"

    def test_get_cached_returns_data(self, manager):
        """get_cached returns cached data when available."""
        manager.cache["test"] = CachedData(
            service="test",
            data={"temperature": 22.5},
            timestamp=time.time(),
            size_bytes=50,
        )
        result = manager.get_cached("test")
        assert result == {"temperature": 22.5}

    def test_update_service_success(self, manager):
        """_update_service fetches and caches data successfully."""
        fetcher = MagicMock(return_value={"status": "ok"})
        sub = Subscription(name="test", fetcher=fetcher, interval=30)
        manager.subscriptions["test"] = sub

        manager._update_service("test", sub)

        fetcher.assert_called_once()
        assert "test" in manager.cache
        assert manager.cache["test"].data == {"status": "ok"}
        assert sub.error_count == 0
        assert sub.last_update > 0

    def test_update_service_error_increments_count(self, manager):
        """_update_service increments error count on failure."""
        fetcher = MagicMock(side_effect=Exception("Connection failed"))
        sub = Subscription(name="failing", fetcher=fetcher, interval=30)
        manager.subscriptions["failing"] = sub

        manager._update_service("failing", sub)

        assert sub.error_count == 1
        assert "failing" not in manager.cache

    def test_update_service_resets_error_count(self, manager):
        """Successful update resets error count."""
        fetcher = MagicMock(return_value="data")
        sub = Subscription(
            name="recovering", fetcher=fetcher, interval=30, error_count=5
        )
        manager.subscriptions["recovering"] = sub

        manager._update_service("recovering", sub)

        assert sub.error_count == 0

    def test_force_update_unknown_service(self, manager):
        """force_update handles unknown service gracefully."""
        # Should not raise
        manager.force_update("nonexistent")

    def test_force_update_triggers_update(self, manager):
        """force_update triggers background update."""
        fetcher = MagicMock(return_value="fresh_data")
        manager.subscribe("test", fetcher, interval=300)

        manager.force_update("test")

        # Give the background thread time to execute
        time.sleep(0.1)
        fetcher.assert_called()

    def test_start_sets_running_flag(self, manager):
        """start() sets _running flag and creates thread."""
        fetcher = MagicMock(return_value="data")
        manager.subscribe("test", fetcher)

        manager.start()

        assert manager._running is True
        assert manager._thread is not None
        assert manager._thread.is_alive()

    def test_start_twice_is_safe(self, manager):
        """Calling start() twice doesn't create duplicate threads."""
        manager.subscribe("test", lambda: "data")
        manager.start()
        first_thread = manager._thread

        manager.start()  # Second call

        assert manager._thread is first_thread

    def test_stop_clears_running_flag(self, manager):
        """stop() clears _running flag."""
        manager.subscribe("test", lambda: "data")
        manager.start()
        assert manager._running is True

        manager.stop()

        assert manager._running is False

    def test_get_stats(self, manager):
        """get_stats returns correct statistics."""
        fetcher1 = MagicMock(return_value="data1")
        fetcher2 = MagicMock(return_value="data2")
        manager.subscribe("service1", fetcher1, interval=30)
        manager.subscribe("service2", fetcher2, interval=60)

        # Manually add cache entry
        manager.cache["service1"] = CachedData(
            service="service1",
            data="cached_data",
            timestamp=time.time(),
            size_bytes=100,
        )

        stats = manager.get_stats()

        assert stats["subscriptions"] == 2
        assert stats["cached_services"] == 1
        assert stats["total_cache_size_bytes"] == 100
        assert len(stats["services"]) == 2

    def test_cleanup_stale_cache_removes_old(self, manager):
        """cleanup_stale_cache removes entries older than max_cache_age."""
        old_time = time.time() - 7200  # 2 hours ago
        manager.cache["stale"] = CachedData(
            service="stale",
            data="old_data",
            timestamp=old_time,
            size_bytes=50,
        )
        manager.cache["fresh"] = CachedData(
            service="fresh",
            data="new_data",
            timestamp=time.time(),
            size_bytes=50,
        )

        manager.cleanup_stale_cache()

        assert "stale" not in manager.cache
        assert "fresh" in manager.cache

    def test_update_all_services_respects_interval(self, manager):
        """_update_all_services only updates services that are due."""
        fetcher1 = MagicMock(return_value="data1")
        fetcher2 = MagicMock(return_value="data2")

        sub1 = Subscription(
            name="due", fetcher=fetcher1, interval=30, last_update=0
        )
        sub2 = Subscription(
            name="not_due",
            fetcher=fetcher2,
            interval=30,
            last_update=time.time(),
        )

        manager.subscriptions["due"] = sub1
        manager.subscriptions["not_due"] = sub2

        manager._update_all_services()

        fetcher1.assert_called_once()
        fetcher2.assert_not_called()

    def test_update_all_services_skips_disabled(self, manager):
        """_update_all_services skips disabled subscriptions."""
        fetcher = MagicMock(return_value="data")
        sub = Subscription(
            name="disabled",
            fetcher=fetcher,
            interval=30,
            last_update=0,
            enabled=False,
        )
        manager.subscriptions["disabled"] = sub

        manager._update_all_services()

        fetcher.assert_not_called()

    def test_thread_safety_get_cached(self, manager):
        """get_cached is thread-safe with concurrent access."""
        manager.cache["test"] = CachedData(
            service="test",
            data={"value": 42},
            timestamp=time.time(),
            size_bytes=20,
        )

        results = []

        def reader():
            for _ in range(100):
                result = manager.get_cached("test")
                results.append(result)

        threads = [threading.Thread(target=reader) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 500
        assert all(r == {"value": 42} for r in results)

    def test_cache_size_estimation(self, manager):
        """Cache size is estimated from data string representation."""
        fetcher = MagicMock(return_value={"key": "value" * 100})
        sub = Subscription(name="test", fetcher=fetcher, interval=30)
        manager.subscriptions["test"] = sub

        manager._update_service("test", sub)

        cached = manager.cache["test"]
        assert cached.size_bytes > 0

    def test_cache_size_none_data(self, manager):
        """Cache handles None data gracefully."""
        fetcher = MagicMock(return_value=None)
        sub = Subscription(name="test", fetcher=fetcher, interval=30)
        manager.subscriptions["test"] = sub

        manager._update_service("test", sub)

        cached = manager.cache["test"]
        assert cached.size_bytes == 0
        assert cached.data is None
