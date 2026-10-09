"""Pytest configuration for valheim-admin tests.

src.main now fails closed: it raises at import time if PC_AGENT_TOKEN is not
set. The test environment has no real token, so provide a dummy one here —
this runs before any test module imports src.main, keeping import-time
validation intact while letting the suite exercise the app.
"""

import os

os.environ.setdefault("PC_AGENT_TOKEN", "test-token")
