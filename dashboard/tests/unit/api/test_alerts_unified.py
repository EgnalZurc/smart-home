"""Unit tests for api/alerts.py (unified alerts aggregator)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from httpx import Response

from api.alerts import (
    _extract_alerts,
    _fetch_memory,
    _fetch_remote,
    _sort_key,
    get_unified_alerts,
    router,
)

# ServiceProxy uses httpx under the hood; patch the shared client.
HTTPX_PATCH = "libs.service_proxy.proxy.httpx.AsyncClient"


def make_mock_response(data, status_code=200):
    """Create a mock HTTP response for the httpx client."""
    resp = MagicMock(spec=Response)
    resp.status_code = status_code
    resp.json.return_value = data
    resp.text = str(data)
    return resp


def make_mock_request():
    """Create a minimal mock FastAPI request."""
    return MagicMock()


# ---------------------------------------------------------------------------
# _extract_alerts
# ---------------------------------------------------------------------------
class TestExtractAlerts:
    def test_extracts_from_alerts_key(self):
        data = {"alerts": [{"id": 1}, {"id": 2}]}
        result = _extract_alerts(data, "ac")
        assert len(result) == 2
        assert all(a["source"] == "ac" for a in result)

    def test_extracts_from_active_key(self):
        """metrics-service uses 'active' instead of 'alerts'."""
        data = {"ts": 123, "active": [{"id": 1}]}
        result = _extract_alerts(data, "metrics")
        assert len(result) == 1
        assert result[0]["source"] == "metrics"

    def test_alerts_key_takes_precedence_over_active(self):
        data = {"alerts": [{"id": "a"}], "active": [{"id": "b"}]}
        result = _extract_alerts(data, "x")
        assert len(result) == 1
        assert result[0]["id"] == "a"

    def test_preserves_existing_source(self):
        data = {"alerts": [{"id": 1, "source": "upstream"}]}
        result = _extract_alerts(data, "ac")
        assert result[0]["source"] == "upstream"

    def test_empty_on_missing_keys(self):
        assert _extract_alerts({"something": 1}, "x") == []

    def test_empty_on_non_dict_payload(self):
        assert _extract_alerts(None, "x") == []
        assert _extract_alerts([1, 2, 3], "x") == []

    def test_empty_on_non_list_alerts(self):
        assert _extract_alerts({"alerts": "oops"}, "x") == []

    def test_skips_non_dict_items(self):
        data = {"alerts": [{"id": 1}, "bad", 42, {"id": 2}]}
        result = _extract_alerts(data, "x")
        assert len(result) == 2


# ---------------------------------------------------------------------------
# _sort_key / ordering
# ---------------------------------------------------------------------------
class TestSortKey:
    def test_severity_ordering(self):
        assert _sort_key({"severity": "critical"})[0] == 0
        assert _sort_key({"severity": "warning"})[0] == 1
        assert _sort_key({"severity": "info"})[0] == 2

    def test_unknown_severity_defaults_to_info(self):
        assert _sort_key({"severity": "weird"})[0] == 2
        assert _sort_key({})[0] == 2

    def test_timestamp_is_string(self):
        assert _sort_key({"timestamp": None}) == (2, "")
        assert _sort_key({"severity": "info", "timestamp": "2024-01-01"}) == (
            2,
            "2024-01-01",
        )


# ---------------------------------------------------------------------------
# _fetch_remote
# ---------------------------------------------------------------------------
class TestFetchRemote:
    @pytest.mark.asyncio
    async def test_success(self):
        from api.proxy.base import ServiceProxy

        proxy = ServiceProxy("http://svc:1234")
        with patch(HTTPX_PATCH) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = make_mock_response({"alerts": [{"id": 1}]})
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await _fetch_remote("ac", proxy, "/api/ac/alerts")
            assert len(result) == 1
            assert result[0]["source"] == "ac"

    @pytest.mark.asyncio
    async def test_returns_empty_on_connection_error(self):
        from api.proxy.base import ServiceProxy

        proxy = ServiceProxy("http://svc:1234")
        with patch(HTTPX_PATCH) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.side_effect = Exception("Connection refused")
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await _fetch_remote("ac", proxy, "/api/ac/alerts")
            assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_on_http_error(self):
        """A 500 from the upstream yields the default_on_error ({"alerts": []})."""
        from api.proxy.base import ServiceProxy

        proxy = ServiceProxy("http://svc:1234")
        with patch(HTTPX_PATCH) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = make_mock_response(
                {"detail": "boom"}, status_code=500
            )
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await _fetch_remote("ac", proxy, "/api/ac/alerts")
            assert result == []


# ---------------------------------------------------------------------------
# _fetch_memory
# ---------------------------------------------------------------------------
class TestFetchMemory:
    @pytest.mark.asyncio
    async def test_success(self):
        fake = {"alerts": [{"container": "x", "percent": 90}]}
        with patch("api.monitoring.get_memory_alerts", new=AsyncMock(return_value=fake)):
            result = await _fetch_memory(days=7)
            assert len(result) == 1
            assert result[0]["source"] == "memory"

    @pytest.mark.asyncio
    async def test_returns_empty_on_error(self):
        with patch(
            "api.monitoring.get_memory_alerts",
            new=AsyncMock(side_effect=Exception("disk fail")),
        ):
            result = await _fetch_memory(days=7)
            assert result == []


# ---------------------------------------------------------------------------
# get_unified_alerts endpoint
# ---------------------------------------------------------------------------
class TestUnifiedAlerts:
    @pytest.mark.asyncio
    async def test_aggregates_and_sorts(self):
        request = make_mock_request()

        memory_alerts = [{"source": "memory", "severity": "info"}]
        ac_alerts = [{"source": "ac", "severity": "critical"}]
        portfolio_alerts = [{"source": "portfolio", "severity": "warning"}]

        async def fake_memory(days):
            return memory_alerts

        async def fake_remote(name, proxy, path):
            return {
                "ac": ac_alerts,
                "portfolio": portfolio_alerts,
            }.get(name, [])

        with (
            patch("api.alerts.require_authenticated", return_value="tester"),
            patch("api.alerts._fetch_memory", new=fake_memory),
            patch("api.alerts._fetch_remote", new=fake_remote),
        ):
            result = await get_unified_alerts(request, days=1)

        assert result["count"] == 3
        assert "timestamp" in result
        # critical first, then warning, then info
        severities = [a["severity"] for a in result["alerts"]]
        assert severities == ["critical", "warning", "info"]

    @pytest.mark.asyncio
    async def test_one_failing_source_does_not_break_others(self):
        request = make_mock_request()

        async def fake_memory(days):
            return []

        async def fake_remote(name, proxy, path):
            # 'casita' fails -> empty, 'ac' succeeds
            if name == "ac":
                return [{"source": "ac", "severity": "warning"}]
            return []

        with (
            patch("api.alerts.require_authenticated", return_value="tester"),
            patch("api.alerts._fetch_memory", new=fake_memory),
            patch("api.alerts._fetch_remote", new=fake_remote),
        ):
            result = await get_unified_alerts(request, days=1)

        assert result["count"] == 1
        assert result["alerts"][0]["source"] == "ac"

    @pytest.mark.asyncio
    async def test_empty_when_all_sources_empty(self):
        request = make_mock_request()

        async def fake_memory(days):
            return []

        async def fake_remote(name, proxy, path):
            return []

        with (
            patch("api.alerts.require_authenticated", return_value="tester"),
            patch("api.alerts._fetch_memory", new=fake_memory),
            patch("api.alerts._fetch_remote", new=fake_remote),
        ):
            result = await get_unified_alerts(request, days=1)

        assert result["count"] == 0
        assert result["alerts"] == []

    @pytest.mark.asyncio
    async def test_requires_authentication(self):
        request = make_mock_request()

        with patch(
            "api.alerts.require_authenticated",
            side_effect=HTTPException(status_code=401, detail="Not authenticated"),
        ):
            with pytest.raises(HTTPException) as exc:
                await get_unified_alerts(request, days=1)
            assert exc.value.status_code == 401


# ---------------------------------------------------------------------------
# Router wiring
# ---------------------------------------------------------------------------
def test_router_has_unified_route():
    paths = {route.path for route in router.routes}
    assert "/api/alerts/unified" in paths
