"""Domain models for presence-service.

Pure data types shared across the engine, sources and storage layers
(``docs/designs/presence-service-design.md`` §3). Kept dependency-free
(stdlib + pydantic only) so they are trivially testable without any I/O.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class PresenceState(str, Enum):
    """Per-person presence state (design §3.2).

    ``just_left`` / ``just_home`` are transient debounce states that collapse
    into ``away`` / ``home`` once the debounce window elapses; they are exposed
    so the dashboard can show "llegando…" / "saliendo…", but automations
    typically treat them as the pending target state.
    """

    AWAY = "away"
    HOME = "home"
    SLEEPING = "sleeping"
    JUST_LEFT = "just_left"
    JUST_HOME = "just_home"
    UNKNOWN = "unknown"


class HouseMode(str, Enum):
    """House-level derived mode (design §3.3)."""

    OCCUPIED = "occupied"
    EMPTY = "empty"
    ASLEEP = "asleep"


class Source(str, Enum):
    """Evidence source identifiers (design §2)."""

    ROUTER = "router"
    BLE = "ble"
    MOTION = "motion"


class Device(BaseModel):
    """A router/ARP source device owned by a person."""

    mac: str = Field(..., description="Enrolled MAC, non-randomized for home SSID")
    label: str = Field("", description="Human label, e.g. 'iPhone de Ana'")


class Beacon(BaseModel):
    """A BLE source beacon owned by a person."""

    ble_id: str = Field(..., description="BLE MAC or iBeacon UUID:major:minor")
    label: str = Field("", description="Human label, e.g. 'Reloj de Ana'")


class Person(BaseModel):
    """An enrolled, trackable household member (design §3.1)."""

    id: str = Field(..., description="Slug, stable key, e.g. 'ana'")
    name: str = Field(..., description="Display name")
    devices: list[Device] = Field(default_factory=list)
    beacons: list[Beacon] = Field(default_factory=list)
    track: bool = Field(True, description="Enrolled / paused")


class Zone(BaseModel):
    """A motion-sensor grouping (not per-person) used for occupancy + sleep."""

    id: str = Field(..., description="Zone slug, e.g. 'bedroom'")
    sensors: list[str] = Field(
        default_factory=list, description="zigbee2mqtt friendly names"
    )


class Evidence(BaseModel):
    """A single timestamped presence observation for a person (design §4.1).

    Evidence decays: it only counts toward confidence while
    ``now - seen_at < source_ttl`` for its source.
    """

    person_id: str
    source: Source
    seen_at: int = Field(..., description="Unix epoch seconds the evidence was seen")
    strength: float = Field(1.0, description="Source-reported strength, 0..1")


class PresenceEvent(BaseModel):
    """A confirmed state transition for a person (design §7.2 ``transitions``).

    This is the durable audit-trail record persisted to SQLite and the payload
    carried to the notifier / MQTT publisher on a confirmed transition.
    """

    ts: int = Field(..., description="Unix epoch seconds the transition occurred")
    person_id: str
    from_state: PresenceState
    to_state: PresenceState
    confidence: float = Field(0.0, description="Confidence at transition time")
    source: str = Field("", description="Source that triggered the transition")
