"""Unit tests for vacaciones_controller module."""

import json

import pytest


class TestDataPersistence:
    """Tests for data loading and saving."""

    def test_load_data_returns_defaults_for_missing_file(self, tmp_data_file):
        """_load_data should return default data when file doesn't exist."""
        from vacaciones_controller import _load_data
        
        data = _load_data()
        
        assert data.nucleos == []
        assert data.personas == []
        assert len(data.years) == 1  # Default year
        assert data.years[0].year == 2026

    def test_save_and_load_round_trip(self, tmp_data_file):
        """Data should survive save and load cycle."""
        from vacaciones_controller import NucleoFamiliar, Persona, VacacionesData, _load_data, _save_data
        
        original = VacacionesData(
            nucleos=[NucleoFamiliar(id="n1", nombre="Test Nucleo", color="#ff0000")],
            personas=[Persona(id="p1", nombre="Test Persona", inicial="T")],
            years=[]
        )
        _save_data(original)
        loaded = _load_data()
        
        assert len(loaded.nucleos) == 1
        assert loaded.nucleos[0].nombre == "Test Nucleo"
        assert len(loaded.personas) == 1
        assert loaded.personas[0].nombre == "Test Persona"


class TestInicialGeneration:
    """Tests for automatic inicial generation."""

    def test_generate_inicial_uses_first_letter(self, tmp_data_file):
        """_generate_inicial should use first letter if available."""
        from vacaciones_controller import _generate_inicial
        
        inicial = _generate_inicial("María", [])
        assert inicial == "M"

    def test_generate_inicial_extends_for_conflict(self, tmp_data_file):
        """_generate_inicial should extend if first letter is taken."""
        from vacaciones_controller import _generate_inicial
        
        inicial = _generate_inicial("María", ["M"])
        assert inicial == "MA"

    def test_generate_inicial_further_extends(self, tmp_data_file):
        """_generate_inicial should keep extending for more conflicts."""
        from vacaciones_controller import _generate_inicial
        
        inicial = _generate_inicial("María", ["M", "MA", "MAR"])
        assert inicial == "MARÍ"

    def test_generate_inicial_uses_counter_as_fallback(self, tmp_data_file):
        """_generate_inicial should use counter when name exhausted."""
        from vacaciones_controller import _generate_inicial
        
        # All letters taken
        existing = ["A", "AN", "ANA"]
        inicial = _generate_inicial("Ana", existing)
        assert inicial == "ANA2"

    def test_generate_inicial_empty_name(self, tmp_data_file):
        """_generate_inicial should return empty for empty name."""
        from vacaciones_controller import _generate_inicial
        
        inicial = _generate_inicial("", [])
        assert inicial == ""


class TestConfigManagement:
    """Tests for configuration (nucleos and personas) management."""

    def test_get_config_returns_empty_initially(self, tmp_data_file):
        """get_config should return empty lists initially."""
        from vacaciones_controller import get_config
        
        config = get_config()
        
        assert config["nucleos"] == []
        assert config["personas"] == []

    def test_save_config_stores_nucleos(self, tmp_data_file):
        """save_config should store nucleos."""
        from vacaciones_controller import get_config, save_config
        
        nucleos = [
            {"id": "n1", "nombre": "Padres de Angel", "color": "#ff0000", "hijo_id": "a"},
            {"id": "n2", "nombre": "Padres de Virginia", "color": "#00ff00", "hijo_id": "v"}
        ]
        save_config(nucleos=nucleos, personas=[])
        
        config = get_config()
        assert len(config["nucleos"]) == 2
        assert config["nucleos"][0]["nombre"] == "Padres de Angel"

    def test_save_config_generates_iniciales(self, tmp_data_file):
        """save_config should auto-generate iniciales for personas."""
        from vacaciones_controller import get_config, save_config
        
        personas = [
            {"id": "p1", "nombre": "Angel"},
            {"id": "p2", "nombre": "Virginia"},
            {"id": "p3", "nombre": "Abuela"}
        ]
        save_config(nucleos=[], personas=personas)
        
        config = get_config()
        iniciales = [p["inicial"] for p in config["personas"]]
        
        # Should be unique
        assert len(set(iniciales)) == 3
        assert "A" in iniciales
        assert "V" in iniciales
        # Third A person gets AN or similar
        assert any(i.startswith("A") and i != "A" for i in iniciales)

    def test_save_config_preserves_existing_inicial(self, tmp_data_file):
        """save_config should preserve existing valid iniciales."""
        from vacaciones_controller import get_config, save_config
        
        personas = [
            {"id": "p1", "nombre": "Angel", "inicial": "ANG"},
        ]
        save_config(nucleos=[], personas=personas)
        
        config = get_config()
        assert config["personas"][0]["inicial"] == "ANG"

    def test_save_config_skips_empty_names(self, tmp_data_file):
        """save_config should skip personas with empty names."""
        from vacaciones_controller import get_config, save_config
        
        personas = [
            {"id": "p1", "nombre": "Angel"},
            {"id": "p2", "nombre": "   "},  # Empty after strip
            {"id": "p3", "nombre": "Virginia"}
        ]
        save_config(nucleos=[], personas=personas)
        
        config = get_config()
        assert len(config["personas"]) == 2


class TestYearManagement:
    """Tests for year planning management."""

    def test_add_year_creates_next_year(self, tmp_data_file):
        """add_year should create the next year after highest existing."""
        from vacaciones_controller import add_year, get_vacaciones_data
        
        result = add_year()
        
        assert result["status"] == "ok"
        assert result["year"] == 2027  # Default is 2026, so next is 2027
        
        data = get_vacaciones_data()
        years = [y["year"] for y in data["years"]]
        assert 2027 in years

    def test_add_year_initializes_comidas(self, tmp_data_file):
        """add_year should initialize comidas for the new year."""
        from vacaciones_controller import MOMENTOS, add_year, get_vacaciones_data
        
        add_year()
        data = get_vacaciones_data()
        
        new_year = next(y for y in data["years"] if y["year"] == 2027)
        assert len(new_year["comidas"]) == len(MOMENTOS)

    def test_save_year_updates_existing(self, tmp_data_file):
        """save_year should update an existing year's comidas."""
        from vacaciones_controller import get_vacaciones_data, save_year
        
        comidas = [
            {
                "momento": "cena_24",
                "nucleo_id": "padres_angel",
                "personas": ["angel", "virginia"],
                "notas": "Test note"
            }
        ]
        save_year(2026, comidas, notas="Year note")
        
        data = get_vacaciones_data()
        year_2026 = next(y for y in data["years"] if y["year"] == 2026)
        
        assert year_2026["notas"] == "Year note"
        assert len(year_2026["comidas"]) == 1
        assert year_2026["comidas"][0]["nucleo_id"] == "padres_angel"

    def test_save_year_creates_if_missing(self, tmp_data_file):
        """save_year should create year if it doesn't exist."""
        from vacaciones_controller import get_vacaciones_data, save_year
        
        save_year(2030, [], notas="Future year")
        
        data = get_vacaciones_data()
        years = [y["year"] for y in data["years"]]
        assert 2030 in years

    def test_delete_year_removes_highest(self, tmp_data_file):
        """delete_year should remove the highest year."""
        from vacaciones_controller import add_year, delete_year, get_vacaciones_data
        
        add_year()  # Creates 2027
        result = delete_year(2027)
        
        assert result["status"] == "ok"
        
        data = get_vacaciones_data()
        years = [y["year"] for y in data["years"]]
        assert 2027 not in years

    def test_delete_year_rejects_non_highest(self, tmp_data_file):
        """delete_year should reject deleting non-highest year."""
        from vacaciones_controller import add_year, delete_year
        
        add_year()  # Creates 2027
        result = delete_year(2026)  # Try to delete lower year
        
        assert result["status"] == "error"
        assert "highest" in result["message"].lower()

    def test_delete_year_rejects_last_year(self, tmp_data_file):
        """delete_year should reject deleting the only year."""
        from vacaciones_controller import delete_year
        
        result = delete_year(2026)  # Only year
        
        assert result["status"] == "error"
        assert "only" in result["message"].lower()


class TestMomentos:
    """Tests for MOMENTOS configuration."""

    def test_momentos_has_required_fields(self, tmp_data_file):
        """Each momento should have required fields."""
        from vacaciones_controller import MOMENTOS
        
        for momento in MOMENTOS:
            assert "id" in momento
            assert "label" in momento
            assert "dia" in momento
            assert "tipo" in momento
            assert "importante" in momento

    def test_momentos_covers_key_dates(self, tmp_data_file):
        """MOMENTOS should cover key Christmas dates."""
        from vacaciones_controller import MOMENTOS
        
        dias = [m["dia"] for m in MOMENTOS]
        
        assert 24 in dias  # Nochebuena
        assert 25 in dias  # Navidad
        assert 31 in dias  # Nochevieja
        assert 1 in dias   # Año Nuevo
        assert 6 in dias   # Reyes

    def test_important_meals_marked(self, tmp_data_file):
        """Important meals (24, 25, 31, 1) should be marked importante."""
        from vacaciones_controller import MOMENTOS
        
        important_ids = ["cena_24", "comida_25", "cena_31", "comida_1"]
        for m in MOMENTOS:
            if m["id"] in important_ids:
                assert m["importante"] is True


class TestHealthCheck:
    """Tests for health check functionality."""

    def test_is_healthy_returns_true(self, tmp_data_file):
        """is_healthy should return True."""
        from vacaciones_controller import is_healthy
        
        assert is_healthy() is True


class TestDataclasses:
    """Tests for dataclass serialization."""

    def test_persona_to_dict(self, tmp_data_file):
        """Persona should serialize correctly."""
        from vacaciones_controller import Persona
        
        persona = Persona(id="p1", nombre="Test", inicial="T")
        result = persona.to_dict()
        
        assert result == {"id": "p1", "nombre": "Test", "inicial": "T"}

    def test_nucleo_familiar_to_dict(self, tmp_data_file):
        """NucleoFamiliar should serialize correctly."""
        from vacaciones_controller import NucleoFamiliar
        
        nucleo = NucleoFamiliar(id="n1", nombre="Test", color="#fff", hijo_id="h1")
        result = nucleo.to_dict()
        
        assert result["id"] == "n1"
        assert result["nombre"] == "Test"
        assert result["color"] == "#fff"
        assert result["hijo_id"] == "h1"

    def test_comida_to_dict(self, tmp_data_file):
        """Comida should serialize correctly."""
        from vacaciones_controller import Comida
        
        comida = Comida(
            momento="cena_24",
            nucleo_id="n1",
            personas=["p1", "p2"],
            personas_por_nucleo={"n1": ["p1"], "n2": ["p2"]},
            notas="Test note"
        )
        result = comida.to_dict()
        
        assert result["momento"] == "cena_24"
        assert result["nucleo_id"] == "n1"
        assert result["personas"] == ["p1", "p2"]
        assert result["personas_por_nucleo"] == {"n1": ["p1"], "n2": ["p2"]}
        assert result["notas"] == "Test note"
