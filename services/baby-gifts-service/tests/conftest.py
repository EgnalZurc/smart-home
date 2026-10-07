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
os.environ["TRUSTED_PROXY_IPS"] = "127.0.0.1,testclient"


@pytest.fixture
def tmp_data_dir(tmp_path):
    """Provide a temporary data directory for tests.

    This fixture ensures complete isolation between tests by:
    1. Using a fresh temp directory for each test
    2. Resetting module-level variables in config
    3. Deleting any existing data files
    """
    import config
    import gifts_controller

    # Save original values
    original_data_dir = config.DATA_DIR
    original_gifts_file = config.GIFTS_FILE
    original_db_file = config.DB_FILE

    # Set new paths in config
    config.DATA_DIR = tmp_path
    config.GIFTS_FILE = tmp_path / "gifts.json"
    config.DB_FILE = tmp_path / "baby_gifts.db"

    # Also update gifts_controller's references (it imports from config at module load)
    gifts_controller.DATA_DIR = tmp_path
    gifts_controller.GIFTS_FILE = tmp_path / "gifts.json"
    gifts_controller.DB_FILE = tmp_path / "baby_gifts.db"

    # Ensure no leftover data
    if config.GIFTS_FILE.exists():
        config.GIFTS_FILE.unlink()
    if config.DB_FILE.exists():
        config.DB_FILE.unlink()

    yield tmp_path

    # Restore original values
    config.DATA_DIR = original_data_dir
    config.GIFTS_FILE = original_gifts_file
    config.DB_FILE = original_db_file


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
        "priority": 1,
    }


@pytest.fixture
def sample_invitation_name():
    """Sample invitation name for testing."""
    return "Tía María"
