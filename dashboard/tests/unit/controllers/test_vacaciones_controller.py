"""Unit tests for vacaciones_controller.py - Christmas planning API."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from controllers.vacaciones_controller import (
    MOMENTOS,
    Comida,
    NucleoFamiliar,
    Persona,
    VacacionesData,
    YearPlan,
    _generate_inicial,
    add_year,
    delete_year,
    get_config,
    get_vacaciones_data,
    is_healthy,
    save_config,
    save_year,
)


class TestDataClasses:
    def test_persona_to_dict(self):
        persona = Persona(id="p1", nombre="Angel", inicial="A")
        d = persona.to_dict()
        assert d["id"] == "p1"
        assert d["nombre"] == "Angel"
        assert d["inicial"] == "A"

    def test_nucleo_familiar_to_dict(self):
        nucleo = NucleoFamiliar(
            id="n1", nombre="Padres de Angel", color="#ff0000", hijo_id="p1"
        )
        d = nucleo.to_dict()
        assert d["id"] == "n1"
        assert d["nombre"] == "Padres de Angel"
        assert d["color"] == "#ff0000"
        assert d["hijo_id"] == "p1"

    def test_comida_to_dict(self):
        comida = Comida(
            momento="cena_24",
            nucleo_id="n1",
            personas=["p1", "p2"],
            personas_por_nucleo={"n1": ["p1"], "n2": ["p2"]},
            notas="Nota test",
        )
        d = comida.to_dict()
        assert d["momento"] == "cena_24"
        assert d["nucleo_id"] == "n1"
        assert d["personas"] == ["p1", "p2"]
        assert d["notas"] == "Nota test"

    def test_year_plan_to_dict(self):
        year = YearPlan(
            year=2026,
            comidas=[Comida(momento="cena_24")],
            notas="Year notes",
        )
        d = year.to_dict()
        assert d["year"] == 2026
        assert len(d["comidas"]) == 1
        assert d["notas"] == "Year notes"

    def test_vacaciones_data_to_dict(self):
        data = VacacionesData(
            nucleos=[NucleoFamiliar(id="n1", nombre="Test")],
            personas=[Persona(id="p1", nombre="Angel")],
            years=[YearPlan(year=2026)],
        )
        d = data.to_dict()
        assert len(d["nucleos"]) == 1
        assert len(d["personas"]) == 1
        assert len(d["years"]) == 1


class TestGenerateInicial:
    def test_first_letter_when_available(self):
        result = _generate_inicial("Angel", [])
        assert result == "A"

    def test_two_letters_when_first_taken(self):
        result = _generate_inicial("Angel", ["A"])
        assert result == "AN"

    def test_increments_when_all_prefixes_taken(self):
        result = _generate_inicial("AB", ["A", "AB"])
        assert result == "AB2"

    def test_empty_name_returns_empty(self):
        result = _generate_inicial("", [])
        assert result == ""

    def test_case_insensitive(self):
        result = _generate_inicial("angel", ["A"])
        assert result == "AN"


class TestMomentos:
    def test_has_six_moments(self):
        assert len(MOMENTOS) == 6

    def test_moments_have_required_fields(self):
        for m in MOMENTOS:
            assert "id" in m
            assert "label" in m
            assert "dia" in m
            assert "tipo" in m
            assert "importante" in m


class TestVacacionesDataOperations:
    """Tests using a temporary data file."""

    def setup_method(self):
        """Create a temp file for each test."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_file = Path(self.temp_dir) / "data" / "vacaciones.json"

    def teardown_method(self):
        """Cleanup temp files."""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("controllers.vacaciones_controller.DATA_FILE")
    def test_get_vacaciones_data_returns_default_on_missing_file(self, mock_path):
        mock_path.__class__ = Path
        mock_path.exists.return_value = False
        mock_path.parent.mkdir = lambda **kw: None

        # Actually patch the module-level constant
        with patch(
            "controllers.vacaciones_controller.DATA_FILE",
            Path(self.temp_dir) / "nonexistent.json",
        ):
            result = get_vacaciones_data()

        assert "nucleos" in result
        assert "personas" in result
        assert "years" in result
        assert "momentos" in result

    @patch("controllers.vacaciones_controller.DATA_FILE")
    def test_get_config_returns_nucleos_and_personas(self, mock_data_file):
        mock_data_file.__class__ = Path
        test_data = {
            "nucleos": [{"id": "n1", "nombre": "Test", "color": "#000", "hijo_id": ""}],
            "personas": [{"id": "p1", "nombre": "Angel", "inicial": "A"}],
            "years": [],
        }

        with patch("controllers.vacaciones_controller.DATA_FILE", self.temp_file):
            self.temp_file.parent.mkdir(parents=True, exist_ok=True)
            self.temp_file.write_text(json.dumps(test_data))

            result = get_config()

        assert len(result["nucleos"]) == 1
        assert len(result["personas"]) == 1

    @patch("controllers.vacaciones_controller.DATA_FILE")
    def test_save_config_persists_data(self, mock_data_file):
        with patch("controllers.vacaciones_controller.DATA_FILE", self.temp_file):
            self.temp_file.parent.mkdir(parents=True, exist_ok=True)
            # Create initial empty data
            self.temp_file.write_text(
                json.dumps({"nucleos": [], "personas": [], "years": []})
            )

            result = save_config(
                nucleos=[{"id": "n1", "nombre": "Padres", "color": "#fff"}],
                personas=[{"id": "p1", "nombre": "Angel"}],
            )

            assert result["status"] == "ok"

            # Verify file was written
            saved = json.loads(self.temp_file.read_text())
            assert len(saved["nucleos"]) == 1
            assert len(saved["personas"]) == 1
            # Inicial should be auto-generated
            assert saved["personas"][0]["inicial"] == "A"

    @patch("controllers.vacaciones_controller.DATA_FILE")
    def test_save_year_creates_new_year(self, mock_data_file):
        with patch("controllers.vacaciones_controller.DATA_FILE", self.temp_file):
            self.temp_file.parent.mkdir(parents=True, exist_ok=True)
            self.temp_file.write_text(
                json.dumps({"nucleos": [], "personas": [], "years": []})
            )

            result = save_year(
                2026,
                comidas=[{"momento": "cena_24", "nucleo_id": "n1"}],
                notas="Test notes",
            )

            assert result["status"] == "ok"

            saved = json.loads(self.temp_file.read_text())
            assert len(saved["years"]) == 1
            assert saved["years"][0]["year"] == 2026

    @patch("controllers.vacaciones_controller.DATA_FILE")
    def test_save_year_updates_existing_year(self, mock_data_file):
        with patch("controllers.vacaciones_controller.DATA_FILE", self.temp_file):
            self.temp_file.parent.mkdir(parents=True, exist_ok=True)
            self.temp_file.write_text(
                json.dumps(
                    {
                        "nucleos": [],
                        "personas": [],
                        "years": [{"year": 2026, "comidas": [], "notas": "old"}],
                    }
                )
            )

            save_year(2026, comidas=[], notas="new notes")

            saved = json.loads(self.temp_file.read_text())
            assert saved["years"][0]["notas"] == "new notes"

    @patch("controllers.vacaciones_controller.DATA_FILE")
    def test_add_year_increments_highest(self, mock_data_file):
        with patch("controllers.vacaciones_controller.DATA_FILE", self.temp_file):
            self.temp_file.parent.mkdir(parents=True, exist_ok=True)
            self.temp_file.write_text(
                json.dumps(
                    {
                        "nucleos": [],
                        "personas": [],
                        "years": [{"year": 2026, "comidas": [], "notas": ""}],
                    }
                )
            )

            result = add_year()

            assert result["status"] == "ok"
            assert result["year"] == 2027

    @patch("controllers.vacaciones_controller.DATA_FILE")
    def test_delete_year_removes_highest(self, mock_data_file):
        with patch("controllers.vacaciones_controller.DATA_FILE", self.temp_file):
            self.temp_file.parent.mkdir(parents=True, exist_ok=True)
            self.temp_file.write_text(
                json.dumps(
                    {
                        "nucleos": [],
                        "personas": [],
                        "years": [
                            {"year": 2026, "comidas": [], "notas": ""},
                            {"year": 2027, "comidas": [], "notas": ""},
                        ],
                    }
                )
            )

            result = delete_year(2027)

            assert result["status"] == "ok"
            saved = json.loads(self.temp_file.read_text())
            assert len(saved["years"]) == 1
            assert saved["years"][0]["year"] == 2026

    @patch("controllers.vacaciones_controller.DATA_FILE")
    def test_delete_year_rejects_non_highest(self, mock_data_file):
        with patch("controllers.vacaciones_controller.DATA_FILE", self.temp_file):
            self.temp_file.parent.mkdir(parents=True, exist_ok=True)
            self.temp_file.write_text(
                json.dumps(
                    {
                        "nucleos": [],
                        "personas": [],
                        "years": [
                            {"year": 2026, "comidas": [], "notas": ""},
                            {"year": 2027, "comidas": [], "notas": ""},
                        ],
                    }
                )
            )

            result = delete_year(2026)

            assert result["status"] == "error"

    @patch("controllers.vacaciones_controller.DATA_FILE")
    def test_delete_year_rejects_only_year(self, mock_data_file):
        with patch("controllers.vacaciones_controller.DATA_FILE", self.temp_file):
            self.temp_file.parent.mkdir(parents=True, exist_ok=True)
            self.temp_file.write_text(
                json.dumps(
                    {
                        "nucleos": [],
                        "personas": [],
                        "years": [{"year": 2026, "comidas": [], "notas": ""}],
                    }
                )
            )

            result = delete_year(2026)

            assert result["status"] == "error"


class TestIsHealthy:
    def test_returns_true(self):
        assert is_healthy() is True
