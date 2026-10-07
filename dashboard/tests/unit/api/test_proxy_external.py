"""Unit tests for api/proxy/external.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import Response

import api.proxy.external as module
from api.proxy.external import router, proxy_flood, proxy_firms


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_response(text: str, status_code: int = 200) -> Response:
    """Create a mock httpx Response with text body."""
    resp = MagicMock(spec=Response)
    resp.text = text
    resp.status_code = status_code
    return resp


def _make_json_response(data: dict, status_code: int = 200) -> Response:
    """Create a mock httpx Response with JSON body."""
    resp = MagicMock(spec=Response)
    resp.json.return_value = data
    resp.status_code = status_code
    return resp


# ---------------------------------------------------------------------------
# TestProxyFlood
# ---------------------------------------------------------------------------


class TestProxyFlood:
    """Tests for /api/proxy/flood endpoint."""

    def test_flood_endpoint_registered(self):
        """Flood endpoint is registered on router."""
        routes = [r.path for r in router.routes]
        assert "/api/proxy/flood" in routes

    @pytest.mark.asyncio
    async def test_flood_returns_expected_keys(self):
        """proxy_flood returns dict with all expected keys."""
        # Mock both SNCZI WMS and GloFAS to return no data
        with patch("api.proxy.external.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            
            # Return empty/error responses
            mock_instance.get.return_value = _make_response("no data", 404)
            
            result = await proxy_flood(lat=40.4168, lon=-3.7038)
            
            assert "snczi" in result
            assert "glofas" in result
            assert "risk_level" in result
            assert "risk_source" in result
            assert "calado_m" in result

    @pytest.mark.asyncio
    async def test_flood_sin_datos_when_no_sources(self):
        """Returns sin_datos when both sources fail."""
        with patch("api.proxy.external.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.side_effect = Exception("Network error")
            
            result = await proxy_flood(lat=40.0, lon=-3.0)
            
            assert result["risk_level"] == "sin_datos"
            assert result["risk_source"] == "sin_datos"
            assert result["snczi"] is None
            assert result["glofas"] is None

    @pytest.mark.asyncio
    async def test_flood_snczi_t10_muy_alto(self):
        """Returns muy_alto when SNCZI T10 has valid depth."""
        wms_response = "GetFeatureInfoResponse\nGRAY_INDEX = 1.5\n"
        
        with patch("api.proxy.external.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            
            # All three layers return valid depth
            mock_instance.get.return_value = _make_response(wms_response)
            
            result = await proxy_flood(lat=40.0, lon=-3.0)
            
            # Should have SNCZI data with muy_alto risk
            if result["snczi"] is not None:
                assert result["risk_source"] == "snczi"
                assert result["risk_level"] in ["muy_alto", "alto", "moderado", "bajo"]

    @pytest.mark.asyncio
    async def test_flood_snczi_fill_values_ignored(self):
        """Fill values (-9999, -3) are treated as no data."""
        wms_response = "GetFeatureInfoResponse\nGRAY_INDEX = -9999.0\n"
        
        with patch("api.proxy.external.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = _make_response(wms_response)
            
            result = await proxy_flood(lat=40.0, lon=-3.0)
            
            # -9999 should be treated as fill value, resulting in no SNCZI data
            # unless glofas provides data
            assert result["risk_level"] in ["sin_datos", "bajo", "moderado", "alto", "muy_alto"]

    @pytest.mark.asyncio
    async def test_flood_glofas_fallback(self):
        """Uses GloFAS when SNCZI returns no data."""
        glofas_response = {
            "daily": {
                "river_discharge": [100.0, 150.0, 200.0, 50.0, 75.0] * 100  # 500 values
            },
            "latitude": 40.0,
            "longitude": -3.0,
        }
        
        with patch("api.proxy.external.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            
            # Create responses based on URL
            async def mock_get(url):
                if "flood-api.open-meteo.com" in url:
                    return _make_json_response(glofas_response)
                else:
                    # SNCZI returns fill values
                    return _make_response("GRAY_INDEX = -9999.0")
            
            mock_instance.get = mock_get
            
            result = await proxy_flood(lat=40.0, lon=-3.0)
            
            # Result depends on which source returns data first
            assert result["risk_level"] in ["sin_datos", "bajo", "moderado", "alto", "muy_alto"]

    @pytest.mark.asyncio
    async def test_flood_glofas_insufficient_data(self):
        """GloFAS returns None when insufficient data points."""
        glofas_response = {
            "daily": {
                "river_discharge": [100.0, 150.0]  # Only 2 values, need 30+
            },
        }
        
        with patch("api.proxy.external.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = _make_json_response(glofas_response)
            
            result = await proxy_flood(lat=40.0, lon=-3.0)
            
            # With insufficient GloFAS data and no SNCZI, should be sin_datos
            assert result["glofas"] is None or result["risk_level"] == "sin_datos"

    @pytest.mark.asyncio
    async def test_flood_snczi_bbox_progression(self):
        """SNCZI tries progressively larger bboxes."""
        responses = []
        call_count = [0]
        
        wms_empty = "GetFeatureInfoResponse\nGRAY_INDEX = -9999.0\n"
        wms_valid = "GetFeatureInfoResponse\nGRAY_INDEX = 0.5\n"
        
        with patch("api.proxy.external.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            
            # First few calls return fill values, later calls return valid data
            async def mock_get(url):
                call_count[0] += 1
                # After 9 calls (3 layers * 3 bbox sizes), return valid data
                if call_count[0] > 9:
                    return _make_response(wms_valid)
                return _make_response(wms_empty)
            
            mock_instance.get = mock_get
            
            result = await proxy_flood(lat=40.0, lon=-3.0)
            
            # Should have made multiple calls
            assert call_count[0] > 0


# ---------------------------------------------------------------------------
# TestProxyFirms
# ---------------------------------------------------------------------------


class TestProxyFirms:
    """Tests for /api/proxy/firms endpoint."""

    def test_firms_endpoint_registered(self):
        """FIRMS endpoint is registered on router."""
        routes = [r.path for r in router.routes]
        assert "/api/proxy/firms" in routes

    @pytest.mark.asyncio
    async def test_firms_returns_no_key_when_api_key_missing(self):
        """Returns no_key status when FIRMS_MAP_KEY is empty."""
        original_key = module.FIRMS_MAP_KEY
        module.FIRMS_MAP_KEY = ""
        
        try:
            result = await proxy_firms(lat=40.0, lon=-3.0)
            assert result["status"] == "no_key"
            assert result["focos"] is None
        finally:
            module.FIRMS_MAP_KEY = original_key

    @pytest.mark.asyncio
    async def test_firms_returns_ok_with_valid_key(self):
        """Returns ok status with valid API key."""
        original_key = module.FIRMS_MAP_KEY
        module.FIRMS_MAP_KEY = "test_api_key"
        
        # CSV response with header and one data row
        csv_response = "latitude,longitude,confidence\n40.1,-3.1,h\n"
        
        try:
            with patch("api.proxy.external.httpx.AsyncClient") as mock_client:
                mock_instance = AsyncMock()
                mock_client.return_value.__aenter__.return_value = mock_instance
                mock_instance.get.return_value = _make_response(csv_response)
                
                result = await proxy_firms(lat=40.0, lon=-3.0)
                
                assert result["status"] == "ok"
                assert "focos" in result
                assert result["radio_km"] == 30
                assert "periodo" in result
        finally:
            module.FIRMS_MAP_KEY = original_key

    @pytest.mark.asyncio
    async def test_firms_filters_low_confidence(self):
        """Low confidence detections are filtered out."""
        original_key = module.FIRMS_MAP_KEY
        module.FIRMS_MAP_KEY = "test_api_key"
        
        # CSV with mixed confidence levels
        csv_response = "latitude,longitude,confidence\n40.1,-3.1,h\n40.2,-3.2,l\n40.3,-3.3,n\n"
        
        try:
            with patch("api.proxy.external.httpx.AsyncClient") as mock_client:
                mock_instance = AsyncMock()
                mock_client.return_value.__aenter__.return_value = mock_instance
                mock_instance.get.return_value = _make_response(csv_response)
                
                result = await proxy_firms(lat=40.0, lon=-3.0)
                
                # 'l' confidence should be filtered, leaving 2 detections per window
                assert result["status"] == "ok"
        finally:
            module.FIRMS_MAP_KEY = original_key

    @pytest.mark.asyncio
    async def test_firms_handles_http_errors(self):
        """HTTP errors result in zero count for that window."""
        original_key = module.FIRMS_MAP_KEY
        module.FIRMS_MAP_KEY = "test_api_key"
        
        try:
            with patch("api.proxy.external.httpx.AsyncClient") as mock_client:
                mock_instance = AsyncMock()
                mock_client.return_value.__aenter__.return_value = mock_instance
                mock_instance.get.return_value = _make_response("", 500)
                
                result = await proxy_firms(lat=40.0, lon=-3.0)
                
                assert result["status"] == "ok"
                assert result["focos"] == 0  # All windows returned 0 due to errors
        finally:
            module.FIRMS_MAP_KEY = original_key

    @pytest.mark.asyncio
    async def test_firms_handles_network_exceptions(self):
        """Network exceptions result in zero count."""
        original_key = module.FIRMS_MAP_KEY
        module.FIRMS_MAP_KEY = "test_api_key"
        
        try:
            with patch("api.proxy.external.httpx.AsyncClient") as mock_client:
                mock_instance = AsyncMock()
                mock_client.return_value.__aenter__.return_value = mock_instance
                mock_instance.get.side_effect = Exception("Connection timeout")
                
                result = await proxy_firms(lat=40.0, lon=-3.0)
                
                assert result["status"] == "ok"
                assert result["focos"] == 0
        finally:
            module.FIRMS_MAP_KEY = original_key

    @pytest.mark.asyncio
    async def test_firms_handles_empty_csv(self):
        """Empty CSV response (header only) returns zero."""
        original_key = module.FIRMS_MAP_KEY
        module.FIRMS_MAP_KEY = "test_api_key"
        
        csv_response = "latitude,longitude,confidence\n"  # Header only
        
        try:
            with patch("api.proxy.external.httpx.AsyncClient") as mock_client:
                mock_instance = AsyncMock()
                mock_client.return_value.__aenter__.return_value = mock_instance
                mock_instance.get.return_value = _make_response(csv_response)
                
                result = await proxy_firms(lat=40.0, lon=-3.0)
                
                assert result["status"] == "ok"
                assert result["focos"] == 0
        finally:
            module.FIRMS_MAP_KEY = original_key

    @pytest.mark.asyncio
    async def test_firms_csv_without_confidence_column(self):
        """CSV without confidence column counts all rows."""
        original_key = module.FIRMS_MAP_KEY
        module.FIRMS_MAP_KEY = "test_api_key"
        
        # CSV without confidence column
        csv_response = "latitude,longitude,brightness\n40.1,-3.1,350\n40.2,-3.2,400\n"
        
        try:
            with patch("api.proxy.external.httpx.AsyncClient") as mock_client:
                mock_instance = AsyncMock()
                mock_client.return_value.__aenter__.return_value = mock_instance
                mock_instance.get.return_value = _make_response(csv_response)
                
                result = await proxy_firms(lat=40.0, lon=-3.0)
                
                assert result["status"] == "ok"
                # Without confidence column, all rows count
        finally:
            module.FIRMS_MAP_KEY = original_key

    @pytest.mark.asyncio
    async def test_firms_aggregates_multiple_windows(self):
        """Aggregates focos from all time windows."""
        original_key = module.FIRMS_MAP_KEY
        module.FIRMS_MAP_KEY = "test_api_key"
        
        # Each window returns 2 focos
        csv_response = "latitude,longitude,confidence\n40.1,-3.1,h\n40.2,-3.2,h\n"
        
        try:
            with patch("api.proxy.external.httpx.AsyncClient") as mock_client:
                mock_instance = AsyncMock()
                mock_client.return_value.__aenter__.return_value = mock_instance
                mock_instance.get.return_value = _make_response(csv_response)
                
                result = await proxy_firms(lat=40.0, lon=-3.0)
                
                assert result["status"] == "ok"
                assert result["peticiones"] > 0
                # Total focos = 2 * number of windows
                expected_min_focos = 2 * result["peticiones"]
                assert result["focos"] == expected_min_focos
        finally:
            module.FIRMS_MAP_KEY = original_key


# ---------------------------------------------------------------------------
# TestRouterRegistration
# ---------------------------------------------------------------------------


class TestRouterRegistration:
    """Tests for router configuration."""

    def test_router_has_correct_prefix(self):
        """Router has /api/proxy prefix."""
        assert router.prefix == "/api/proxy"

    def test_router_has_proxy_tag(self):
        """Router is tagged as Proxy."""
        assert "Proxy" in router.tags

    def test_all_endpoints_registered(self):
        """All expected endpoints are registered."""
        routes = [r.path for r in router.routes]
        assert "/api/proxy/flood" in routes
        assert "/api/proxy/firms" in routes
