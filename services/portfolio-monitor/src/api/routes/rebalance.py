"""
Portfolio Monitor — Rebalance endpoint.

Exposes the target-allocation drift analysis computed by
``monitors.rebalance.compute_rebalance`` over the orchestrator's cached
per-asset analyses. Read-only; no network or disk access on the request path.

``get_orchestrator`` is resolved through the ``api.routes`` package namespace at
call time so tests patching ``api.routes.get_orchestrator`` take effect here.
"""

import config
from fastapi import APIRouter
from monitors.rebalance import compute_rebalance

from .helpers import _safe_json

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


def _build_rebalance_payload() -> dict:
    """Compute the rebalance payload from the current cached summary + config.

    Shared by the endpoint and the active-alerts surface so both read exactly
    the same drift calculation.
    """
    import api.routes as routes

    orch = routes.get_orchestrator()
    summary = orch.get_summary()

    etf_funds = list(config.get_etf_portfolio().values())
    crypto_positions = config.get_crypto_positions()
    threshold = config.get_rebalance_config().get("threshold_pct", 5.0)

    return compute_rebalance(
        etf_analyses=summary.etf_analysis or [],
        crypto_analyses=summary.crypto_analysis or [],
        etf_funds=etf_funds,
        crypto_positions=crypto_positions,
        threshold_pct=threshold,
    )


@router.get("/rebalance")
async def get_rebalance():
    """Return per-position allocation drift and suggested rebalancing trades."""
    return _safe_json(_build_rebalance_payload())
