"""Unit tests for the presence-service SQLite store (scaffold)."""

from __future__ import annotations

import time

import pytest
from database import PresenceStore
from models import PresenceEvent, PresenceState


@pytest.fixture
def store(tmp_path):
    return PresenceStore(str(tmp_path / "presence.db"))


def test_schema_is_created_and_db_ok(store):
    # A fresh store answers a trivial query → healthy, empty history.
    assert store.db_ok() is True
    assert store.count_transitions() == 0


def test_upsert_and_read_current_snapshot(store):
    now = int(time.time())
    store.upsert_current("ana", "home", 1.0, now, last_seen=now, last_source="router")
    rows = store.get_current()
    assert len(rows) == 1
    row = rows[0]
    assert row["person_id"] == "ana"
    assert row["state"] == "home"
    assert row["confidence"] == 1.0
    assert row["last_source"] == "router"


def test_upsert_current_replaces_existing_row(store):
    now = int(time.time())
    store.upsert_current("ana", "home", 1.0, now)
    store.upsert_current("ana", "away", 0.0, now + 10)
    rows = store.get_current()
    assert len(rows) == 1
    assert rows[0]["state"] == "away"


def test_record_and_read_transition_history(store):
    now = int(time.time())
    event = PresenceEvent(
        ts=now,
        person_id="ana",
        from_state=PresenceState.AWAY,
        to_state=PresenceState.HOME,
        confidence=0.6,
        source="router",
    )
    row_id = store.record_transition(event)
    assert row_id > 0
    assert store.count_transitions() == 1

    history = store.history()
    assert len(history) == 1
    assert history[0]["from_state"] == "away"
    assert history[0]["to_state"] == "home"
    assert history[0]["person_id"] == "ana"


def test_history_filters_by_person_and_range(store):
    now = int(time.time())
    store.record_transition(
        PresenceEvent(
            ts=now - 100,
            person_id="ana",
            from_state=PresenceState.AWAY,
            to_state=PresenceState.HOME,
        )
    )
    store.record_transition(
        PresenceEvent(
            ts=now,
            person_id="juan",
            from_state=PresenceState.HOME,
            to_state=PresenceState.AWAY,
        )
    )
    # Filter by person.
    ana = store.history(person_id="ana")
    assert len(ana) == 1
    assert ana[0]["person_id"] == "ana"
    # Filter by time range (only the recent one).
    recent = store.history(since=now - 10)
    assert len(recent) == 1
    assert recent[0]["person_id"] == "juan"


def test_history_is_newest_first(store):
    now = int(time.time())
    for i in range(3):
        store.record_transition(
            PresenceEvent(
                ts=now + i,
                person_id="ana",
                from_state=PresenceState.AWAY,
                to_state=PresenceState.HOME,
            )
        )
    history = store.history()
    timestamps = [r["ts"] for r in history]
    assert timestamps == sorted(timestamps, reverse=True)


def test_prune_removes_old_transitions(store):
    now = int(time.time())
    old_ts = now - 400 * 24 * 3600  # ~400 days ago, beyond 365-day retention
    store.record_transition(
        PresenceEvent(
            ts=old_ts,
            person_id="ana",
            from_state=PresenceState.AWAY,
            to_state=PresenceState.HOME,
        )
    )
    store.record_transition(
        PresenceEvent(
            ts=now,
            person_id="ana",
            from_state=PresenceState.HOME,
            to_state=PresenceState.AWAY,
        )
    )
    deleted = store.prune(now=now, retention_days=365)
    assert deleted == 1
    assert store.count_transitions() == 1


# ── Tests for hash_mac and validate_person_id ────────────────────────────────
from database import hash_mac, validate_person_id


def test_hash_mac_returns_16_char_hex():
    """Hash should return 16 hex characters (64 bits)."""
    result = hash_mac("AA:BB:CC:DD:EE:FF")
    assert len(result) == 16
    assert all(c in "0123456789abcdef" for c in result)


def test_hash_mac_normalizes_formats():
    """Different MAC formats should produce the same hash."""
    mac1 = hash_mac("AA:BB:CC:DD:EE:FF")
    mac2 = hash_mac("aa:bb:cc:dd:ee:ff")
    mac3 = hash_mac("aabbccddeeff")
    mac4 = hash_mac("aa-bb-cc-dd-ee-ff")
    assert mac1 == mac2 == mac3 == mac4


def test_hash_mac_is_deterministic():
    """Same MAC should always produce same hash."""
    mac = "11:22:33:44:55:66"
    assert hash_mac(mac) == hash_mac(mac)


def test_validate_person_id_accepts_valid():
    """Valid person_ids should pass validation."""
    assert validate_person_id("ana") == "ana"
    assert validate_person_id("juan_perez") == "juan_perez"
    assert validate_person_id("user-123") == "user-123"
    assert validate_person_id("A1b2C3") == "A1b2C3"


def test_validate_person_id_rejects_empty():
    """Empty person_id should raise ValueError."""
    with pytest.raises(ValueError, match="Invalid person_id"):
        validate_person_id("")


def test_validate_person_id_rejects_special_chars():
    """person_id with special characters should raise ValueError."""
    with pytest.raises(ValueError, match="Invalid person_id"):
        validate_person_id("ana'; DROP TABLE--")
    with pytest.raises(ValueError, match="Invalid person_id"):
        validate_person_id("user/admin")
    with pytest.raises(ValueError, match="Invalid person_id"):
        validate_person_id("user@domain")


def test_validate_person_id_rejects_too_long():
    """person_id over 64 chars should raise ValueError."""
    with pytest.raises(ValueError, match="Invalid person_id"):
        validate_person_id("a" * 65)


def test_upsert_current_rejects_invalid_person_id(store):
    """upsert_current should reject invalid person_id."""
    import time

    now = int(time.time())
    with pytest.raises(ValueError, match="Invalid person_id"):
        store.upsert_current("'; DROP TABLE--", "home", 1.0, now)


def test_record_transition_rejects_invalid_person_id(store):
    """record_transition should reject invalid person_id."""
    import time

    now = int(time.time())
    event = PresenceEvent(
        ts=now,
        person_id="user/../../etc",
        from_state=PresenceState.AWAY,
        to_state=PresenceState.HOME,
    )
    with pytest.raises(ValueError, match="Invalid person_id"):
        store.record_transition(event)


def test_history_rejects_invalid_person_id(store):
    """history should reject invalid person_id filter."""
    with pytest.raises(ValueError, match="Invalid person_id"):
        store.history(person_id="<script>alert(1)</script>")
