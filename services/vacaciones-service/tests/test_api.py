"""Unit tests for FastAPI endpoints."""


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
            "/api/vacaciones/config", json={"nucleos": [sample_nucleo], "personas": []}
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
            "/api/vacaciones/config", json={"nucleos": [], "personas": [sample_persona]}
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
            "/api/vacaciones/config", json={"nucleos": [], "personas": personas}
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
                "notas": "Test",
            }
        ]

        response = client.post(
            "/api/vacaciones/year/2026", json={"comidas": comidas, "notas": "Year note"}
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


class TestInputValidation:
    """Tests for Pydantic input validation."""

    def test_nucleo_id_pattern_rejects_invalid(self, client):
        """Nucleo ID must match pattern [a-z0-9_]+."""
        response = client.post(
            "/api/vacaciones/config",
            json={
                "nucleos": [{"id": "Invalid-ID!", "nombre": "Test"}],
                "personas": [],
            },
        )
        assert response.status_code == 422

    def test_nucleo_nombre_max_length(self, client):
        """Nucleo nombre max length is 100."""
        response = client.post(
            "/api/vacaciones/config",
            json={
                "nucleos": [{"id": "valid_id", "nombre": "x" * 101}],
                "personas": [],
            },
        )
        assert response.status_code == 422

    def test_persona_id_pattern_rejects_invalid(self, client):
        """Persona ID must match pattern [a-z0-9_]+."""
        response = client.post(
            "/api/vacaciones/config",
            json={
                "nucleos": [],
                "personas": [{"id": "BAD ID", "nombre": "Test"}],
            },
        )
        assert response.status_code == 422

    def test_config_valid_data_accepted(self, client):
        """Valid config data should be accepted."""
        response = client.post(
            "/api/vacaciones/config",
            json={
                "nucleos": [
                    {"id": "nucleo_1", "nombre": "Test Nucleo", "color": "#ff0000"}
                ],
                "personas": [{"id": "persona_1", "nombre": "Test Person"}],
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


class TestResourceLimits:
    """Tests for resource limits."""

    def test_too_many_nucleos_rejected(self, client):
        """More than MAX_NUCLEOS should be rejected."""
        nucleos = [{"id": f"n_{i}", "nombre": f"Nucleo {i}"} for i in range(21)]
        response = client.post(
            "/api/vacaciones/config",
            json={"nucleos": nucleos, "personas": []},
        )
        # Pydantic max_length on list rejects at 422
        assert response.status_code == 422

    def test_too_many_personas_rejected(self, client):
        """More than MAX_PERSONAS should be rejected."""
        personas = [{"id": f"p_{i}", "nombre": f"Persona {i}"} for i in range(51)]
        response = client.post(
            "/api/vacaciones/config",
            json={"nucleos": [], "personas": personas},
        )
        assert response.status_code == 422

    def test_max_years_limit(self, client):
        """Adding years beyond MAX_YEARS should fail."""
        # Add 19 more years (default has 1)
        for _ in range(19):
            resp = client.post("/api/vacaciones/year")
            assert resp.json()["status"] == "ok"

        # The 21st year should fail
        response = client.post("/api/vacaciones/year")
        data = response.json()
        assert data["status"] == "error"
        assert "max" in data["message"].lower()


class TestRateLimiting:
    """Tests for rate limiting on write endpoints."""

    def test_rate_limit_allows_normal_usage(self, client):
        """Normal usage should not be rate limited."""
        # 5 requests should all succeed
        for _ in range(5):
            response = client.post(
                "/api/vacaciones/config",
                json={"nucleos": [], "personas": []},
            )
            assert response.status_code == 200

    def test_rate_limit_blocks_after_threshold(self, client):
        """Requests beyond threshold should return 429."""
        import main
        from smart_home_common.rate_limiter import InMemoryRateLimiter

        # Replace with a low-limit rate limiter for testing
        original_limiter = main._rate_limiter
        main._rate_limiter = InMemoryRateLimiter(max_requests=3, window_seconds=60)

        try:
            # First 3 should succeed
            for _ in range(3):
                response = client.post(
                    "/api/vacaciones/config",
                    json={"nucleos": [], "personas": []},
                )
                assert response.status_code == 200

            # 4th should be rate limited
            response = client.post(
                "/api/vacaciones/config",
                json={"nucleos": [], "personas": []},
            )
            assert response.status_code == 429
            assert (
                "too many" in response.json()["detail"].lower()
                or "rate limit" in response.json()["detail"].lower()
            )
        finally:
            main._rate_limiter = original_limiter

    def test_rate_limit_applies_to_year_endpoints(self, client):
        """Rate limiting should apply to year management endpoints."""
        import main
        from smart_home_common.rate_limiter import InMemoryRateLimiter

        original_limiter = main._rate_limiter
        main._rate_limiter = InMemoryRateLimiter(max_requests=2, window_seconds=60)

        try:
            # Use up rate limit
            for _ in range(2):
                client.post(
                    "/api/vacaciones/config",
                    json={"nucleos": [], "personas": []},
                )

            # Year endpoint should also be limited
            response = client.post("/api/vacaciones/year")
            assert response.status_code == 429
        finally:
            main._rate_limiter = original_limiter

    def test_rate_limit_respects_x_forwarded_for(self, client):
        """Rate limiting should use X-Forwarded-For header."""
        import main
        from smart_home_common.rate_limiter import InMemoryRateLimiter

        original_limiter = main._rate_limiter
        main._rate_limiter = InMemoryRateLimiter(max_requests=2, window_seconds=60)

        try:
            # Requests from IP 1.2.3.4 (via header)
            for _ in range(2):
                response = client.post(
                    "/api/vacaciones/config",
                    json={"nucleos": [], "personas": []},
                    headers={"X-Forwarded-For": "1.2.3.4"},
                )
                assert response.status_code == 200

            # 3rd from same IP should be limited
            response = client.post(
                "/api/vacaciones/config",
                json={"nucleos": [], "personas": []},
                headers={"X-Forwarded-For": "1.2.3.4"},
            )
            assert response.status_code == 429

            # But different IP should succeed
            response = client.post(
                "/api/vacaciones/config",
                json={"nucleos": [], "personas": []},
                headers={"X-Forwarded-For": "5.6.7.8"},
            )
            assert response.status_code == 200
        finally:
            main._rate_limiter = original_limiter

    def test_get_endpoints_not_rate_limited(self, client):
        """GET endpoints should not be rate limited."""
        import main
        from smart_home_common.rate_limiter import InMemoryRateLimiter

        original_limiter = main._rate_limiter
        main._rate_limiter = InMemoryRateLimiter(max_requests=2, window_seconds=60)

        try:
            # Exhaust rate limit
            for _ in range(3):
                client.post(
                    "/api/vacaciones/config",
                    json={"nucleos": [], "personas": []},
                )

            # GET should still work
            response = client.get("/api/vacaciones")
            assert response.status_code == 200

            response = client.get("/api/vacaciones/config")
            assert response.status_code == 200

            response = client.get("/health")
            assert response.status_code == 200
        finally:
            main._rate_limiter = original_limiter


class TestCSRFProtection:
    """Tests for CSRF protection via Origin/Referer validation."""

    def test_csrf_blocks_request_without_origin_when_enabled(self, tmp_data_file):
        """POST without Origin/Referer should be rejected when CSRF enabled."""
        import importlib
        import os

        import main

        # Re-import main with CSRF enabled
        os.environ["ALLOWED_ORIGINS"] = "https://example.com"
        importlib.reload(main)

        from fastapi.testclient import TestClient

        client = TestClient(main.app)

        try:
            response = client.post(
                "/api/vacaciones/config",
                json={"nucleos": [], "personas": []},
            )
            assert response.status_code == 403
            assert "Origin" in response.json()["detail"]
        finally:
            # Restore disabled CSRF for other tests
            os.environ["ALLOWED_ORIGINS"] = "*"
            importlib.reload(main)

    def test_csrf_blocks_wrong_origin(self, tmp_data_file):
        """POST with wrong Origin should be rejected."""
        import importlib
        import os

        import main

        os.environ["ALLOWED_ORIGINS"] = "https://allowed.com"
        importlib.reload(main)

        from fastapi.testclient import TestClient

        client = TestClient(main.app)

        try:
            response = client.post(
                "/api/vacaciones/config",
                json={"nucleos": [], "personas": []},
                headers={"Origin": "https://evil.com"},
            )
            assert response.status_code == 403
            assert "not allowed" in response.json()["detail"]
        finally:
            os.environ["ALLOWED_ORIGINS"] = "*"
            importlib.reload(main)

    def test_csrf_allows_correct_origin(self, tmp_data_file):
        """POST with correct Origin should succeed."""
        import importlib
        import os

        import main

        os.environ["ALLOWED_ORIGINS"] = "https://allowed.com"
        importlib.reload(main)

        from fastapi.testclient import TestClient

        client = TestClient(main.app)

        try:
            response = client.post(
                "/api/vacaciones/config",
                json={"nucleos": [], "personas": []},
                headers={"Origin": "https://allowed.com"},
            )
            assert response.status_code == 200
        finally:
            os.environ["ALLOWED_ORIGINS"] = "*"
            importlib.reload(main)

    def test_csrf_allows_referer_when_no_origin(self, tmp_data_file):
        """POST with Referer (no Origin) should succeed if Referer allowed."""
        import importlib
        import os

        import main

        os.environ["ALLOWED_ORIGINS"] = "https://allowed.com"
        importlib.reload(main)

        from fastapi.testclient import TestClient

        client = TestClient(main.app)

        try:
            response = client.post(
                "/api/vacaciones/config",
                json={"nucleos": [], "personas": []},
                headers={"Referer": "https://allowed.com/some/path"},
            )
            assert response.status_code == 200
        finally:
            os.environ["ALLOWED_ORIGINS"] = "*"
            importlib.reload(main)

    def test_csrf_allows_multiple_origins(self, tmp_data_file):
        """ALLOWED_ORIGINS can contain multiple comma-separated origins."""
        import importlib
        import os

        import main

        os.environ["ALLOWED_ORIGINS"] = "https://a.com, https://b.com"
        importlib.reload(main)

        from fastapi.testclient import TestClient

        client = TestClient(main.app)

        try:
            # Origin a.com should work
            response = client.post(
                "/api/vacaciones/config",
                json={"nucleos": [], "personas": []},
                headers={"Origin": "https://a.com"},
            )
            assert response.status_code == 200

            # Origin b.com should work
            response = client.post(
                "/api/vacaciones/year",
                headers={"Origin": "https://b.com"},
            )
            assert response.status_code == 200

            # Origin c.com should be blocked
            response = client.delete(
                "/api/vacaciones/year/2025",
                headers={"Origin": "https://c.com"},
            )
            assert response.status_code == 403
        finally:
            os.environ["ALLOWED_ORIGINS"] = "*"
            importlib.reload(main)

    def test_csrf_disabled_with_star(self, client):
        """ALLOWED_ORIGINS='*' should disable CSRF checking."""
        # This test uses the default client which has CSRF disabled via conftest
        # Just verify POST works without any Origin header
        response = client.post(
            "/api/vacaciones/config",
            json={"nucleos": [], "personas": []},
        )
        assert response.status_code == 200

    def test_csrf_get_requests_not_checked(self, tmp_data_file):
        """GET requests should not require Origin header."""
        import importlib
        import os

        import main

        os.environ["ALLOWED_ORIGINS"] = "https://allowed.com"
        importlib.reload(main)

        from fastapi.testclient import TestClient

        client = TestClient(main.app)

        try:
            # GET without Origin should work
            response = client.get("/api/vacaciones")
            assert response.status_code == 200

            response = client.get("/api/vacaciones/config")
            assert response.status_code == 200

            response = client.get("/health")
            assert response.status_code == 200
        finally:
            os.environ["ALLOWED_ORIGINS"] = "*"
            importlib.reload(main)

    def test_csrf_delete_endpoint_protected(self, tmp_data_file):
        """DELETE endpoints should also be CSRF protected."""
        import importlib
        import os

        import main

        os.environ["ALLOWED_ORIGINS"] = "https://allowed.com"
        importlib.reload(main)

        from fastapi.testclient import TestClient

        client = TestClient(main.app)

        try:
            # First add a year with correct origin
            client.post(
                "/api/vacaciones/year", headers={"Origin": "https://allowed.com"}
            )

            # DELETE without Origin should fail
            response = client.delete("/api/vacaciones/year/2025")
            assert response.status_code == 403
        finally:
            os.environ["ALLOWED_ORIGINS"] = "*"
            importlib.reload(main)


class TestSecurityHeaders:
    """Tests for security headers middleware."""

    def test_security_headers_present_on_get(self, tmp_data_file):
        """Security headers should be present on GET responses."""
        import importlib

        import main

        importlib.reload(main)

        from fastapi.testclient import TestClient

        client = TestClient(main.app)

        response = client.get("/api/vacaciones")

        assert response.status_code == 200
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["X-XSS-Protection"] == "1; mode=block"
        assert response.headers["Content-Security-Policy"] == "default-src 'self'"
        assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"

    def test_security_headers_present_on_post(self, tmp_data_file):
        """Security headers should be present on POST responses."""
        import importlib

        import main

        importlib.reload(main)

        from fastapi.testclient import TestClient

        client = TestClient(main.app)

        response = client.post(
            "/api/vacaciones/config",
            json={"nucleos": [], "personas": []},
        )

        assert response.status_code == 200
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["X-XSS-Protection"] == "1; mode=block"
        assert response.headers["Content-Security-Policy"] == "default-src 'self'"
        assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"

    def test_security_headers_present_on_health(self, tmp_data_file):
        """Security headers should be present on health endpoint."""
        import importlib

        import main

        importlib.reload(main)

        from fastapi.testclient import TestClient

        client = TestClient(main.app)

        response = client.get("/health")

        assert response.status_code == 200
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"

    def test_security_headers_present_on_error(self, tmp_data_file):
        """Security headers should be present even on error responses."""
        import importlib

        import main

        importlib.reload(main)

        from fastapi.testclient import TestClient

        client = TestClient(main.app)

        response = client.post(
            "/api/vacaciones/config",
            json={
                "nucleos": [{"id": "INVALID!", "nombre": "Test"}],
                "personas": [],
            },
        )

        assert response.status_code == 422
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"


class TestRateLimitLogging:
    """Tests for rate limit logging."""

    def test_rate_limit_logs_warning(self, tmp_data_file):
        """Rate limit should log warning with IP and path."""
        import importlib
        from unittest.mock import patch

        import main
        from smart_home_common.rate_limiter import InMemoryRateLimiter

        importlib.reload(main)

        from fastapi.testclient import TestClient

        client = TestClient(main.app)

        original_limiter = main._rate_limiter
        main._rate_limiter = InMemoryRateLimiter(
            max_requests=2, window_seconds=60, max_entries=100
        )

        try:
            # Exhaust rate limit
            for _ in range(2):
                client.post(
                    "/api/vacaciones/config",
                    json={"nucleos": [], "personas": []},
                    headers={"X-Forwarded-For": "10.20.30.40"},
                )

            # Next request should be rate limited and logged
            with patch.object(main.logger, "warning") as mock_warning:
                response = client.post(
                    "/api/vacaciones/config",
                    json={"nucleos": [], "personas": []},
                    headers={"X-Forwarded-For": "10.20.30.40"},
                )

                assert response.status_code == 429
                mock_warning.assert_called_once()
                call_args = mock_warning.call_args
                # Verify the log message format
                assert "[rate-limit]" in call_args[0][0]
                assert "10.20.30.40" in call_args[0][1]
                assert "/api/vacaciones/config" in call_args[0][2]
        finally:
            main._rate_limiter = original_limiter

    def test_rate_limiter_has_max_entries(self, tmp_data_file):
        """Rate limiter should be configured with max_entries."""
        import importlib

        import main

        importlib.reload(main)

        assert main._rate_limiter.max_entries == 10000
