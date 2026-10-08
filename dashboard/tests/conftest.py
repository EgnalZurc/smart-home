"""Shared fixtures for all tests.

pytest.ini sets pythonpath = dashboard/src so all imports work directly.

The former AC/MQTT/MELCloud fixtures referenced modules that no longer live in
this service and have been removed.

SQLite test isolation
---------------------
The auth/profile stores open SQLite in WAL mode. WAL keeps sidecar file handles
(``*.db-wal`` / ``*.db-shm``) open for the lifetime of the connection, so a
connection that is never closed makes the temp directory impossible to delete on
Windows (``PermissionError``/``WinError 32``) and leaks state between tests on
every platform. The source helpers now expose context managers that always
close the connection; the ``temp_auth_db`` fixture below gives each test a fresh
database and tears the directory down tolerantly as a backstop.
"""

import gc
import sys
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_auth_db(monkeypatch):
    """Point every auth/profile store at a fresh per-test SQLite database.

    Yields the ``Path`` to the database file. ``AUTH_DB_PATH`` is patched (via
    ``monkeypatch`` so it is restored automatically) in each module that owns a
    SQLite helper. On teardown the temp directory is removed with
    ``ignore_cleanup_errors=True`` so a stray open handle can never fail a test
    run — though with connections now closed deterministically this should not
    happen.
    """
    # ``ignore_cleanup_errors`` makes TemporaryDirectory tolerate a lingering
    # WAL handle on Windows instead of raising on __exit__.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = Path(tmp) / "test_auth.db"

        for module_name in ("auth_users", "auth_devices", "profiles.db"):
            module = sys.modules.get(module_name)
            if module is None:
                try:
                    module = __import__(module_name, fromlist=["AUTH_DB_PATH"])
                except ImportError:
                    continue
            if hasattr(module, "AUTH_DB_PATH"):
                monkeypatch.setattr(module, "AUTH_DB_PATH", str(db_path))

        try:
            yield db_path
        finally:
            # Drop any connection objects the test left referenced so their
            # __del__ runs (and WAL handles close) before cleanup.
            gc.collect()
