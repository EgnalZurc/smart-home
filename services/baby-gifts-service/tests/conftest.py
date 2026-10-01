"""Pytest configuration and fixtures for baby-gifts-service tests."""

import os
import sys
import tempfile
from pathlib import Path

import pytest

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Set test environment variables before importing modules
os.environ["DATA_DIR"] = tempfile.mkdtemp()


@pytest.fixture
def tmp_data_dir(tmp_path):
    """Provide a temporary data directory for tests."""
    import gifts_controller
    
    original_data_dir = gifts_controller.DATA_DIR
    original_gifts_file = gifts_controller.GIFTS_FILE
    original_db_file = gifts_controller.DB_FILE
    
    gifts_controller.DATA_DIR = tmp_path
    gifts_controller.GIFTS_FILE = tmp_path / "gifts.json"
    gifts_controller.DB_FILE = tmp_path / "baby_gifts.db"
    
    yield tmp_path
    
    gifts_controller.DATA_DIR = original_data_dir
    gifts_controller.GIFTS_FILE = original_gifts_file
    gifts_controller.DB_FILE = original_db_file


@pytest.fixture
def client(tmp_data_dir):
    """Create a test client with isolated data directory."""
    from fastapi.testclient import TestClient
    from main import app
    
    return TestClient(app)


@pytest.fixture
def sample_gift():
    """Sample gift data for testing."""
    return {
        "name": "Carrito de bebé",
        "description": "Preferiblemente ligero y plegable",
        "url": "https://example.com/carrito",
        "price_range": "€€€",
        "category": "transporte",
        "priority": 1,
    }


@pytest.fixture
def sample_invitation_name():
    """Sample invitation name for testing."""
    return "Tía María"
