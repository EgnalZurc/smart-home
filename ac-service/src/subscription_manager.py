"""Subscription Manager for external services.

Manages subscriptions to external APIs with controlled cache and
periodic synchronized updates. Ensures GET requests always return
cached data (zero additional latency).
"""

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class SubscriptionConfig:
    """Configuration for subscription system."""
    
    # Default update intervals (seconds)
    melcloud_interval: int = 30      # AC state
    outdoor_interval: int = 600      # Outdoor temp (10 min)
    
    # Cache limits (memory control)
    max_cache_age: int = 3600        # 1 hour (stale data threshold)


@dataclass
class Subscription:
    """Represents a subscription to an external service."""
    
    name: str                    # Service name
    fetcher: Callable            # Function to fetch data
    interval: int                # Update interval (seconds)
    last_update: float = 0.0     # Last update timestamp
    enabled: bool = True         # Can be disabled
    error_count: int = 0         # Consecutive errors


@dataclass
class CachedData:
    """Cached data from a service."""
    
    service: str                 # Service name
    data: Any                    # Cached data
    timestamp: float             # Cache timestamp
    size_bytes: int              # Approximate size in bytes
    
    @property
    def age(self) -> float:
        """Age of cached data in seconds."""
        return time.time() - self.timestamp
    
    def is_stale(self, max_age: int) -> bool:
        """Check if cache is too old."""
        return self.age > max_age


class SubscriptionManager:
    """Central manager for all external service subscriptions.
    
    Features:
    - Periodic synchronized updates of all services
    - GET requests always return cached data (zero latency)
    - POST operations trigger immediate cache refresh
    - Memory-controlled cache with limits
    """
    
    def __init__(self, config: SubscriptionConfig):
        self.config = config
        self.subscriptions: dict[str, Subscription] = {}
        self.cache: dict[str, CachedData] = {}
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None
        
        logger.info("=== Subscription Manager Initialized ===")
    
    def subscribe(
        self, 
        service: str, 
        fetcher: Callable, 
        interval: int | None = None
    ):
        """Subscribe to a service.
        
        Args:
            service: Service name (e.g., "melcloud", "outdoor")
            fetcher: Function that returns data when called
            interval: Update interval in seconds (uses config default if None)
        """
        if interval is None:
            interval = self.config.melcloud_interval  # Default
        
        self.subscriptions[service] = Subscription(
            name=service,
            fetcher=fetcher,
            interval=interval,
            last_update=0.0
        )
        
        logger.info("✓ Subscribed to '%s' (interval=%ds)", service, interval)
    
    def start(self):
        """Start periodic updates."""
        if self._running:
            logger.warning("Subscription Manager already running")
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._update_loop, daemon=True)
        self._thread.start()
        
        logger.info("=== Subscription Manager Started ===")
        logger.info("Subscriptions active: %d", len(self.subscriptions))
        
        # Initial fetch for all subscriptions
        self._update_all_services()
    
    def stop(self):
        """Stop periodic updates."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Subscription Manager stopped")
    
    def get_cached(self, service: str, default=None) -> Any:
        """Get cached data (NEVER fetches, always returns cached).
        
        This method is designed for GET requests. It NEVER triggers
        an external API call, ensuring zero additional latency.
        
        Args:
            service: Service name
            default: Default value if not in cache
            
        Returns:
            Cached data or default
        """
        with self._lock:
            cached = self.cache.get(service)
            if cached is None:
                return default
            return cached.data
    
    def force_update(self, service: str):
        """Force immediate update of a specific service.
        
        Called after POST operations to refresh cache immediately.
        Runs in background (non-blocking).
        
        Args:
            service: Service name to update
        """
        sub = self.subscriptions.get(service)
        if sub is None:
            logger.warning("Cannot force update: service '%s' not subscribed", service)
            return
        
        # Update in background thread to avoid blocking
        threading.Thread(
            target=self._update_service,
            args=(service, sub),
            daemon=True
        ).start()
    
    def _update_loop(self):
        """Background thread that updates all subscriptions periodically."""
        while self._running:
            try:
                self._update_all_services()
            except Exception as e:
                logger.error("Error in subscription update loop: %s", e, exc_info=True)
            
            # Sleep for shortest interval (check more frequently)
            # We check every 5 seconds to ensure timely updates
            time.sleep(5)
    
    def _update_all_services(self):
        """Update all subscriptions that are due."""
        now = time.time()
        
        for service, sub in self.subscriptions.items():
            if not sub.enabled:
                continue
            
            # Check if update is due
            if now - sub.last_update >= sub.interval:
                self._update_service(service, sub)
    
    def _update_service(self, service: str, sub: Subscription):
        """Update a specific service by fetching fresh data.
        
        Args:
            service: Service name
            sub: Subscription object
        """
        try:
            # Fetch data using the subscription's fetcher
            data = sub.fetcher()
            
            # Estimate size (approximate)
            size = len(str(data).encode('utf-8')) if data is not None else 0
            
            # Update cache
            with self._lock:
                self.cache[service] = CachedData(
                    service=service,
                    data=data,
                    timestamp=time.time(),
                    size_bytes=size
                )
            
            # Update subscription metadata
            sub.last_update = time.time()
            sub.error_count = 0
            
            logger.debug("✓ Updated cache for '%s' (%d bytes)", service, size)
            
        except Exception as e:
            sub.error_count += 1
            logger.error(
                "✗ Failed to update '%s' (error %d): %s",
                service, sub.error_count, e
            )
    
    def get_stats(self) -> dict:
        """Get subscription manager statistics.
        
        Returns:
            Dict with subscription and cache statistics
        """
        with self._lock:
            total_size = sum(c.size_bytes for c in self.cache.values())
            
            return {
                "subscriptions": len(self.subscriptions),
                "cached_services": len(self.cache),
                "total_cache_size_bytes": total_size,
                "total_cache_size_kb": round(total_size / 1024, 2),
                "services": [
                    {
                        "name": sub.name,
                        "interval": sub.interval,
                        "last_update": sub.last_update,
                        "age": round(time.time() - sub.last_update, 1),
                        "enabled": sub.enabled,
                        "errors": sub.error_count
                    }
                    for sub in self.subscriptions.values()
                ]
            }
    
    def cleanup_stale_cache(self):
        """Remove stale cache entries (older than max_cache_age).
        
        Called periodically to prevent memory issues.
        """
        now = time.time()
        removed = []
        
        with self._lock:
            for service, cached in list(self.cache.items()):
                if cached.is_stale(self.config.max_cache_age):
                    del self.cache[service]
                    removed.append(service)
        
        if removed:
            logger.warning("Removed stale cache for: %s", ", ".join(removed))

