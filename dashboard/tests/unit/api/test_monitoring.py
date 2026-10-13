"""Unit tests for the memory monitoring API.

These tests import the monitoring module directly to avoid loading the full
routes module which has many dependencies.
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest


# Prevent conftest from trying to load full api.routes (has many deps)
@pytest.fixture(autouse=True)
def isolate_monitoring_module():
    """Ensure monitoring module is imported fresh for each test."""
    # Remove any cached imports that might pull in routes
    mods_to_remove = [k for k in sys.modules if k.startswith("api.")]
    for mod in mods_to_remove:
        sys.modules.pop(mod, None)
    yield


class TestMemoryMonitoring:
    """Tests for /api/monitoring/memory/* endpoints."""

    @pytest.fixture
    def temp_storage(self, tmp_path):
        """Return paths for temporary history storage."""
        history_dir = tmp_path / "monitoring"
        history_file = history_dir / "memory_history.json"
        return history_dir, history_file

    def _get_module_with_patches(self, history_dir, history_file):
        """Import monitoring module with patched paths."""
        with patch.dict(
            "sys.modules",
            {
                # Prevent routes from loading when monitoring imports
            },
        ):
            # Patch the module-level constants before import
            import api.monitoring as monitoring

            # Override the module constants
            monitoring.HISTORY_DIR = history_dir
            monitoring.HISTORY_FILE = history_file
            return monitoring

    def test_load_history_returns_empty_on_missing_file(self, temp_storage):
        """_load_history returns empty dict when file doesn't exist."""
        history_dir, history_file = temp_storage

        import api.monitoring as monitoring

        monitoring.HISTORY_DIR = history_dir
        monitoring.HISTORY_FILE = history_file

        result = monitoring._load_history()
        assert result == {"snapshots": []}

    def test_load_history_handles_corrupt_json(self, temp_storage):
        """_load_history handles corrupt JSON gracefully."""
        history_dir, history_file = temp_storage

        history_dir.mkdir(parents=True, exist_ok=True)
        history_file.write_text("not valid json {{{", encoding="utf-8")

        import api.monitoring as monitoring

        monitoring.HISTORY_DIR = history_dir
        monitoring.HISTORY_FILE = history_file

        result = monitoring._load_history()
        assert result == {"snapshots": []}

    def test_save_history_creates_directory(self, temp_storage):
        """_save_history creates the history directory if missing."""
        history_dir, history_file = temp_storage

        import api.monitoring as monitoring

        monitoring.HISTORY_DIR = history_dir
        monitoring.HISTORY_FILE = history_file

        # Directory doesn't exist yet
        assert not history_dir.exists()

        monitoring._save_history(
            {"snapshots": [{"timestamp": "2024-01-01T00:00:00Z", "stats": []}]}
        )

        # Now it should exist
        assert history_dir.exists()
        assert history_file.exists()

    def test_save_history_prunes_old_entries(self, temp_storage):
        """_save_history removes entries older than MAX_HISTORY_DAYS."""
        history_dir, history_file = temp_storage

        import api.monitoring as monitoring

        monitoring.HISTORY_DIR = history_dir
        monitoring.HISTORY_FILE = history_file

        old_timestamp = (datetime.utcnow() - timedelta(days=40)).isoformat()
        recent_timestamp = datetime.utcnow().isoformat()

        monitoring._save_history(
            {
                "snapshots": [
                    {"timestamp": old_timestamp, "stats": []},
                    {"timestamp": recent_timestamp, "stats": []},
                ]
            }
        )

        data = monitoring._load_history()
        # Old entry should be pruned
        assert len(data["snapshots"]) == 1
        assert data["snapshots"][0]["timestamp"] == recent_timestamp

    @pytest.mark.asyncio
    async def test_snapshot_returns_alerts_for_high_usage(self, temp_storage):
        """POST /memory/snapshot returns alerts for services > 80%."""
        history_dir, history_file = temp_storage

        import api.monitoring as monitoring

        monitoring.HISTORY_DIR = history_dir
        monitoring.HISTORY_FILE = history_file

        payload = monitoring.SnapshotPayload(
            timestamp="2024-01-01T12:00:00Z",
            stats=[
                monitoring.MemorySnapshot(
                    container="healthy-service",
                    used_mib=50,
                    limit_mib=100,
                    percent=50,
                ),
                monitoring.MemorySnapshot(
                    container="warning-service",
                    used_mib=85,
                    limit_mib=100,
                    percent=85,
                ),
                monitoring.MemorySnapshot(
                    container="critical-service",
                    used_mib=95,
                    limit_mib=100,
                    percent=95,
                ),
            ],
        )

        result = await monitoring.receive_memory_snapshot(payload)

        assert result["status"] == "ok"
        assert result["received"] == 3
        assert len(result["alerts"]) == 2

        alert_containers = {a["container"] for a in result["alerts"]}
        assert "healthy-service" not in alert_containers
        assert "warning-service" in alert_containers
        assert "critical-service" in alert_containers

    @pytest.mark.asyncio
    async def test_get_history_filters_by_days(self, temp_storage):
        """GET /memory/history filters by days parameter."""
        history_dir, history_file = temp_storage

        import api.monitoring as monitoring

        monitoring.HISTORY_DIR = history_dir
        monitoring.HISTORY_FILE = history_file

        now = datetime.utcnow()
        timestamps = [
            (now - timedelta(days=1)).isoformat(),
            (now - timedelta(days=5)).isoformat(),
            (now - timedelta(days=10)).isoformat(),
        ]

        monitoring._save_history(
            {"snapshots": [{"timestamp": ts, "stats": []} for ts in timestamps]}
        )

        # Request 3 days - should get 1 snapshot
        result = await monitoring.get_memory_history(days=3)
        assert result["count"] == 1

        # Request 7 days - should get 2 snapshots
        result = await monitoring.get_memory_history(days=7)
        assert result["count"] == 2

        # Request 14 days - should get all 3
        result = await monitoring.get_memory_history(days=14)
        assert result["count"] == 3

    @pytest.mark.asyncio
    async def test_get_alerts_returns_sorted_by_percent(self, temp_storage):
        """GET /memory/alerts returns alerts sorted by percent descending."""
        history_dir, history_file = temp_storage

        import api.monitoring as monitoring

        monitoring.HISTORY_DIR = history_dir
        monitoring.HISTORY_FILE = history_file

        now = datetime.utcnow()

        monitoring._save_history(
            {
                "snapshots": [
                    {
                        "timestamp": now.isoformat(),
                        "stats": [
                            {
                                "container": "low",
                                "used_mib": 50,
                                "limit_mib": 100,
                                "percent": 50,
                            },
                            {
                                "container": "high",
                                "used_mib": 95,
                                "limit_mib": 100,
                                "percent": 95,
                            },
                            {
                                "container": "medium",
                                "used_mib": 82,
                                "limit_mib": 100,
                                "percent": 82,
                            },
                        ],
                    }
                ]
            }
        )

        result = await monitoring.get_memory_alerts(days=7)

        assert result["threshold_percent"] == 80
        assert result["count"] == 2

        # Should be sorted descending
        alerts = result["alerts"]
        assert alerts[0]["container"] == "high"
        assert alerts[0]["percent"] == 95
        assert alerts[1]["container"] == "medium"
        assert alerts[1]["percent"] == 82

    @pytest.mark.asyncio
    async def test_alerts_excludes_services_below_threshold(self, temp_storage):
        """GET /memory/alerts excludes services below 80%."""
        history_dir, history_file = temp_storage

        import api.monitoring as monitoring

        monitoring.HISTORY_DIR = history_dir
        monitoring.HISTORY_FILE = history_file

        now = datetime.utcnow()

        monitoring._save_history(
            {
                "snapshots": [
                    {
                        "timestamp": now.isoformat(),
                        "stats": [
                            {
                                "container": "safe",
                                "used_mib": 79,
                                "limit_mib": 100,
                                "percent": 79,
                            },
                            {
                                "container": "exactly-80",
                                "used_mib": 80,
                                "limit_mib": 100,
                                "percent": 80,
                            },
                        ],
                    }
                ]
            }
        )

        result = await monitoring.get_memory_alerts(days=7)

        # 79% should be excluded, 80% should be included (>= threshold)
        assert result["count"] == 1
        assert result["alerts"][0]["container"] == "exactly-80"
