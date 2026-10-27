"""Unit tests for api/alerts.py (unified alerts aggregator)."""

import gc
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from api import alert_reads_db
from api.alerts import (
    _alert_identifier,
    _alert_key,
    _extract_alerts,
    _fetch_memory,
    _fetch_remote,
    _sort_key,
    get_unified_alerts,
    router,
)
from fastapi import HTTPException
from httpx import Response

# ServiceProxy uses httpx under the hood; patch the shared client.
HTTPX_PATCH = "libs.service_proxy.proxy.httpx.AsyncClient"


@pytest.fixture
def temp_alert_db(monkeypatch):
    """Point ``alert_reads_db`` at a fresh per-test SQLite database.

    Mirrors the fixture in ``test_alert_reads.py`` so unified-alert tests can
    exercise the real read-tracking store rather than mocking it.
    """
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = Path(tmp) / "test_alert_reads.db"
        monkeypatch.setattr(alert_reads_db, "AUTH_DB_PATH", str(db_path))
        try:
            yield db_path
        finally:
            gc.collect()


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
        with patch(
            "api.monitoring.get_memory_alerts", new=AsyncMock(return_value=fake)
        ):
            result = await _fetch_memory(days=7)
            assert len(result) == 1
            assert result[0]["source"] == "memory"

    @pytest.mark.asyncio
    async def test_returns_empty_on_error(self):
        with patch(
            "api.monitoring.get_memory_alerts",
            new=AsyncMock(side_effect=AttributeError("disk fail")),
        ):
            result = await _fetch_memory(days=7)
            assert result == []


# ---------------------------------------------------------------------------
# get_unified_alerts endpoint
# ---------------------------------------------------------------------------
class TestUnifiedAlerts:
    @pytest.mark.asyncio
    async def test_aggregates_and_sorts(self, temp_alert_db):
        request = make_mock_request()

        memory_alerts = [{"source": "memory", "severity": "info", "id": "m1"}]
        ac_alerts = [{"source": "ac", "severity": "critical", "id": "a1"}]
        portfolio_alerts = [{"source": "portfolio", "severity": "warning", "id": "p1"}]

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
        assert result["unread_count"] == 3
        assert "timestamp" in result
        # critical first, then warning, then info
        severities = [a["severity"] for a in result["alerts"]]
        assert severities == ["critical", "warning", "info"]
        # every alert is tagged with a key and read flag
        assert all("key" in a and a["read"] is False for a in result["alerts"])
        assert result["alerts"][0]["key"] == "ac:a1"

    @pytest.mark.asyncio
    async def test_one_failing_source_does_not_break_others(self, temp_alert_db):
        request = make_mock_request()

        async def fake_memory(days):
            return []

        async def fake_remote(name, proxy, path):
            # 'casita' fails -> empty, 'ac' succeeds
            if name == "ac":
                return [{"source": "ac", "severity": "warning", "id": "a1"}]
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
    async def test_empty_when_all_sources_empty(self, temp_alert_db):
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
        assert result["unread_count"] == 0
        assert result["alerts"] == []

    @pytest.mark.asyncio
    async def test_read_alerts_are_flagged(self, temp_alert_db):
        """Alerts the user already marked read come back with read=True."""
        request = make_mock_request()

        async def fake_memory(days):
            return []

        async def fake_remote(name, proxy, path):
            if name == "ac":
                return [
                    {"source": "ac", "severity": "info", "id": "a1"},
                    {"source": "ac", "severity": "info", "id": "a2"},
                ]
            return []

        # Mark one of the two alerts as read for the calling user.
        alert_reads_db.mark_alert_read("tester", "ac:a1")

        with (
            patch("api.alerts.require_authenticated", return_value="tester"),
            patch("api.alerts._fetch_memory", new=fake_memory),
            patch("api.alerts._fetch_remote", new=fake_remote),
        ):
            result = await get_unified_alerts(request, days=1)

        assert result["count"] == 2
        assert result["unread_count"] == 1
        by_key = {a["key"]: a["read"] for a in result["alerts"]}
        assert by_key == {"ac:a1": True, "ac:a2": False}

    @pytest.mark.asyncio
    async def test_read_state_is_scoped_per_user(self, temp_alert_db):
        """One user's read mark must not affect another user's view."""
        request = make_mock_request()

        async def fake_memory(days):
            return []

        async def fake_remote(name, proxy, path):
            if name == "ac":
                return [{"source": "ac", "severity": "info", "id": "a1"}]
            return []

        alert_reads_db.mark_alert_read("alice", "ac:a1")

        with (
            patch("api.alerts.require_authenticated", return_value="bob"),
            patch("api.alerts._fetch_memory", new=fake_memory),
            patch("api.alerts._fetch_remote", new=fake_remote),
        ):
            result = await get_unified_alerts(request, days=1)

        assert result["unread_count"] == 1
        assert result["alerts"][0]["read"] is False

    @pytest.mark.asyncio
    async def test_unread_only_filters_read_alerts(self, temp_alert_db):
        """unread_only=true drops read alerts but keeps the full unread_count."""
        request = make_mock_request()

        async def fake_memory(days):
            return []

        async def fake_remote(name, proxy, path):
            if name == "ac":
                return [
                    {"source": "ac", "severity": "info", "id": "a1"},
                    {"source": "ac", "severity": "info", "id": "a2"},
                    {"source": "ac", "severity": "info", "id": "a3"},
                ]
            return []

        alert_reads_db.mark_alert_read("tester", "ac:a1")

        with (
            patch("api.alerts.require_authenticated", return_value="tester"),
            patch("api.alerts._fetch_memory", new=fake_memory),
            patch("api.alerts._fetch_remote", new=fake_remote),
        ):
            result = await get_unified_alerts(request, days=1, unread_only=True)

        # Only the two unread alerts are returned...
        assert result["count"] == 2
        returned_keys = {a["key"] for a in result["alerts"]}
        assert returned_keys == {"ac:a2", "ac:a3"}
        assert all(a["read"] is False for a in result["alerts"])
        # ...but unread_count reflects the full aggregate (still 2 here).
        assert result["unread_count"] == 2

    @pytest.mark.asyncio
    async def test_requires_authentication(self, temp_alert_db):
        request = make_mock_request()

        with patch(
            "api.alerts.require_authenticated",
            side_effect=HTTPException(status_code=401, detail="Not authenticated"),
        ):
            with pytest.raises(HTTPException) as exc:
                await get_unified_alerts(request, days=1)
            assert exc.value.status_code == 401


# ---------------------------------------------------------------------------
# _alert_identifier / _alert_key
# ---------------------------------------------------------------------------
class TestAlertKey:
    def test_prefers_id_field(self):
        assert _alert_identifier({"id": "182159128"}) == "182159128"

    def test_prefers_alert_id_when_no_id(self):
        assert _alert_identifier({"alert_id": 42}) == "42"

    def test_prefers_container_for_memory_alerts(self):
        assert _alert_identifier({"container": "casita-suenos"}) == "casita-suenos"

    def test_hashes_title_url_when_no_id(self):
        ident = _alert_identifier({"title": "New flat", "url": "http://x/1"})
        # Deterministic, short hex digest.
        assert len(ident) == 12
        assert ident == _alert_identifier({"title": "New flat", "url": "http://x/1"})

    def test_different_titles_hash_differently(self):
        a = _alert_identifier({"title": "flat A"})
        b = _alert_identifier({"title": "flat B"})
        assert a != b

    def test_hashes_full_payload_as_last_resort(self):
        ident = _alert_identifier({"severity": "info"})
        assert len(ident) == 12

    def test_key_combines_source_and_identifier(self):
        assert _alert_key({"source": "casita", "id": "fotocasa_182159128"}) == (
            "casita:fotocasa_182159128"
        )

    def test_key_defaults_source_to_unknown(self):
        assert _alert_key({"id": "x"}).startswith("unknown:")


# ---------------------------------------------------------------------------
# Router wiring
# ---------------------------------------------------------------------------
def test_router_has_unified_route():
    paths = {route.path for route in router.routes}
    assert "/api/alerts/unified" in paths
