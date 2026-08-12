"""Vacaciones (Christmas Planning) API controller.

Provides the data for the Planilla Vacaciones app.
This module generates the Christmas planning data for 2026-2029.
"""

from dataclasses import dataclass
from typing import List, Dict, Any


@dataclass
class FamilyMoment:
    """A family's location and details for a specific moment."""
    family: str  # PV, PA, PI
    familyName: str  # Virginia, Angel, Irene
    location: str  # Madrid, Murcia, supuesto
    detail: str = ""


@dataclass  
class Moment:
    """A specific moment (meal) during Christmas."""
    id: str  # 24, 25, 31, 1, 6
    icon: str
    label: str
    families: List[FamilyMoment]


@dataclass
class Alert:
    """An alert/note for a year."""
    type: str  # ok, warn, info
    text: str


@dataclass
class YearPlan:
    """The complete plan for a year."""
    year: int
    tipo: str  # PAR or IMPAR
    murcia: str  # 31+1 or 24+25 or 24+1
    note: str
    diff: str
    moments: List[Moment]
    alerts: List[Alert]


def get_propuesta1_data() -> Dict[str, Any]:
    """Returns the Propuesta 1 data for all years."""
    
    years = [
        # 2026 - IMPAR - Embarazo
        YearPlan(
            year=2026,
            tipo="IMPAR",
            murcia="31+1",
            note="Ano IMPAR - prioridad PV - Embarazo: A+V no viajan a Murcia",
            diff="Sin flexibilidad por embarazo. PA va Murcia 31+1 (su preferencia).",
            moments=[
                Moment(id="24", icon="&#127769;", label="Cena 24", families=[
                    FamilyMoment("PV", "Virginia", "Madrid", "Con <strong>A+V, H+I</strong>, abuela, tios &#10003;"),
                    FamilyMoment("PA", "Angel", "Madrid", "Con Maria"),
                ]),
                Moment(id="25", icon="&#9728;", label="Comida 25", families=[
                    FamilyMoment("PV", "Virginia", "Madrid", "Con abuela y tios"),
                    FamilyMoment("PA", "Angel", "Madrid", "Con Maria, <strong>A+V</strong>"),
                ]),
                Moment(id="31", icon="&#127769;", label="Cena 31", families=[
                    FamilyMoment("PV", "Virginia", "Madrid", "Con <strong>A+V</strong>, abuela"),
                    FamilyMoment("PA", "Angel", "Murcia", "Con Maria"),
                ]),
                Moment(id="1", icon="&#9728;", label="Comida 1", families=[
                    FamilyMoment("PV", "Virginia", "Madrid", "Con <strong>A+V, H+I</strong>, abuela &#10003;"),
                    FamilyMoment("PA", "Angel", "Murcia", "Con Maria"),
                ]),
                Moment(id="6", icon="&#127869;", label="6 Ene - PA peor (1 dia vs 3)", families=[
                    FamilyMoment("PV", "Virginia", "Desayuno", ""),
                    FamilyMoment("PA", "Angel", "Comida", "Con Maria, A+V"),
                ]),
            ],
            alerts=[
                Alert("ok", "PV 2 dias con A+V+H+I: 24 y 1"),
                Alert("ok", "Murcia 31+1. A+V: 3 PV, 1 PA"),
            ]
        ),
        
        # 2027 - PAR - Prioridad PA
        YearPlan(
            year=2027,
            tipo="PAR",
            murcia="31+1",
            note="Ano PAR - prioridad PA - <strong>A+V: 24+25 PV / 31+1 Murcia</strong> - H+I se adaptan: 24+25 PV / 31+1 PI",
            diff="PA elige Murcia 31+1 (su preferencia). H+I se adaptan para que PV tenga A+V+H+I juntos el 24+25. PV solo 31+1 - comida 6.",
            moments=[
                Moment(id="24", icon="&#127769;", label="Cena 24", families=[
                    FamilyMoment("PV", "Virginia", "Madrid", "Con <strong>A+V, H+I</strong>, abuela, tios &#10003;"),
                    FamilyMoment("PA", "Angel", "Madrid", "Con Maria"),
                    FamilyMoment("PI", "Irene", "supuesto", "Con su familia"),
                ]),
                Moment(id="25", icon="&#9728;", label="Comida 25", families=[
                    FamilyMoment("PV", "Virginia", "Madrid", "Con <strong>A+V, H+I</strong>, abuela, tios &#10003;"),
                    FamilyMoment("PA", "Angel", "Madrid", "Con Maria"),
                    FamilyMoment("PI", "Irene", "supuesto", "Con su familia"),
                ]),
                Moment(id="31", icon="&#127769;", label="Cena 31", families=[
                    FamilyMoment("PV", "Virginia", "Madrid", "Con abuela (solos)"),
                    FamilyMoment("PA", "Angel", "Murcia", "Con Maria, <strong>A+V</strong>"),
                    FamilyMoment("PI", "Irene", "supuesto", "Con H+I y familia"),
                ]),
                Moment(id="1", icon="&#9728;", label="Comida 1", families=[
                    FamilyMoment("PV", "Virginia", "Madrid", "Con abuela (solos)"),
                    FamilyMoment("PA", "Angel", "Murcia", "Con Maria, <strong>A+V</strong>"),
                    FamilyMoment("PI", "Irene", "supuesto", "Con H+I y familia"),
                ]),
                Moment(id="6", icon="&#127869;", label="6 Ene - PV peor (solos 31+1)", families=[
                    FamilyMoment("PA", "Angel", "Desayuno", "Con Maria, A+V"),
                    FamilyMoment("PV", "Virginia", "Comida", "Con A+V, H+I, abuela"),
                ]),
            ],
            alerts=[
                Alert("ok", "PV 2 dias con A+V+H+I: 24 y 25"),
                Alert("ok", "Murcia 31+1 (preferencia PA). A+V: 2 PV, 2 PA"),
                Alert("warn", "PV solos 31+1 - Comida 6 compensa"),
            ]
        ),
        
        # 2028 - IMPAR - Prioridad PV
        YearPlan(
            year=2028,
            tipo="IMPAR",
            murcia="24+1",
            note="Ano IMPAR - prioridad PV - H: 24+1 PI / 25+31 PV - <strong>A+V: 24+1 Murcia / 25+31 PV</strong>",
            diff="PV tiene prioridad. A+V van 25+31 con PV (coinciden con H+I). Murcia 24+1 (no 31+1).",
            moments=[
                Moment(id="24", icon="&#127769;", label="Cena 24", families=[
                    FamilyMoment("PV", "Virginia", "Madrid", "Con abuela y tios"),
                    FamilyMoment("PA", "Angel", "Murcia", "Con Maria, <strong>A+V</strong>"),
                    FamilyMoment("PI", "Irene", "supuesto", "Con H+I y familia"),
                ]),
                Moment(id="25", icon="&#9728;", label="Comida 25", families=[
                    FamilyMoment("PV", "Virginia", "Madrid", "Con <strong>A+V, H+I</strong>, abuela, tios &#10003;"),
                    FamilyMoment("PA", "Angel", "Madrid", "Con Maria"),
                    FamilyMoment("PI", "Irene", "supuesto", "Con su familia"),
                ]),
                Moment(id="31", icon="&#127769;", label="Cena 31", families=[
                    FamilyMoment("PV", "Virginia", "Madrid", "Con <strong>A+V, H+I</strong>, abuela &#10003;"),
                    FamilyMoment("PA", "Angel", "Madrid", "Con Maria"),
                    FamilyMoment("PI", "Irene", "supuesto", "Con su familia"),
                ]),
                Moment(id="1", icon="&#9728;", label="Comida 1", families=[
                    FamilyMoment("PV", "Virginia", "Madrid", "Con abuela"),
                    FamilyMoment("PA", "Angel", "Murcia", "Con Maria, <strong>A+V</strong>"),
                    FamilyMoment("PI", "Irene", "supuesto", "Con H+I y familia"),
                ]),
                Moment(id="6", icon="&#127869;", label="6 Ene - Empate 2-2 - 2027 comio PV - comida PA", families=[
                    FamilyMoment("PV", "Virginia", "Desayuno", "Con A+V, abuela"),
                    FamilyMoment("PA", "Angel", "Comida", "Con Maria, A+V"),
                ]),
            ],
            alerts=[
                Alert("ok", "PV 2 dias con A+V+H+I: 25 y 31"),
                Alert("ok", "Murcia 24+1. A+V: 2 PV, 2 PA"),
                Alert("info", "Coste: PA no va Murcia 31+1 (PV prioridad)"),
            ]
        ),
        
        # 2029 - PAR - Prioridad PA
        YearPlan(
            year=2029,
            tipo="PAR",
            murcia="31+1",
            note="Ano PAR - prioridad PA - <strong>A+V: 24+25 PV / 31+1 Murcia</strong> - H+I se adaptan: 24+25 PV / 31+1 PI",
            diff="PA elige Murcia 31+1 (su preferencia). H+I se adaptan para que PV tenga A+V+H+I juntos el 24+25. PV solo 31+1 - comida 6.",
            moments=[
                Moment(id="24", icon="&#127769;", label="Cena 24", families=[
                    FamilyMoment("PV", "Virginia", "Madrid", "Con <strong>A+V, H+I</strong>, abuela, tios &#10003;"),
                    FamilyMoment("PA", "Angel", "Madrid", "Con Maria"),
                    FamilyMoment("PI", "Irene", "supuesto", "Con su familia"),
                ]),
                Moment(id="25", icon="&#9728;", label="Comida 25", families=[
                    FamilyMoment("PV", "Virginia", "Madrid", "Con <strong>A+V, H+I</strong>, abuela, tios &#10003;"),
                    FamilyMoment("PA", "Angel", "Madrid", "Con Maria"),
                    FamilyMoment("PI", "Irene", "supuesto", "Con su familia"),
                ]),
                Moment(id="31", icon="&#127769;", label="Cena 31", families=[
                    FamilyMoment("PV", "Virginia", "Madrid", "Con abuela (solos)"),
                    FamilyMoment("PA", "Angel", "Murcia", "Con Maria, <strong>A+V</strong>"),
                    FamilyMoment("PI", "Irene", "supuesto", "Con H+I y familia"),
                ]),
                Moment(id="1", icon="&#9728;", label="Comida 1", families=[
                    FamilyMoment("PV", "Virginia", "Madrid", "Con abuela (solos)"),
                    FamilyMoment("PA", "Angel", "Murcia", "Con Maria, <strong>A+V</strong>"),
                    FamilyMoment("PI", "Irene", "supuesto", "Con H+I y familia"),
                ]),
                Moment(id="6", icon="&#127869;", label="6 Ene - PV peor (solos 31+1)", families=[
                    FamilyMoment("PA", "Angel", "Desayuno", "Con Maria, A+V"),
                    FamilyMoment("PV", "Virginia", "Comida", "Con A+V, H+I, abuela"),
                ]),
            ],
            alerts=[
                Alert("ok", "PV 2 dias con A+V+H+I: 24 y 25"),
                Alert("ok", "Murcia 31+1 (preferencia PA). A+V: 2 PV, 2 PA"),
                Alert("warn", "PV solos 31+1 - Comida 6 compensa"),
            ]
        ),
    ]
    
    # Convert to dict for JSON serialization
    def to_dict(obj):
        if hasattr(obj, '__dataclass_fields__'):
            return {k: to_dict(v) for k, v in obj.__dict__.items()}
        elif isinstance(obj, list):
            return [to_dict(i) for i in obj]
        return obj
    
    return {"years": [to_dict(y) for y in years]}


# Health check - always returns True since this is a static data provider
def is_healthy() -> bool:
    """Returns True if the vacaciones module is working."""
    return True