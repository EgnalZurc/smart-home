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


ETF_PORTFOLIO: dict[str, dict[str, Any]] = {
    fund["id"]: _build_fund_entry(fund)
    for fund in _get(_S, "etf.funds", [])
    if "id" in fund
}
ETF_FUND_IDS: list[str] = list(ETF_PORTFOLIO.keys())

# ETF Plan
_plan_raw = _get(_S, "etf.plan", {})
_milestones = _get(_S, "etf.plan.milestones", {})

# Default IRPF brackets for 2025 (Ley 7/2024) - base liquidable del ahorro
_DEFAULT_TAX_BRACKETS = [
    (6_000, 0.19),  # 0 - 6.000€: 19%
    (50_000, 0.21),  # 6.000 - 50.000€: 21%
    (200_000, 0.23),  # 50.000 - 200.000€: 23%
    (300_000, 0.27),  # 200.000 - 300.000€: 27%
    (float("inf"), 0.30),  # +300.000€: 30% (nuevo tramo 2025)
]

_raw_brackets = _get(_S, "etf.tax.brackets", [])
ETF_PLAN: dict[str, Any] = {
    "phase_change_date": datetime.fromisoformat(
        _plan_raw.get("phase_change_date", "2027-03-01")
    ),
    "milestones": {int(k): tuple(v) for k, v in _milestones.items()},
    "tax_brackets": [
        (float("inf") if limit >= 999_999_999 else float(limit), rate)
        for limit, rate in _raw_brackets
    ]
    if _raw_brackets
    else _DEFAULT_TAX_BRACKETS,
}

# ETF Thresholds
_etf_thr = _get(_S, "etf.thresholds", {})
ETF_THRESHOLDS = {
    "ma_short": _etf_thr.get("ma_short", 50),
    "ma_long": _etf_thr.get("ma_long", 200),
    "drop_from_high_warn": _etf_thr.get("drop_from_high_warn", -0.15),
    "loss_vs_cost_warn": _etf_thr.get("loss_vs_cost_warn", -0.10),
    "critical_threshold": _etf_thr.get("critical_threshold", -0.20),
}


# ─────────────────────────────────────────────────────────────────────────────
# Crypto Configuration
# ─────────────────────────────────────────────────────────────────────────────
CRYPTO_POSITIONS: list[dict[str, Any]] = _get(_S, "crypto.positions", [])

# Crypto Thresholds
# Note: Fear & Greed is a sentiment indicator, not a price predictor
_crypto_thr = _get(_S, "crypto.thresholds", {})
CRYPTO_THRESHOLDS = {
    "fg_extreme_greed": _crypto_thr.get("fg_extreme_greed", 75),  # Adjusted from 80
    "fg_high_greed": _crypto_thr.get("fg_high_greed", 60),  # Adjusted from 65
    "fg_extreme_fear": _crypto_thr.get("fg_extreme_fear", 25),  # Adjusted from 20
    "change_24h_danger": _crypto_thr.get("change_24h_danger", -10),
    "change_24h_warn": _crypto_thr.get("change_24h_warn", -5),
    "change_24h_pump": _crypto_thr.get("change_24h_pump", 10),
    "change_30d_bear": _crypto_thr.get("change_30d_bear", -20),
    "change_30d_bull": _crypto_thr.get("change_30d_bull", 20),
    "ath_danger_pct": _crypto_thr.get("ath_danger_pct", -5),
    "ath_warn_pct": _crypto_thr.get("ath_warn_pct", -15),
}


# ─────────────────────────────────────────────────────────────────────────────
# Utility: Reload configuration
# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
# Savings Accounts Configuration
# ─────────────────────────────────────────────────────────────────────────────
SAVINGS_ACCOUNTS: list[dict[str, Any]] = _get(_S, "savings.accounts", [])


# ─────────────────────────────────────────────────────────────────────────────
# Scheduled Alerts Configuration
# ─────────────────────────────────────────────────────────────────────────────
SCHEDULED_ALERTS: list[dict[str, Any]] = _get(_S, "alerts.scheduled", [])


# ─────────────────────────────────────────────────────────────────────────────
# Utility: Reload configuration
# ─────────────────────────────────────────────────────────────────────────────
def reload_config() -> dict[str, Any]:
    """Reload settings from disk. Returns the raw config dict."""
    global _S, ETF_PORTFOLIO, ETF_FUND_IDS, ETF_PLAN, CRYPTO_POSITIONS
    global SAVINGS_ACCOUNTS, SCHEDULED_ALERTS
    _S = _load_settings()

    ETF_PORTFOLIO = {
        fund["id"]: _build_fund_entry(fund)
        for fund in _get(_S, "etf.funds", [])
        if "id" in fund
    }
    ETF_FUND_IDS = list(ETF_PORTFOLIO.keys())

    _plan_raw = _get(_S, "etf.plan", {})
    _milestones = _get(_S, "etf.plan.milestones", {})
    ETF_PLAN = {
        "phase_change_date": datetime.fromisoformat(
            _plan_raw.get("phase_change_date", "2027-03-01")
        ),
        "milestones": {int(k): tuple(v) for k, v in _milestones.items()},
        "tax_brackets": [
            (float("inf") if limit >= 999_999_999 else float(limit), rate)
            for limit, rate in _get(_S, "etf.tax.brackets", [])
        ],
    }

    CRYPTO_POSITIONS = _get(_S, "crypto.positions", [])
    SAVINGS_ACCOUNTS = _get(_S, "savings.accounts", [])
    SCHEDULED_ALERTS = _get(_S, "alerts.scheduled", [])

    return _S
