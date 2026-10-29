"""Vacaciones (Christmas Planning) API controller.

This module provides the data layer for the Vacaciones service, handling
persistence of family gathering plans to a JSON file.

Business Objects:
    NucleoFamiliar: Family group / reunion place (e.g., "Padres de Angel").
    Persona: Individual person who attends family gatherings (with unique
        inicial for compact UI display).
    YearPlan: Annual planning with meals for Christmas period dates.
    Comida: A single meal event (breakfast, lunch, or dinner).

Key Dates:
    - Dec 24: Christmas Eve dinner
    - Dec 25: Christmas Day lunch
    - Dec 31: New Year's Eve dinner
    - Jan 1: New Year's Day lunch
    - Jan 6: Epiphany breakfast and lunch (wildcard to balance the year)

Typical usage:
    The controller is imported by main.py and provides these operations::

        from vacaciones_controller import (
            get_vacaciones_data,
            get_config,
            save_config,
            save_year,
            add_year,
            delete_year,
            is_healthy,
        )
"""

import json
import logging
import os as _os
import tempfile
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, NamedTuple

# Public API exports for this module
__all__ = [
    "Persona",
    "NucleoFamiliar",
    "Comida",
    "YearPlan",
    "VacacionesData",
    "Momento",
    "MOMENTOS",
    "MAX_NUCLEOS",
    "MAX_PERSONAS",
    "MAX_YEARS",
    "DATA_FILE",
    "get_vacaciones_data",
    "get_config",
    "save_config",
    "save_year",
    "add_year",
    "delete_year",
    "is_healthy",
]

logger = logging.getLogger(__name__)

DATA_FILE = Path(_os.environ.get("VACACIONES_DATA_FILE", "/app/data/vacaciones.json"))

# Resource limits — prevent unbounded growth and cap memory/storage usage.
# MAX_NUCLEOS=20: families rarely have more than 20 distinct gathering groups.
# MAX_PERSONAS=50: upper bound for extended family members tracked in the app.
# MAX_YEARS=20: planning horizon; 20 years of history is more than enough.
MAX_NUCLEOS = 20
MAX_PERSONAS = 50
MAX_YEARS = 20


@dataclass
class Persona:
    """A person who attends family gatherings.

    Each person has a unique inicial (abbreviation) generated from their
    name for compact display in the UI calendar grid.

    Attributes:
        id: Unique identifier for the person.
        nombre: Full name of the person.
        inicial: Short abbreviation (1-3 chars) for compact display.
    """

    id: str
    nombre: str
    inicial: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization.

        Returns:
            Dictionary with all persona fields.
        """
        return asdict(self)


@dataclass
class NucleoFamiliar:
    """A family nucleus or gathering location.

    Represents a family unit that hosts gatherings, such as "Casa de los
    abuelos" or "Padres de Angel".

    Attributes:
        id: Unique identifier for the nucleus.
        nombre: Human-readable name of the nucleus.
        color: Hex color code for UI display (default: indigo #6366f1).
        hijo_id: Optional ID of the primary child/host person.
    """

    id: str
    nombre: str
    color: str = "#6366f1"
    hijo_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization.

        Returns:
            Dictionary with all nucleus fields.
        """
        return asdict(self)


@dataclass
class Comida:
    """A meal event during the Christmas gathering period.

    Represents a single meal (breakfast, lunch, or dinner) on a specific
    day, tracking which nucleus hosts and which persons attend.

    Attributes:
        momento: Meal identifier (e.g., "cena_24", "comida_25").
        nucleo_id: ID of the hosting nucleus, or None if unassigned.
        personas: List of person IDs attending (legacy format).
        personas_por_nucleo: Mapping of nucleus ID to list of person IDs
            from that nucleus attending this meal.
        notas: Optional notes about this specific meal.
    """

    momento: str
    nucleo_id: str | None = None
    personas: list[str] = field(default_factory=list)
    personas_por_nucleo: dict[str, list[str]] = field(default_factory=dict)
    notas: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization.

        Returns:
            Dictionary with all meal fields.
        """
        return {
            "momento": self.momento,
            "nucleo_id": self.nucleo_id,
            "personas": self.personas,
            "personas_por_nucleo": self.personas_por_nucleo,
            "notas": self.notas,
        }


@dataclass
class YearPlan:
    """A year's worth of Christmas gathering plans.

    Contains all meal assignments for a single year's Christmas period.

    Attributes:
        year: The year (e.g., 2026).
        comidas: List of meal entries for this year.
        notas: General notes for this year's planning.
    """

    year: int
    comidas: list[Comida] = field(default_factory=list)
    notas: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization.

        Returns:
            Dictionary with year, comidas list, and notas.
        """
        return {
            "year": self.year,
            "comidas": [c.to_dict() for c in self.comidas],
            "notas": self.notas,
        }


@dataclass
class VacacionesData:
    """Complete vacaciones dataset.

    The root data structure containing all configuration and year plans.

    Attributes:
        nucleos: List of family nuclei.
        personas: List of persons.
        years: List of year plans.
    """

    nucleos: list[NucleoFamiliar] = field(default_factory=list)
    personas: list[Persona] = field(default_factory=list)
    years: list[YearPlan] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization.

        Returns a deep copy to prevent mutation of internal state through
        the returned dictionary.

        Returns:
            Dictionary with nucleos, personas, and years lists.
        """
        return {
            "nucleos": [n.to_dict() for n in self.nucleos],
            "personas": [p.to_dict() for p in self.personas],
            "years": [y.to_dict() for y in self.years],
        }


# MOMENTOS uses NamedTuple for true immutability (the outer tuple prevents
# reassigning the sequence, and NamedTuple instances are immutable).
# Each momento represents a meal during the Christmas gathering period.


class Momento(NamedTuple):
    """Immutable representation of a meal moment during Christmas."""

    id: str
    label: str
    icon: str
    dia: int
    tipo: str
    importante: bool

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return self._asdict()


MOMENTOS: tuple[Momento, ...] = (
    Momento(
        id="cena_24",
        label="Cena 24",
        icon="&#127770;",
        dia=24,
        tipo="cena",
        importante=True,
    ),
    Momento(
        id="comida_25",
        label="Comida 25",
        icon="&#9728;&#65039;",
        dia=25,
        tipo="comida",
        importante=True,
    ),
    Momento(
        id="cena_31",
        label="Cena 31",
        icon="&#127770;",
        dia=31,
        tipo="cena",
        importante=True,
    ),
    Momento(
        id="comida_1",
        label="Comida 1",
        icon="&#9728;&#65039;",
        dia=1,
        tipo="comida",
        importante=True,
    ),
    Momento(
        id="desayuno_6",
        label="Desayuno 6",
        icon="&#9728;&#65039;",
        dia=6,
        tipo="desayuno",
        importante=False,
    ),
    Momento(
        id="comida_6",
        label="Comida 6",
        icon="&#127869;",
        dia=6,
        tipo="comida",
        importante=False,
    ),
)


def _generate_inicial(nombre: str, existing_iniciales: Sequence[str]) -> str:
    """Generate a unique initial abbreviation for a person's name.

    Tries progressively longer prefixes of the name until finding one
    that doesn't conflict with existing iniciales. If all prefixes
    conflict, appends a numeric suffix.

    Args:
        nombre: The person's full name.
        existing_iniciales: List of already-used iniciales to avoid.

    Returns:
        A unique inicial string (uppercase). Empty string if nombre is
        empty or whitespace-only.

    Examples:
        >>> _generate_inicial("Angel", [])
        'A'
        >>> _generate_inicial("Ana", ["A"])
        'AN'
        >>> _generate_inicial("Angel", ["ANGEL"])
        'ANGEL2'

    Note:
        The numeric suffix loop is bounded to MAX_PERSONAS iterations to
        prevent infinite loops in pathological cases (e.g., if existing_iniciales
        somehow contains all possible suffixes).
    """
    nombre_clean = nombre.strip().upper()
    if not nombre_clean:
        return ""
    for length in range(1, len(nombre_clean) + 1):
        candidate = nombre_clean[:length]
        if candidate not in existing_iniciales:
            return candidate
    base = nombre_clean
    counter = 2
    # Guard against infinite loop: limit iterations to MAX_PERSONAS.
    # In practice, we'll never hit this limit since we cap personas at MAX_PERSONAS,
    # but this provides defense-in-depth against pathological input.
    max_attempts = MAX_PERSONAS
    while f"{base}{counter}" in existing_iniciales and max_attempts > 0:
        counter += 1
        max_attempts -= 1
    return f"{base}{counter}"


def _ensure_data_dir() -> None:
    """Ensure the data directory exists.

    Creates the parent directory of DATA_FILE if it doesn't exist,
    including any necessary intermediate directories.
    """
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)


def _load_data() -> VacacionesData:
    """Load vacaciones data from the JSON file.

    Reads and deserializes the data file into VacacionesData. If the
    file doesn't exist, is corrupt, or unreadable, returns sane defaults
    with a single year (2026) initialized with empty meals.

    Returns:
        VacacionesData instance with the loaded or default data.

    Note:
        Errors are logged but not raised — the service stays usable
        with defaults rather than failing completely.
    """
    _ensure_data_dir()
    if DATA_FILE.exists():
        try:
            with open(DATA_FILE, encoding="utf-8") as f:
                raw = json.load(f)
            nucleos = [NucleoFamiliar(**n) for n in raw.get("nucleos", [])]
            personas = [Persona(**p) for p in raw.get("personas", [])]
            years = []
            for y in raw.get("years", []):
                comidas = []
                for c in y.get("comidas", []):
                    comidas.append(
                        Comida(
                            momento=c.get("momento", ""),
                            nucleo_id=c.get("nucleo_id"),
                            personas=c.get("personas", []),
                            personas_por_nucleo=c.get("personas_por_nucleo", {}),
                            notas=c.get("notas", ""),
                        )
                    )
                years.append(
                    YearPlan(year=y["year"], comidas=comidas, notas=y.get("notas", ""))
                )
            return VacacionesData(nucleos=nucleos, personas=personas, years=years)
        except (OSError, ValueError, KeyError, TypeError) as e:
            # Corrupt or unreadable data file: log it instead of silently
            # swallowing the error, then fall through to sane defaults so the
            # service stays usable. (A partial/corrupt file can happen after a
            # crash mid-write — see _save_data for the atomic-write fix.)
            logger.error(
                "Failed to load vacaciones data from %s (%s): %s — "
                "falling back to defaults",
                DATA_FILE,
                type(e).__name__,
                e,
            )
    return VacacionesData(
        nucleos=[],
        personas=[],
        years=[
            YearPlan(
                year=datetime.now().year,
                comidas=[Comida(momento=m.id) for m in MOMENTOS],
                notas="",
            )
        ],
    )


def _save_data(data: VacacionesData) -> None:
    """Persist vacaciones data atomically to JSON.

    Writes to a temporary file in the same directory, flushes it to
    disk, and atomically renames it over the target with os.replace().
    A crash at any point leaves either the old complete file or the new
    complete file on disk — never a half-written one.

    Args:
        data: The VacacionesData instance to persist.

    Note:
        The temp file must live on the same filesystem as the target for
        the rename to be atomic, hence dir=DATA_FILE.parent.
    """
    _ensure_data_dir()
    dir_path = DATA_FILE.parent
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=dir_path,
            prefix=f".{DATA_FILE.name}.",
            suffix=".tmp",
            delete=False,
        ) as f:
            temp_path = f.name
            json.dump(data.to_dict(), f, ensure_ascii=False, indent=2)
            f.flush()
            _os.fsync(f.fileno())
        _os.replace(temp_path, DATA_FILE)  # atomic on POSIX and Windows
        temp_path = None
    finally:
        # If replace never ran (exception during write), drop the stray temp file.
        if temp_path is not None and _os.path.exists(temp_path):
            try:
                _os.remove(temp_path)
            except OSError as e:
                logger.warning("Could not remove temp file %s: %s", temp_path, e)


def get_vacaciones_data() -> dict[str, Any]:
    """Get all vacaciones data including momentos reference.

    Returns:
        Dictionary with 'nucleos', 'personas', 'years' lists and
        'momentos' reference data.
    """
    data = _load_data()
    return {**data.to_dict(), "momentos": [m.to_dict() for m in MOMENTOS]}


def get_config() -> dict[str, Any]:
    """Get vacaciones configuration (nucleos and personas only).

    Returns:
        Dictionary with 'nucleos' and 'personas' lists.
    """
    data = _load_data()
    return {
        "nucleos": [n.to_dict() for n in data.nucleos],
        "personas": [p.to_dict() for p in data.personas],
    }


def save_config(nucleos: list[dict], personas: list[dict]) -> dict[str, Any]:
    """Save vacaciones configuration.

    Replaces all nucleos and personas with the provided lists. Auto-
    generates unique iniciales for persons if not provided or if there
    are conflicts.

    Args:
        nucleos: List of nucleus dictionaries with id, nombre, color,
            hijo_id fields.
        personas: List of persona dictionaries with id, nombre, inicial,
            nucleo_id fields.

    Returns:
        Dictionary with 'status' key:
        - {'status': 'ok'} on success
        - {'status': 'error', 'message': '...'} if limits exceeded
    """
    if len(nucleos) > MAX_NUCLEOS:
        return {
            "status": "error",
            "message": f"Too many nucleos (max {MAX_NUCLEOS})",
        }
    if len(personas) > MAX_PERSONAS:
        return {
            "status": "error",
            "message": f"Too many personas (max {MAX_PERSONAS})",
        }
    data = _load_data()
    data.nucleos = [NucleoFamiliar(**n) for n in nucleos]
    new_personas = []
    used_iniciales: list[str] = []
    for p in personas:
        nombre = p.get("nombre", "").strip()
        if not nombre:
            continue
        existing_inicial = p.get("inicial", "")
        if existing_inicial and existing_inicial.upper() not in used_iniciales:
            inicial = existing_inicial.upper()
        else:
            inicial = _generate_inicial(nombre, used_iniciales)
        used_iniciales.append(inicial)
        new_personas.append(
            Persona(
                id=p.get("id", f"p_{len(new_personas)}"), nombre=nombre, inicial=inicial
            )
        )
    data.personas = new_personas
    _save_data(data)
    return {"status": "ok"}


def save_year(year: int, comidas: list[dict], notas: str = "") -> dict[str, Any]:
    """Save a year's meal planning.

    Updates an existing year plan or creates a new one if the year
    doesn't exist.

    Args:
        year: The year to save (e.g., 2026).
        comidas: List of meal dictionaries with momento, nucleo_id,
            personas, personas_por_nucleo, notas fields.
        notas: General notes for this year.

    Returns:
        Dictionary with 'status': 'ok' on success.
    """
    data = _load_data()
    year_plan = None
    for y in data.years:
        if y.year == year:
            year_plan = y
            break
    if year_plan is None:
        year_plan = YearPlan(year=year)
        data.years.append(year_plan)
    year_plan.comidas = [
        Comida(
            momento=c.get("momento", ""),
            nucleo_id=c.get("nucleo_id"),
            personas=c.get("personas", []),
            personas_por_nucleo=c.get("personas_por_nucleo", {}),
            notas=c.get("notas", ""),
        )
        for c in comidas
    ]
    year_plan.notas = notas
    _save_data(data)
    return {"status": "ok"}


def delete_year(year: int) -> dict[str, Any]:
    """Delete a year from the planning.

    Only allowed if there is more than one year and the year being
    deleted is the highest (most recent). This prevents accidental
    deletion of historical data.

    Args:
        year: The year to delete.

    Returns:
        Dictionary with 'status' key:
        - {'status': 'ok'} on success
        - {'status': 'error', 'message': '...'} if deletion not allowed
    """
    data = _load_data()
    if len(data.years) <= 1:
        return {"status": "error", "message": "Cannot delete the only year"}
    max_year = max(y.year for y in data.years)
    if year != max_year:
        return {"status": "error", "message": "Can only delete the highest year"}
    data.years = [y for y in data.years if y.year != year]
    _save_data(data)
    return {"status": "ok"}


def add_year() -> dict[str, Any]:
    """Add a new year to the planning.

    Creates a new year plan for the year after the highest existing
    year, initialized with empty meals for all standard momentos.

    Returns:
        Dictionary with 'status' and 'year' keys:
        - {'status': 'ok', 'year': NNNN} on success
        - {'status': 'error', 'message': '...'} if max years reached
    """
    data = _load_data()
    if len(data.years) >= MAX_YEARS:
        return {"status": "error", "message": f"Too many years (max {MAX_YEARS})"}
    max_year = (
        max(y.year for y in data.years) if data.years else datetime.now().year - 1
    )
    new_year = max_year + 1
    new_year_plan = YearPlan(
        year=new_year, comidas=[Comida(momento=m.id) for m in MOMENTOS], notas=""
    )
    data.years.append(new_year_plan)
    data.years.sort(key=lambda y: y.year)
    _save_data(data)
    return {"status": "ok", "year": new_year}


def is_healthy() -> bool:
    """Check if the service is healthy.

    Verifies that the data directory exists and is accessible.

    Limitations:
        This check only verifies directory existence, not write capability.
        A more thorough check would attempt a test write, but that adds I/O
        overhead on every health probe (nginx polls frequently). Since the
        service uses atomic writes with temp files in the same directory,
        directory existence is a reasonable proxy for writability.
        If write failures become an issue in production, consider:
        1. A periodic background write test (not on every probe)
        2. Caching the last successful write timestamp
        3. Monitoring _save_data exceptions via metrics

    Returns:
        True if the data directory is accessible, False otherwise.
    """
    try:
        return DATA_FILE.parent.exists() and DATA_FILE.parent.is_dir()
    except OSError:
        return False
