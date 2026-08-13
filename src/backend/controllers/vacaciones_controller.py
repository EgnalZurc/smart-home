"""Vacaciones (Christmas Planning) API controller.

Business Objects:
- NucleoFamiliar: Family group / reunion place (e.g., "Padres de Angel")
- Persona: Individual person who attends family gatherings (with unique inicial)
- Year: Annual planning with meals (cena 24, comida 25, cena 31, comida 1, desayuno 6, comida 6)

Key dates: 24, 25, 31, 1 (important days)
Day 6 is a wildcard to balance the year between family nuclei.
"""

from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional
import json
from pathlib import Path

DATA_FILE = Path(__file__).parent.parent / "data" / "vacaciones.json"


@dataclass
class Persona:
    id: str
    nombre: str
    inicial: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class NucleoFamiliar:
    id: str
    nombre: str
    color: str = "#6366f1"
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Comida:
    momento: str
    nucleo_id: Optional[str] = None
    personas: List[str] = field(default_factory=list)
    personas_por_nucleo: Dict[str, List[str]] = field(default_factory=dict)
    notas: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "momento": self.momento,
            "nucleo_id": self.nucleo_id,
            "personas": self.personas,
            "personas_por_nucleo": self.personas_por_nucleo,
            "notas": self.notas
        }


@dataclass
class YearPlan:
    year: int
    comidas: List[Comida] = field(default_factory=list)
    notas: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "year": self.year,
            "comidas": [c.to_dict() for c in self.comidas],
            "notas": self.notas
        }


@dataclass
class VacacionesData:
    nucleos: List[NucleoFamiliar] = field(default_factory=list)
    personas: List[Persona] = field(default_factory=list)
    years: List[YearPlan] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "nucleos": [n.to_dict() for n in self.nucleos],
            "personas": [p.to_dict() for p in self.personas],
            "years": [y.to_dict() for y in self.years]
        }


MOMENTOS = [
    {"id": "cena_24", "label": "Cena 24", "icon": "&#127770;", "dia": 24, "tipo": "cena", "importante": True},
    {"id": "comida_25", "label": "Comida 25", "icon": "&#9728;&#65039;", "dia": 25, "tipo": "comida", "importante": True},
    {"id": "cena_31", "label": "Cena 31", "icon": "&#127770;", "dia": 31, "tipo": "cena", "importante": True},
    {"id": "comida_1", "label": "Comida 1", "icon": "&#9728;&#65039;", "dia": 1, "tipo": "comida", "importante": True},
    {"id": "desayuno_6", "label": "Desayuno 6", "icon": "&#9728;&#65039;", "dia": 6, "tipo": "desayuno", "importante": False},
    {"id": "comida_6", "label": "Comida 6", "icon": "&#127869;", "dia": 6, "tipo": "comida", "importante": False},
]


def _generate_inicial(nombre: str, existing_iniciales: List[str]) -> str:
    nombre_clean = nombre.strip().upper()
    if not nombre_clean:
        return ""
    for length in range(1, len(nombre_clean) + 1):
        candidate = nombre_clean[:length]
        if candidate not in existing_iniciales:
            return candidate
    base = nombre_clean
    counter = 2
    while f"{base}{counter}" in existing_iniciales:
        counter += 1
    return f"{base}{counter}"


def _ensure_data_dir():
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)


def _load_data() -> VacacionesData:
    _ensure_data_dir()
    if DATA_FILE.exists():
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
            nucleos = [NucleoFamiliar(**n) for n in raw.get("nucleos", [])]
            personas = [Persona(**p) for p in raw.get("personas", [])]
            years = []
            for y in raw.get("years", []):
                comidas = []
                for c in y.get("comidas", []):
                    comidas.append(Comida(
                        momento=c.get("momento", ""),
                        nucleo_id=c.get("nucleo_id"),
                        personas=c.get("personas", []),
                        personas_por_nucleo=c.get("personas_por_nucleo", {}),
                        notas=c.get("notas", "")
                    ))
                years.append(YearPlan(year=y["year"], comidas=comidas, notas=y.get("notas", "")))
            return VacacionesData(nucleos=nucleos, personas=personas, years=years)
        except Exception:
            pass
    return VacacionesData(
        nucleos=[],
        personas=[],
        years=[YearPlan(year=2026, comidas=[Comida(momento=m["id"]) for m in MOMENTOS], notas="")]
    )


def _save_data(data: VacacionesData):
    _ensure_data_dir()
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data.to_dict(), f, ensure_ascii=False, indent=2)


def get_vacaciones_data() -> Dict[str, Any]:
    data = _load_data()
    return {**data.to_dict(), "momentos": MOMENTOS}


def get_config() -> Dict[str, Any]:
    data = _load_data()
    return {"nucleos": [n.to_dict() for n in data.nucleos], "personas": [p.to_dict() for p in data.personas]}


def save_config(nucleos: List[Dict], personas: List[Dict]) -> Dict[str, Any]:
    data = _load_data()
    data.nucleos = [NucleoFamiliar(**n) for n in nucleos]
    new_personas = []
    used_iniciales = []
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
        new_personas.append(Persona(id=p.get("id", f"p_{len(new_personas)}"), nombre=nombre, inicial=inicial))
    data.personas = new_personas
    _save_data(data)
    return {"status": "ok"}


def save_year(year: int, comidas: List[Dict], notas: str = "") -> Dict[str, Any]:
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
            notas=c.get("notas", "")
        ) for c in comidas
    ]
    year_plan.notas = notas
    _save_data(data)
    return {"status": "ok"}


def delete_year(year: int) -> Dict[str, Any]:
    """Delete a year. Only allowed if >1 years and is the highest year."""
    data = _load_data()
    if len(data.years) <= 1:
        return {"status": "error", "message": "Cannot delete the only year"}
    max_year = max(y.year for y in data.years)
    if year != max_year:
        return {"status": "error", "message": "Can only delete the highest year"}
    data.years = [y for y in data.years if y.year != year]
    _save_data(data)
    return {"status": "ok"}


def add_year() -> Dict[str, Any]:
    """Add a new year (next after highest existing)."""
    data = _load_data()
    max_year = max(y.year for y in data.years) if data.years else 2025
    new_year = max_year + 1
    new_year_plan = YearPlan(year=new_year, comidas=[Comida(momento=m["id"]) for m in MOMENTOS], notas="")
    data.years.append(new_year_plan)
    data.years.sort(key=lambda y: y.year)
    _save_data(data)
    return {"status": "ok", "year": new_year}


def is_healthy() -> bool:
    return True