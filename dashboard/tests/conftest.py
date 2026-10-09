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

Authorization bypass for proxy unit tests
-----------------------------------------
The proxy endpoints now call ``require_super(request)`` for admin operations.
Unit tests that call these functions directly (not via TestClient with a real
auth flow) need to bypass this check. The ``mock_require_super`` fixture patches
the auth check to always succeed, returning a fake admin username.
"""

import gc
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def mock_require_super():
    """Bypass require_super authorization for direct function calls in tests.

    This fixture is autouse=True so it applies to all tests automatically.
    Tests that call proxy functions directly (not via TestClient) would otherwise
    fail with 401/403 because there's no real authenticated request.

    We patch in EVERY module that imports the function, because Python's
    `from X import Y` creates a local reference that isn't updated when X.Y
    is patched. The proxy modules import require_super at module level.

    For integration tests that DO want to test auth, they can override this
    fixture locally or use TestClient with proper auth setup.
    """
    # All modules that import require_super and need it bypassed in tests
    patch_targets = [
        "api.auth_helpers.require_super",  # The source module
        "api.proxy.ac.require_super",
        "api.proxy.vacaciones.require_super",
        "api.proxy.casita.require_super",
        "api.proxy.portfolio.require_super",
        "api.proxy.pc.require_super",
        "api.proxy.baby_gifts.require_super",
    ]

    # Stack multiple patches
    patches = [patch(target, return_value="test_admin") for target in patch_targets]

    for p in patches:
        p.start()

    yield

    for p in patches:
        p.stop()


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
