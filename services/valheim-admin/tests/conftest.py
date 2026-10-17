"""Pytest configuration for valheim-admin tests.

src.main now fails closed: it raises at import time if PC_AGENT_TOKEN is not
set. The test environment has no real token, so provide a dummy one here —
this runs before any test module imports src.main, keeping import-time
validation intact while letting the suite exercise the app.
"""

import os
import sys
from pathlib import Path

# Add src directory to path so 'from config import' works
src_dir = Path(__file__).parent.parent / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

# Add libs directories for async_http_client and smart_home_common
libs_dir = Path(__file__).parent.parent.parent.parent / "libs"
smart_home_common_src = libs_dir / "smart_home_common" / "src"
for path in [libs_dir, smart_home_common_src]:
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

os.environ.setdefault("PC_AGENT_TOKEN", "test-token")
