"""Shared fixtures for pc-agent tests.

These tests run on CI (Linux, no Docker Desktop) and locally on Windows.
Everything that touches Docker, the Windows filesystem or ``powercfg`` is
mocked, so no external process or daemon is ever required.

Import strategy
---------------
``src/main.py`` is imported under ``PYTHONPATH=src`` (as both CI and the local
dev helper do), so it is importable as the top-level module ``main``. The module
calls ``docker.from_env()`` at import time, but ``get_docker()`` swallows every
exception and returns ``None`` when no daemon is reachable, so importing the
module on a Docker-less CI runner is safe.
"""

import importlib
import sys
from pathlib import Path

import pytest

# Make ``src/`` importable even when pytest is not launched with PYTHONPATH=src
# (e.g. running the file directly). CI/dev already set PYTHONPATH=src, so this
# is a belt-and-braces fallback and a no-op when the path is already present.
SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

TEST_TOKEN = "test-secret-token"  # noqa: S105 - fake token for tests only


@pytest.fixture
def main_module():
    """Return the freshly imported ``main`` module.

    Imported once per test so patches applied via other fixtures/monkeypatch do
    not leak between tests.
    """
    if "main" in sys.modules:
        importlib.reload(sys.modules["main"])
    return importlib.import_module("main")


@pytest.fixture
def client(main_module, monkeypatch):
    """FastAPI ``TestClient`` with a known API token configured.

    ``API_TOKEN`` is read into a module global at import time, so patch the
    global directly rather than fiddling with env-var ordering.
    """
    from fastapi.testclient import TestClient

    monkeypatch.setattr(main_module, "API_TOKEN", TEST_TOKEN)
    return TestClient(main_module.app)


@pytest.fixture
def auth_headers():
    """Headers carrying the valid test token."""
    return {"X-Api-Token": TEST_TOKEN}
