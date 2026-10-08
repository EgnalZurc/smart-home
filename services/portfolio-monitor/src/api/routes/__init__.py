"""
Portfolio Monitor — API Routes (package).

Aggregates the focused sub-routers into a single ``router`` exposed via
``api.__init__`` → ``main.py``, keeping the HTTP surface exactly the same as
the monolithic routes.py it replaces.

Every name that tests reference as ``api.routes.X`` is re-exported here so
existing patch targets (``patch("api.routes.get_orchestrator")``, etc.) keep
working without test changes.
"""

from fastapi import APIRouter
from orchestrator import get_orchestrator  # noqa: F401 — patched by tests

# ─── Sub-routers ─────────────────────────────────────────────────────────────
from .alerts import router as _alerts_router
from .control import router as _control_router

# ─── Re-export: helpers (imported directly by tests) ─────────────────────────
from .helpers import (  # noqa: F401
    _config_limiter,
    _enforce_rate_limit,
    _refresh_limiter,
    _retry_after_seconds,
    _safe_float,
    _safe_json,
    _scrub_payload,
    _serialize_alert,
    _serialize_analysis,
    rate_limit,
)
from .helpers import _SafeJSONResponse  # noqa: F401
from .health import router as _health_router

# ─── Re-export: health checks (patched at callsite by tests) ────────────────
from .health_checks import (  # noqa: F401
    _check_coingecko_sync,
    _check_fear_greed_sync,
    _check_smtp_sync,
    _check_yahoo_sync,
    check_coingecko,
    check_fear_greed,
    check_smtp,
    check_yahoo_finance,
)
from .notifications import router as _notifications_router
from .summary import router as _summary_router

# ─── Aggregate router ───────────────────────────────────────────────────────
router = APIRouter()
router.include_router(_summary_router)
router.include_router(_control_router)
router.include_router(_alerts_router)
router.include_router(_notifications_router)
router.include_router(_health_router)
