"""Pytest configuration and fixtures for vacaciones-service tests."""

import os
import sys
import tempfile
from pathlib import Path

import pytest

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Set test environment variables before importing modules
os.environ["VACACIONES_DATA_FILE"] = str(Path(tempfile.mkdtemp()) / "vacaciones.json")


@pytest.fixture
def tmp_data_file(tmp_path):
    """Provide a temporary data file for tests."""
    import vacaciones_controller
    
    original = vacaciones_controller.DATA_FILE
    vacaciones_controller.DATA_FILE = tmp_path / "vacaciones.json"
    
    yield tmp_path / "vacaciones.json"
    
    vacaciones_controller.DATA_FILE = original


@pytest.fixture
def client(tmp_data_file):
    """Create a test client with isolated data file."""
    from fastapi.testclient import TestClient
    from main import app
    
    return TestClient(app)


@pytest.fixture
def sample_nucleo():
    """Sample nucleo familiar data."""
    return {
        "id": "padres_angel",
        "nombre": "Padres de Angel",
        "color": "#6366f1",
        "hijo_id": "angel"
    }


@pytest.fixture
def sample_persona():
    """Sample persona data."""
    return {
        "id": "angel",
        "nombre": "Angel",
        "inicial": "A"
    }
