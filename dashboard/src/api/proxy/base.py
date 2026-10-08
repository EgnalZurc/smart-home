"""Service proxy base class for the dashboard.

This module is a thin re-export of the shared ``ServiceProxy`` implementation
in ``libs/service_proxy``. The dashboard previously carried its own hand-copied
duplicate of this class; it now consumes the shared library so there is a single
source of truth for proxy behaviour across all services.

The shared library ships two flavours:

* ``libs.service_proxy.proxy`` — framework-agnostic, raises the library's own
  ``HTTPException``.
* ``libs.service_proxy.fastapi`` — FastAPI adapter that converts the library's
  ``HTTPException`` into ``fastapi.HTTPException`` so route handlers behave
  exactly as before.

The dashboard runs on FastAPI, so we re-export the FastAPI adapter here. All
dashboard proxy modules import ``ServiceProxy`` from this module, keeping the
import surface stable (``from .base import ServiceProxy``).

Import resolution: at runtime the ``libs`` package lives at ``/app/libs`` and is
importable because ``/app`` is on ``sys.path``. In the test/CI environment the
dashboard runs pytest with ``PYTHONPATH=src`` from the ``dashboard`` directory,
so the repository root is not on ``sys.path`` by default; the fallback below
inserts it, mirroring the pattern used by the other services (see
``services/baby-gifts-service/src/notifier.py``).
"""

try:
    from libs.service_proxy.fastapi import ServiceProxy
    from libs.service_proxy.proxy import HTTPException
except ImportError:  # pragma: no cover - exercised only outside the container
    import sys
    from pathlib import Path

    # base.py lives at <repo>/dashboard/src/api/proxy/base.py → repo root is 5 up.
    _repo_root = Path(__file__).resolve().parents[4]
    sys.path.insert(0, str(_repo_root))
    from libs.service_proxy.fastapi import ServiceProxy
    from libs.service_proxy.proxy import HTTPException

__all__ = ["ServiceProxy", "HTTPException"]
