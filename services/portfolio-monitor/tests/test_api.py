"""
Test API endpoints.

Basic smoke tests for API endpoints to ensure they respond correctly.
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create a test client for the API."""
    from main import app

    return TestClient(app)


class TestHealthEndpoint:
    """Tests for health check endpoint."""

    def test_health_returns_200(self, client):
        """Health endpoint should return 200."""
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_returns_status(self, client):
        """Health endpoint should return online field."""
        response = client.get("/health")
        data = response.json()
        assert "online" in data
        assert data["online"] is True


class TestAPIEndpoints:
    """Tests for main API endpoints."""

    def test_summary_endpoint_exists(self, client):
        """Summary endpoint should exist and return JSON."""
        response = client.get("/api/portfolio/summary")
        # May return 200 or 500 depending on config, but should not 404
        assert response.status_code != 404

    def test_etf_endpoint_exists(self, client):
        """ETF endpoint should exist."""
        response = client.get("/api/portfolio/etf")
        assert response.status_code != 404

    def test_crypto_endpoint_exists(self, client):
        """Crypto endpoint should exist."""
        response = client.get("/api/portfolio/crypto")
        assert response.status_code != 404

    def test_schedule_endpoint_exists(self, client):
        """Schedule endpoint should exist."""
        response = client.get("/api/portfolio/schedule")
        assert response.status_code == 200

    def test_schedule_returns_times(self, client):
        """Schedule endpoint should return monitor times."""
        response = client.get("/api/portfolio/schedule")
        data = response.json()

        # Schedule times are nested under 'schedule' key
        assert "schedule" in data
        assert "etf_time" in data["schedule"]
        assert "crypto_time" in data["schedule"]


class TestStaticFiles:
    """Tests for static file serving."""

    def test_dashboard_html_served(self, client):
        """Dashboard HTML should be served at /smart-home/portfolio."""
        response = client.get("/smart-home/portfolio")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")


class TestSerializationNaNSafety:
    """Regression tests: NaN/Inf must be scrubbed to None at any nesting depth.

    A real yfinance OHLC gap produced np.float64(nan) inside the nested
    ``ohlc`` list, which crashed /api/portfolio/summary with
    'Out of range float values are not JSON compliant'.
    """

    def test_safe_float_scrubs_nan_and_inf(self):
        from api.routes import _safe_float

        assert _safe_float(float("nan")) is None
        assert _safe_float(float("inf")) is None
        assert _safe_float(float("-inf")) is None
        assert _safe_float(1.5) == 1.5
        assert _safe_float(None) is None

    def test_serialize_scrubs_nan_in_nested_ohlc(self):
        """NaN inside a list-of-lists (ohlc sparkline) must become None."""
        import json

        from api.routes import _serialize_analysis
        from models import ETFAnalysis

        analysis = ETFAnalysis(
            fund_id="f1",
            ticker="VWCE",
            name="Vanguard FTSE All-World",
            color="#abcdef",
            ohlc=[[1.0, 2.0, float("nan"), 4.0], [float("inf"), 5.0, 6.0, 7.0]],
        )

        result = _serialize_analysis(analysis)

        # Must be JSON-serializable without allow_nan (FastAPI uses strict JSON).
        json.dumps(result, allow_nan=False)

        assert result["ohlc"][0][2] is None
        assert result["ohlc"][1][0] is None
        assert result["ohlc"][0][0] == 1.0

    def test_serialize_scrubs_nan_in_scalar_field(self):
        import json

        from api.routes import _serialize_analysis
        from models import ETFAnalysis

        analysis = ETFAnalysis(
            fund_id="f1",
            ticker="VWCE",
            name="Vanguard FTSE All-World",
            color="#abcdef",
            annual_vol=float("nan"),
        )

        result = _serialize_analysis(analysis)
        json.dumps(result, allow_nan=False)
        assert result["annual_vol"] is None


class TestResponseScrubNaNSafety:
    """The response-layer safety net: no endpoint may ever emit NaN/Inf.

    These tests guard the belt-and-braces defense added so this class of bug
    cannot recur even if a future field, code path, or serializer leaks a raw
    non-finite float that bypasses _serialize_analysis.
    """

    def test_scrub_payload_scrubs_nan_at_any_depth(self):
        from api.routes import _scrub_payload

        payload = {
            "a": float("nan"),
            "b": [1.0, float("inf"), {"c": float("-inf")}],
            "d": (float("nan"), 2.0),
            "ok": {"x": 3.0, "s": "text", "n": None, "flag": True, "i": 5},
        }
        scrubbed = _scrub_payload(payload)

        assert scrubbed["a"] is None
        assert scrubbed["b"][1] is None
        assert scrubbed["b"][2]["c"] is None
        assert scrubbed["d"][0] is None
        assert scrubbed["d"][1] == 2.0
        assert scrubbed["ok"] == {
            "x": 3.0,
            "s": "text",
            "n": None,
            "flag": True,
            "i": 5,
        }

    def test_scrub_payload_handles_numpy_floats(self):
        np = pytest.importorskip("numpy")
        from api.routes import _scrub_payload

        payload = {"v": np.float64("nan"), "w": np.float64(1.25)}
        scrubbed = _scrub_payload(payload)

        assert scrubbed["v"] is None
        assert scrubbed["w"] == 1.25

    def test_safe_json_render_is_strict_json(self):
        """_SafeJSONResponse must produce valid JSON even with NaN/Inf input."""
        import json

        from api.routes import _SafeJSONResponse

        resp = _SafeJSONResponse(content=None)
        body = resp.render({"a": float("nan"), "b": [float("inf")], "c": 1.0})

        # Round-trips as strict JSON (no NaN/Infinity literals).
        parsed = json.loads(body.decode("utf-8"))
        assert parsed == {"a": None, "b": [None], "c": 1.0}
        assert b"NaN" not in body
        assert b"Infinity" not in body

    def test_summary_endpoint_survives_nan_in_ohlc(self, monkeypatch):
        """End-to-end: a NaN in ohlc must NOT 500 the summary endpoint.

        Reproduces the production failure (yfinance OHLC gap) through the real
        FastAPI stack and asserts 200 + strict-JSON compliant body.
        """
        import orchestrator
        from fastapi.testclient import TestClient
        from main import app
        from models import ETFAnalysis, PortfolioSummary

        summary = PortfolioSummary()
        summary.etf_analysis = [
            ETFAnalysis(
                fund_id="f1",
                ticker="VWCE",
                name="Vanguard FTSE All-World",
                color="#abcdef",
                annual_vol=float("nan"),
                ohlc=[[1.0, 2.0, float("nan"), 4.0], [float("inf"), 5.0, 6.0, 7.0]],
            )
        ]

        class _FakeOrch:
            def get_summary(self):
                return summary

        monkeypatch.setattr(orchestrator, "get_orchestrator", lambda: _FakeOrch())
        # routes.py imports get_orchestrator by name — patch that binding too.
        import api.routes as routes_mod

        monkeypatch.setattr(routes_mod, "get_orchestrator", lambda: _FakeOrch())

        client = TestClient(app)
        response = client.get("/api/portfolio/summary")

        assert response.status_code == 200
        assert b"NaN" not in response.content
        assert b"Infinity" not in response.content
        data = response.json()
        assert data["etf"]["analysis"][0]["ohlc"][0][2] is None
        assert data["etf"]["analysis"][0]["annual_vol"] is None
