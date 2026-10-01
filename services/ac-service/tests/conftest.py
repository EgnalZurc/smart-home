"""Pytest configuration and fixtures for ac-service tests."""

import os
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Set required environment variables for tests
os.environ.setdefault("MELCLOUD_EMAIL", "test@example.com")
os.environ.setdefault("MELCLOUD_PASSWORD", "testpassword")
os.environ.setdefault("MELCLOUD_DEVICE_ID", "12345")
os.environ.setdefault("MELCLOUD_BUILDING_ID", "67890")
os.environ.setdefault("MQTT_BROKER", "localhost")
