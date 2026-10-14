"""Unit tests for the presence-service domain models (scaffold)."""

from __future__ import annotations

from models import (
    Beacon,
    Device,
    Evidence,
    HouseMode,
    Person,
    PresenceEvent,
    PresenceState,
    Source,
    Zone,
)


def test_person_defaults():
    p = Person(id="ana", name="Ana")
    assert p.id == "ana"
    assert p.name == "Ana"
    assert p.track is True
    assert p.devices == []
    assert p.beacons == []


def test_person_with_devices_and_beacons():
    p = Person(
        id="ana",
        name="Ana",
        devices=[Device(mac="AA:BB:CC:11:22:33", label="iPhone de Ana")],
        beacons=[Beacon(ble_id="ad:12:34", label="Reloj de Ana")],
    )
    assert p.devices[0].mac == "AA:BB:CC:11:22:33"
    assert p.beacons[0].ble_id == "ad:12:34"


def test_zone_model():
    z = Zone(id="bedroom", sensors=["motion_dormitorio", "motion_pasillo"])
    assert z.id == "bedroom"
    assert len(z.sensors) == 2


def test_presence_state_values():
    assert PresenceState.AWAY.value == "away"
    assert PresenceState.HOME.value == "home"
    assert PresenceState.SLEEPING.value == "sleeping"
    assert PresenceState.JUST_LEFT.value == "just_left"
    assert PresenceState.JUST_HOME.value == "just_home"
    assert PresenceState.UNKNOWN.value == "unknown"


def test_house_mode_and_source_values():
    assert HouseMode.OCCUPIED.value == "occupied"
    assert HouseMode.EMPTY.value == "empty"
    assert HouseMode.ASLEEP.value == "asleep"
    assert Source.ROUTER.value == "router"
    assert Source.BLE.value == "ble"
    assert Source.MOTION.value == "motion"


def test_evidence_defaults_strength():
    e = Evidence(person_id="ana", source=Source.ROUTER, seen_at=1000)
    assert e.strength == 1.0
    assert e.source is Source.ROUTER


def test_presence_event_roundtrip():
    e = PresenceEvent(
        ts=1000,
        person_id="ana",
        from_state=PresenceState.AWAY,
        to_state=PresenceState.HOME,
        confidence=0.6,
        source="router",
    )
    assert e.from_state is PresenceState.AWAY
    assert e.to_state is PresenceState.HOME
    assert e.confidence == 0.6
