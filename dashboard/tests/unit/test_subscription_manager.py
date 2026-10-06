"""Unit tests for subscription_manager.py - external service subscription cache."""

import time
from unittest.mock import MagicMock, patch

from subscription_manager import (
    CachedData,
    Subscription,
    SubscriptionConfig,
    SubscriptionManager,
)


class TestSubscriptionConfig:
    def test_default_values(self):
        config = SubscriptionConfig()
        assert config.melcloud_interval == 30
        assert config.outdoor_interval == 600
        assert config.max_cache_age == 3600


class TestSubscription:
    def test_default_values(self):
        sub = Subscription(name="test", fetcher=lambda: None, interval=60)
        assert sub.name == "test"
        assert sub.interval == 60
        assert sub.last_update == 0.0
        assert sub.enabled is True
        assert sub.error_count == 0


class TestCachedData:
    def test_age_calculation(self):
        now = time.time()
        data = CachedData(
            service="test", data={"key": "value"}, timestamp=now - 10, size_bytes=100
        )
        assert abs(data.age - 10) < 1  # Allow 1 second tolerance

    def test_is_stale_returns_true_when_old(self):
        old_time = time.time() - 7200  # 2 hours ago
        data = CachedData(service="test", data={}, timestamp=old_time, size_bytes=0)
        assert data.is_stale(3600) is True  # 1 hour max age

    def test_is_stale_returns_false_when_fresh(self):
        recent_time = time.time() - 60  # 1 minute ago
        data = CachedData(service="test", data={}, timestamp=recent_time, size_bytes=0)
        assert data.is_stale(3600) is False


class TestSubscriptionManager:
    def test_init(self):
        config = SubscriptionConfig()
        manager = SubscriptionManager(config)
        assert manager.config == config
        assert manager.subscriptions == {}
        assert manager.cache == {}
        assert manager._running is False

    def test_subscribe_adds_service(self):
        manager = SubscriptionManager(SubscriptionConfig())
        fetcher = MagicMock(return_value={"data": "test"})
        manager.subscribe("test_service", fetcher, interval=120)

        assert "test_service" in manager.subscriptions
        sub = manager.subscriptions["test_service"]
        assert sub.name == "test_service"
        assert sub.interval == 120

    def test_subscribe_uses_default_interval(self):
        config = SubscriptionConfig(melcloud_interval=45)
        manager = SubscriptionManager(config)
        manager.subscribe("test", lambda: None)

        assert manager.subscriptions["test"].interval == 45

    def test_get_cached_returns_none_for_missing(self):
        manager = SubscriptionManager(SubscriptionConfig())
        result = manager.get_cached("nonexistent")
        assert result is None

    def test_get_cached_returns_default_for_missing(self):
        manager = SubscriptionManager(SubscriptionConfig())
        result = manager.get_cached("nonexistent", default={"fallback": True})
        assert result == {"fallback": True}

    def test_get_cached_returns_data(self):
        manager = SubscriptionManager(SubscriptionConfig())
        manager.cache["test"] = CachedData(
            service="test", data={"key": "value"}, timestamp=time.time(), size_bytes=50
        )
        result = manager.get_cached("test")
        assert result == {"key": "value"}

    def test_update_service_populates_cache(self):
        manager = SubscriptionManager(SubscriptionConfig())
        fetcher = MagicMock(return_value={"result": 42})
        sub = Subscription(name="test", fetcher=fetcher, interval=30)
        manager.subscriptions["test"] = sub

        manager._update_service("test", sub)

        assert "test" in manager.cache
        assert manager.cache["test"].data == {"result": 42}
        assert sub.error_count == 0

    def test_update_service_handles_errors(self):
        manager = SubscriptionManager(SubscriptionConfig())
        fetcher = MagicMock(side_effect=Exception("Network error"))
        sub = Subscription(name="test", fetcher=fetcher, interval=30)
        manager.subscriptions["test"] = sub

        manager._update_service("test", sub)

        assert "test" not in manager.cache
        assert sub.error_count == 1

    def test_force_update_starts_background_thread(self):
        manager = SubscriptionManager(SubscriptionConfig())
        fetcher = MagicMock(return_value={"data": "fresh"})
        manager.subscribe("test", fetcher)

        with patch("threading.Thread") as mock_thread:
            mock_thread_instance = MagicMock()
            mock_thread.return_value = mock_thread_instance
            manager.force_update("test")
            mock_thread.assert_called_once()
            mock_thread_instance.start.assert_called_once()

    def test_force_update_warns_for_unknown_service(self):
        manager = SubscriptionManager(SubscriptionConfig())
        with patch("subscription_manager.logger") as mock_logger:
            manager.force_update("unknown")
            mock_logger.warning.assert_called()

    def test_get_stats_returns_structure(self):
        manager = SubscriptionManager(SubscriptionConfig())
        manager.subscribe("test", lambda: None, interval=60)
        manager.cache["test"] = CachedData(
            service="test", data={}, timestamp=time.time(), size_bytes=100
        )

        stats = manager.get_stats()

        assert stats["subscriptions"] == 1
        assert stats["cached_services"] == 1
        assert stats["total_cache_size_bytes"] == 100
        assert "total_cache_size_kb" in stats
        assert len(stats["services"]) == 1

    def test_cleanup_stale_cache_removes_old_entries(self):
        manager = SubscriptionManager(SubscriptionConfig(max_cache_age=3600))
        manager.cache["old"] = CachedData(
            service="old", data={}, timestamp=time.time() - 7200, size_bytes=100
        )
        manager.cache["fresh"] = CachedData(
            service="fresh", data={}, timestamp=time.time(), size_bytes=100
        )

        manager.cleanup_stale_cache()

        assert "old" not in manager.cache
        assert "fresh" in manager.cache

    def test_start_sets_running_flag(self):
        manager = SubscriptionManager(SubscriptionConfig())
        with patch.object(manager, "_update_all_services"):
            with patch("threading.Thread") as mock_thread:
                mock_thread.return_value = MagicMock()
                manager.start()
                assert manager._running is True
                manager.stop()

    def test_stop_clears_running_flag(self):
        manager = SubscriptionManager(SubscriptionConfig())
        manager._running = True
        manager._thread = MagicMock()
        manager.stop()
        assert manager._running is False

    def test_update_all_services_respects_interval(self):
        manager = SubscriptionManager(SubscriptionConfig())
        fetcher = MagicMock(return_value={})
        manager.subscribe("test", fetcher, interval=3600)

        # First update
        manager._update_all_services()
        assert fetcher.call_count == 1

        # Immediate second call should not update (not enough time passed)
        manager._update_all_services()
        assert fetcher.call_count == 1

    def test_update_all_services_skips_disabled(self):
        manager = SubscriptionManager(SubscriptionConfig())
        fetcher = MagicMock(return_value={})
        manager.subscribe("test", fetcher, interval=0)
        manager.subscriptions["test"].enabled = False

        manager._update_all_services()
        assert fetcher.call_count == 0
