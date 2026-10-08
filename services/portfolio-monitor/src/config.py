"""
Portfolio Monitor — Configuration loader.
Loads settings from TOML file and exposes typed configuration.
"""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ImportError:
        print("ERROR: Install 'tomli' for Python < 3.11: pip install tomli")
        sys.exit(1)

# ─────────────────────────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────────────────────────
DATA_DIR = Path(os.environ.get("DATA_DIR", "/app/data"))
SETTINGS_PATH = DATA_DIR / "settings.toml"

# ─────────────────────────────────────────────────────────────────────────────
# Default configuration (used if no settings.toml exists)
# ─────────────────────────────────────────────────────────────────────────────
_DEFAULT_CONFIG: dict[str, Any] = {
    "general": {"lang": "es", "log_level": "INFO"},
    "etf": {"funds": [], "plan": {}, "thresholds": {}},
    "crypto": {"positions": [], "thresholds": {}},
    "schedule": {
        "etf_time": "18:00",  # After European markets close
        "crypto_time": "09:00",  # Morning check
    },
}


def _load_settings() -> dict[str, Any]:
    """Load settings from TOML file, or return defaults if not found."""
    if not SETTINGS_PATH.exists():
        return _DEFAULT_CONFIG.copy()

    with open(SETTINGS_PATH, "rb") as f:
        return tomllib.load(f)


def _get(data: dict, path: str, default: Any = None) -> Any:
    """Dot-separated key access into nested dict."""
    node = data
    for key in path.split("."):
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return node


# ─────────────────────────────────────────────────────────────────────────────
# Load configuration
# ─────────────────────────────────────────────────────────────────────────────
_S = _load_settings()

# General
LANG: str = os.environ.get("MONITOR_LANG", _get(_S, "general.lang", "es")).lower()
LOG_LEVEL: str = os.environ.get(
    "LOG_LEVEL", _get(_S, "general.log_level", "INFO")
).upper()

# Schedule
SCHEDULE = {
    "etf_time": _get(_S, "schedule.etf_time", "18:00"),
    "crypto_time": _get(_S, "schedule.crypto_time", "09:00"),
}


# ─────────────────────────────────────────────────────────────────────────────
# Default IRPF brackets for 2025 (Ley 7/2024) - base liquidable del ahorro
# Defined before the builder so both initial load and reload reuse the same list.
# ─────────────────────────────────────────────────────────────────────────────
_DEFAULT_TAX_BRACKETS = [
    (6_000, 0.19),  # 0 - 6.000€: 19%
    (50_000, 0.21),  # 6.000 - 50.000€: 21%
    (200_000, 0.23),  # 50.000 - 200.000€: 23%
    (300_000, 0.27),  # 200.000 - 300.000€: 27%
    (float("inf"), 0.30),  # +300.000€: 30% (nuevo tramo 2025)
]


# ─────────────────────────────────────────────────────────────────────────────
# ETF Configuration
# ─────────────────────────────────────────────────────────────────────────────
def _build_fund_entry(raw: dict[str, Any]) -> dict[str, Any]:
    """Convert one [[etf.funds]] TOML entry into runtime dict."""
    start_date = raw.get("inicio", "").strip()
    avg_cost = raw.get("precio_medio", 0.0)
    return {
        "id": raw.get("id", ""),
        "ticker": raw.get("ticker", ""),
        "name": raw.get("name", raw.get("id", "")),
        "isin": raw.get("isin", ""),
        "avg_cost": avg_cost if avg_cost > 0 else None,
        "units": raw.get("participaciones", 0.0),
        "monthly_contrib": raw.get("aportacion_mes", 0.0),
        "phase2_contrib": raw.get("aportacion_fase2", 0.0),
        "start_date": start_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "color": raw.get("color", "#3A7BD5"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Builders — pure functions that derive runtime config from a raw settings dict.
# Both the initial import and reload_config() go through the same code path, so
# defaults (e.g. tax brackets) are applied identically every time.
# ─────────────────────────────────────────────────────────────────────────────
def _build_etf_portfolio(settings: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        fund["id"]: _build_fund_entry(fund)
        for fund in _get(settings, "etf.funds", [])
        if "id" in fund
    }


def _build_etf_plan(settings: dict[str, Any]) -> dict[str, Any]:
    plan_raw = _get(settings, "etf.plan", {})
    milestones = _get(settings, "etf.plan.milestones", {})
    raw_brackets = _get(settings, "etf.tax.brackets", [])
    return {
        "phase_change_date": datetime.fromisoformat(
            plan_raw.get("phase_change_date", "2027-03-01")
        ),
        "milestones": {int(k): tuple(v) for k, v in milestones.items()},
        # Fall back to the built-in IRPF defaults when the TOML has no brackets.
        # This must happen on reload too, otherwise reloading would wipe them.
        "tax_brackets": [
            (float("inf") if limit >= 999_999_999 else float(limit), rate)
            for limit, rate in raw_brackets
        ]
        if raw_brackets
        else list(_DEFAULT_TAX_BRACKETS),
    }


def _build_etf_thresholds(settings: dict[str, Any]) -> dict[str, Any]:
    thr = _get(settings, "etf.thresholds", {})
    return {
        "ma_short": thr.get("ma_short", 50),
        "ma_long": thr.get("ma_long", 200),
        "drop_from_high_warn": thr.get("drop_from_high_warn", -0.15),
        "loss_vs_cost_warn": thr.get("loss_vs_cost_warn", -0.10),
        "critical_threshold": thr.get("critical_threshold", -0.20),
    }


def _build_crypto_thresholds(settings: dict[str, Any]) -> dict[str, Any]:
    # Note: Fear & Greed is a sentiment indicator, not a price predictor
    thr = _get(settings, "crypto.thresholds", {})
    return {
        "fg_extreme_greed": thr.get("fg_extreme_greed", 75),  # Adjusted from 80
        "fg_high_greed": thr.get("fg_high_greed", 60),  # Adjusted from 65
        "fg_extreme_fear": thr.get("fg_extreme_fear", 25),  # Adjusted from 20
        "change_24h_danger": thr.get("change_24h_danger", -10),
        "change_24h_warn": thr.get("change_24h_warn", -5),
        "change_24h_pump": thr.get("change_24h_pump", 10),
        "change_30d_bear": thr.get("change_30d_bear", -20),
        "change_30d_bull": thr.get("change_30d_bull", 20),
        "ath_danger_pct": thr.get("ath_danger_pct", -5),
        "ath_warn_pct": thr.get("ath_warn_pct", -15),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Module-level config values.
#
# These are assigned once at import and reassigned on reload_config(). Because
# `from config import X` binds a *copy* of the reference at import time, other
# modules MUST NOT do that for values that can be reloaded — reassigning the
# module global here would not update the already-imported name elsewhere.
# Use the accessor functions below (or `import config; config.X`) at call time
# so reloaded values are always observed.
# ─────────────────────────────────────────────────────────────────────────────
ETF_PORTFOLIO: dict[str, dict[str, Any]] = _build_etf_portfolio(_S)
ETF_FUND_IDS: list[str] = list(ETF_PORTFOLIO.keys())
ETF_PLAN: dict[str, Any] = _build_etf_plan(_S)
ETF_THRESHOLDS: dict[str, Any] = _build_etf_thresholds(_S)
CRYPTO_POSITIONS: list[dict[str, Any]] = _get(_S, "crypto.positions", [])
CRYPTO_THRESHOLDS: dict[str, Any] = _build_crypto_thresholds(_S)
SAVINGS_ACCOUNTS: list[dict[str, Any]] = _get(_S, "savings.accounts", [])
SCHEDULED_ALERTS: list[dict[str, Any]] = _get(_S, "alerts.scheduled", [])


# ─────────────────────────────────────────────────────────────────────────────
# Accessors — always return the CURRENT module-level value.
#
# Consumers should call these (instead of importing the globals) so they see
# values refreshed by reload_config(). They are intentionally trivial wrappers.
# ─────────────────────────────────────────────────────────────────────────────
def get_etf_portfolio() -> dict[str, dict[str, Any]]:
    return ETF_PORTFOLIO


def get_etf_fund_ids() -> list[str]:
    return ETF_FUND_IDS


def get_etf_plan() -> dict[str, Any]:
    return ETF_PLAN


def get_etf_thresholds() -> dict[str, Any]:
    return ETF_THRESHOLDS


def get_crypto_positions() -> list[dict[str, Any]]:
    return CRYPTO_POSITIONS


def get_crypto_thresholds() -> dict[str, Any]:
    return CRYPTO_THRESHOLDS


def get_savings_accounts() -> list[dict[str, Any]]:
    return SAVINGS_ACCOUNTS


def get_scheduled_alerts() -> list[dict[str, Any]]:
    return SCHEDULED_ALERTS


def get_schedule() -> dict[str, str]:
    return SCHEDULE


# ─────────────────────────────────────────────────────────────────────────────
# Utility: Reload configuration
# ─────────────────────────────────────────────────────────────────────────────
def reload_config() -> dict[str, Any]:
    """Reload settings from disk and refresh all derived config values.

    Rebuilds every module-level value through the same builders used at import,
    so defaults (tax brackets, thresholds, schedule) are preserved on reload.
    Returns the raw settings dict.
    """
    global _S, SCHEDULE
    global ETF_PORTFOLIO, ETF_FUND_IDS, ETF_PLAN, ETF_THRESHOLDS
    global CRYPTO_POSITIONS, CRYPTO_THRESHOLDS
    global SAVINGS_ACCOUNTS, SCHEDULED_ALERTS

    _S = _load_settings()

    SCHEDULE = {
        "etf_time": _get(_S, "schedule.etf_time", "18:00"),
        "crypto_time": _get(_S, "schedule.crypto_time", "09:00"),
    }
    ETF_PORTFOLIO = _build_etf_portfolio(_S)
    ETF_FUND_IDS = list(ETF_PORTFOLIO.keys())
    ETF_PLAN = _build_etf_plan(_S)
    ETF_THRESHOLDS = _build_etf_thresholds(_S)
    CRYPTO_POSITIONS = _get(_S, "crypto.positions", [])
    CRYPTO_THRESHOLDS = _build_crypto_thresholds(_S)
    SAVINGS_ACCOUNTS = _get(_S, "savings.accounts", [])
    SCHEDULED_ALERTS = _get(_S, "alerts.scheduled", [])

    return _S
