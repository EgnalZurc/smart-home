"""Pytest configuration for presence-service.

Ensures the service source and shared ``smart_home_common`` library are
importable when running tests in isolation (CI runs from the service directory).
"""

import sys
from pathlib import Path

# Service root is the parent of this tests/ directory
_SERVICE_ROOT: Path = Path(__file__).resolve().parent.parent
_SRC_PATH: Path = _SERVICE_ROOT / "src"

# Shared library lives at repo_root/libs/smart_home_common/src
_COMMON_SRC: Path = _SERVICE_ROOT.parent.parent / "libs" / "smart_home_common" / "src"

# Add paths if not already present (idempotent)
for path in (_SRC_PATH, _COMMON_SRC):
    path_str: str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)
