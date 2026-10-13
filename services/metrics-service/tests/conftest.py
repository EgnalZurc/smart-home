"""Pytest configuration for metrics-service.

Ensures the shared ``smart_home_common`` library is importable when the service
is tested in isolation (CI runs ``PYTHONPATH=src`` from the service directory;
the shared lib lives at ``../../libs/smart_home_common/src``).
"""

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _SERVICE_ROOT.parents[1]
_COMMON_SRC = _REPO_ROOT / "libs" / "smart_home_common" / "src"

for p in (str(_SERVICE_ROOT / "src"), str(_COMMON_SRC)):
    if p not in sys.path:
        sys.path.insert(0, p)
