"""Unit tests for FastAPI endpoints."""

import pytest


class TestHealthEndpoints:
    """Tests for health check endpoints."""

    def test_health_returns_online(self, client):
        """Health endpoint should return online status."""
        response = client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["online"] is True
        assert data["service"] == "vacaciones"

    def test_health_alias_returns_online(self, client):
        """Health alias endpoint should return online status."""
        response = client.get("/api/health/vacaciones")
        
        assert response.status_code == 200
        data = response.json()
        assert data["online"] is True


class TestDataEndpoints:
    """Tests for main data retrieval endpoints."""

    def test_get_vacaciones_returns_data(self, client):
        """GET /api/vacaciones should return all data."""
        response = client.get("/api/vacaciones")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "nucleos" in data
        assert "personas" in data
        assert "years" in data
        assert "momentos" in data

    def test_get_vacaciones_includes_momentos(self, client):
        """GET /api/vacaciones should include momentos configuration."""
        response = client.get("/api/vacaciones")
        data = response.json()
        
        assert len(data["momentos"]) > 0
        assert all("id" in m for m in data["momentos"])

    def test_get_config_returns_config(self, client):
        """GET /api/vacaciones/config should return nucleos and personas."""
        response = client.get("/api/vacaciones/config")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "nucleos" in data
        assert "personas" in data


class TestConfigEndpoints:
    """Tests for configuration management endpoints."""

    def test_post_config_saves_nucleos(self, client, sample_nucleo):
        """POST /api/vacaciones/config should save nucleos."""
        response = client.post(
            "/api/vacaciones/config",
            json={"nucleos": [sample_nucleo], "personas": []}
        )
        
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        
        # Verify
        config = client.get("/api/vacaciones/config").json()
        assert len(config["nucleos"]) == 1
        assert config["nucleos"][0]["nombre"] == sample_nucleo["nombre"]

    def test_post_config_saves_personas(self, client, sample_persona):
        """POST /api/vacaciones/config should save personas."""
        response = client.post(
            "/api/vacaciones/config",
            json={"nucleos": [], "personas": [sample_persona]}
        )
        
        assert response.status_code == 200
        
        config = client.get("/api/vacaciones/config").json()
        assert len(config["personas"]) == 1
        assert config["personas"][0]["nombre"] == sample_persona["nombre"]

    def test_post_config_generates_iniciales(self, client):
        """POST /api/vacaciones/config should generate iniciales."""
        personas = [
            {"id": "p1", "nombre": "Angel"},
            {"id": "p2", "nombre": "Virginia"},
        ]
        
        client.post(
            "/api/vacaciones/config",
            json={"nucleos": [], "personas": personas}
        )
        
        config = client.get("/api/vacaciones/config").json()
        iniciales = [p["inicial"] for p in config["personas"]]
        
        assert "A" in iniciales
        assert "V" in iniciales


class TestYearEndpoints:
    """Tests for year management endpoints."""

    def test_add_year_creates_new(self, client):
        """POST /api/vacaciones/year should create a new year."""
        response = client.post("/api/vacaciones/year")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "year" in data

    def test_post_year_saves_comidas(self, client):
        """POST /api/vacaciones/year/{year} should save comidas."""
        comidas = [
            {
                "momento": "cena_24",
                "nucleo_id": "n1",
                "personas": ["p1"],
                "personas_por_nucleo": {},
                "notas": "Test"
            }
        ]
        
        response = client.post(
            "/api/vacaciones/year/2026",
            json={"comidas": comidas, "notas": "Year note"}
        )
        
        assert response.status_code == 200
        
        # Verify
        data = client.get("/api/vacaciones").json()
        year_2026 = next(y for y in data["years"] if y["year"] == 2026)
        assert year_2026["notas"] == "Year note"

    def test_delete_year_removes_highest(self, client):
        """DELETE /api/vacaciones/year/{year} should remove the highest year."""
        # First add a year
        add_resp = client.post("/api/vacaciones/year")
        new_year = add_resp.json()["year"]
        
        # Then delete it
        response = client.delete(f"/api/vacaciones/year/{new_year}")
        
        assert response.status_code == 200
        
        # Verify it's gone
        data = client.get("/api/vacaciones").json()
        years = [y["year"] for y in data["years"]]
        assert new_year not in years

    def test_delete_non_highest_year_fails(self, client):
        """DELETE /api/vacaciones/year/{year} should fail for non-highest year."""
        # Add a year first so we have > 1
        client.post("/api/vacaciones/year")
        
        # Try to delete the lower year
        response = client.delete("/api/vacaciones/year/2026")
        
        assert response.status_code == 400

    def test_delete_only_year_fails(self, client):
        """DELETE /api/vacaciones/year/{year} should fail for the only year."""
        response = client.delete("/api/vacaciones/year/2026")
        
        assert response.status_code == 400


class TestSPAServing:
    """Tests for SPA HTML serving."""

    def test_spa_served(self, client):
        """GET /smart-home/vacaciones should serve HTML."""
        response = client.get("/smart-home/vacaciones")
        
        # May fail if static file doesn't exist in test env
        # but endpoint should at least not 404
        assert response.status_code in (200, 500)

    def test_serve_html_returns_200(self, client):
        """GET /smart-home/vacaciones must return 200, not silently 500.

        The bundled static/vacaciones.html ships with the service, so
        _serve_html should always succeed. A 500 here means the SPA file is
        missing or unreadable — a real failure the suite must not tolerate.
        """
        response = client.get("/smart-home/vacaciones")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert response.headers["cache-control"] == (
            "no-cache, no-store, must-revalidate, max-age=0"
        )
        assert len(response.text) > 0


class TestDefaultData:
    """Tests for default data initialization."""

    def test_default_year_exists(self, client):
        """Default year should exist on first access."""
        response = client.get("/api/vacaciones")
        data = response.json()
        
        assert len(data["years"]) >= 1
        assert data["years"][0]["year"] == 2026

    def test_default_year_has_all_momentos(self, client):
        """Default year should have comidas for all momentos."""
        response = client.get("/api/vacaciones")
        data = response.json()
        
        year_2026 = next(y for y in data["years"] if y["year"] == 2026)
        momentos_ids = [m["id"] for m in data["momentos"]]
        comidas_momentos = [c["momento"] for c in year_2026["comidas"]]
        
        for momento_id in momentos_ids:
            assert momento_id in comidas_momentos
