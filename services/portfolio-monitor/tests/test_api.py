"""
Test API endpoints.

Includes:
- Basic smoke tests for API endpoints
- Rate limiting tests
- External health check tests
- JSON serialization safety tests
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create a test client for the API."""
    from main import app

    return TestClient(app)


@pytest.fixture(autouse=True)
def reset_rate_limiters():
    """Reset rate limiters before each test."""
    from api.routes import _config_limiter, _refresh_limiter

    _refresh_limiter._requests.clear()
    _config_limiter._requests.clear()
    yield
    _refresh_limiter._requests.clear()
    _config_limiter._requests.clear()


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


class TestRateLimiting:
    """Tests for rate limiting on expensive endpoints."""

    def test_rate_limiter_allows_initial_requests(self):
        """Rate limiter allows requests under the limit."""
        from api.routes import RateLimiter

        limiter = RateLimiter(max_requests=3, window_seconds=60)

        assert limiter.is_allowed("test-key") is True
        assert limiter.is_allowed("test-key") is True
        assert limiter.is_allowed("test-key") is True

    def test_rate_limiter_blocks_excess_requests(self):
        """Rate limiter blocks requests over the limit."""
        from api.routes import RateLimiter

        limiter = RateLimiter(max_requests=2, window_seconds=60)

        assert limiter.is_allowed("test-key") is True
        assert limiter.is_allowed("test-key") is True
        assert limiter.is_allowed("test-key") is False

    def test_rate_limiter_separate_keys(self):
        """Different keys have separate limits."""
        from api.routes import RateLimiter

        limiter = RateLimiter(max_requests=1, window_seconds=60)

        assert limiter.is_allowed("key-1") is True
        assert limiter.is_allowed("key-2") is True
        assert limiter.is_allowed("key-1") is False
        assert limiter.is_allowed("key-2") is False

    def test_rate_limiter_time_until_allowed(self):
        """Time until allowed is calculated correctly."""
        from api.routes import RateLimiter

        limiter = RateLimiter(max_requests=1, window_seconds=60)

        assert limiter.time_until_allowed("new-key") == 0
        limiter.is_allowed("new-key")
        wait_time = limiter.time_until_allowed("new-key")
        assert wait_time > 0
        assert wait_time <= 60

    def test_refresh_endpoint_rate_limited(self, client):
        """Refresh endpoint returns 429 after too many requests."""
        from api.routes import _refresh_limiter

        _refresh_limiter._requests.clear()

        # Make requests up to the limit
        for _ in range(5):
            response = client.post("/api/portfolio/refresh")
            assert response.status_code in (200, 202)

        # Next request should be rate limited
        response = client.post("/api/portfolio/refresh")
        assert response.status_code == 429
        assert "Retry-After" in response.headers

    def test_reload_config_rate_limited(self, client):
        """Reload config endpoint is rate limited."""
        from api.routes import _config_limiter

        _config_limiter._requests.clear()

        # Make requests up to the limit (2)
        for _ in range(2):
            response = client.post("/api/portfolio/reload-config")
            assert response.status_code == 200

        # Next request should be rate limited
        response = client.post("/api/portfolio/reload-config")
        assert response.status_code == 429


class TestExternalHealthChecks:
    """Tests for external service health checks."""

    def test_health_external_endpoint_exists(self, client):
        """External health endpoint should exist."""
        # Mock the external checks to avoid real network calls
        with patch("api.routes.check_yahoo_finance", new_callable=AsyncMock) as mock_yf:
            with patch("api.routes.check_coingecko", new_callable=AsyncMock) as mock_cg:
                with patch(
                    "api.routes.check_fear_greed", new_callable=AsyncMock
                ) as mock_fg:
                    with patch(
                        "api.routes.check_smtp", new_callable=AsyncMock
                    ) as mock_smtp:
                        mock_yf.return_value = {"status": "ok"}
                        mock_cg.return_value = {"status": "ok"}
                        mock_fg.return_value = {"status": "ok", "current_value": 50}
                        mock_smtp.return_value = {"status": "ok"}

                        response = client.get("/api/portfolio/health/external")

        assert response.status_code == 200
        data = response.json()
        assert "overall" in data
        assert "services" in data

    def test_health_external_reports_degraded(self, client):
        """External health reports degraded status."""
        with patch("api.routes.check_yahoo_finance", new_callable=AsyncMock) as mock_yf:
            with patch("api.routes.check_coingecko", new_callable=AsyncMock) as mock_cg:
                with patch(
                    "api.routes.check_fear_greed", new_callable=AsyncMock
                ) as mock_fg:
                    with patch(
                        "api.routes.check_smtp", new_callable=AsyncMock
                    ) as mock_smtp:
                        mock_yf.return_value = {"status": "ok"}
                        mock_cg.return_value = {"status": "rate_limited"}  # Not OK
                        mock_fg.return_value = {"status": "ok"}
                        mock_smtp.return_value = {"status": "not_configured"}

                        response = client.get("/api/portfolio/health/external")

        assert response.status_code == 200
        data = response.json()
        assert data["overall"] == "degraded"

    def test_health_external_reports_unhealthy(self, client):
        """External health reports unhealthy when error."""
        with patch("api.routes.check_yahoo_finance", new_callable=AsyncMock) as mock_yf:
            with patch("api.routes.check_coingecko", new_callable=AsyncMock) as mock_cg:
                with patch(
                    "api.routes.check_fear_greed", new_callable=AsyncMock
                ) as mock_fg:
                    with patch(
                        "api.routes.check_smtp", new_callable=AsyncMock
                    ) as mock_smtp:
                        mock_yf.return_value = {
                            "status": "error",
                            "message": "Connection failed",
                        }
                        mock_cg.return_value = {"status": "ok"}
                        mock_fg.return_value = {"status": "ok"}
                        mock_smtp.return_value = {"status": "ok"}

                        response = client.get("/api/portfolio/health/external")

        assert response.status_code == 200
        data = response.json()
        assert data["overall"] == "unhealthy"

    @pytest.mark.asyncio
    async def test_check_yahoo_finance_success(self):
        """Yahoo Finance check returns OK on success."""
        from api.routes import _check_yahoo_sync

        mock_ticker = MagicMock()
        mock_ticker.fast_info = MagicMock(last_price=150.0)

        with patch("yfinance.Ticker", return_value=mock_ticker):
            result = _check_yahoo_sync()

        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_check_coingecko_success(self):
        """CoinGecko check returns OK on success."""
        from api.routes import _check_coingecko_sync

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("requests.get", return_value=mock_response):
            result = _check_coingecko_sync()

        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_check_coingecko_rate_limited(self):
        """CoinGecko check reports rate limited."""
        from api.routes import _check_coingecko_sync

        mock_response = MagicMock()
        mock_response.status_code = 429

        with patch("requests.get", return_value=mock_response):
            result = _check_coingecko_sync()

        assert result["status"] == "rate_limited"

    @pytest.mark.asyncio
    async def test_check_fear_greed_success(self):
        """Fear & Greed check returns value on success."""
        from api.routes import _check_fear_greed_sync

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": [{"value": "65"}]}

        with patch("requests.get", return_value=mock_response):
            result = _check_fear_greed_sync()

        assert result["status"] == "ok"
        assert result["current_value"] == 65

    @pytest.mark.asyncio
    async def test_check_smtp_not_configured(self):
        """SMTP check reports not configured when no credentials."""
        from api.routes import check_smtp

        with patch.dict("os.environ", {"SMTP_USER": "", "AUTH_SMTP_USER": ""}):
            result = await check_smtp()

        assert result["status"] == "not_configured"


class TestAlertsEndpoint:
    """Tests for alerts endpoints."""

    def test_get_alerts_endpoint(self, client):
        """Get alerts endpoint returns list."""
        response = client.get("/api/portfolio/alerts")
        assert response.status_code == 200
        data = response.json()
        assert "upcoming" in data
        assert "count" in data

    def test_complete_alert_not_found(self, client):
        """Complete alert returns 400 for non-existent alert."""
        response = client.post("/api/portfolio/alerts/nonexistent-alert-id/complete")
        assert response.status_code == 400


class TestSavingsEndpoint:
    """Tests for savings endpoint."""

    def test_savings_endpoint_exists(self, client):
        """Savings endpoint should exist."""
        response = client.get("/api/portfolio/savings")
        assert response.status_code != 404


class TestNotificationEndpoint:
    """Tests for notification endpoints."""

    def test_notification_status_endpoint(self, client):
        """Notification status endpoint returns status."""
        response = client.get("/api/portfolio/notifications/status")
        assert response.status_code == 200
        data = response.json()
        assert "enabled" in data
        assert "type" in data


class TestExternalHealthChecksFunctions:
    """Additional tests for external health check sync functions."""

    def test_check_yahoo_degraded_no_price(self):
        """Yahoo Finance returns degraded when no price data."""
        from api.routes import _check_yahoo_sync

        mock_ticker = MagicMock()
        mock_ticker.fast_info = MagicMock(spec=[])  # No last_price attribute

        with patch("yfinance.Ticker", return_value=mock_ticker):
            result = _check_yahoo_sync()

        assert result["status"] == "degraded"

    def test_check_yahoo_error_exception(self):
        """Yahoo Finance returns error on exception."""
        from api.routes import _check_yahoo_sync

        with patch("yfinance.Ticker", side_effect=Exception("Network error")):
            result = _check_yahoo_sync()

        assert result["status"] == "error"
        assert "network error" in result["message"].lower()

    def test_check_coingecko_other_error_code(self):
        """CoinGecko returns error for non-200/429 codes."""
        from api.routes import _check_coingecko_sync

        mock_response = MagicMock()
        mock_response.status_code = 500

        with patch("requests.get", return_value=mock_response):
            result = _check_coingecko_sync()

        assert result["status"] == "error"
        assert result["http_code"] == 500

    def test_check_coingecko_timeout(self):
        """CoinGecko returns timeout on request timeout."""
        import requests
        from api.routes import _check_coingecko_sync

        with patch("requests.get", side_effect=requests.Timeout("Timeout")):
            result = _check_coingecko_sync()

        assert result["status"] == "timeout"

    def test_check_coingecko_exception(self):
        """CoinGecko returns error on generic exception."""
        from api.routes import _check_coingecko_sync

        with patch("requests.get", side_effect=RuntimeError("Unexpected")):
            result = _check_coingecko_sync()

        assert result["status"] == "error"
        assert "unexpected" in result["message"].lower()

    def test_check_fear_greed_error_code(self):
        """Fear & Greed returns error for non-200 codes."""
        from api.routes import _check_fear_greed_sync

        mock_response = MagicMock()
        mock_response.status_code = 503

        with patch("requests.get", return_value=mock_response):
            result = _check_fear_greed_sync()

        assert result["status"] == "error"
        assert result["http_code"] == 503

    def test_check_fear_greed_exception(self):
        """Fear & Greed returns error on exception."""
        from api.routes import _check_fear_greed_sync

        with patch("requests.get", side_effect=ConnectionError("Failed")):
            result = _check_fear_greed_sync()

        assert result["status"] == "error"

    def test_check_smtp_sync_success(self):
        """SMTP sync check returns OK on successful connection."""
        from api.routes import _check_smtp_sync

        mock_socket = MagicMock()
        with patch("socket.create_connection", return_value=mock_socket):
            result = _check_smtp_sync("smtp.test.com", 587)

        assert result["status"] == "ok"
        assert result["host"] == "smtp.test.com"
        assert result["port"] == 587
        mock_socket.close.assert_called_once()

    def test_check_smtp_sync_timeout(self):
        """SMTP sync check returns timeout on connection timeout."""
        from api.routes import _check_smtp_sync

        with patch("socket.create_connection", side_effect=TimeoutError("Timed out")):
            result = _check_smtp_sync("smtp.test.com", 587)

        assert result["status"] == "timeout"

    def test_check_smtp_sync_error(self):
        """SMTP sync check returns error on connection error."""
        from api.routes import _check_smtp_sync

        with patch(
            "socket.create_connection", side_effect=OSError("Connection refused")
        ):
            result = _check_smtp_sync("smtp.test.com", 587)

        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_check_yahoo_finance_async_wrapper(self):
        """check_yahoo_finance async wrapper handles results."""
        from api.routes import check_yahoo_finance

        mock_ticker = MagicMock()
        mock_ticker.fast_info = MagicMock(last_price=150.0)

        with patch("yfinance.Ticker", return_value=mock_ticker):
            result = await check_yahoo_finance()

        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_check_yahoo_finance_async_exception(self):
        """check_yahoo_finance async wrapper handles exceptions."""
        from api.routes import check_yahoo_finance

        with patch("api.routes._check_yahoo_sync", side_effect=Exception("Error")):
            result = await check_yahoo_finance()

        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_check_coingecko_async_wrapper(self):
        """check_coingecko async wrapper handles results."""
        from api.routes import check_coingecko

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("requests.get", return_value=mock_response):
            result = await check_coingecko()

        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_check_coingecko_async_exception(self):
        """check_coingecko async wrapper handles exceptions."""
        from api.routes import check_coingecko

        with patch("api.routes._check_coingecko_sync", side_effect=Exception("Error")):
            result = await check_coingecko()

        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_check_fear_greed_async_wrapper(self):
        """check_fear_greed async wrapper handles results."""
        from api.routes import check_fear_greed

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": [{"value": "50"}]}

        with patch("requests.get", return_value=mock_response):
            result = await check_fear_greed()

        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_check_fear_greed_async_exception(self):
        """check_fear_greed async wrapper handles exceptions."""
        from api.routes import check_fear_greed

        with patch("api.routes._check_fear_greed_sync", side_effect=Exception("Error")):
            result = await check_fear_greed()

        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_check_smtp_configured(self):
        """SMTP check works when configured."""
        from api.routes import check_smtp

        with patch.dict("os.environ", {"SMTP_USER": "user@test.com"}):
            mock_socket = MagicMock()
            with patch("socket.create_connection", return_value=mock_socket):
                result = await check_smtp()

        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_check_smtp_async_exception(self):
        """check_smtp async wrapper handles exceptions."""
        from api.routes import check_smtp

        with patch.dict("os.environ", {"SMTP_USER": "user@test.com"}):
            with patch("api.routes._check_smtp_sync", side_effect=Exception("Error")):
                result = await check_smtp()

        assert result["status"] == "error"


class TestHealthExternalExceptions:
    """Test health/external endpoint handling of exceptions."""

    def test_health_external_handles_exception_results(self, client):
        """External health handles Exception objects from gather."""
        with patch("api.routes.check_yahoo_finance", new_callable=AsyncMock) as mock_yf:
            with patch("api.routes.check_coingecko", new_callable=AsyncMock) as mock_cg:
                with patch(
                    "api.routes.check_fear_greed", new_callable=AsyncMock
                ) as mock_fg:
                    with patch(
                        "api.routes.check_smtp", new_callable=AsyncMock
                    ) as mock_smtp:
                        # Simulate an exception being returned from gather
                        mock_yf.side_effect = Exception("Yahoo failed")
                        mock_cg.return_value = {"status": "ok"}
                        mock_fg.return_value = {"status": "ok"}
                        mock_smtp.return_value = {"status": "ok"}

                        response = client.get("/api/portfolio/health/external")

        assert response.status_code == 200
        data = response.json()
        assert data["services"]["yahoo_finance"]["status"] == "error"


class TestRefreshMonitorEndpoint:
    """Tests for refresh single monitor endpoint."""

    def test_refresh_unknown_monitor(self, client):
        """Refresh with unknown monitor returns 404."""
        response = client.post("/api/portfolio/refresh/unknown")
        assert response.status_code == 404
        assert "unknown" in response.json()["detail"].lower()

    def test_refresh_etf_monitor(self, client):
        """Refresh ETF monitor returns 200 and starts background task."""
        from api.routes import _refresh_limiter

        _refresh_limiter._requests.clear()

        # Mock the orchestrator to avoid actual monitor execution
        with patch("api.routes.get_orchestrator") as mock_get_orch:
            mock_orch = MagicMock()
            mock_orch.run_monitor = AsyncMock()
            mock_get_orch.return_value = mock_orch

            response = client.post("/api/portfolio/refresh/etf")

        assert response.status_code == 200
        assert response.json()["monitor"] == "etf"
        assert response.json()["status"] == "refresh_started"

    def test_refresh_crypto_monitor(self, client):
        """Refresh crypto monitor returns 200."""
        from api.routes import _refresh_limiter

        _refresh_limiter._requests.clear()

        with patch("api.routes.get_orchestrator") as mock_get_orch:
            mock_orch = MagicMock()
            mock_orch.run_monitor = AsyncMock()
            mock_get_orch.return_value = mock_orch

            response = client.post("/api/portfolio/refresh/crypto")

        assert response.status_code == 200
        assert response.json()["monitor"] == "crypto"

    def test_refresh_savings_monitor(self, client):
        """Refresh savings monitor returns 200."""
        from api.routes import _refresh_limiter

        _refresh_limiter._requests.clear()

        with patch("api.routes.get_orchestrator") as mock_get_orch:
            mock_orch = MagicMock()
            mock_orch.run_monitor = AsyncMock()
            mock_get_orch.return_value = mock_orch

            response = client.post("/api/portfolio/refresh/savings")

        assert response.status_code == 200
        assert response.json()["monitor"] == "savings"

    def test_refresh_monitor_rate_limited(self, client):
        """Single monitor refresh is rate limited."""
        from api.routes import _refresh_limiter

        _refresh_limiter._requests.clear()

        with patch("api.routes.get_orchestrator") as mock_get_orch:
            mock_orch = MagicMock()
            mock_orch.run_monitor = AsyncMock()
            mock_get_orch.return_value = mock_orch

            # Exhaust rate limit
            for _ in range(5):
                resp = client.post("/api/portfolio/refresh/etf")
                assert resp.status_code == 200

            response = client.post("/api/portfolio/refresh/crypto")

        assert response.status_code == 429


class TestNotificationTestEndpoint:
    """Tests for notification test endpoint."""

    def test_notification_test_disabled(self, client):
        """Test notification returns 503 when email disabled."""
        from api.routes import _config_limiter

        _config_limiter._requests.clear()

        with patch("email_notifier.EmailNotifier") as mock_notifier_class:
            mock_notifier = MagicMock()
            mock_notifier.enabled = False
            mock_notifier_class.return_value = mock_notifier

            response = client.post("/api/portfolio/notifications/test")

        assert response.status_code == 503

    def test_notification_test_success(self, client):
        """Test notification returns success when email works."""
        from api.routes import _config_limiter

        _config_limiter._requests.clear()

        with patch("email_notifier.EmailNotifier") as mock_notifier_class:
            mock_notifier = MagicMock()
            mock_notifier.enabled = True
            mock_notifier.send_test.return_value = MagicMock(
                success=True, message="Email sent"
            )
            mock_notifier_class.return_value = mock_notifier

            response = client.post("/api/portfolio/notifications/test")

        assert response.status_code == 200
        assert response.json()["status"] == "sent"

    def test_notification_test_failure(self, client):
        """Test notification returns 500 when email fails."""
        from api.routes import _config_limiter

        _config_limiter._requests.clear()

        with patch("email_notifier.EmailNotifier") as mock_notifier_class:
            mock_notifier = MagicMock()
            mock_notifier.enabled = True
            mock_notifier.send_test.return_value = MagicMock(
                success=False, message="SMTP error"
            )
            mock_notifier_class.return_value = mock_notifier

            response = client.post("/api/portfolio/notifications/test")

        assert response.status_code == 500

    def test_notification_test_rate_limited(self, client):
        """Test notification is rate limited."""
        from api.routes import _config_limiter

        _config_limiter._requests.clear()

        # Exhaust rate limit (uses config limiter, 2 req/min)
        for _ in range(2):
            client.post("/api/portfolio/reload-config")

        response = client.post("/api/portfolio/notifications/test")
        assert response.status_code == 429


class TestSerializeAlert:
    """Tests for _serialize_alert function."""

    def test_serialize_alert_calls_alerts_module(self):
        """_serialize_alert delegates to alerts.serialize_alert."""
        from api.routes import _serialize_alert

        # Create a minimal mock alert to test
        mock_alert = MagicMock()
        mock_alert.id = "test-id"
        mock_alert.title = "Test Alert"

        with patch("alerts.serialize_alert") as mock_serialize:
            mock_serialize.return_value = {"id": "test", "title": "Test Alert"}
            result = _serialize_alert(mock_alert)

        mock_serialize.assert_called_once_with(mock_alert)
        assert result["id"] == "test"


class TestCompleteAlertEndpoint:
    """Additional tests for complete alert endpoint."""

    def test_complete_alert_success(self, client):
        """Complete alert succeeds when alert exists and date arrived."""
        with patch("alerts.mark_alert_completed", return_value=True):
            with patch("api.routes.get_orchestrator") as mock_get_orch:
                mock_orch = MagicMock()
                mock_get_orch.return_value = mock_orch

                response = client.post("/api/portfolio/alerts/valid-alert-id/complete")

        assert response.status_code == 200
        assert response.json()["status"] == "completed"
        mock_orch._load_upcoming_alerts.assert_called_once()


class TestRateLimiterWindowExpiry:
    """Tests for rate limiter window expiration."""

    def test_rate_limiter_window_expires(self):
        """Rate limiter allows requests after window expires."""
        from api.routes import RateLimiter

        limiter = RateLimiter(max_requests=1, window_seconds=1)

        assert limiter.is_allowed("test-key") is True
        assert limiter.is_allowed("test-key") is False

        # Wait for window to expire
        time.sleep(1.1)

        assert limiter.is_allowed("test-key") is True
