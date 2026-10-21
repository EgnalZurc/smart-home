"""Unit tests for the presence-service SQLite store (scaffold)."""

from __future__ import annotations

import time

import pytest
from database import PresenceStore, hash_mac, validate_person_id, _HASH_LENGTH
from models import PresenceEvent, PresenceState


# ── hash_mac tests ───────────────────────────────────────────────────────────


def test_hash_mac_returns_correct_length():
    """Hash should be exactly _HASH_LENGTH (16) hex chars for 64-bit security."""
    result = hash_mac("AA:BB:CC:DD:EE:FF")
    assert len(result) == _HASH_LENGTH
    assert len(result) == 16  # Explicit check for security minimum


def test_hash_mac_is_deterministic():
    """Same MAC should always produce the same hash."""
    mac = "11:22:33:44:55:66"
    assert hash_mac(mac) == hash_mac(mac)


def test_hash_mac_normalizes_formats():
    """Different MAC formats should hash to the same value."""
    expected = hash_mac("aabbccddeeff")
    assert hash_mac("AA:BB:CC:DD:EE:FF") == expected
    assert hash_mac("aa-bb-cc-dd-ee-ff") == expected
    assert hash_mac("AABB.CCDD.EEFF") == expected


def test_hash_mac_different_macs_differ():
    """Different MACs should produce different hashes."""
    assert hash_mac("AA:BB:CC:DD:EE:FF") != hash_mac("11:22:33:44:55:66")


# ── validate_person_id tests ─────────────────────────────────────────────────


def test_validate_person_id_accepts_valid_ids():
    """Valid person_ids should pass validation unchanged."""
    assert validate_person_id("ana") == "ana"
    assert validate_person_id("juan_garcia") == "juan_garcia"
    assert validate_person_id("user-123") == "user-123"
    assert validate_person_id("User_Name-42") == "User_Name-42"


def test_validate_person_id_rejects_empty():
    """Empty person_id should raise ValueError."""
    with pytest.raises(ValueError, match="cannot be empty"):
        validate_person_id("")


def test_validate_person_id_rejects_too_long():
    """person_id over 64 chars should raise ValueError."""
    long_id = "a" * 65
    with pytest.raises(ValueError, match="exceeds maximum length"):
        validate_person_id(long_id)


def test_validate_person_id_rejects_invalid_chars():
    """person_id with special characters should raise ValueError."""
    invalid_ids = [
        "user;drop table",  # SQL injection attempt
        "user' OR '1'='1",  # SQL injection attempt
        "../../../etc/passwd",  # Path traversal
        "user@domain",  # Email-like
        "user name",  # Spaces
        "user\ttab",  # Tabs
        "user\nnewline",  # Newlines
    ]
    for invalid_id in invalid_ids:
        with pytest.raises(ValueError, match="invalid characters"):
            validate_person_id(invalid_id)


# ── PresenceStore tests ──────────────────────────────────────────────────────


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


# ── person_id validation in store methods ────────────────────────────────────


def test_upsert_current_validates_person_id(store):
    """upsert_current should reject invalid person_id."""
    now = int(time.time())
    with pytest.raises(ValueError, match="invalid characters"):
        store.upsert_current("user;drop", "home", 1.0, now)


def test_record_transition_validates_person_id(store):
    """record_transition should reject events with invalid person_id."""
    now = int(time.time())
    event = PresenceEvent(
        ts=now,
        person_id="../etc/passwd",
        from_state=PresenceState.AWAY,
        to_state=PresenceState.HOME,
    )
    with pytest.raises(ValueError, match="invalid characters"):
        store.record_transition(event)


def test_history_validates_person_id(store):
    """history should reject invalid person_id filter."""
    with pytest.raises(ValueError, match="invalid characters"):
        store.history(person_id="user' OR '1'='1")
