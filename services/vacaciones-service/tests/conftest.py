"""Pytest configuration and fixtures for vacaciones-service tests.

This module provides test fixtures with proper isolation:
- tmp_data_file: Isolated data file per test
- client: Test client with CSRF DISABLED (for most tests)
- client_csrf_enabled: Test client with CSRF ENABLED (for CSRF-specific tests)

CSRF Strategy:
    Most tests use `client` fixture which disables CSRF via ALLOWED_ORIGINS="*".
    This allows testing business logic without Origin header boilerplate.

    Tests that specifically verify CSRF behavior use `client_csrf_enabled`
    which requires proper Origin/Referer headers on state-changing requests.
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Store original ALLOWED_ORIGINS to restore later
_ORIGINAL_ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "")

# Set test environment variables before importing modules
os.environ["VACACIONES_DATA_FILE"] = str(Path(tempfile.mkdtemp()) / "vacaciones.json")
# Disable CSRF protection for default client (most tests don't need Origin headers)
os.environ["ALLOWED_ORIGINS"] = "*"


@pytest.fixture
def tmp_data_file(tmp_path):
    """Provide a temporary data file for tests.

    Creates an isolated data file in a temporary directory, ensuring
    tests don't interfere with each other's data.
    """
    import vacaciones_controller

    original = vacaciones_controller.DATA_FILE
    vacaciones_controller.DATA_FILE = tmp_path / "vacaciones.json"

    yield tmp_path / "vacaciones.json"

    vacaciones_controller.DATA_FILE = original


@pytest.fixture
def client(tmp_data_file):
    """Create a test client with CSRF DISABLED.

    This is the default client for most tests. CSRF is disabled via
    ALLOWED_ORIGINS="*" so tests can focus on business logic without
    needing to include Origin headers on every request.

    Use client_csrf_enabled for tests that specifically verify CSRF behavior.
    """
    from fastapi.testclient import TestClient
    from main import _rate_limiter, app

    # Clear rate limit state between tests to ensure isolation
    with _rate_limiter._lock:
        _rate_limiter._data.clear()

    return TestClient(app)


@pytest.fixture
def client_csrf_enabled(tmp_data_file):
    """Create a test client with CSRF ENABLED.

    Use this fixture for tests that need to verify CSRF protection.
    State-changing requests (POST/PUT/DELETE) must include a valid
    Origin header from ALLOWED_ORIGINS.

    Example:
        def test_post_requires_origin(client_csrf_enabled):
            # This should fail - no Origin header
            response = client_csrf_enabled.post("/api/vacaciones/config", json={...})
            assert response.status_code == 403

            # This should succeed - valid Origin
            response = client_csrf_enabled.post(
                "/api/vacaciones/config",
                json={...},
                headers={"Origin": "https://test.example.com"},
            )
            assert response.status_code == 200
    """
    import importlib

    import main

    # Enable CSRF with a test origin
    os.environ["ALLOWED_ORIGINS"] = "https://test.example.com"
    importlib.reload(main)

    from fastapi.testclient import TestClient

    # Clear rate limit state
    with main._rate_limiter._lock:
        main._rate_limiter._data.clear()

    client = TestClient(main.app)

    yield client

    # Restore CSRF disabled for subsequent tests
    os.environ["ALLOWED_ORIGINS"] = "*"
    importlib.reload(main)


@pytest.fixture
def sample_nucleo():
    """Sample nucleo familiar data."""
    return {
        "id": "padres_angel",
        "nombre": "Padres de Angel",
        "color": "#6366f1",
        "hijo_id": "angel",
    }


@pytest.fixture
def sample_persona():
    """Sample persona data."""
    return {"id": "angel", "nombre": "Angel", "inicial": "A"}
