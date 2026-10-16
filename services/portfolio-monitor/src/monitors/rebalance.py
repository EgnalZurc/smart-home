"""
Portfolio Monitor — Rebalance deviation logic.

Pure, side-effect-free helpers that compare each position's *current* weight in
the combined portfolio (ETF + crypto) against a configured *target* allocation
and flag positions whose drift exceeds a threshold.

Design notes
------------
- This is a pure module: it takes the already-computed per-asset analyses
  (``ETFAnalysis`` / ``CryptoAnalysis``) plus the target map and threshold, and
  returns plain dicts. It never touches the network or disk, so the API layer
  and the orchestrator can both call it cheaply and it is trivial to test.
- Targets live in the TOML config (``target_allocation_pct`` per
  ``[[etf.funds]]`` / ``[[crypto.positions]]``) and are keyed by the position's
  stable identifier: ``fund_id`` for ETFs, ``symbol`` for crypto.
- Only positions with a positive target are considered: a target of 0 (the
  default) means "not tracked for rebalancing" and is skipped so untargeted
  positions do not pollute the analysis.
"""

from __future__ import annotations

from typing import Any

# Default drift threshold (percentage points) if config omits it.
DEFAULT_THRESHOLD_PCT: float = 5.0


def _resolve_targets(
    etf_funds: list[dict[str, Any]],
    crypto_positions: list[dict[str, Any]],
) -> dict[str, float]:
    """Build a ``{position_key: target_pct}`` map from raw config entries.

    ``position_key`` is the ETF ``id`` or the crypto ``symbol``. Entries with a
    non-positive target are omitted (treated as "not tracked for rebalancing").
    """
    targets: dict[str, float] = {}
    for fund in etf_funds:
        key = fund.get("id")
        target = _as_float(fund.get("target_allocation_pct"))
        if key and target > 0:
            targets[key] = target
    for pos in crypto_positions:
        key = pos.get("symbol")
        target = _as_float(pos.get("target_allocation_pct"))
        if key and target > 0:
            targets[key] = target
    return targets


def _as_float(value: Any) -> float:
    """Coerce a possibly-missing config value to float, defaulting to 0.0."""
    try:
        return float(value) if value is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def compute_rebalance(
    etf_analyses: list[Any],
    crypto_analyses: list[Any],
    etf_funds: list[dict[str, Any]],
    crypto_positions: list[dict[str, Any]],
    threshold_pct: float = DEFAULT_THRESHOLD_PCT,
) -> dict[str, Any]:
    """Compute per-position allocation drift and suggested rebalancing trades.

    Args:
        etf_analyses: ``ETFAnalysis`` items (need ``fund_id``, ``name``,
            ``current_value``).
        crypto_analyses: ``CryptoAnalysis`` items (need ``symbol``, ``name``,
            ``current_value``).
        etf_funds: raw ETF config entries (carry ``target_allocation_pct``).
        crypto_positions: raw crypto config entries (carry
            ``target_allocation_pct``).
        threshold_pct: absolute deviation (in percentage points) above which a
            position is flagged ``needs_rebalance``.

    Returns a dict with:
        - ``positions``: one entry per *targeted* position with
          ``{symbol, name, current_value, current_allocation,
          target_allocation, deviation, needs_rebalance}``.
        - ``suggested_trades``: BUY/SELL suggestions that move each flagged
          position back to its target weight of the current total.
        - ``total_value``: combined portfolio value used as the denominator.
        - ``threshold_pct``: the threshold applied (echoed for transparency).
        - ``needs_rebalance``: True if any position is flagged.
    """
    targets = _resolve_targets(etf_funds, crypto_positions)

    # Collect (key, name, value) for every analysis that has a target.
    rows: list[tuple[str, str, float]] = []
    for a in etf_analyses or []:
        key = getattr(a, "fund_id", None)
        if key in targets:
            rows.append(
                (
                    key,
                    getattr(a, "name", key),
                    _as_float(getattr(a, "current_value", 0.0)),
                )
            )
    for a in crypto_analyses or []:
        key = getattr(a, "symbol", None)
        if key in targets:
            rows.append(
                (
                    key,
                    getattr(a, "name", key),
                    _as_float(getattr(a, "current_value", 0.0)),
                )
            )

    total_value = sum(value for _, _, value in rows)

    positions: list[dict[str, Any]] = []
    suggested_trades: list[dict[str, Any]] = []

    for key, name, value in rows:
        target = targets[key]
        # With no portfolio value we cannot compute a meaningful weight; report
        # current_allocation as 0 and defer flagging (deviation == -target would
        # otherwise fire spurious alerts on an empty/unpriced portfolio).
        current_allocation = (value / total_value * 100) if total_value > 0 else 0.0
        deviation = current_allocation - target
        needs = total_value > 0 and abs(deviation) > threshold_pct

        positions.append(
            {
                "symbol": key,
                "name": name,
                "current_value": round(value, 2),
                "current_allocation": round(current_allocation, 2),
                "target_allocation": round(target, 2),
                "deviation": round(deviation, 2),
                "needs_rebalance": needs,
            }
        )

        if needs:
            # Target value = target weight applied to the CURRENT total. The
            # delta tells us how much to buy (positive) or sell (negative) to
            # restore the target weight of today's portfolio.
            target_value = target / 100 * total_value
            delta = target_value - value
            suggested_trades.append(
                {
                    "symbol": key,
                    "name": name,
                    "action": "BUY" if delta > 0 else "SELL",
                    "amount_eur": round(abs(delta), 2),
                    "current_allocation": round(current_allocation, 2),
                    "target_allocation": round(target, 2),
                }
            )

    return {
        "total_value": round(total_value, 2),
        "threshold_pct": threshold_pct,
        "needs_rebalance": any(p["needs_rebalance"] for p in positions),
        "positions": positions,
        "suggested_trades": suggested_trades,
    }
