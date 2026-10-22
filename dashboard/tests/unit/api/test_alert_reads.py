"""Unit tests for per-user alert read tracking.

Covers the persistence layer (``api.alert_reads_db``) and the two endpoints
added to ``api.alerts`` (``POST /api/alerts/mark-read`` and
``GET /api/alerts/read-status``).
"""

import gc
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from api import alert_reads_db
from api.alerts import MarkReadRequest, get_read_status, mark_alert_read, router


@pytest.fixture
def temp_alert_db(monkeypatch):
    """Point ``alert_reads_db`` at a fresh per-test SQLite database.

    Mirrors the ``temp_auth_db`` fixture in the root conftest: WAL side-files
    are released by the shared sqlite helpers, and the temp dir is torn down
    tolerantly as a backstop.
    """
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = Path(tmp) / "test_alert_reads.db"
        monkeypatch.setattr(alert_reads_db, "AUTH_DB_PATH", str(db_path))
        try:
            yield db_path
        finally:
            gc.collect()


def make_mock_request():
    """Create a minimal mock FastAPI request."""
    return MagicMock()


# ---------------------------------------------------------------------------
# Persistence layer: mark_alert_read / get_read_alerts / is_alert_read
# ---------------------------------------------------------------------------
class TestAlertReadsDb:
    def test_mark_then_is_read(self, temp_alert_db):
        assert alert_reads_db.is_alert_read("alice", "mem:web") is False
        alert_reads_db.mark_alert_read("alice", "mem:web")
        assert alert_reads_db.is_alert_read("alice", "mem:web") is True

    def test_get_read_alerts_returns_marked_keys(self, temp_alert_db):
        alert_reads_db.mark_alert_read("alice", "a")
        alert_reads_db.mark_alert_read("alice", "b")
        read = alert_reads_db.get_read_alerts("alice")
        assert set(read) == {"a", "b"}

    def test_read_state_is_scoped_per_user(self, temp_alert_db):
        alert_reads_db.mark_alert_read("alice", "shared")
        assert alert_reads_db.is_alert_read("alice", "shared") is True
        # Bob never marked it — must stay unread for him.
        assert alert_reads_db.is_alert_read("bob", "shared") is False
        assert alert_reads_db.get_read_alerts("bob") == []

    def test_marking_twice_is_idempotent(self, temp_alert_db):
        alert_reads_db.mark_alert_read("alice", "dup")
        alert_reads_db.mark_alert_read("alice", "dup")
        read = alert_reads_db.get_read_alerts("alice")
        assert read.count("dup") == 1

    def test_marking_twice_refreshes_timestamp(self, temp_alert_db):
        import api.alert_reads_db as mod

        with patch.object(mod, "datetime") as mock_dt:
            mock_dt.now.return_value.isoformat.return_value = (
                "2020-01-01T00:00:00+00:00"
            )
            alert_reads_db.mark_alert_read("alice", "ts")
        with patch.object(mod, "datetime") as mock_dt:
            mock_dt.now.return_value.isoformat.return_value = (
                "2021-06-06T00:00:00+00:00"
            )
            alert_reads_db.mark_alert_read("alice", "ts")

        with alert_reads_db._db() as conn:
            row = conn.execute(
                "SELECT read_at FROM alert_reads WHERE user_id = ? AND alert_key = ?",
                ("alice", "ts"),
            ).fetchone()
        assert row["read_at"] == "2021-06-06T00:00:00+00:00"

    def test_get_read_alerts_empty_for_unknown_user(self, temp_alert_db):
        assert alert_reads_db.get_read_alerts("nobody") == []

    def test_get_read_alerts_most_recent_first(self, temp_alert_db):
        import api.alert_reads_db as mod

        with patch.object(mod, "datetime") as mock_dt:
            mock_dt.now.return_value.isoformat.return_value = (
                "2020-01-01T00:00:00+00:00"
            )
            alert_reads_db.mark_alert_read("alice", "old")
        with patch.object(mod, "datetime") as mock_dt:
            mock_dt.now.return_value.isoformat.return_value = (
                "2022-01-01T00:00:00+00:00"
            )
            alert_reads_db.mark_alert_read("alice", "new")

        assert alert_reads_db.get_read_alerts("alice") == ["new", "old"]


# ---------------------------------------------------------------------------
# POST /api/alerts/mark-read
# ---------------------------------------------------------------------------
class TestMarkReadEndpoint:
    @pytest.mark.asyncio
    async def test_marks_alert_for_current_user(self, temp_alert_db):
        request = make_mock_request()
        body = MarkReadRequest(alert_key="mem:web")

        with patch("api.alerts.require_authenticated", return_value="alice"):
            result = await mark_alert_read(request, body)

        assert result == {"status": "ok", "alert_key": "mem:web"}
        assert alert_reads_db.is_alert_read("alice", "mem:web") is True

    @pytest.mark.asyncio
    async def test_requires_authentication(self, temp_alert_db):
        from fastapi import HTTPException

        request = make_mock_request()
        body = MarkReadRequest(alert_key="mem:web")

        with patch(
            "api.alerts.require_authenticated",
            side_effect=HTTPException(status_code=401, detail="Not authenticated"),
        ):
            with pytest.raises(HTTPException) as exc:
                await mark_alert_read(request, body)
            assert exc.value.status_code == 401
        # Nothing should have been written.
        assert alert_reads_db.get_read_alerts("alice") == []


# ---------------------------------------------------------------------------
# GET /api/alerts/read-status
# ---------------------------------------------------------------------------
class TestReadStatusEndpoint:
    @pytest.mark.asyncio
    async def test_returns_users_read_keys(self, temp_alert_db):
        alert_reads_db.mark_alert_read("alice", "a")
        alert_reads_db.mark_alert_read("alice", "b")
        request = make_mock_request()

        with patch("api.alerts.require_authenticated", return_value="alice"):
            result = await get_read_status(request)

        assert result["count"] == 2
        assert set(result["read"]) == {"a", "b"}

    @pytest.mark.asyncio
    async def test_empty_for_user_with_no_reads(self, temp_alert_db):
        request = make_mock_request()

        with patch("api.alerts.require_authenticated", return_value="fresh"):
            result = await get_read_status(request)

        assert result == {"count": 0, "read": []}

    @pytest.mark.asyncio
    async def test_scoped_to_calling_user(self, temp_alert_db):
        alert_reads_db.mark_alert_read("alice", "a")
        request = make_mock_request()

        with patch("api.alerts.require_authenticated", return_value="bob"):
            result = await get_read_status(request)

        assert result == {"count": 0, "read": []}

    @pytest.mark.asyncio
    async def test_requires_authentication(self, temp_alert_db):
        from fastapi import HTTPException

        request = make_mock_request()
        with patch(
            "api.alerts.require_authenticated",
            side_effect=HTTPException(status_code=401, detail="Not authenticated"),
        ):
            with pytest.raises(HTTPException) as exc:
                await get_read_status(request)
            assert exc.value.status_code == 401


# ---------------------------------------------------------------------------
# MarkReadRequest validation
# ---------------------------------------------------------------------------
class TestMarkReadRequestModel:
    def test_rejects_empty_alert_key(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            MarkReadRequest(alert_key="")

    def test_accepts_non_empty_key(self):
        assert MarkReadRequest(alert_key="x").alert_key == "x"


# ---------------------------------------------------------------------------
# Router wiring
# ---------------------------------------------------------------------------
def test_router_registers_new_routes():
    paths = {route.path for route in router.routes}
    assert "/api/alerts/mark-read" in paths
    assert "/api/alerts/read-status" in paths
