"""Tests for the shared TTLCache."""

from datetime import UTC, datetime, timedelta

from smart_home_common.cache import TTLCache


def test_set_and_get_returns_value():
    cache = TTLCache(default_ttl_seconds=300)
    cache.set("k", {"price": 50000})
    assert cache.get("k") == {"price": 50000}


def test_get_missing_key_returns_none():
    cache = TTLCache()
    assert cache.get("absent") is None


def test_entry_expires_after_ttl():
    cache = TTLCache(default_ttl_seconds=300)
    cache.set("k", "v", ttl_seconds=0)
    # TTL of 0 means expires_at == now; the >= comparison makes it immediately stale.
    assert cache.get("k") is None


def test_per_entry_ttl_overrides_default():
    cache = TTLCache(default_ttl_seconds=0)
    cache.set("fresh", "v", ttl_seconds=300)
    assert cache.get("fresh") == "v"


def test_is_expired_for_missing_key():
    cache = TTLCache()
    assert cache.is_expired("absent") is True


def test_is_expired_for_fresh_entry():
    cache = TTLCache(default_ttl_seconds=300)
    cache.set("k", "v")
    assert cache.is_expired("k") is False


def test_is_expired_for_stale_entry():
    cache = TTLCache()
    cache.set("k", "v", ttl_seconds=0)
    assert cache.is_expired("k") is True


def test_is_expired_does_not_evict():
    cache = TTLCache(default_ttl_seconds=300)
    cache.set("k", "v")
    cache.is_expired("k")
    # Entry is still present and retrievable.
    assert cache.get("k") == "v"


def test_get_evicts_expired_entry():
    cache = TTLCache()
    cache.set("k", "v", ttl_seconds=0)
    assert cache.get("k") is None
    # After eviction the backing store no longer holds the key.
    assert cache._cache == {}  # noqa: SLF001 — intentional internal state check


def test_expired_entry_detected_against_wall_clock(monkeypatch):
    cache = TTLCache(default_ttl_seconds=300)
    cache.set("k", "v")

    future = datetime.now(UTC) + timedelta(seconds=301)

    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return future

    monkeypatch.setattr("smart_home_common.cache.datetime", _FrozenDatetime)
    assert cache.get("k") is None


def test_clear_removes_all_entries():
    cache = TTLCache(default_ttl_seconds=300)
    cache.set("a", 1)
    cache.set("b", 2)
    cache.clear()
    assert cache.get("a") is None
    assert cache.get("b") is None


def test_set_overwrites_existing_key():
    cache = TTLCache(default_ttl_seconds=300)
    cache.set("k", "old")
    cache.set("k", "new")
    assert cache.get("k") == "new"
