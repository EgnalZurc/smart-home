"""Pytest configuration and fixtures for ac-service tests."""

import os
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# smart_home_common is installed (pip install -e) in CI and via dev.ps1. When
# running pytest directly without that install, fall back to the in-repo source
# so the shared library resolves either way.
try:
    import smart_home_common  # noqa: F401
except ModuleNotFoundError:
    _common_src = (
        Path(__file__).parent.parent.parent.parent
        / "libs"
        / "smart_home_common"
        / "src"
    )
    if _common_src.exists():
        sys.path.insert(0, str(_common_src))

# Set required environment variables for tests
os.environ.setdefault("MELCLOUD_EMAIL", "test@example.com")
os.environ.setdefault("MELCLOUD_PASSWORD", "testpassword")
os.environ.setdefault("MELCLOUD_DEVICE_ID", "12345")
os.environ.setdefault("MELCLOUD_BUILDING_ID", "67890")
os.environ.setdefault("MQTT_BROKER", "localhost")
