"""Unit tests for api/proxy/external.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import Response

from api.proxy.external import router, proxy_flood, proxy_firms


class TestProxyFlood:
    """Tests for /api/proxy/flood endpoint."""

    @pytest.mark.asyncio
    async def test_returns_sin_datos_when_no_data(self):
        """Returns sin_datos when both sources fail."""
        with patch("api.proxy.external.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.side_effect = Exception("Network error")
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await proxy_flood(lat=40.0, lon=-3.0)

            assert result["risk_level"] == "sin_datos"
            assert result["risk_source"] == "sin_datos"
            assert result["snczi"] is None
            assert result["glofas"] is None

    @pytest.mark.asyncio
    async def test_returns_snczi_data_when_available(self):
        """Returns SNCZI data when WMS responds with valid values."""
        wms_response = MagicMock(spec=Response)
        wms_response.text = "GRAY_INDEX = 1.5"

        glofas_response = MagicMock(spec=Response)
        glofas_response.json.return_value = {"daily": None}

        call_count = [0]

        async def mock_get(url):
            call_count[0] += 1
            if "flood-api.open-meteo.com" in url:
                return glofas_response
            return wms_response

        with patch("api.proxy.external.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get = mock_get
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await proxy_flood(lat=40.0, lon=-3.0)

            assert result["risk_source"] == "snczi"
            assert result["snczi"] is not None
            assert result["snczi"]["t10"] == 1.5

    @pytest.mark.asyncio
    async def test_returns_glofas_data_when_snczi_unavailable(self):
        """Returns GloFAS data when SNCZI returns fill values."""
        wms_response = MagicMock(spec=Response)
        wms_response.text = "GRAY_INDEX = -9999.0"

        glofas_response = MagicMock(spec=Response)
        glofas_response.json.return_value = {
            "daily": {"river_discharge": [100.0] * 100},
            "latitude": 40.0,
            "longitude": -3.0,
        }

        async def mock_get(url):
            if "flood-api.open-meteo.com" in url:
                return glofas_response
            return wms_response

        with patch("api.proxy.external.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get = mock_get
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await proxy_flood(lat=40.0, lon=-3.0)

            assert result["risk_source"] == "glofas"
            assert result["glofas"] is not None
            assert result["glofas"]["mean_m3s"] == 100.0

    @pytest.mark.asyncio
    async def test_risk_level_muy_alto_from_snczi_t10(self):
        """Risk level muy_alto when t10 has valid calado."""
        wms_response = MagicMock(spec=Response)
        wms_response.text = "GRAY_INDEX = 2.0"

        async def mock_get(url):
            if "flood-api.open-meteo.com" in url:
                resp = MagicMock(spec=Response)
                resp.json.return_value = {"daily": None}
                return resp
            return wms_response

        with patch("api.proxy.external.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get = mock_get
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await proxy_flood(lat=40.0, lon=-3.0)

            assert result["risk_level"] == "muy_alto"
            assert result["calado_m"] == 2.0

    @pytest.mark.asyncio
    async def test_risk_level_alto_from_glofas(self):
        """Risk level alto from GloFAS when max > 500."""
        wms_response = MagicMock(spec=Response)
        wms_response.text = "GRAY_INDEX = -9999.0"

        glofas_response = MagicMock(spec=Response)
        glofas_response.json.return_value = {
            "daily": {"river_discharge": [600.0] + [50.0] * 99},
            "latitude": 40.0,
            "longitude": -3.0,
        }

        async def mock_get(url):
            if "flood-api.open-meteo.com" in url:
                return glofas_response
            return wms_response

        with patch("api.proxy.external.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get = mock_get
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await proxy_flood(lat=40.0, lon=-3.0)

            assert result["risk_level"] == "alto"

    @pytest.mark.asyncio
    async def test_risk_level_bajo_from_glofas(self):
        """Risk level bajo from GloFAS when values are low."""
        wms_response = MagicMock(spec=Response)
        wms_response.text = "GRAY_INDEX = -9999.0"

        glofas_response = MagicMock(spec=Response)
        glofas_response.json.return_value = {
            "daily": {"river_discharge": [5.0] * 100},
            "latitude": 40.0,
            "longitude": -3.0,
        }

        async def mock_get(url):
            if "flood-api.open-meteo.com" in url:
                return glofas_response
            return wms_response

        with patch("api.proxy.external.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get = mock_get
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await proxy_flood(lat=40.0, lon=-3.0)

            assert result["risk_level"] == "bajo"

    @pytest.mark.asyncio
    async def test_fill_value_detection(self):
        """Fill values (-9999, -3, ~3.4) are treated as no data."""
        for fill_val in ["-9999.0", "-3.0", "3.4"]:
            wms_response = MagicMock(spec=Response)
            wms_response.text = f"GRAY_INDEX = {fill_val}"

            glofas_response = MagicMock(spec=Response)
            glofas_response.json.return_value = {"daily": None}

            async def mock_get(url):
                if "flood-api.open-meteo.com" in url:
                    return glofas_response
                return wms_response

            with patch("api.proxy.external.httpx.AsyncClient") as mock_client:
                mock_instance = AsyncMock()
                mock_instance.get = mock_get
                mock_client.return_value.__aenter__.return_value = mock_instance

                result = await proxy_flood(lat=40.0, lon=-3.0)

                assert result["snczi"] is None or all(
                    v is None for v in [result["snczi"].get("t10"), 
                                        result["snczi"].get("t100"),
                                        result["snczi"].get("t500")]
                )


class TestProxyFirms:
    """Tests for /api/proxy/firms endpoint."""

    @pytest.mark.asyncio
    async def test_returns_no_key_when_api_key_missing(self):
        """Returns no_key status when FIRMS_MAP_KEY is empty."""
        import api.proxy.external as module
        original_key = module.FIRMS_MAP_KEY
        module.FIRMS_MAP_KEY = ""

        try:
            result = await proxy_firms(lat=40.0, lon=-3.0)
            assert result["status"] == "no_key"
            assert result["focos"] is None
        finally:
            module.FIRMS_MAP_KEY = original_key

    @pytest.mark.asyncio
    async def test_returns_ok_with_focos_count(self):
        """Returns fire count when API responds."""
        import api.proxy.external as module
        original_key = module.FIRMS_MAP_KEY
        module.FIRMS_MAP_KEY = "test_key"

        try:
            csv_response = MagicMock(spec=Response)
            csv_response.status_code = 200
            csv_response.text = "confidence,brightness\nh,300\nl,280\nn,290"

            with patch("api.proxy.external.httpx.AsyncClient") as mock_client:
                mock_instance = AsyncMock()
                mock_instance.get.return_value = csv_response
                mock_client.return_value.__aenter__.return_value = mock_instance

                result = await proxy_firms(lat=40.0, lon=-3.0)

                assert result["status"] == "ok"
                assert isinstance(result["focos"], int)
                assert result["radio_km"] == 30
        finally:
            module.FIRMS_MAP_KEY = original_key

    @pytest.mark.asyncio
    async def test_filters_low_confidence_fires(self):
        """Filters out low confidence ('l') fire detections."""
        import api.proxy.external as module
        original_key = module.FIRMS_MAP_KEY
        module.FIRMS_MAP_KEY = "test_key"

        try:
            csv_response = MagicMock(spec=Response)
            csv_response.status_code = 200
            csv_response.text = "confidence,brightness\nl,300\nl,280"  # All low confidence

            with patch("api.proxy.external.httpx.AsyncClient") as mock_client:
                mock_instance = AsyncMock()
                mock_instance.get.return_value = csv_response
                mock_client.return_value.__aenter__.return_value = mock_instance

                result = await proxy_firms(lat=40.0, lon=-3.0)

                assert result["status"] == "ok"
                assert result["focos"] == 0  # All filtered out
        finally:
            module.FIRMS_MAP_KEY = original_key

    @pytest.mark.asyncio
    async def test_handles_api_error(self):
        """Returns zero count when API returns non-200."""
        import api.proxy.external as module
        original_key = module.FIRMS_MAP_KEY
        module.FIRMS_MAP_KEY = "test_key"

        try:
            error_response = MagicMock(spec=Response)
            error_response.status_code = 500

            with patch("api.proxy.external.httpx.AsyncClient") as mock_client:
                mock_instance = AsyncMock()
                mock_instance.get.return_value = error_response
                mock_client.return_value.__aenter__.return_value = mock_instance

                result = await proxy_firms(lat=40.0, lon=-3.0)

                assert result["status"] == "ok"
                assert result["focos"] == 0
        finally:
            module.FIRMS_MAP_KEY = original_key

    @pytest.mark.asyncio
    async def test_handles_network_exception(self):
        """Returns zero count on network exceptions."""
        import api.proxy.external as module
        original_key = module.FIRMS_MAP_KEY
        module.FIRMS_MAP_KEY = "test_key"

        try:
            with patch("api.proxy.external.httpx.AsyncClient") as mock_client:
                mock_instance = AsyncMock()
                mock_instance.get.side_effect = Exception("Network error")
                mock_client.return_value.__aenter__.return_value = mock_instance

                result = await proxy_firms(lat=40.0, lon=-3.0)

                assert result["status"] == "ok"
                assert result["focos"] == 0
        finally:
            module.FIRMS_MAP_KEY = original_key


class TestRouterRegistration:
    """Tests for router configuration."""

    def test_router_has_correct_prefix(self):
        """Router has /api/proxy prefix."""
        assert router.prefix == "/api/proxy"

    def test_router_has_proxy_tag(self):
        """Router is tagged as Proxy."""
        assert "Proxy" in router.tags
